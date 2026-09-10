from config import (
    ACCOUNT_SIZE_USD, RISK_PER_TRADE_PCT,
    ATR_STOP_MULT, PROFIT_TARGET_PCT, MAX_STOP_PCT, MIN_REWARD_RISK,
    FUTURES_ATR_STOP_MULT, FUTURES_ATR_TARGET_MULT,
    FUTURES_MAX_STOP_PCT, FUTURES_MIN_REWARD_RISK,
    FUTURES_MAX_RISK_PCT, FUTURES_WATCHLIST,
    COMPETITION_RISK_PCT, COMP_ATR_STOP_MULT, COMP_ATR_TARGET_MULT,
    COMP_MIN_REWARD_RISK, COMP_MAX_STOP_PCT_STOCK, COMP_MAX_STOP_PCT_FUTURES,
)


def build_trade_setup(
    ticker:   str,
    analysis: dict,             # output of strategies.run_all()
    news:     dict,             # output of news_scraper.fetch_news_sentiment()
    premarket: dict | None = None,  # output of data_fetcher.fetch_premarket_info()
    mode: str = "market",       # "premarket" | "market"
) -> dict | None:
    """
    Build a trade setup targeting PROFIT_TARGET_PCT (default 5%).

    Stop is ATR-based (adapts to each stock's volatility).
    Trade is rejected if:
      - ATR-based stop exceeds MAX_STOP_PCT (stock is too volatile for the target)
      - R:R falls below MIN_REWARD_RISK

    For pre-market mode, entry uses the pre-market price if available.
    """
    direction = analysis["direction"]
    close     = analysis["close"]
    atr       = analysis.get("atr")

    if direction == "HOLD" or not atr or atr <= 0:
        return None

    # Entry: use pre-market price when available during pre-market scan
    if mode == "premarket" and premarket and premarket.get("pre_price"):
        entry = float(premarket["pre_price"])
    else:
        entry = close

    # ── Stop: ATR-based (adapts to volatility) ────────────────────────────────
    stop_dist    = atr * ATR_STOP_MULT
    stop_pct_val = stop_dist / entry * 100

    # Reject if the stop is wider than MAX_STOP_PCT — target too small relative to risk
    if stop_pct_val > MAX_STOP_PCT:
        return None

    if direction == "BUY":
        stop_loss = round(entry - stop_dist, 2)
        target    = round(entry * (1 + PROFIT_TARGET_PCT / 100), 2)  # 5% above entry
    else:
        stop_loss = round(entry + stop_dist, 2)
        target    = round(entry * (1 - PROFIT_TARGET_PCT / 100), 2)  # 5% below entry

    risk_per_share   = abs(entry - stop_loss)
    reward_per_share = abs(target - entry)

    if risk_per_share <= 0:
        return None

    rr = reward_per_share / risk_per_share
    if rr < MIN_REWARD_RISK:
        return None

    risk_usd     = ACCOUNT_SIZE_USD * RISK_PER_TRADE_PCT
    shares       = risk_usd / risk_per_share
    position_usd = shares * entry

    key_level = analysis.get("key_level")

    # Reason string
    strategy_names = [
        t["name"] for t in analysis.get("triggered", [])
        if t["score"] * (1 if direction == "BUY" else -1) > 0
    ]
    reason_parts = []
    if strategy_names:
        reason_parts.append(", ".join(strategy_names[:4]))
    if news["sentiment_label"] != "Neutral":
        reason_parts.append(f"News {news['sentiment_label']}")
    if premarket and abs(premarket.get("pre_change_pct", 0)) >= 0.5:
        sign = "+" if premarket["pre_change_pct"] > 0 else ""
        reason_parts.append(f"Pre-mkt {sign}{premarket['pre_change_pct']:.1f}%")
    reason = " | ".join(reason_parts) or f"{ticker} {direction} setup"

    return {
        "ticker":          ticker,
        "direction":       direction,
        "mode":            mode,
        "entry":           round(entry, 2),
        "stop_loss":       round(stop_loss, 2),
        "target":          round(target, 2),
        "stop_pct":        round(stop_pct_val, 2),
        "target_pct":      PROFIT_TARGET_PCT,
        "rr_ratio":        round(rr, 2),
        "risk_usd":        round(risk_usd, 2),
        "shares":          round(shares, 4),
        "position_usd":    round(position_usd, 2),
        "key_level":       round(key_level, 2) if key_level else None,
        "reason":          reason,
        "strategy_score":  analysis["score"],
        "triggered":       analysis["triggered"],
        "all_signals":     analysis["all_signals"],
        "news_sentiment":  news["sentiment_label"],
        "news_score":      news["total_score"],
        "news_articles":   news["articles"],
        "rsi":             analysis.get("rsi"),
        "atr":             round(atr, 2),
        "premarket":       premarket,
        "instrument_type": "stock",
        "multiplier":      1.0,
        "display_name":    ticker,
    }


