"""
Walk-forward backtester for all strategies.

Usage:
  python3 backtester.py                    # backtest all watchlist tickers
  python3 backtester.py AAPL NVDA MSFT     # backtest specific tickers
  python3 backtester.py --summary          # print last saved results

Results are written to backtest_results.json and picked up automatically
by strategies.run_all() to weight each strategy's live score.
"""

import sys
import json
import os
from datetime import datetime, date

import pandas as pd

from config import WATCHLIST, ATR_STOP_MULT, ATR_TARGET_MULT
from data_fetcher import fetch_ohlcv
from indicators import compute_indicators
from strategies import _DETECTORS

RESULTS_PATH = os.path.join(os.path.dirname(__file__), "backtest_results.json")
LOOKAHEAD    = 20    # bars to check after a signal fires
MIN_SIGNAL   = 2     # minimum |score| from a detector to count as a trade


# ── Core walk-forward engine ──────────────────────────────────────────────────

def backtest_one_strategy(
    name: str,
    fn,
    df: pd.DataFrame,
) -> dict:
    """
    Walk forward bar by bar. Each time the detector fires a signal with
    |score| >= MIN_SIGNAL, open a simulated trade and check whether price
    hits the target or the stop first within LOOKAHEAD bars.

    Returns per-strategy stats dict.
    """
    trades = []

    for i in range(60, len(df) - LOOKAHEAD - 1):
        hist = df.iloc[: i + 1].copy()

        try:
            s, sigs, _ = fn(hist)
        except Exception:
            continue

        if abs(s) < MIN_SIGNAL:
            continue

        direction = "BUY" if s > 0 else "SELL"
        entry     = float(hist.iloc[-1]["close"])

        atr_col = "ATRr_14"
        atr_val = hist.iloc[-1].get(atr_col)
        if atr_val is None or pd.isna(atr_val) or float(atr_val) <= 0:
            continue
        atr = float(atr_val)

        stop_dist   = atr * ATR_STOP_MULT
        target_dist = atr * ATR_TARGET_MULT

        if direction == "BUY":
            stop, target = entry - stop_dist, entry + target_dist
        else:
            stop, target = entry + stop_dist, entry - target_dist

        # Simulate over the next LOOKAHEAD bars
        outcome    = None
        bars_held  = 0
        exit_price = None

        future = df.iloc[i + 1 : i + 1 + LOOKAHEAD]
        for _, bar in future.iterrows():
            bars_held += 1
            if direction == "BUY":
                if float(bar["high"]) >= target:
                    outcome, exit_price = "WIN",  target;  break
                if float(bar["low"])  <= stop:
                    outcome, exit_price = "LOSS", stop;    break
            else:
                if float(bar["low"])  <= target:
                    outcome, exit_price = "WIN",  target;  break
                if float(bar["high"]) >= stop:
                    outcome, exit_price = "LOSS", stop;    break

        if outcome is None:
            continue  # trade still open at end of lookahead — skip

        rr_actual = (
            abs(exit_price - entry) / stop_dist
            if stop_dist > 0 else 0.0
        )

        trades.append({
            "bar":        i,
            "direction":  direction,
            "entry":      round(entry, 4),
            "stop":       round(stop, 4),
            "target":     round(target, 4),
            "exit_price": round(exit_price, 4),
            "outcome":    outcome,
            "bars_held":  bars_held,
            "rr":         round(rr_actual, 2),
            "raw_score":  s,
        })

    wins   = sum(1 for t in trades if t["outcome"] == "WIN")
    losses = sum(1 for t in trades if t["outcome"] == "LOSS")
    total  = wins + losses

    avg_rr = (
        round(sum(t["rr"] for t in trades) / total, 2) if total > 0 else 0.0
    )
    profit_factor = (
        round(wins * ATR_TARGET_MULT / max(losses * ATR_STOP_MULT, 0.0001), 2)
        if losses > 0 else float(wins) if wins > 0 else 0.0
    )

    return {
        "wins":          wins,
        "losses":        losses,
        "total_trades":  total,
        "win_rate":      round(wins / total * 100, 1) if total > 0 else 0.0,
        "avg_rr":        avg_rr,
        "profit_factor": profit_factor,
        "trades":        trades,   # kept for detailed drill-down
    }


# ── Per-ticker runner ─────────────────────────────────────────────────────────

