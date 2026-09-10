import yfinance as yf
import pandas as pd
from config import LOOKBACK_DAYS


def fetch_ohlcv(ticker: str, days: int = LOOKBACK_DAYS) -> pd.DataFrame:
    """Fetch daily OHLCV from Yahoo Finance and normalize column names."""
    t  = yf.Ticker(ticker)
    df = t.history(period=f"{days}d", interval="1d", auto_adjust=True)
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.columns = ["open", "high", "low", "close", "volume"]
    df.index.name = "timestamp"
    df.index = df.index.tz_localize(None)
    if df.empty:
        raise ValueError(f"No data returned for {ticker}")
    return df


def fetch_premarket_info(ticker: str) -> dict:
    """
    Pull pre-market / after-hours price data from Yahoo Finance fast_info.
    Returns a dict with pre-market price, % change vs previous close,
    and pre-market volume.  All values default to 0 / None if unavailable.
    """
    try:
        t  = yf.Ticker(ticker)
        fi = t.fast_info

        prev_close  = float(fi.get("regular_market_previous_close") or fi.get("previous_close") or 0)
        pre_price   = float(fi.get("pre_market_price") or 0)
        post_price  = float(fi.get("post_market_price") or 0)
        pre_vol     = float(fi.get("pre_market_volume") or 0)
        reg_vol_avg = float(fi.get("three_month_average_volume") or fi.get("average_volume") or 1)

        # Use pre-market price if available; fall back to after-hours
        ref_price = pre_price or post_price or prev_close

        change_pct = (
            round((ref_price - prev_close) / prev_close * 100, 2)
            if prev_close and ref_price else 0.0
        )

        # Pre-market volume relative to average daily volume (as %)
        vol_ratio = round(pre_vol / reg_vol_avg * 100, 1) if reg_vol_avg else 0.0

        return {
            "prev_close":    round(prev_close, 2),
            "pre_price":     round(ref_price, 2) if ref_price else None,
            "pre_change_pct": change_pct,
            "pre_volume":    pre_vol,
            "vol_ratio_pct": vol_ratio,          # pre-vol as % of avg daily vol
            "is_gap_up":     change_pct >= 1.0,
            "is_gap_down":   change_pct <= -1.0,
        }
    except Exception:
        return {
            "prev_close": 0, "pre_price": None, "pre_change_pct": 0,
            "pre_volume": 0, "vol_ratio_pct": 0,
            "is_gap_up": False, "is_gap_down": False,
        }


def fetch_news(ticker: str) -> list[dict]:
    """
    Pull the most recent news articles for a stock from Yahoo Finance.
    Returns a list of dicts with 'title', 'summary', 'link'.
    """
    try:
        t = yf.Ticker(ticker)
        raw = t.news or []
        articles = []
        for item in raw[:10]:
            content = item.get("content", {})
            articles.append({
                "title":   content.get("title", item.get("title", "")),
                "summary": content.get("summary", item.get("summary", "")),
                "link":    (content.get("canonicalUrl") or {}).get("url", item.get("link", "")),
            })
        return articles
    except Exception:
        return []