def build_futures_trade_setup(
    ticker:   str,
    analysis: dict,             # output of strategies.run_all()
    news:     dict,             # output of news_scraper.fetch_news_sentiment()
    fx_rate:  float = 1.0,      # JPY→USD conversion if instrument is yen-denominated
) -> dict | None:
    """
    Build a futures trade setup using ATR-based target/stop (2:1 R:R) instead
    of a fixed percentage — index futures don't move 5% intraday under normal
    conditions, so a fixed-% target would almost never fill or would represent
    an unrealistic move.

    Position sizing is in CONTRACTS, not shares:
        contracts = risk_usd / (stop_points * multiplier_usd)
    Minimum 1 contract (you can't trade a fraction of a futures contract).
    """
    spec = FUTURES_WATCHLIST.get(ticker)
    if not spec:
        return None

    direction = analysis["direction"]
    close     = analysis["close"]
    atr       = analysis.get("atr")

    if direction == "HOLD" or not atr or atr <= 0:
        return None

    entry = close

    stop_dist    = atr * FUTURES_ATR_STOP_MULT
    target_dist  = atr * FUTURES_ATR_TARGET_MULT
    stop_pct_val = stop_dist / entry * 100

    if stop_pct_val > FUTURES_MAX_STOP_PCT:
        return None

    if direction == "BUY":
        stop_loss = round(entry - stop_dist, 2)
        target    = round(entry + target_dist, 2)
    else:
        stop_loss = round(entry + stop_dist, 2)
        target    = round(entry - target_dist, 2)

    risk_points   = abs(entry - stop_loss)
    reward_points = abs(target - entry)

    if risk_points <= 0:
        return None

    rr = reward_points / risk_points
    if rr < FUTURES_MIN_REWARD_RISK:
        return None

    # Multiplier is in the instrument's native currency — convert to USD for sizing
    multiplier_native = spec["multiplier"]
    multiplier_usd     = multiplier_native / fx_rate if spec["currency"] == "JPY" else multiplier_native

    risk_usd      = ACCOUNT_SIZE_USD * RISK_PER_TRADE_PCT
    risk_per_contract = risk_points * multiplier_usd
    contracts     = max(1, round(risk_usd / risk_per_contract)) if risk_per_contract > 0 else 1
    actual_risk_usd = risk_per_contract * contracts

    # Reject if even 1 contract overshoots the account risk cap (full-size
    # contracts on a small account — e.g. ES at $50/pt vs a $10k account).
    if actual_risk_usd > ACCOUNT_SIZE_USD * FUTURES_MAX_RISK_PCT:
        return None

    key_level = analysis.get("key_level")

    strategy_names = [
        t["name"] for t in analysis.get("triggered", [])
        if t["score"] * (1 if direction == "BUY" else -1) > 0
    ]
    reason_parts = []
    if strategy_names:
        reason_parts.append(", ".join(strategy_names[:4]))
    if news["sentiment_label"] != "Neutral":
        reason_parts.append(f"News {news['sentiment_label']}")
    reason = " | ".join(reason_parts) or f"{ticker} {direction} setup"

    return {
        "ticker":          ticker,
        "display_name":    spec["name"],
        "direction":       direction,
        "mode":            "futures",
        "entry":           round(entry, 2),
        "stop_loss":       round(stop_loss, 2),
        "target":          round(target, 2),
        "stop_pct":        round(stop_pct_val, 2),
        "target_pct":      round(target_dist / entry * 100, 2),
        "rr_ratio":        round(rr, 2),
        "risk_usd":        round(actual_risk_usd, 2),
        "contracts":       contracts,
        "shares":          contracts,                       # alias for shared display code
        "position_usd":    round(entry * multiplier_usd * contracts, 2),
        "key_level":       round(key_level, 2) if key_level else None,
        "reason":          reason,
        "strategy_score":  analysis["score"],
        "triggered":       analysis["triggered"],
        "all_signals":     analysis["all_signals"],
        "news_sentiment":  news["sentiment_label"],
        "news_score":      news["total_score"],
        "news_articles":   news["articles"],
        "rsi":             analysis.get("rsi"),
        "atr":             round(atr, 2),
        "premarket":       None,
        "instrument_type": "future",
        "multiplier":      multiplier_native,
        "currency":        spec["currency"],
        "risk_points":     round(risk_points, 2),
        "reward_points":   round(reward_points, 2),
    }


