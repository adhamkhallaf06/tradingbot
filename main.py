"""
Futures Trading Bot — 24/5 scanner with paper trading.
Markets: E-mini/Micro S&P 500, Nasdaq-100, Dow, Russell 2000, MidCap 400, Nikkei 225.

Run:
  python3 main.py               # continuous futures scanning (every 30 min)
  python3 main.py --futures     # one futures scan right now
  python3 main.py --best        # ⚡ single best trade right now (competition mode)
  python3 main.py --backtest    # walk-forward backtest
"""

import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import schedule
from dotenv import load_dotenv

from config import (
    FUTURES_WATCHLIST,
    BUY_THRESHOLD, SELL_THRESHOLD,
    SIGNAL_COOLDOWN_HOURS, FUTURES_SCAN_INTERVAL_MINUTES,
    COMP_MIN_SCORE, COMP_CANDIDATES_FOR_NEWS,
)
from data_fetcher import fetch_ohlcv
from indicators import compute_indicators
from strategies import run_all, _load_weights
from news_scraper import fetch_news_sentiment
from trade_setup import build_futures_trade_setup, build_competition_setup
from paper_trader import enter_trade, monitor_positions
from notifier import (
    send_trade_alert, send_daily_summary,
    send_no_signals_message, send_best_trade_alert,
)

load_dotenv()

ET = ZoneInfo("America/New_York")

# In-memory cooldown — persists across scans within the same process
_alerted: dict[tuple[str, str], datetime] = {}


def _on_cooldown(ticker: str, direction: str) -> bool:
    from datetime import timezone as tz
    key  = (ticker, direction)
    last = _alerted.get(key)
    return bool(last and (datetime.now(tz.utc) - last) < timedelta(hours=SIGNAL_COOLDOWN_HOURS))


def _mark(ticker: str, direction: str):
    from datetime import timezone as tz
    _alerted[(ticker, direction)] = datetime.now(tz.utc)


def _usd_jpy_rate() -> float:
    try:
        df = fetch_ohlcv("JPY=X", days=5)
        return float(df["close"].iloc[-1])
    except Exception:
        return 145.0   # sane fallback


def _futures_market_closed(now_et: datetime) -> bool:
    """Futures close Fri 17:00 ET through Sun 18:00 ET."""
    wd, h = now_et.weekday(), now_et.hour
    return (wd == 4 and h >= 17) or wd == 5 or (wd == 6 and h < 18)


# ── Futures scan — runs nearly 24/5 (futures barely close) ───────────────────

