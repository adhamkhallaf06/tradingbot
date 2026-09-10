"""
Eight trading strategies extracted from the video transcript.

Each detector returns (score: int, signals: list[str], key_level: float | None).
  score > 0 → bullish contribution
  score < 0 → bearish contribution

run_all(df) aggregates everything and returns the final analysis dict.
"""

from __future__ import annotations
import pandas as pd
import numpy as np
from config import RSI_OVERSOLD, RSI_OVERBOUGHT


# ── 1. Breakout Buildup ────────────────────────────────────────────────────────
# Uptrend → pause at resistance → successive rejections get WEAKER → high-
# momentum breakout. Conviction is much higher when breakout happens early in
# the session (we flag that separately in main.py using market-hours context).

def detect_breakout_buildup(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    score, signals = 0, []
    if len(df) < 30:
        return score, signals, None

    close = float(df.iloc[-1]["close"])

    # Resistance = highest high in the 5–25 bars back window
    resistance = float(df.iloc[-25:-2]["high"].max())

    # Find tests of resistance (bar whose high is within 1% of resistance)
    tests: list[float] = []
    for i in range(max(0, len(df) - 25), len(df) - 2):
        row = df.iloc[i]
        if float(row["high"]) >= resistance * 0.99:
            # Rejection size = drop from the high within the next 5 bars
            future = df.iloc[i + 1 : min(i + 6, len(df))]
            if not future.empty:
                drop = (float(row["high"]) - float(future["low"].min())) / float(row["high"]) * 100
                tests.append(drop)

    # Check for weakening rejections (each one ≥30% smaller than the prior)
    if len(tests) >= 2 and tests[-1] < tests[-2] * 0.70:
        score += 2
        signals.append(
            f"Weakening rejections at ${resistance:.2f} "
            f"({tests[-2]:.1f}% → {tests[-1]:.1f}% drop) — buyers absorbing sellers"
        )

    # Breakout: price above resistance
    if close > resistance:
        last_range  = float(df.iloc[-1]["range"])
        avg_range   = float(df.iloc[-20:-1]["range"].mean())
        mult        = last_range / avg_range if avg_range > 0 else 1
        if mult >= 1.5:
            score += 4
            signals.append(
                f"High-momentum breakout above ${resistance:.2f} "
                f"(candle {mult:.1f}× avg size) ← high conviction"
            )
        else:
            score += 2
            signals.append(f"Breakout above resistance ${resistance:.2f}")
        return score, signals, resistance

    # Approaching resistance (within 2%)
    dist = (close - resistance) / resistance * 100
    if dist >= -2:
        score += 1
        signals.append(f"Approaching resistance ${resistance:.2f} ({dist:.1f}%)")

    return score, signals, resistance


# ── 2. Supply & Demand Zones ──────────────────────────────────────────────────
# Find outlier candles (body > 2× average). The consolidation *before* the
# outlier = demand zone. Zone stacking: prefer the lowest zone.
# Stop placement: 30% below zone width (as described in the video).

def detect_supply_demand(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    score, signals = 0, []
    if len(df) < 50:
        return score, signals, None

    close = float(df.iloc[-1]["close"])

    # Build demand zones from bullish outlier candles
    demand_zones: list[dict] = []
    for i in range(10, len(df) - 3):
        row   = df.iloc[i]
        b_avg = df["body_avg20"].iloc[i]
        if pd.isna(b_avg) or b_avg == 0:
            continue
        is_bullish_outlier = (
            float(row["body"]) > b_avg * 2.0
            and float(row["close"]) > float(row["open"])
        )
        if is_bullish_outlier:
            consol    = df.iloc[max(0, i - 8) : i]
            zone_low  = float(consol["low"].min())
            zone_high = float(consol["high"].max())
            if zone_high > zone_low:
                demand_zones.append({"low": zone_low, "high": zone_high, "bar": i})

    if not demand_zones:
        return score, signals, None

    # Zone stacking: keep only zones the price hasn't traded below recently
    valid = [z for z in demand_zones if close > z["low"] * 0.97]
    if not valid:
        return score, signals, None

    # Use the lowest zone (as the video recommends)
    zone  = min(valid, key=lambda z: z["low"])
    z_lo  = zone["low"]
    z_hi  = zone["high"]
    width = z_hi - z_lo

    if z_lo <= close <= z_hi * 1.02:
        score += 3
        stop_hint = round(z_lo - width * 0.30, 2)
        signals.append(
            f"Price in demand zone ${z_lo:.2f}–${z_hi:.2f} "
            f"(suggested stop ${stop_hint:.2f} = 30% below zone)"
        )
        return score, signals, z_lo
    elif z_hi < close <= z_hi * 1.08:
        score += 1
        signals.append(f"Just above demand zone ${z_lo:.2f}–${z_hi:.2f} — watch for pullback entry")

    return score, signals, z_lo


# ── 3. Dirty Retest ───────────────────────────────────────────────────────────
# After a breakout the market pulls back into the old resistance (now support).
# Stop zone = where breakout traders would have placed stops. Strong immediate
# momentum away from that zone = very high-probability continuation.

def detect_dirty_retest(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    score, signals = 0, []
    if len(df) < 20:
        return score, signals, None

    close = float(df.iloc[-1]["close"])

    # Previous resistance = high of bars 10–25 back
    prev_res = float(df.iloc[-25:-10]["high"].max())

    # Was there a breakout in the last 10 bars?
    breakout_occurred = any(
        float(df.iloc[i]["close"]) > prev_res and float(df.iloc[i - 1]["close"]) <= prev_res
        for i in range(-10, -2)
    )
    if not breakout_occurred:
        return score, signals, None

    # Is price now near the old resistance (within 1.5%)?
    dist = abs(close - prev_res) / prev_res * 100
    if dist > 1.5:
        return score, signals, None

    # Strength of current candle away from the level
    last_range  = float(df.iloc[-1]["range"])
    avg_range   = float(df["range_avg20"].iloc[-1]) or 1
    mult        = last_range / avg_range

    if mult >= 1.3 and close > prev_res:
        score += 5
        signals.append(
            f"Dirty retest — price swept stop zone at ${prev_res:.2f} "
            f"then pushed away hard ({mult:.1f}× avg candle)"
        )
    elif close > prev_res:
        score += 3
        signals.append(
            f"Dirty retest holding ${prev_res:.2f} as new support"
        )

    return score, signals, prev_res


# ── 4. RSI Divergence ─────────────────────────────────────────────────────────
# Bullish: price making lower lows, RSI making higher lows → downtrend losing
# strength. Bearish: price making higher highs, RSI making lower highs.

def detect_rsi_divergence(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    score, signals = 0, []
    rsi_col = "RSI_14"
    if rsi_col not in df.columns or len(df) < 25:
        return score, signals, None

    lb   = df.tail(25).copy().reset_index(drop=True)
    rsi  = lb[rsi_col].to_numpy(dtype=float)
    lows = lb["low"].to_numpy(dtype=float)
    highs = lb["high"].to_numpy(dtype=float)

    # Find swing lows (local minima)
    swing_lows = [
        i for i in range(1, len(lb) - 1)
        if lows[i] < lows[i - 1] and lows[i] < lows[i + 1] and not np.isnan(rsi[i])
    ]
    if len(swing_lows) >= 2:
        p1, p2 = swing_lows[-2], swing_lows[-1]
        if lows[p2] < lows[p1] and rsi[p2] > rsi[p1]:   # bullish divergence
            score += 3
            signals.append(
                f"Bullish RSI divergence — price lower low but RSI higher low "
                f"({rsi[p1]:.0f} → {rsi[p2]:.0f}) — downtrend losing steam"
            )

    # Find swing highs (local maxima)
    swing_highs = [
        i for i in range(1, len(lb) - 1)
        if highs[i] > highs[i - 1] and highs[i] > highs[i + 1] and not np.isnan(rsi[i])
    ]
    if len(swing_highs) >= 2:
        p1, p2 = swing_highs[-2], swing_highs[-1]
        if highs[p2] > highs[p1] and rsi[p2] < rsi[p1]:  # bearish divergence
            score -= 3
            signals.append(
                f"Bearish RSI divergence — price higher high but RSI lower high "
                f"({rsi[p1]:.0f} → {rsi[p2]:.0f}) — uptrend losing steam"
            )

    return score, signals, None


# ── 5. Candlestick Patterns (Morning Star / Evening Star / Fakeout) ───────────
# Morning star = bullish reversal. Evening star = bearish fakeout reversal.
# These are especially powerful near key levels.

def detect_candlestick_patterns(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    score, signals = 0, []
    if len(df) < 5:
        return score, signals, None

    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    avg_body    = float(df["body_avg20"].iloc[-1]) or 1

    b1 = float(c1["body"])
    b2 = float(c2["body"])
    b3 = float(c3["body"])

    # Morning star (bullish reversal)
    morning_star = (
        float(c1["close"]) < float(c1["open"])   # c1 bearish
        and b1 > avg_body * 1.3
        and b2 < avg_body * 0.5                  # c2 doji/small
        and float(c3["close"]) > float(c3["open"])  # c3 bullish
        and b3 > avg_body * 1.3
        and float(c3["close"]) > (float(c1["open"]) + float(c1["close"])) / 2
    )

    # Evening star (bearish fakeout / reversal)
    evening_star = (
        float(c1["close"]) > float(c1["open"])
        and b1 > avg_body * 1.3
        and b2 < avg_body * 0.5
        and float(c3["close"]) < float(c3["open"])
        and b3 > avg_body * 1.3
        and float(c3["close"]) < (float(c1["open"]) + float(c1["close"])) / 2
    )

    if morning_star:
        score += 4
        signals.append("Morning star pattern — high-probability bullish reversal")
    if evening_star:
        score -= 4
        signals.append("Evening star / fakeout pattern — high-probability bearish reversal")

    return score, signals, None


# ── 6. Round Numbers ──────────────────────────────────────────────────────────
# Many traders and algos cluster orders around round numbers.
# A bounce or break of a round number carries extra conviction.

def detect_round_numbers(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    score, signals = 0, []
    if len(df) < 3:
        return score, signals, None

    close = float(df.iloc[-1]["close"])
    prev  = float(df.iloc[-2]["close"])

    # Choose increment based on price range
    if close < 10:
        incs = [0.5, 1]
    elif close < 50:
        incs = [1, 5, 10]
    elif close < 200:
        incs = [5, 10, 25, 50, 100]
    elif close < 1_000:
        incs = [10, 25, 50, 100, 250]
    else:
        incs = [50, 100, 250, 500]

    for inc in incs:
        nearest = round(close / inc) * inc
        if nearest == 0:
            continue
        dist_pct = abs(close - nearest) / nearest * 100
        if dist_pct < 0.75:
            if prev < nearest <= close:
                score += 2
                signals.append(f"Bounced through round number ${nearest:.0f} ↑")
            elif prev > nearest >= close:
                score -= 2
                signals.append(f"Broke through round number ${nearest:.0f} ↓")
            else:
                score += 1
                signals.append(f"Hugging round number ${nearest:.0f} ({dist_pct:.2f}% away)")
            return score, signals, float(nearest)

    return score, signals, None


# ── 7. Previous Day High / Low ────────────────────────────────────────────────
# Intraday traders watch these levels closely. Breaking above PDH = bullish
# momentum. Reversing from PDL = potential bottom.

def detect_prev_day_hl(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    score, signals = 0, []
    if len(df) < 3:
        return score, signals, None

    close    = float(df.iloc[-1]["close"])
    pdh      = float(df.iloc[-2]["high"])
    pdl      = float(df.iloc[-2]["low"])
    prev_c   = float(df.iloc[-2]["close"])

    if close > pdh:
        score += 2
        signals.append(f"Breaking above previous day high ${pdh:.2f} — bullish momentum")
    elif close >= pdh * 0.99:
        score += 1
        signals.append(f"Testing previous day high ${pdh:.2f} as resistance")
    elif close <= pdl * 1.01:
        # Bouncing off previous day low?
        cur_c = float(df.iloc[-1]["close"])
        if cur_c > pdl and float(df.iloc[-1]["open"]) < pdl:
            score += 2
            signals.append(f"Reversal from previous day low ${pdl:.2f} — potential bottom")
        else:
            score -= 2
            signals.append(f"Breaking below previous day low ${pdl:.2f} — bearish")
    elif close < pdl:
        score -= 2
        signals.append(f"Beneath previous day low ${pdl:.2f}")

    return score, signals, pdh


# ── 8. Fibonacci Retracement ──────────────────────────────────────────────────
# Find the most recent clean A→B swing, then check if price has retraced to
# the 61.8% level (golden pocket). Target = 161.8% extension.

def detect_fibonacci(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    score, signals = 0, []
    if len(df) < 30:
        return score, signals, None

    close  = float(df.iloc[-1]["close"])
    recent = df.tail(40)

    # Find swing low A and swing high B within the lookback
    A_idx  = int(recent["low"].idxmin())
    B_idx  = int(recent["high"].idxmax())
    A_loc  = recent.index.get_loc(A_idx)
    B_loc  = recent.index.get_loc(B_idx)

    if A_loc >= B_loc:
        return score, signals, None  # no clean upswing

    A = float(recent.iloc[A_loc]["low"])
    B = float(recent.iloc[B_loc]["high"])
    if B - A < A * 0.03:          # swing must be at least 3%
        return score, signals, None

    fib_618  = round(B - (B - A) * 0.618, 2)
    fib_382  = round(B - (B - A) * 0.382, 2)
    fib_1618 = round(B + (B - A) * 0.618, 2)

    d618 = abs(close - fib_618) / fib_618 * 100
    d382 = abs(close - fib_382) / fib_382 * 100

    if d618 < 1.5:
        score += 3
        signals.append(
            f"At 61.8% Fib retracement ${fib_618:.2f} "
            f"(A=${A:.2f}, B=${B:.2f}) — target ${fib_1618:.2f}"
        )
        return score, signals, fib_618
    elif d382 < 1.5:
        score += 2
        signals.append(f"At 38.2% Fib retracement ${fib_382:.2f} — target ${fib_1618:.2f}")
        return score, signals, fib_382

    return score, signals, None


# ── 9. EMA Pullback (50 EMA) ──────────────────────────────────────────────────
# The "daily driver" from the article.
# In a clear trend, wait for a pullback to the 50 EMA, then enter on a
# rejection candle: pin bar, bullish engulfing, or strong wick.
# Backtested win rate on EUR/USD & GBP/USD: ~63% at 1:1.8 R:R.

def _is_bullish_pin_bar(row: pd.Series, avg_range: float) -> bool:
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    total     = h - l
    body      = abs(c - o)
    lower_wick = min(c, o) - l
    if total < avg_range * 0.3 or total == 0:
        return False
    return (
        lower_wick > total * 0.50      # big lower wick
        and body < total * 0.35        # small body
        and c > o                      # closes bullish
    )


def _is_bullish_engulfing(prev: pd.Series, curr: pd.Series) -> bool:
    return (
        float(curr["close"]) > float(curr["open"])   # current bullish
        and float(prev["close"]) < float(prev["open"])  # previous bearish
        and float(curr["open"])  <= float(prev["close"])
        and float(curr["close"]) >= float(prev["open"])
    )


def detect_ema_pullback(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    score, signals = 0, []
    ema_col = "EMA_50"
    if ema_col not in df.columns or len(df) < 55:
        return score, signals, None

    close   = float(df.iloc[-1]["close"])
    ema50   = float(df.iloc[-1][ema_col])
    if pd.isna(ema50):
        return score, signals, None

    # ── Step 1: Confirm uptrend — price above EMA50 for last 5 bars ────────
    above_ema = all(
        float(df.iloc[i]["close"]) > float(df.iloc[i][ema_col])
        for i in range(-6, -1)
        if not pd.isna(df.iloc[i][ema_col])
    )
    downtrend = all(
        float(df.iloc[i]["close"]) < float(df.iloc[i][ema_col])
        for i in range(-6, -1)
        if not pd.isna(df.iloc[i][ema_col])
    )
    if not above_ema and not downtrend:
        return score, signals, None

    # ── Step 2: Pullback — current price within 1.5% of the EMA ──────────
    dist_pct = (close - ema50) / ema50 * 100
    if abs(dist_pct) > 1.5:
        return score, signals, None

    avg_range = float(df["range_avg20"].iloc[-1]) or 1

    # ── Step 3: Rejection candle ─────────────────────────────────────────
    last = df.iloc[-1]
    prev = df.iloc[-2]

    if above_ema:   # bullish pullback
        if _is_bullish_pin_bar(last, avg_range):
            score += 4
            signals.append(
                f"EMA Pullback — bullish pin bar at 50 EMA (${ema50:.2f}), "
                f"dist={dist_pct:+.2f}%"
            )
        elif _is_bullish_engulfing(prev, last):
            score += 4
            signals.append(
                f"EMA Pullback — bullish engulfing at 50 EMA (${ema50:.2f})"
            )
        else:
            score += 1
            signals.append(
                f"EMA Pullback — touching 50 EMA (${ema50:.2f}) in uptrend, "
                f"waiting for rejection candle"
            )
    else:  # bearish pullback to EMA from below
        o, h, l, c = float(last["open"]), float(last["high"]), float(last["low"]), float(last["close"])
        total    = h - l
        up_wick  = h - max(c, o)
        body     = abs(c - o)
        if total > 0 and up_wick > total * 0.5 and body < total * 0.35 and c < o:
            score -= 4
            signals.append(
                f"EMA Pullback — bearish pin bar at 50 EMA (${ema50:.2f}) in downtrend"
            )

    return score, signals, ema50


# ── 10. Breakout + Retest Setup ───────────────────────────────────────────────
# From the article: find S/R with 3+ touches, wait for a strong-body breakout,
# then let price come back and enter on a confirmation candle.
# Rules: never enter on the first breakout candle; SL below level; TP = 2× SL.

def detect_breakout_retest(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    score, signals = 0, []
    if len(df) < 40:
        return score, signals, None

    close   = float(df.iloc[-1]["close"])
    avg_rng = float(df["range_avg20"].iloc[-1]) or 1

    # ── Step 1: Find S/R level with 3+ touches ───────────────────────────
    # A "touch" = bar whose high or low comes within 0.5% of a pivot level
    lookback = df.iloc[-40:-2]
    pivot_highs = []
    for i in range(1, len(lookback) - 1):
        h = float(lookback.iloc[i]["high"])
        if h > float(lookback.iloc[i - 1]["high"]) and h > float(lookback.iloc[i + 1]["high"]):
            pivot_highs.append(h)

    # Cluster pivot highs to find S/R levels
    sr_level = None
    best_touches = 0
    for pivot in pivot_highs:
        touches = sum(
            1 for _, row in lookback.iterrows()
            if abs(float(row["high"]) - pivot) / pivot < 0.005
            or abs(float(row["low"]) - pivot) / pivot < 0.005
        )
        if touches >= 3 and touches > best_touches:
            best_touches = touches
            sr_level = pivot

    if sr_level is None:
        return score, signals, None

    # ── Step 2: Was there a strong-body breakout in last 5 bars? ─────────
    breakout_bar = None
    for i in range(-6, -1):
        bar  = df.iloc[i]
        body = float(bar["body"])
        rng  = float(bar["range"])
        if rng == 0:
            continue
        body_ratio = body / rng
        broke_up   = float(bar["close"]) > sr_level and float(df.iloc[i - 1]["close"]) <= sr_level
        broke_down = float(bar["close"]) < sr_level and float(df.iloc[i - 1]["close"]) >= sr_level

        if body_ratio >= 0.6 and (broke_up or broke_down):
            breakout_bar = {"idx": i, "up": broke_up, "level": sr_level}
            break

    if not breakout_bar:
        return score, signals, None

    direction_up = breakout_bar["up"]
    level        = breakout_bar["level"]

    # ── Step 3: Has price retested the level? ────────────────────────────
    dist_pct = (close - level) / level * 100

    if direction_up and 0 <= dist_pct <= 1.0:
        # Price came back to test former resistance as support
        last = df.iloc[-1]
        prev = df.iloc[-2]
        if _is_bullish_engulfing(prev, last):
            score += 5
            signals.append(
                f"Breakout+Retest — bullish engulfing at retested level ${level:.2f} "
                f"({best_touches} touches) — high conviction"
            )
        elif _is_bullish_pin_bar(last, avg_rng):
            score += 4
            signals.append(
                f"Breakout+Retest — pin bar at retested support ${level:.2f} "
                f"({best_touches} touches)"
            )
        else:
            score += 2
            signals.append(
                f"Breakout+Retest — price back at ${level:.2f} after breakout, "
                f"waiting for confirmation candle"
            )
        return score, signals, level

    elif not direction_up and -1.0 <= dist_pct <= 0:
        # Price came back to test former support as resistance
        last = df.iloc[-1]
        o, h, l, c = float(last["open"]), float(last["high"]), float(last["low"]), float(last["close"])
        total   = h - l
        up_wick = h - max(c, o)
        body    = abs(c - o)
        bearish_engulf = (
            float(df.iloc[-2]["close"]) > float(df.iloc[-2]["open"])
            and c < o
            and float(last["open"]) >= float(df.iloc[-2]["close"])
            and c <= float(df.iloc[-2]["open"])
        )
        if total > 0 and up_wick > total * 0.5 and body < total * 0.35 and c < o:
            score -= 5
            signals.append(
                f"Breakout+Retest — bearish pin bar at retested resistance ${level:.2f}"
            )
        elif bearish_engulf:
            score -= 5
            signals.append(
                f"Breakout+Retest — bearish engulfing at retested resistance ${level:.2f}"
            )
        else:
            score -= 2
            signals.append(
                f"Breakout+Retest — price back at ${level:.2f} after down-breakout, "
                f"waiting for bearish confirmation"
            )
        return score, signals, level

    return score, signals, None


# ── Backtest weight loader ─────────────────────────────────────────────────────
# backtester.py writes win rates here; we convert them to score multipliers.
# Strategies with no backtest data default to weight 1.0.

import json, os as _os

_RESULTS_PATH = _os.path.join(_os.path.dirname(__file__), "backtest_results.json")


def _load_weights() -> dict[str, float]:
    """
    Load per-strategy aggregate win rates and convert to score multipliers.
    win_rate >= 65% → 1.5×  |  50–65% → 1.0×  |  35–50% → 0.75×  |  <35% → 0.5×
    """
    if not _os.path.exists(_RESULTS_PATH):
        return {}
    try:
        with open(_RESULTS_PATH) as f:
            data = json.load(f)
        weights = {}
        for name, stats in data.get("aggregate", {}).items():
            wr = stats.get("win_rate", 50.0)
            if wr >= 65:
                weights[name] = 1.5
            elif wr >= 50:
                weights[name] = 1.0
            elif wr >= 35:
                weights[name] = 0.75
            else:
                weights[name] = 0.5
        return weights
    except Exception:
        return {}


# ── Aggregate ─────────────────────────────────────────────────────────────────

from chart_patterns import PATTERN_DETECTORS

_DETECTORS = [
    # ── Original 8 strategies (video transcript) ──────────────────────────
    ("Breakout Buildup",     detect_breakout_buildup),
    ("Supply & Demand",      detect_supply_demand),
    ("Dirty Retest",         detect_dirty_retest),
    ("RSI Divergence",       detect_rsi_divergence),
    ("Candlestick Patterns", detect_candlestick_patterns),
    ("Round Numbers",        detect_round_numbers),
    ("Prev Day H/L",         detect_prev_day_hl),
    ("Fibonacci",            detect_fibonacci),
    # ── Article strategies ────────────────────────────────────────────────
    ("EMA Pullback",         detect_ema_pullback),
    ("Breakout Retest",      detect_breakout_retest),
    # ── Chart pattern library (12 patterns) ──────────────────────────────
    *PATTERN_DETECTORS,
]


def run_all(df: pd.DataFrame, use_weights: bool = True) -> dict:
    """
    Run every strategy detector, apply backtest win-rate weights, and return
    an aggregated analysis dict.

    use_weights=True → multiply each strategy's raw score by its backtest
    win-rate multiplier (loaded from backtest_results.json).
    """
    weights     = _load_weights() if use_weights else {}
    total_score = 0.0
    triggered   = []
    all_signals = []
    best_level  = None

    for name, fn in _DETECTORS:
        try:
            s, sigs, level = fn(df)
        except Exception:
            s, sigs, level = 0, [], None

        if s == 0 and not sigs:
            continue

        weight      = weights.get(name, 1.0)
        weighted_s  = s * weight
        total_score += weighted_s

        triggered.append({
            "name":       name,
            "score":      s,
            "weighted":   round(weighted_s, 2),
            "weight":     weight,
            "signals":    sigs,
            "key_level":  level,
        })
        all_signals.extend(sigs)
        if level and best_level is None:
            best_level = level

    total_score = round(total_score, 2)

    from config import BUY_THRESHOLD, SELL_THRESHOLD
    if total_score >= BUY_THRESHOLD:
        direction = "BUY"
    elif total_score <= SELL_THRESHOLD:
        direction = "SELL"
    else:
        direction = "HOLD"

    atr_val = df.iloc[-1].get("ATRr_14")
    rsi_val = df.iloc[-1].get("RSI_14")

    return {
        "score":       total_score,
        "direction":   direction,
        "triggered":   triggered,
        "all_signals": all_signals,
        "key_level":   best_level,
        "close":       float(df.iloc[-1]["close"]),
        "atr":         float(atr_val) if atr_val and not pd.isna(atr_val) else None,
        "rsi":         float(rsi_val) if rsi_val and not pd.isna(rsi_val) else None,
        "weights_used": bool(weights),
    }
