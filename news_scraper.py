"""
News sentiment for individual NASDAQ stocks.
Primary source: yfinance news (ticker-specific articles).
Secondary source: macro RSS feeds (Fed, CPI, broad market).
"""

import feedparser
from datetime import datetime, timezone, timedelta
from data_fetcher import fetch_news as _yf_news
from config import MARKET_NEWS_FEEDS, MAX_ARTICLES_PER_FEED

# ── Keyword dictionaries ──────────────────────────────────────────────────────

BULLISH_KW = {
    "earnings beat": 3, "revenue beat": 3, "guidance raised": 3,
    "upgrade":  2, "buy rating":  2, "outperform": 2, "strong buy": 3,
    "record":   1, "record high": 2, "all-time high": 2,
    "ai":       1, "growth":      1, "expansion": 1,
    "rate cut": 2, "dovish":      2, "soft landing": 2,
    "rally":    2, "surge":       2, "breakout": 2,
    "partnership": 1, "acquisition": 1, "buyback": 2,
    "beat":     1, "strong":      1, "positive": 1,
}

BEARISH_KW = {
    "earnings miss": 3, "revenue miss": 3, "guidance cut": 3,
    "downgrade":  2, "sell rating": 2, "underperform": 2,
    "investigation": 2, "lawsuit": 2, "sec": 1, "fine": 2,
    "rate hike": 2, "hawkish": 2, "inflation": 1, "recession": 2,
    "layoffs":   2, "job cuts": 2,
    "miss":      1, "weak":    1, "decline": 1, "drop": 1,
    "crash":     2, "selloff": 2, "warning":  1,
}

# Per-ticker keywords to decide if an article is relevant
_TICKER_KW: dict[str, list[str]] = {
    "AAPL":  ["apple", "aapl", "iphone", "mac", "ipad", "app store"],
    "MSFT":  ["microsoft", "msft", "azure", "windows", "copilot", "activision"],
    "NVDA":  ["nvidia", "nvda", "gpu", "cuda", "blackwell", "hopper", "jensen"],
    "META":  ["meta", "facebook", "instagram", "whatsapp", "zuckerberg"],
    "GOOGL": ["google", "alphabet", "googl", "youtube", "gemini", "search"],
    "AMZN":  ["amazon", "amzn", "aws", "prime", "bezos", "jassy"],
    "TSLA":  ["tesla", "tsla", "musk", "elon", "model", "cybertruck", "ev"],
    "AVGO":  ["broadcom", "avgo", "vmware"],
    "AMD":   ["amd", "advanced micro", "ryzen", "epyc", "radeon", "lisa su"],
    "QCOM":  ["qualcomm", "qcom", "snapdragon"],
    "MU":    ["micron", "mu", "dram", "nand", "memory chip"],
    "AMAT":  ["applied materials", "amat", "semiconductor equipment"],
    "ARM":   ["arm holdings", "arm chip"],
    "MRVL":  ["marvell", "mrvl"],
    "NFLX":  ["netflix", "nflx", "streaming"],
    "ADBE":  ["adobe", "adbe", "photoshop", "firefly"],
    "CRM":   ["salesforce", "crm", "slack"],
    "NOW":   ["servicenow", "now"],
    "SNOW":  ["snowflake", "snow", "data cloud"],
    "PLTR":  ["palantir", "pltr", "karp"],
    "PANW":  ["palo alto", "panw", "cybersecurity"],
    "PYPL":  ["paypal", "pypl", "venmo"],
    "COIN":  ["coinbase", "coin", "crypto exchange"],
    "UBER":  ["uber", "rideshare", "gig economy"],
    "ABNB":  ["airbnb", "abnb", "short-term rental"],
    "QQQ":   ["nasdaq", "qqq", "tech", "fed", "rate"],
    # ── Index futures ───────────────────────────────────────────────────────
    "ES=F":  ["s&p 500", "s&p", "sp500", "e-mini", "wall street", "dow jones", "fed", "rate"],
    "MES=F": ["s&p 500", "s&p", "sp500", "e-mini", "wall street", "fed", "rate"],
    "NQ=F":  ["nasdaq", "tech stocks", "e-mini", "big tech", "fed", "rate"],
    "MNQ=F": ["nasdaq", "tech stocks", "e-mini", "big tech", "fed", "rate"],
    "YM=F":  ["dow jones", "dow", "industrial average", "e-mini", "fed", "rate"],
    "MYM=F": ["dow jones", "dow", "industrial average", "e-mini", "fed", "rate"],
    "RTY=F": ["russell 2000", "small cap", "small-cap", "e-mini", "fed", "rate"],
    "M2K=F": ["russell 2000", "small cap", "small-cap", "e-mini", "fed", "rate"],
    "EMD=F": ["midcap", "mid-cap", "s&p 400", "e-mini", "fed", "rate"],
    "NIY=F": ["nikkei", "japan", "boj", "bank of japan", "yen", "tokyo stock"],
    "MNI=F": ["nikkei", "japan", "boj", "bank of japan", "yen", "tokyo stock"],
}

_MARKET_WIDE = [
    "nasdaq", "stock market", "equities", "s&p", "fed", "federal reserve",
    "fomc", "interest rate", "inflation", "cpi", "gdp", "earnings",
]


def _score(text: str) -> int:
    t = text.lower()
    s = sum(w for kw, w in BULLISH_KW.items() if kw in t)
    s -= sum(w for kw, w in BEARISH_KW.items() if kw in t)
    return s


def _relevant(text: str, ticker: str) -> bool:
    t = text.lower()
    kws = _TICKER_KW.get(ticker, [ticker.lower()])
    return any(k in t for k in kws) or any(k in t for k in _MARKET_WIDE)


def _is_recent(entry) -> bool:
    pub = entry.get("published_parsed") or entry.get("updated_parsed")
    if not pub:
        return True
    dt = datetime(*pub[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - dt < timedelta(hours=24)


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_news_sentiment(ticker: str) -> dict:
    """
    Returns:
        {
          "sentiment_label": "Bullish" | "Bearish" | "Neutral",
          "total_score": int,
          "articles": [{"title", "score", "source"}, ...]
        }
    """
    articles = []
    total    = 0

    # ── Source 1: yfinance news (ticker-specific) ──────────────────────────
    for item in _yf_news(ticker):
        text  = f"{item.get('title', '')} {item.get('summary', '')}"
        s     = _score(text)
        total += s
        articles.append({
            "title":  item.get("title", "")[:100],
            "link":   item.get("link", ""),
            "score":  s,
            "source": f"{ticker} news",
        })

    # ── Source 2: macro RSS feeds ─────────────────────────────────────────
    for feed_url in MARKET_NEWS_FEEDS:
        try:
            feed  = feedparser.parse(feed_url)
            count = 0
            for entry in feed.entries:
                if count >= MAX_ARTICLES_PER_FEED:
                    break
                if not _is_recent(entry):
                    continue
                text = f"{entry.get('title', '')} {entry.get('summary', '')}"
                if not _relevant(text, ticker):
                    continue
                s = _score(text)
                total += s
                articles.append({
                    "title":  entry.get("title", "")[:100],
                    "link":   entry.get("link", ""),
                    "score":  s,
                    "source": feed.feed.get("title", "News"),
                })
                count += 1
        except Exception:
            continue

    articles.sort(key=lambda a: a["score"], reverse=True)

    label = "Bullish" if total > 0 else "Bearish" if total < 0 else "Neutral"
    return {
        "sentiment_label": label,
        "total_score":     total,
        "articles":        articles[:8],
    }
