"""
Paper trader — opens positions from trade setups, monitors prices,
auto-closes on target / stop, and notifies Discord.
"""

import yfinance as yf
from database import (
    open_position as db_open, close_position as db_close,
    update_last_price, get_open_positions, position_exists_open,
)
from notifier import send_trade_alert


def _current_price(ticker: str) -> float | None:
    try:
        fi = yf.Ticker(ticker).fast_info
        p  = fi.get("last_price") or fi.get("regular_market_price")
        return float(p) if p else None
    except Exception:
        return None


def enter_trade(setup: dict) -> int | None:
    """
    Open a paper position from a build_trade_setup() result.
    Returns the new position ID, or None if it already exists.
    """
    ticker    = setup["ticker"]
    direction = setup["direction"]

    if position_exists_open(ticker, direction):
        print(f"  [{ticker}] Already have open {direction} — skipping duplicate")
        return None

    pos_id = db_open(setup)
    print(f"  [{ticker}] 📝 Paper position opened  id={pos_id}  "
          f"{direction} {setup['shares']:.3f} shares @ ${setup['entry']:,.2f}")
    return pos_id


def monitor_positions() -> list[dict]:
    """
    Fetch current prices for all open positions, update P/L,
    and auto-close any that hit their target or stop.
    Returns list of updated position dicts.
    """
    positions = get_open_positions()
    if not positions:
        return []

    updated = []
    for pos in positions:
        ticker     = pos["ticker"]
        side       = pos["side"]
        entry      = pos["avg_fill"]
        qty        = pos["quantity"]
        tp         = pos["take_profit"]
        sl         = pos["stop_loss"]
        pos_id     = pos["id"]
        mult       = pos.get("multiplier") or 1.0

        price = _current_price(ticker)
        if price is None:
            updated.append(pos)
            continue

        # P/L (multiplier applies the futures point value, e.g. $5/pt for MES)
        if side == "BUY":
            pnl_usd = (price - entry) * qty * mult
        else:
            pnl_usd = (entry - price) * qty * mult
        pnl_pct = pnl_usd / (entry * qty * mult) * 100 if (entry * qty * mult) else 0

        update_last_price(pos_id, price, pnl_usd, pnl_pct)

        # Auto-close checks
        reason = None
        if side == "BUY":
            if tp and price >= tp:
                reason = f"Take profit hit (${price:.2f} ≥ ${tp:.2f})"
            elif sl and price <= sl:
                reason = f"Stop loss hit (${price:.2f} ≤ ${sl:.2f})"
        else:
            if tp and price <= tp:
                reason = f"Take profit hit (${price:.2f} ≤ ${tp:.2f})"
            elif sl and price >= sl:
                reason = f"Stop loss hit (${price:.2f} ≥ ${sl:.2f})"

        if reason:
            db_close(pos_id, price, reason)
            print(f"  [{ticker}] 🔒 Closed  {reason}  P/L ${pnl_usd:+.2f} ({pnl_pct:+.1f}%)")
            pos = {**pos, "last_price": price, "pnl_usd": pnl_usd, "pnl_pct": pnl_pct,
                   "status": "CLOSED", "exit_reason": reason}

        updated.append({**pos, "last_price": price, "pnl_usd": round(pnl_usd, 2),
                        "pnl_pct": round(pnl_pct, 4)})

    return updated