def run_futures_scan():
    """
    Scans the futures watchlist (E-mini/Micro S&P, Nasdaq, Dow, Russell,
    MidCap, Nikkei). Futures trade nearly 24 hours Sun 6pm–Fri 5pm ET, so
    this only pauses during the Fri 5pm–Sun 6pm weekend close.
    """
    now_et = datetime.now(ET)

    if _futures_market_closed(now_et):
        print(f"[{now_et.strftime('%a %H:%M ET')}] Futures market closed (weekend) — skipping")
        return

    weights = _load_weights()
    fx_rate = _usd_jpy_rate()

    print(f"\n{'='*65}")
    print(f"🌐  FUTURES SCAN  |  {now_et.strftime('%a %b %d  %H:%M ET')}")
    print(f"    {len(FUTURES_WATCHLIST)} contracts  ·  ATR target/stop (2:1 R:R)  ·  "
          f"USD/JPY {fx_rate:.2f}")
    print(f"    Weights: {'active' if weights else 'none'}")
    print(f"{'='*65}")

    monitor_positions()

    setups = []
    for ticker, spec in FUTURES_WATCHLIST.items():
        try:
            df       = fetch_ohlcv(ticker)
            df       = compute_indicators(df)
            analysis = run_all(df)
            score     = analysis["score"]
            direction = analysis["direction"]
            close     = analysis["close"]

            print(f"[{ticker:6s}] {spec['name']:<26s} {close:>10.2f}  {score:+6.1f}  {direction}")

            if analysis["triggered"]:
                for t in analysis["triggered"]:
                    for sig in t["signals"]:
                        print(f"  ↳ {t['name']} ({t['score']:+.1f}): {sig}")

            if direction == "HOLD":
                continue
            if direction == "BUY"  and score < BUY_THRESHOLD:
                continue
            if direction == "SELL" and score > SELL_THRESHOLD:
                continue

            if _on_cooldown(ticker, direction):
                print(f"  [{ticker}] {direction} on cooldown")
                continue

            news = fetch_news_sentiment(ticker)
            if direction=="BUY"  and news["sentiment_label"]=="Bearish" and news["total_score"]<-5:
                print(f"  [{ticker}] skipped — bearish news override")
                continue
            if direction=="SELL" and news["sentiment_label"]=="Bullish" and news["total_score"]>5:
                print(f"  [{ticker}] skipped — bullish news override")
                continue

            setup = build_futures_trade_setup(ticker, analysis, news, fx_rate=fx_rate)
            if not setup:
                print(f"  [{ticker}] skipped — stop too wide or R:R insufficient")
                continue

            print(f"  [{ticker}] ✓ {direction}  {spec['name']}  "
                  f"{setup['entry']:,.2f} → {setup['target']:,.2f}  "
                  f"stop {setup['stop_loss']:,.2f}  "
                  f"R:R {setup['rr_ratio']:.1f}  "
                  f"{setup['contracts']} contract(s)  risk ${setup['risk_usd']:.2f}")

            setups.append(setup)
            _mark(ticker, direction)
            enter_trade(setup)

        except Exception as e:
            print(f"[{ticker}] Error: {e}")

    print(f"\n{'='*65}")
    print(f"  Futures scan done — {len(setups)} signal(s)  "
          f"|  next in {FUTURES_SCAN_INTERVAL_MINUTES}m")
    print(f"{'='*65}\n")

    if setups:
        send_daily_summary(setups)
        for s in setups:
            send_trade_alert(s)
    else:
        send_no_signals_message(mode="futures")


# ── Competition mode: single best futures trade, right now ──────────────────