def build_competition_setup(
    ticker:   str,
    analysis: dict,             # output of strategies.run_all()
    news:     dict,             # output of news_scraper.fetch_news_sentiment()
    fx_rate:  float = 1.0,      # JPY→USD conversion (only relevant for Nikkei futures)
) -> dict | None:
    """
    Competition mode: bigger target (5× ATR), tight stop (1× ATR), demands a
    big payoff (min 3:1 R:R). Works for both stocks and futures — detects
    which one `ticker` is and applies the right position-sizing math.

    Adds "competition_score" = |weighted strategy score| × R:R, used to rank
    every candidate and surface the single best trade.
    """
    is_future = ticker in FUTURES_WATCHLIST
    spec      = FUTURES_WATCHLIST.get(ticker)

    direction = analysis["direction"]
    close     = analysis["close"]
    atr       = analysis.get("atr")

    if direction == "HOLD" or not atr or atr <= 0:
        return None

    entry = close
    stop_dist    = atr * COMP_ATR_STOP_MULT
    target_dist  = atr * COMP_ATR_TARGET_MULT
    stop_pct_val = stop_dist / entry * 100

    max_stop = COMP_MAX_STOP_PCT_FUTURES if is_future else COMP_MAX_STOP_PCT_STOCK
    if stop_pct_val > max_stop:
        return None

    if direction == "BUY":
        stop_loss = round(entry - stop_dist, 2)
        target    = round(entry + target_dist, 2)
    else:
        stop_loss = round(entry + stop_dist, 2)
        target    = round(entry - target_dist, 2)

    risk_dist   = abs(entry - stop_loss)
    reward_dist = abs(target - entry)
    if risk_dist <= 0:
        return None

    rr = reward_dist / risk_dist
    if rr < COMP_MIN_REWARD_RISK:
        return None

    risk_usd = ACCOUNT_SIZE_USD * COMPETITION_RISK_PCT

    if is_future:
        multiplier_native = spec["multiplier"]
        multiplier_usd     = multiplier_native / fx_rate if spec["currency"] == "JPY" else multiplier_native
        risk_per_contract  = risk_dist * multiplier_usd
        qty       = max(1, round(risk_usd / risk_per_contract)) if risk_per_contract > 0 else 1
        actual_risk_usd = risk_per_contract * qty
        # Even in competition mode, don't let 1 contract blow past 2x the intended risk
        if actual_risk_usd > risk_usd * 2:
            return None
        position_usd = entry * multiplier_usd * qty
        display_name = spec["name"]
        instrument_type = "future"
        multiplier = multiplier_native
        currency = spec["currency"]
    else:
        qty = risk_usd / risk_dist
        actual_risk_usd = risk_usd
        position_usd = qty * entry
        display_name = ticker
        instrument_type = "stock"
        multiplier = 1.0
        currency = "USD"

    key_level = analysis.get("key_level")

    strategy_names = [
        t["name"] for t in analysis.get("triggered", [])
        if t["score"] * (1 if direction == "BUY" else -1) > 0
    ]
    reason_parts = []
    if strategy_names:
        reason_parts.append(", ".join(strategy_names[:4]))
    if news["sentiment_label"] != "Neutral":
        reason_parts.append(f"News {news['sentiment_label']}")
    reason = " | ".join(reason_parts) or f"{ticker} {direction} setup"

    competition_score = abs(analysis["score"]) * rr

    return {
        "ticker":             ticker,
        "display_name":       display_name,
        "direction":          direction,
        "mode":               "competition",
        "entry":              round(entry, 2),
        "stop_loss":          round(stop_loss, 2),
        "target":             round(target, 2),
        "stop_pct":           round(stop_pct_val, 2),
        "target_pct":         round(target_dist / entry * 100, 2),
        "rr_ratio":           round(rr, 2),
        "risk_usd":           round(actual_risk_usd, 2),
        "contracts":          qty if is_future else None,
        "shares":             round(qty, 4),
        "position_usd":       round(position_usd, 2),
        "key_level":          round(key_level, 2) if key_level else None,
        "reason":             reason,
        "strategy_score":     analysis["score"],
        "competition_score":  round(competition_score, 2),
        "triggered":          analysis["triggered"],
        "all_signals":        analysis["all_signals"],
        "news_sentiment":     news["sentiment_label"],
        "news_score":         news["total_score"],
        "news_articles":      news["articles"],
        "rsi":                analysis.get("rsi"),
        "atr":                round(atr, 2),
        "premarket":          None,
        "instrument_type":    instrument_type,
        "multiplier":         multiplier,
        "currency":           currency,
        "risk_points":        round(risk_dist, 2) if is_future else None,
        "reward_points":      round(reward_dist, 2) if is_future else None,
    }
