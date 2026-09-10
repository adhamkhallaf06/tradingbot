# ── NASDAQ watchlist ──────────────────────────────────────────────────────────
WATCHLIST = [
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "META", "GOOGL", "AMZN", "TSLA", "AVGO",
    # Large-cap tech / semis
    "AMD", "QCOM", "MU", "AMAT", "ARM", "MRVL",
    # Growth / software
    "NFLX", "ADBE", "CRM", "NOW", "SNOW", "PLTR", "PANW",
    # Fintech / consumer
    "PYPL", "COIN", "UBER", "ABNB",
    # Broad NASDAQ exposure
    "QQQ",
]

# ── Futures watchlist ──────────────────────────────────────────────────────────
# Yahoo Finance continuous-contract tickers. "multiplier" = $ value per 1.00
# index point move (used for contract sizing & P/L). Nikkei contracts are
# yen-denominated — multiplier is in JPY, converted to USD at scan time.
FUTURES_WATCHLIST = {
    "ES=F":  {"name": "E-mini S&P 500",            "multiplier": 50.0,  "tick": 0.25, "currency": "USD"},
    "MES=F": {"name": "Micro E-mini S&P 500",      "multiplier": 5.0,   "tick": 0.25, "currency": "USD"},
    "NQ=F":  {"name": "E-mini Nasdaq-100",         "multiplier": 20.0,  "tick": 0.25, "currency": "USD"},
    "MNQ=F": {"name": "Micro E-mini Nasdaq-100",   "multiplier": 2.0,   "tick": 0.25, "currency": "USD"},
    "YM=F":  {"name": "E-mini Dow ($5)",           "multiplier": 5.0,   "tick": 1.0,  "currency": "USD"},
    "MYM=F": {"name": "Micro E-mini Dow",          "multiplier": 0.50,  "tick": 1.0,  "currency": "USD"},
    "RTY=F": {"name": "E-mini Russell 2000",       "multiplier": 50.0,  "tick": 0.1,  "currency": "USD"},
    "M2K=F": {"name": "Micro E-mini Russell 2000", "multiplier": 5.0,   "tick": 0.1,  "currency": "USD"},
    "EMD=F": {"name": "E-mini MidCap 400",         "multiplier": 100.0, "tick": 0.1,  "currency": "USD"},
    "NIY=F": {"name": "Nikkei 225 (Yen)",          "multiplier": 500.0, "tick": 5.0,  "currency": "JPY"},
    "MNI=F": {"name": "Micro Nikkei (JPY)",        "multiplier": 100.0, "tick": 5.0,  "currency": "JPY"},
}

LOOKBACK_DAYS = 200

# ── Scan schedule (24/5 — Mon 00:00 through Fri 23:59 ET) ────────────────────
PRE_MARKET_SCAN_TIME  = "08:00"   # ET — daily morning briefing
SCAN_INTERVAL_MINUTES = 60        # hourly during the trading week
SIGNAL_COOLDOWN_HOURS = 4         # don't re-alert same ticker within 4h

# ── Trade sizing ──────────────────────────────────────────────────────────────
ACCOUNT_SIZE_USD   = 10_000
RISK_PER_TRADE_PCT = 0.01          # 1% of account at risk per trade

# ── Profit target & stop — percentage-based for consistency ──────────────────
# Target: fixed 5% from entry. Achievable intraday without needing a home run.
PROFIT_TARGET_PCT  = 5.0

# Stop: ATR × multiplier (adapts to each stock's volatility).
# Kept at 1.0× so we only trade when ATR is tight enough to give ≥1.5 R:R.
ATR_STOP_MULT      = 1.0

# Reject the trade if the ATR-based stop is wider than this % from entry.
# Prevents taking trades on too-volatile stocks where 5% target is insufficient.
MAX_STOP_PCT       = 3.5           # e.g. skip TSLA if ATR stop = 5%

# Minimum reward-to-risk ratio to send an alert.
MIN_REWARD_RISK    = 1.5

# ── Futures trade sizing ──────────────────────────────────────────────────────
# Indices don't move 5% intraday (that's a crash) — use ATR multiples instead.
FUTURES_ATR_STOP_MULT   = 1.0
FUTURES_ATR_TARGET_MULT = 2.0     # 2:1 R:R baked into the target itself
FUTURES_MIN_REWARD_RISK = 1.5
FUTURES_MAX_STOP_PCT    = 1.5     # reject if ATR stop > 1.5% of price (too volatile/news-driven)
FUTURES_SCAN_INTERVAL_MINUTES = 30   # futures trade nearly 24/5 — scan more often than stocks

# Hard cap on account risk per futures trade. A full-size contract (e.g. ES at
# $50/point) can blow way past the 1% risk target even at 1 contract — the
# minimum tradable size. Reject the trade rather than over-risk the account.
FUTURES_MAX_RISK_PCT = 0.05    # 5% of account max — filters out oversized full contracts

# ── Competition mode — `python3 main.py --best` ──────────────────────────────
# Scans stocks + futures together and surfaces the single best trade right
# now. Bigger target, tighter stop, ranked by conviction × reward-to-risk —
# built for racking up gains fast rather than steady 5% wins.
COMPETITION_RISK_PCT      = 0.02   # 2% of account per trade (vs 1% normal mode)
COMP_ATR_STOP_MULT        = 1.0    # tight stop — keeps R:R high
COMP_ATR_TARGET_MULT      = 5.0    # let the target run — bigger payoff per trade
COMP_MIN_REWARD_RISK      = 3.0    # only surface trades with a big payoff
COMP_MAX_STOP_PCT_STOCK   = 4.0    # stocks: skip if ATR stop > 4% of price
COMP_MAX_STOP_PCT_FUTURES = 2.0    # futures: skip if ATR stop > 2% of price
COMP_MIN_SCORE            = 3       # still require real technical conviction
COMP_CANDIDATES_FOR_NEWS  = 8       # only fetch news for the top N TA candidates (speed)

# ── Signal thresholds ─────────────────────────────────────────────────────────
# Pre-market: require higher conviction (score ≥ 6) — fewer but better setups.
PRE_MARKET_BUY_THRESHOLD  =  6
PRE_MARKET_SELL_THRESHOLD = -6

# Market-hours: slightly relaxed (score ≥ 4).
BUY_THRESHOLD  =  4
SELL_THRESHOLD = -4

# ── News sources ──────────────────────────────────────────────────────────────
MARKET_NEWS_FEEDS = [
    "https://feeds.marketwatch.com/marketwatch/topstories/",
    "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
]
MAX_ARTICLES_PER_FEED = 8

# RSI thresholds
RSI_OVERSOLD   = 35
RSI_OVERBOUGHT = 70
