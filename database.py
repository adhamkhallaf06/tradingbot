"""
SQLite layer for paper positions.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).parent / "positions.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker          TEXT    NOT NULL,
            side            TEXT    NOT NULL,
            quantity        REAL    DEFAULT 0,
            avg_fill        REAL    NOT NULL,
            take_profit     REAL,
            stop_loss       REAL,
            last_price      REAL,
            entry_time      TEXT    NOT NULL,
            exit_time       TEXT,
            exit_price      REAL,
            status          TEXT    DEFAULT 'OPEN',
            leverage        REAL    DEFAULT 1.0,
            risk_usd        REAL    DEFAULT 0,
            strategy_score  REAL    DEFAULT 0,
            signals         TEXT    DEFAULT '[]',
            news_sentiment  TEXT,
            expiration_date TEXT,
            exit_reason     TEXT,
            pnl_usd         REAL    DEFAULT 0,
            pnl_pct         REAL    DEFAULT 0,
            instrument_type TEXT    DEFAULT 'stock',
            multiplier      REAL    DEFAULT 1.0,
            display_name    TEXT
        )""")
        # Backfill columns for DBs created before this migration
        existing_cols = {row[1] for row in c.execute("PRAGMA table_info(positions)").fetchall()}
        for col, ddl in [
            ("instrument_type", "ALTER TABLE positions ADD COLUMN instrument_type TEXT DEFAULT 'stock'"),
            ("multiplier",      "ALTER TABLE positions ADD COLUMN multiplier REAL DEFAULT 1.0"),
            ("display_name",    "ALTER TABLE positions ADD COLUMN display_name TEXT"),
        ]:
            if col not in existing_cols:
                c.execute(ddl)
        c.execute("""
        CREATE INDEX IF NOT EXISTS idx_positions_status
            ON positions (status)
        """)
    print("✅ Positions DB ready")


def open_position(setup: dict) -> int:
    """Insert a new OPEN position from a trade setup dict. Returns row id."""
    now = datetime.now(timezone.utc).isoformat()
    signals_json = json.dumps([s for t in setup.get("triggered", []) for s in t.get("signals", [])])

    # Futures setups use "contracts" instead of "shares" — guard against the
    # key being present but explicitly None (e.g. stock setups in competition mode)
    qty = setup.get("contracts") or setup.get("shares") or 0

    with _conn() as c:
        cur = c.execute("""
        INSERT INTO positions
            (ticker, side, quantity, avg_fill, take_profit, stop_loss,
             last_price, entry_time, status, leverage, risk_usd,
             strategy_score, signals, news_sentiment, expiration_date,
             instrument_type, multiplier, display_name)
        VALUES (?,?,?,?,?,?,?,?, 'OPEN',?,?,?,?,?,?,?,?,?)
        """, (
            setup["ticker"],
            setup["direction"],
            round(qty, 4),
            setup["entry"],
            setup["target"],
            setup["stop_loss"],
            setup["entry"],                         # last_price starts at entry
            now,
            setup.get("leverage", 1.0),
            setup.get("risk_usd", 0),
            setup.get("strategy_score", 0),
            signals_json,
            setup.get("news_sentiment", ""),
            setup.get("expiration_date"),
            setup.get("instrument_type", "stock"),
            setup.get("multiplier", 1.0),
            setup.get("display_name", setup["ticker"]),
        ))
        return cur.lastrowid


def update_last_price(position_id: int, price: float, pnl_usd: float, pnl_pct: float):
    with _conn() as c:
        c.execute(
            "UPDATE positions SET last_price=?, pnl_usd=?, pnl_pct=? WHERE id=?",
            (price, round(pnl_usd, 2), round(pnl_pct, 4), position_id),
        )


def close_position(position_id: int, exit_price: float, reason: str):
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        row = c.execute("SELECT * FROM positions WHERE id=?", (position_id,)).fetchone()
        if not row:
            return
        entry = row["avg_fill"]
        qty   = row["quantity"]
        side  = row["side"]
        mult  = row["multiplier"] or 1.0
        pnl_usd = ((exit_price - entry) * qty * mult) if side == "BUY" else ((entry - exit_price) * qty * mult)
        pnl_pct = pnl_usd / (entry * qty * mult) * 100 if (entry * qty * mult) else 0

        c.execute("""
        UPDATE positions
            SET status='CLOSED', exit_time=?, exit_price=?,
                exit_reason=?, pnl_usd=?, pnl_pct=?, last_price=?
        WHERE id=?
        """, (now, round(exit_price, 2), reason,
              round(pnl_usd, 2), round(pnl_pct, 4),
              round(exit_price, 2), position_id))


def get_open_positions() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM positions WHERE status='OPEN' ORDER BY entry_time DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_positions(limit: int = 200) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM positions ORDER BY entry_time DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    with _conn() as c:
        total     = c.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
        open_cnt  = c.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN'").fetchone()[0]
        closed    = c.execute(
            "SELECT pnl_usd FROM positions WHERE status='CLOSED'"
        ).fetchall()

    closed_pnl = [r[0] or 0 for r in closed]
    wins   = sum(1 for p in closed_pnl if p > 0)
    losses = sum(1 for p in closed_pnl if p <= 0)
    total_closed = wins + losses

    return {
        "total_trades":   total,
        "open_positions": open_cnt,
        "closed_trades":  total_closed,
        "wins":           wins,
        "losses":         losses,
        "win_rate":       round(wins / total_closed * 100, 1) if total_closed else 0.0,
        "realized_pnl":   round(sum(closed_pnl), 2),
    }


def position_exists_open(ticker: str, side: str) -> bool:
    """True if there's already an open position for this ticker+side."""
    with _conn() as c:
        cnt = c.execute(
            "SELECT COUNT(*) FROM positions WHERE ticker=? AND side=? AND status='OPEN'",
            (ticker, side),
        ).fetchone()[0]
    return cnt > 0


init_db()