def run_best_trade(show_top: int = 3):
    """
    Scans the full futures watchlist and surfaces the single best trade right
    now, ranked by conviction × reward-to-risk. Built for racking up gains
    fast in a competition, not steady small wins.

    Two-pass approach for speed:
      1. Quick TA-only pass over every contract (no news fetch yet).
      2. Fetch news only for the top N candidates by raw |score|, then build
         the final competition setup and rank by competition_score.
    """
    print(f"\n{'='*65}")
    print(f"⚡  COMPETITION SCAN — finding the single best futures trade right now")
    print(f"    Universe: {len(FUTURES_WATCHLIST)} futures contracts")
    print(f"    Target: 5× ATR  ·  Stop: 1× ATR  ·  Min R:R 3:1  ·  Min score {COMP_MIN_SCORE}")
    print(f"{'='*65}\n")

    now_et = datetime.now(ET)
    if _futures_market_closed(now_et):
        print(f"[{now_et.strftime('%a %H:%M ET')}] Futures market closed (weekend) — no trade to show")
        send_no_signals_message(mode="competition")
        return

    fx_rate = _usd_jpy_rate()

    # ── Pass 1: TA-only, fast ──────────────────────────────────────────────────
    prelim = []
    for ticker, spec in FUTURES_WATCHLIST.items():
        try:
            df       = fetch_ohlcv(ticker)
            df       = compute_indicators(df)
            analysis = run_all(df)
            direction = analysis["direction"]
            score     = analysis["score"]

            if direction == "HOLD" or abs(score) < COMP_MIN_SCORE:
                continue

            print(f"  [{ticker:6s}] {spec['name']:<26s} ${analysis['close']:>10.2f}  "
                  f"{score:+6.1f}  {direction}")

            prelim.append({"ticker": ticker, "analysis": analysis})
        except Exception as e:
            print(f"  [{ticker}] Error: {e}")

    if not prelim:
        print("\n  No contracts showed any technical conviction right now.")
        send_no_signals_message(mode="competition")
        return

    # Rank by raw |score| and only fetch news for the top N — keeps this fast
    prelim.sort(key=lambda p: abs(p["analysis"]["score"]), reverse=True)
    shortlist = prelim[:COMP_CANDIDATES_FOR_NEWS]

    print(f"\n  Shortlisted top {len(shortlist)} by raw score — fetching news + building setups...\n")

    # ── Pass 2: news + final setup for the shortlist ───────────────────────────
    candidates = []
    for p in shortlist:
        ticker, analysis = p["ticker"], p["analysis"]
        try:
            news      = fetch_news_sentiment(ticker)
            direction = analysis["direction"]

            if direction=="BUY"  and news["sentiment_label"]=="Bearish" and news["total_score"]<-5:
                print(f"  [{ticker}] dropped — bearish news override")
                continue
            if direction=="SELL" and news["sentiment_label"]=="Bullish" and news["total_score"]>5:
                print(f"  [{ticker}] dropped — bullish news override")
                continue

            setup = build_competition_setup(ticker, analysis, news, fx_rate=fx_rate)
            if setup is None:
                print(f"  [{ticker}] dropped — stop too wide or R:R below 3:1")
                continue

            print(f"  [{ticker}] qualifies — comp score {setup['competition_score']:.1f}  "
                  f"R:R {setup['rr_ratio']:.1f}  news {news['sentiment_label']}")
            candidates.append(setup)

        except Exception as e:
            print(f"  [{ticker}] Error: {e}")

    if not candidates:
        print("\n  Shortlist all failed risk/reward checks — no trade to show.")
        send_no_signals_message(mode="competition")
        return

    candidates.sort(key=lambda s: s["competition_score"], reverse=True)
    best = candidates[0]
    alts = candidates[1:show_top]

    print(f"\n{'='*65}")
    print(f"⚡  BEST TRADE RIGHT NOW")
    print(f"{'='*65}")
    print(f"  {best.get('display_name', best['ticker'])} ({best['ticker']})  —  {best['direction']}")
    print(f"  Entry:   {best['entry']:,.2f}")
    print(f"  Stop:    {best['stop_loss']:,.2f}")
    print(f"  Target:  {best['target']:,.2f}")
    print(f"  R:R:     {best['rr_ratio']:.1f}:1")
    print(f"  Size:    {best['shares']:.4f} contract(s)  (risking ${best['risk_usd']:.2f})")
    print(f"  Score:   {best['strategy_score']:+.1f}  ·  Comp score: {best['competition_score']:.1f}")
    print(f"  Why:     {best['reason']}")
    for t in best["triggered"]:
        for sig in t["signals"]:
            print(f"    ↳ {t['name']} ({t['score']:+.1f}): {sig}")

    if alts:
        print(f"\n  Runner-up alternatives:")
        for a in alts:
            print(f"    {a.get('display_name', a['ticker'])}  {a['direction']}  "
                  f"comp score {a['competition_score']:.1f}  R:R {a['rr_ratio']:.1f}")
    print(f"{'='*65}\n")

    send_best_trade_alert(best, alts)
    enter_trade(best)   # track it as a paper position immediately


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--backtest" in args:
        from backtester import run_backtest
        tickers = [a.upper() for a in args if not a.startswith("--")] or list(FUTURES_WATCHLIST)
        run_backtest(tickers)

    elif "--best" in args:
        run_best_trade()

    elif "--futures" in args or "--now" in args:
        run_futures_scan()

    else:
        print("Futures Trading Bot — 24/5")
        print(f"  Markets   : {', '.join(FUTURES_WATCHLIST)}")
        print(f"  Scan every: {FUTURES_SCAN_INTERVAL_MINUTES} min "
              f"(Sun 6pm – Fri 5pm ET, nearly 24/5)")
        print(f"  Dashboard : run  python3 app.py  → http://localhost:8888")
        print("\nFlags:  --futures     futures scan now (alias: --now)")
        print("        --best        ⚡ single best trade right now (competition mode)")
        print("        --backtest    walk-forward backtest\n")

        schedule.every(FUTURES_SCAN_INTERVAL_MINUTES).minutes.do(run_futures_scan)

        # Run once immediately on start
        run_futures_scan()

        while True:
            schedule.run_pending()
            time.sleep(30)
