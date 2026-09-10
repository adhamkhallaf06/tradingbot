"""
Dashboard server — run with:  python3 app.py
Opens at http://localhost:8888
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Set

import yfinance as yf
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from database import (
    get_open_positions, get_all_positions, get_stats,
    update_last_price,
)
from config import ACCOUNT_SIZE_USD

load_dotenv()

app = FastAPI(title="NASDAQ Trading Bot Dashboard")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

STATIC = Path(__file__).parent / "static"
_clients: Set[WebSocket] = set()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _price(ticker: str) -> float | None:
    try:
        fi = yf.Ticker(ticker).fast_info
        p  = fi.get("last_price") or fi.get("regular_market_price")
        return float(p) if p else None
    except Exception:
        return None


def _enrich(pos: dict) -> dict:
    """Add computed columns to a position dict. Applies the contract
    multiplier for futures (e.g. $5/point for MES) — stocks default to 1.0."""
    entry = pos["avg_fill"] or 0
    qty   = pos["quantity"] or 0
    side  = pos["side"]
    price = pos.get("last_price") or entry
    lev   = pos.get("leverage") or 1.0
    mult  = pos.get("multiplier") or 1.0

    trade_value  = round(entry * qty * mult, 2)
    market_value = round(price * qty * mult, 2)
    margin       = round(market_value / lev, 2) if lev else market_value

    if side == "BUY":
        pnl_usd = round((price - entry) * qty * mult, 2)
    else:
        pnl_usd = round((entry - price) * qty * mult, 2)

    pnl_pct = round(pnl_usd / trade_value * 100, 2) if trade_value else 0.0

    return {
        **pos,
        "trade_value":  trade_value,
        "market_value": market_value,
        "margin":       margin,
        "pnl_usd":      pnl_usd,
        "pnl_pct":      pnl_pct,
        "last_price":   round(price, 2),
        "display_name": pos.get("display_name") or pos["ticker"],
    }


async def _broadcast(payload: dict):
    dead = set()
    msg  = json.dumps(payload)
    for ws in list(_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    _clients -= dead


# ── Background price updater ──────────────────────────────────────────────────

async def price_loop():
    """Every 3 s: fetch live prices, update DB, push to all WebSocket clients."""
    while True:
        try:
            positions = get_open_positions()
            enriched  = []

            if positions:
                tickers = list({p["ticker"] for p in positions})
                prices  = {}
                for t in tickers:
                    p = _price(t)
                    if p:
                        prices[t] = p

                from database import close_position
                from datetime import timezone as tz

                for pos in positions:
                    ticker = pos["ticker"]
                    price  = prices.get(ticker)
                    if not price:
                        enriched.append(_enrich(pos))
                        continue

                    entry = pos["avg_fill"]
                    qty   = pos["quantity"]
                    side  = pos["side"]
                    tp    = pos["take_profit"]
                    sl    = pos["stop_loss"]
                    mult  = pos.get("multiplier") or 1.0

                    if side == "BUY":
                        pnl_usd = (price - entry) * qty * mult
                    else:
                        pnl_usd = (entry - price) * qty * mult
                    pnl_pct = pnl_usd / (entry * qty * mult) * 100 if entry * qty * mult else 0

                    update_last_price(pos["id"], price, pnl_usd, pnl_pct)

                    # Auto-close
                    reason = None
                    if side == "BUY":
                        if tp and price >= tp:  reason = f"Take profit hit (${price:.2f})"
                        elif sl and price <= sl: reason = f"Stop loss hit (${price:.2f})"
                    else:
                        if tp and price <= tp:  reason = f"Take profit hit (${price:.2f})"
                        elif sl and price >= sl: reason = f"Stop loss hit (${price:.2f})"

                    if reason:
                        close_position(pos["id"], price, reason)

                    enriched.append(_enrich({**pos, "last_price": price}))

            stats  = get_stats()
            open_p = [p for p in enriched if p.get("status") == "OPEN"]
            total_unrealized = sum(p["pnl_usd"] for p in open_p)
            total_mkt_val    = sum(p["market_value"] for p in open_p)

            payload = {
                "type":       "update",
                "ts":         datetime.now(timezone.utc).isoformat(),
                "positions":  enriched,
                "stats": {
                    **stats,
                    "account_balance":    ACCOUNT_SIZE_USD + stats["realized_pnl"],
                    "unrealized_pnl":     round(total_unrealized, 2),
                    "total_market_value": round(total_mkt_val, 2),
                },
            }
            if _clients:
                await _broadcast(payload)

        except Exception as e:
            print(f"[price_loop] {e}")

        await asyncio.sleep(3)


@app.on_event("startup")
async def startup():
    asyncio.create_task(price_loop())


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC / "index.html").read_text()


@app.get("/api/positions")
def api_positions():
    return [_enrich(p) for p in get_all_positions()]


@app.get("/api/positions/open")
def api_open():
    return [_enrich(p) for p in get_open_positions()]


@app.get("/api/stats")
def api_stats():
    s      = get_stats()
    open_p = [_enrich(p) for p in get_open_positions()]
    unrealized = sum(p["pnl_usd"] for p in open_p)
    return {
        **s,
        "account_balance":    round(ACCOUNT_SIZE_USD + s["realized_pnl"], 2),
        "unrealized_pnl":     round(unrealized, 2),
        "total_market_value": round(sum(p["market_value"] for p in open_p), 2),
    }


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    _clients.add(ws)
    # Send current snapshot immediately on connect
    positions = [_enrich(p) for p in get_all_positions(50)]
    stats     = get_stats()
    open_p    = [p for p in positions if p.get("status") == "OPEN"]
    await ws.send_text(json.dumps({
        "type": "update",
        "ts":   datetime.now(timezone.utc).isoformat(),
        "positions": positions,
        "stats": {
            **stats,
            "account_balance":    ACCOUNT_SIZE_USD + stats["realized_pnl"],
            "unrealized_pnl":     round(sum(p["pnl_usd"] for p in open_p), 2),
            "total_market_value": round(sum(p["market_value"] for p in open_p), 2),
        },
    }))
    try:
        while True:
            await ws.receive_text()   # keep alive
    except WebSocketDisconnect:
        _clients.discard(ws)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8888, reload=False)