def backtest_ticker(ticker: str) -> dict:
    print(f"  Backtesting {ticker}...")
    try:
        df = fetch_ohlcv(ticker, days=400)
        df = compute_indicators(df)
    except Exception as e:
        print(f"  [{ticker}] Data error: {e}")
        return {}

    results = {}
    for name, fn in _DETECTORS:
        stats = backtest_one_strategy(name, fn, df)
        results[name] = stats
        wl = f"{stats['wins']}W/{stats['losses']}L"
        wr = f"{stats['win_rate']}%"
        n  = stats["total_trades"]
        pf = stats["profit_factor"]
        print(f"    {name:<22} {wl:<10} WR={wr:<7} n={n:<4} PF={pf}")

    return results


# ── Aggregate across tickers ──────────────────────────────────────────────────

def aggregate(all_results: dict[str, dict]) -> dict:
    """Roll up per-ticker results into aggregate win rates per strategy."""
    agg: dict[str, dict] = {}
    for ticker_results in all_results.values():
        for name, stats in ticker_results.items():
            if name not in agg:
                agg[name] = {"wins": 0, "losses": 0, "total_trades": 0}
            agg[name]["wins"]         += stats["wins"]
            agg[name]["losses"]       += stats["losses"]
            agg[name]["total_trades"] += stats["total_trades"]

    for name, a in agg.items():
        t = a["total_trades"]
        a["win_rate"]      = round(a["wins"] / t * 100, 1) if t > 0 else 0.0
        a["profit_factor"] = round(
            (a["wins"] * ATR_TARGET_MULT) / max(a["losses"] * ATR_STOP_MULT, 0.0001), 2
        ) if a["losses"] > 0 else float(a["wins"]) if a["wins"] > 0 else 0.0

    return dict(sorted(agg.items(), key=lambda x: x[1]["win_rate"], reverse=True))


# ── Save / load ───────────────────────────────────────────────────────────────

def save_results(ticker_results: dict, agg: dict):
    data = {
        "last_updated": datetime.utcnow().isoformat(),
        "tickers":      list(ticker_results.keys()),
        "per_ticker":   {
            k: {n: {kk: vv for kk, vv in s.items() if kk != "trades"}
                for n, s in v.items()}
            for k, v in ticker_results.items()
        },
        "aggregate":    agg,
    }
    with open(RESULTS_PATH, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\n✅ Results saved to {RESULTS_PATH}")


def load_results() -> dict | None:
    if not os.path.exists(RESULTS_PATH):
        return None
    with open(RESULTS_PATH) as f:
        return json.load(f)


# ── Pretty printer ────────────────────────────────────────────────────────────

def print_summary(data: dict):
    agg = data.get("aggregate", {})
    updated = data.get("last_updated", "unknown")
    tickers = data.get("tickers", [])

    print(f"\n{'═'*72}")
    print(f"  BACKTEST RESULTS  |  Updated: {updated[:19]}  |  Tickers: {len(tickers)}")
    print(f"{'═'*72}")
    print(f"  {'Strategy':<24} {'Win Rate':>9} {'Trades':>7} {'W/L':>10}  {'PF':>6}  {'Weight'}")
    print(f"  {'-'*64}")

    for name, s in agg.items():
        wr  = s["win_rate"]
        tot = s["total_trades"]
        wl  = f"{s['wins']}W/{s['losses']}L"
        pf  = s["profit_factor"]
        if wr >= 65:
            wt, badge = "1.5×", "🔥"
        elif wr >= 50:
            wt, badge = "1.0×", "✅"
        elif wr >= 35:
            wt, badge = "0.75×", "⚠️ "
        else:
            wt, badge = "0.5×", "❌"
        print(f"  {badge} {name:<22} {wr:>8.1f}%  {tot:>6}   {wl:<10} {pf:>5.2f}   {wt}")

    print(f"{'═'*72}\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def run_backtest(tickers: list[str]):
    print(f"\n{'='*60}")
    print(f"Walk-Forward Backtest  |  {len(tickers)} ticker(s)")
    print(f"Lookahead: {LOOKAHEAD} bars  |  ATR stop: {ATR_STOP_MULT}×  |  ATR target: {ATR_TARGET_MULT}×")
    print(f"{'='*60}\n")

    all_results: dict[str, dict] = {}
    for t in tickers:
        res = backtest_ticker(t)
        if res:
            all_results[t] = res

    if not all_results:
        print("No results — check data feeds.")
        return

    agg = aggregate(all_results)
    save_results(all_results, agg)
    print_summary({"aggregate": agg, "last_updated": datetime.utcnow().isoformat(),
                   "tickers": list(all_results.keys())})

    print("Weights have been saved. Re-run main.py --now to use them in live signals.\n")


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--summary" in args:
        data = load_results()
        if data:
            print_summary(data)
        else:
            print("No backtest_results.json found. Run: python3 backtester.py")
        sys.exit(0)

    tickers = [a.upper() for a in args if not a.startswith("--")] or WATCHLIST
    run_backtest(tickers)
