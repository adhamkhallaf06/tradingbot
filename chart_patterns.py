"""
Chart Pattern Detectors
=======================
Patterns implemented (all return (score, signals, key_level)):

  Reversal patterns (signal a trend change)
  ─────────────────────────────────────────
  1.  Double Top             → bearish reversal  score -4 to -6
  2.  Double Bottom          → bullish reversal  score +4 to +6
  3.  Head & Shoulders       → bearish reversal  score -5 to -7
  4.  Inverse H&S            → bullish reversal  score +5 to +7
  5.  Rising Wedge           → bearish reversal  score -3 to -5
  6.  Falling Wedge          → bullish reversal  score +3 to +5
  7.  Cup and Handle         → bullish reversal  score +4 to +6

  Continuation patterns (signal trend continuation)
  ──────────────────────────────────────────────────
  8.  Ascending Triangle     → bullish breakout  score +3 to +5
  9.  Descending Triangle    → bearish breakdown score -3 to -5
  10. Bull Flag / Pennant    → bullish continuation score +3 to +5
  11. Bear Flag / Pennant    → bearish continuation score -3 to -5
"""

from __future__ import annotations
import numpy as np
import pandas as pd


# ── Swing point helpers ────────────────────────────────────────────────────────

def _swing_highs(arr: np.ndarray, w: int = 3) -> list[int]:
    n = len(arr)
    return [
        i for i in range(w, n - w)
        if all(arr[i] >= arr[i - j] for j in range(1, w + 1))
        and all(arr[i] >= arr[i + j] for j in range(1, w + 1))
    ]


def _swing_lows(arr: np.ndarray, w: int = 3) -> list[int]:
    n = len(arr)
    return [
        i for i in range(w, n - w)
        if all(arr[i] <= arr[i - j] for j in range(1, w + 1))
        and all(arr[i] <= arr[i + j] for j in range(1, w + 1))
    ]


def _pct(a: float, b: float) -> float:
    """Percentage difference between a and b relative to b."""
    return abs(a - b) / b * 100 if b else 0.0


# ── 1. Double Top ──────────────────────────────────────────────────────────────

def detect_double_top(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    """
    Two peaks at similar level, valley between them.
    Confirmed when price closes below the neckline (valley low).
    """
    score, signals = 0, []
    if len(df) < 30:
        return score, signals, None

    lb    = df.tail(60)
    highs = lb["high"].to_numpy(float)
    lows  = lb["low"].to_numpy(float)
    close = float(df.iloc[-1]["close"])

    sh = _swing_highs(highs, w=3)
    if len(sh) < 2:
        return score, signals, None

    # Take the two most recent prominent peaks
    p2_idx = sh[-1]
    # Find the previous peak that is within 3% and at least 7 bars earlier
    p1_idx = next(
        (i for i in reversed(sh[:-1])
         if p2_idx - i >= 7 and _pct(highs[i], highs[p2_idx]) <= 3.0),
        None,
    )
    if p1_idx is None:
        return score, signals, None

    p1, p2    = highs[p1_idx], highs[p2_idx]
    avg_peak  = (p1 + p2) / 2
    neckline  = float(lows[p1_idx:p2_idx + 1].min())

    # Valley must be at least 3% below peaks
    if (avg_peak - neckline) / avg_peak * 100 < 3.0:
        return score, signals, None

    dist_to_neck = (close - neckline) / neckline * 100

    if dist_to_neck < -0.5:                     # confirmed breakdown
        score -= 6
        signals.append(
            f"Double Top — confirmed breakdown below neckline ${neckline:.2f} "
            f"(peaks ${p1:.2f} / ${p2:.2f}) ← high-probability reversal"
        )
    elif -0.5 <= dist_to_neck <= 1.5:           # testing neckline
        score -= 4
        signals.append(
            f"Double Top — testing neckline ${neckline:.2f}, "
            f"peaks ${p1:.2f} / ${p2:.2f} ({_pct(p1,p2):.1f}% apart)"
        )
    else:
        return score, signals, None

    return score, signals, neckline


# ── 2. Double Bottom ───────────────────────────────────────────────────────────

def detect_double_bottom(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    """
    Two troughs at similar level, peak between them.
    Confirmed when price closes above the neckline (peak high).
    """
    score, signals = 0, []
    if len(df) < 30:
        return score, signals, None

    lb    = df.tail(60)
    lows  = lb["low"].to_numpy(float)
    highs = lb["high"].to_numpy(float)
    close = float(df.iloc[-1]["close"])

    sl = _swing_lows(lows, w=3)
    if len(sl) < 2:
        return score, signals, None

    b2_idx = sl[-1]
    b1_idx = next(
        (i for i in reversed(sl[:-1])
         if b2_idx - i >= 7 and _pct(lows[i], lows[b2_idx]) <= 3.0),
        None,
    )
    if b1_idx is None:
        return score, signals, None

    b1, b2    = lows[b1_idx], lows[b2_idx]
    avg_trough = (b1 + b2) / 2
    neckline   = float(highs[b1_idx:b2_idx + 1].max())

    if (neckline - avg_trough) / avg_trough * 100 < 3.0:
        return score, signals, None

    dist_to_neck = (close - neckline) / neckline * 100

    if dist_to_neck > 0.5:                       # confirmed breakout
        score += 6
        signals.append(
            f"Double Bottom — confirmed breakout above neckline ${neckline:.2f} "
            f"(troughs ${b1:.2f} / ${b2:.2f}) ← high-probability reversal"
        )
    elif -1.5 <= dist_to_neck <= 0.5:            # testing neckline
        score += 4
        signals.append(
            f"Double Bottom — testing neckline ${neckline:.2f}, "
            f"troughs ${b1:.2f} / ${b2:.2f} ({_pct(b1,b2):.1f}% apart)"
        )
    else:
        return score, signals, None

    return score, signals, neckline


# ── 3. Head and Shoulders ──────────────────────────────────────────────────────

def detect_head_and_shoulders(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    """
    Three peaks: middle (head) is highest; two shoulders roughly equal.
    Neckline connects the two troughs between shoulders and head.
    Breakdown below neckline = confirmed bearish signal.
    """
    score, signals = 0, []
    if len(df) < 40:
        return score, signals, None

    lb    = df.tail(80)
    highs = lb["high"].to_numpy(float)
    lows  = lb["low"].to_numpy(float)
    close = float(df.iloc[-1]["close"])

    sh = _swing_highs(highs, w=4)
    if len(sh) < 3:
        return score, signals, None

    # Try last 3 / 4 swing highs to find H&S
    for triplet in [sh[-3:], sh[-4:-1] if len(sh) >= 4 else []]:
        if len(triplet) < 3:
            continue
        ls_i, h_i, rs_i = triplet[-3], triplet[-2], triplet[-1]
        ls, head, rs = highs[ls_i], highs[h_i], highs[rs_i]

        if head <= ls or head <= rs:
            continue                               # head must be highest
        if _pct(ls, rs) > 15:
            continue                               # shoulders within 15%

        # Neckline = average of two troughs between ls-head and head-rs
        t1 = float(lows[ls_i:h_i + 1].min())
        t2 = float(lows[h_i:rs_i + 1].min())
        neckline = (t1 + t2) / 2

        dist = (close - neckline) / neckline * 100

        if dist < -0.5:
            score -= 7
            signals.append(
                f"Head & Shoulders — breakdown below neckline ${neckline:.2f} "
                f"(LS ${ls:.2f}, Head ${head:.2f}, RS ${rs:.2f})"
            )
            return score, signals, neckline
        elif -0.5 <= dist <= 2.0:
            score -= 5
            signals.append(
                f"Head & Shoulders — testing neckline ${neckline:.2f} "
                f"(LS ${ls:.2f}, Head ${head:.2f}, RS ${rs:.2f})"
            )
            return score, signals, neckline

    return score, signals, None


# ── 4. Inverse Head and Shoulders ─────────────────────────────────────────────

def detect_inverse_head_and_shoulders(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    """
    Three troughs: middle (head) is lowest; two shoulders roughly equal.
    Breakout above neckline = confirmed bullish signal.
    """
    score, signals = 0, []
    if len(df) < 40:
        return score, signals, None

    lb   = df.tail(80)
    lows = lb["low"].to_numpy(float)
    highs = lb["high"].to_numpy(float)
    close = float(df.iloc[-1]["close"])

    sl = _swing_lows(lows, w=4)
    if len(sl) < 3:
        return score, signals, None

    for triplet in [sl[-3:], sl[-4:-1] if len(sl) >= 4 else []]:
        if len(triplet) < 3:
            continue
        ls_i, h_i, rs_i = triplet[-3], triplet[-2], triplet[-1]
        ls, head, rs = lows[ls_i], lows[h_i], lows[rs_i]

        if head >= ls or head >= rs:
            continue
        if _pct(ls, rs) > 15:
            continue

        t1 = float(highs[ls_i:h_i + 1].max())
        t2 = float(highs[h_i:rs_i + 1].max())
        neckline = (t1 + t2) / 2

        dist = (close - neckline) / neckline * 100

        if dist > 0.5:
            score += 7
            signals.append(
                f"Inverse H&S — breakout above neckline ${neckline:.2f} "
                f"(LS ${ls:.2f}, Head ${head:.2f}, RS ${rs:.2f})"
            )
            return score, signals, neckline
        elif -2.0 <= dist <= 0.5:
            score += 5
            signals.append(
                f"Inverse H&S — testing neckline ${neckline:.2f} "
                f"(LS ${ls:.2f}, Head ${head:.2f}, RS ${rs:.2f})"
            )
            return score, signals, neckline

    return score, signals, None


# ── 5 & 6. Wedges ─────────────────────────────────────────────────────────────

def _linear_slope(arr: np.ndarray) -> float:
    """Return the slope of a linear fit (per bar) normalized by array mean."""
    x = np.arange(len(arr), dtype=float)
    if arr.mean() == 0:
        return 0.0
    coeffs = np.polyfit(x, arr, 1)
    return float(coeffs[0]) / float(arr.mean())   # normalized slope


def detect_rising_wedge(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    """
    Both highs and lows rising but converging (highs rising slower).
    Bearish reversal signal.
    """
    score, signals = 0, []
    if len(df) < 25:
        return score, signals, None

    lb   = df.tail(30)
    highs = lb["high"].to_numpy(float)
    lows  = lb["low"].to_numpy(float)
    close = float(df.iloc[-1]["close"])

    slope_h = _linear_slope(highs)
    slope_l = _linear_slope(lows)

    # Both slopes positive (rising), but lows rising faster (converging)
    if not (slope_h > 0 and slope_l > 0):
        return score, signals, None
    if slope_l <= slope_h * 1.3:           # lows must rise meaningfully faster
        return score, signals, None

    # Channel width is narrowing
    width_start = highs[:5].mean() - lows[:5].mean()
    width_end   = highs[-5:].mean() - lows[-5:].mean()
    if width_end >= width_start * 0.8:     # need at least 20% narrowing
        return score, signals, None

    support = float(lows[-1])
    score -= 4
    signals.append(
        f"Rising Wedge — converging highs/lows (H slope {slope_h*100:.2f}%, "
        f"L slope {slope_l*100:.2f}%) — bearish reversal likely on breakdown"
    )
    return score, signals, support


def detect_falling_wedge(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    """
    Both highs and lows falling but converging (lows falling slower).
    Bullish reversal signal.
    """
    score, signals = 0, []
    if len(df) < 25:
        return score, signals, None

    lb   = df.tail(30)
    highs = lb["high"].to_numpy(float)
    lows  = lb["low"].to_numpy(float)
    close = float(df.iloc[-1]["close"])

    slope_h = _linear_slope(highs)
    slope_l = _linear_slope(lows)

    if not (slope_h < 0 and slope_l < 0):
        return score, signals, None
    if slope_h >= slope_l * 1.3:
        return score, signals, None

    width_start = highs[:5].mean() - lows[:5].mean()
    width_end   = highs[-5:].mean() - lows[-5:].mean()
    if width_end >= width_start * 0.8:
        return score, signals, None

    resistance = float(highs[-1])
    score += 4
    signals.append(
        f"Falling Wedge — converging highs/lows (H slope {slope_h*100:.2f}%, "
        f"L slope {slope_l*100:.2f}%) — bullish reversal likely on breakout"
    )
    return score, signals, resistance


# ── 7. Cup and Handle ─────────────────────────────────────────────────────────

def detect_cup_and_handle(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    """
    U-shaped recovery (cup) with a small pullback (handle).
    Breakout above the cup rim = bullish signal.
    """
    score, signals = 0, []
    if len(df) < 50:
        return score, signals, None

    lb    = df.tail(60)
    highs = lb["high"].to_numpy(float)
    lows  = lb["low"].to_numpy(float)
    close = float(df.iloc[-1]["close"])

    # Left rim: high in the first third of the lookback
    n      = len(lb)
    third  = n // 3
    left_rim   = float(highs[:third].max())
    left_rim_i = int(highs[:third].argmax())

    # Cup bottom: lowest point in the middle third
    cup_bot   = float(lows[third:2*third].min())
    cup_bot_i = int(lows[third:2*third].argmin()) + third

    # Right rim: high in the last third approaching left rim level
    right_rim   = float(highs[2*third:].max())
    right_rim_i = int(highs[2*third:].argmax()) + 2 * third

    # Cup depth must be at least 10%
    cup_depth_pct = (left_rim - cup_bot) / left_rim * 100
    if cup_depth_pct < 10:
        return score, signals, None

    # Right rim must be within 5% of left rim
    if _pct(left_rim, right_rim) > 5:
        return score, signals, None

    # Order must be: left rim → cup bottom → right rim
    if not (left_rim_i < cup_bot_i < right_rim_i):
        return score, signals, None

    # Handle: slight pullback (3–15%) after right rim in last 10 bars
    handle_low = float(lows[right_rim_i:].min())
    handle_pct = (right_rim - handle_low) / right_rim * 100
    if not (3 <= handle_pct <= 15):
        return score, signals, None

    rim = (left_rim + right_rim) / 2
    dist_to_rim = (close - rim) / rim * 100

    if dist_to_rim > 0.5:
        score += 6
        signals.append(
            f"Cup & Handle — breakout above rim ${rim:.2f} "
            f"(cup depth {cup_depth_pct:.1f}%, handle {handle_pct:.1f}%)"
        )
    elif -2 <= dist_to_rim <= 0.5:
        score += 4
        signals.append(
            f"Cup & Handle — approaching rim ${rim:.2f} "
            f"(cup depth {cup_depth_pct:.1f}%, handle {handle_pct:.1f}%)"
        )
    else:
        return score, signals, None

    return score, signals, rim


# ── 8. Ascending Triangle ─────────────────────────────────────────────────────

def detect_ascending_triangle(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    """
    Flat resistance ceiling + rising support lows → bullish breakout.
    """
    score, signals = 0, []
    if len(df) < 25:
        return score, signals, None

    lb    = df.tail(30)
    highs = lb["high"].to_numpy(float)
    lows  = lb["low"].to_numpy(float)
    close = float(df.iloc[-1]["close"])

    # Resistance = multiple highs within 1.5% of each other
    high_max = highs.max()
    near_top  = [h for h in highs if _pct(h, high_max) <= 1.5]
    if len(near_top) < 3:
        return score, signals, None

    resistance = high_max

    # Support lows must be rising
    slope_l = _linear_slope(lows)
    if slope_l <= 0:
        return score, signals, None

    # Price approaching resistance
    dist = (close - resistance) / resistance * 100
    if not (-3 <= dist <= 1.5):
        return score, signals, None

    if dist > 0:
        score += 5
        signals.append(
            f"Ascending Triangle — breakout above flat resistance ${resistance:.2f} "
            f"with rising lows (slope {slope_l*100:.2f}%/bar)"
        )
    else:
        score += 3
        signals.append(
            f"Ascending Triangle — approaching flat resistance ${resistance:.2f} "
            f"with rising lows — bullish setup"
        )

    return score, signals, resistance


# ── 9. Descending Triangle ────────────────────────────────────────────────────

def detect_descending_triangle(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    """
    Falling resistance highs + flat support → bearish breakdown.
    """
    score, signals = 0, []
    if len(df) < 25:
        return score, signals, None

    lb    = df.tail(30)
    highs = lb["high"].to_numpy(float)
    lows  = lb["low"].to_numpy(float)
    close = float(df.iloc[-1]["close"])

    # Flat support: multiple lows within 1.5%
    low_min  = lows.min()
    near_bot = [l for l in lows if _pct(l, low_min) <= 1.5]
    if len(near_bot) < 3:
        return score, signals, None

    support = low_min

    # Highs must be falling
    slope_h = _linear_slope(highs)
    if slope_h >= 0:
        return score, signals, None

    # Price approaching support
    dist = (close - support) / support * 100
    if not (-1.5 <= dist <= 3):
        return score, signals, None

    if dist < 0:
        score -= 5
        signals.append(
            f"Descending Triangle — breakdown below flat support ${support:.2f} "
            f"with falling highs (slope {slope_h*100:.2f}%/bar)"
        )
    else:
        score -= 3
        signals.append(
            f"Descending Triangle — approaching flat support ${support:.2f} "
            f"with falling highs — bearish setup"
        )

    return score, signals, support


# ── 10 & 11. Bull Flag / Bear Flag ────────────────────────────────────────────

def detect_bull_flag(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    """
    Strong up-move (flagpole) + tight consolidation (flag) → bullish continuation.
    """
    score, signals = 0, []
    if len(df) < 15:
        return score, signals, None

    close = float(df.iloc[-1]["close"])

    # Flagpole: price moved up ≥6% in last 4–7 bars
    pole_bars = 5
    pole_start = float(df.iloc[-pole_bars - 5]["close"])
    pole_end   = float(df.iloc[-6]["close"])
    pole_pct   = (pole_end - pole_start) / pole_start * 100

    if pole_pct < 6:
        return score, signals, None

    # Flag: last 5 bars in a tight range (<4% range) and slight downward drift
    flag      = df.iloc[-6:]
    flag_high = float(flag["high"].max())
    flag_low  = float(flag["low"].min())
    flag_range = (flag_high - flag_low) / flag_low * 100

    if flag_range > 6:
        return score, signals, None

    # Flag should drift slightly down (pullback) not blast up
    flag_drift = (float(flag.iloc[-1]["close"]) - float(flag.iloc[0]["close"])) \
                 / float(flag.iloc[0]["close"]) * 100
    if flag_drift > 2:
        return score, signals, None

    # Breakout: price above flag high
    dist_to_breakout = (close - flag_high) / flag_high * 100

    if dist_to_breakout > 0:
        score += 5
        signals.append(
            f"Bull Flag — breakout from flag (pole +{pole_pct:.1f}%, "
            f"flag range {flag_range:.1f}%, drift {flag_drift:.1f}%)"
        )
    elif dist_to_breakout > -1.5:
        score += 3
        signals.append(
            f"Bull Flag — approaching breakout level ${flag_high:.2f} "
            f"(pole +{pole_pct:.1f}%, flag {flag_range:.1f}% tight)"
        )
    else:
        return score, signals, None

    return score, signals, flag_high


def detect_bear_flag(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    """
    Strong down-move (flagpole) + tight consolidation → bearish continuation.
    """
    score, signals = 0, []
    if len(df) < 15:
        return score, signals, None

    close = float(df.iloc[-1]["close"])

    # Flagpole: price moved down ≥6% in last 4–7 bars
    pole_start = float(df.iloc[-pole_bars - 5]["close"]) if (pole_bars := 5) else 1
    pole_end   = float(df.iloc[-6]["close"])
    pole_pct   = (pole_start - pole_end) / pole_start * 100

    if pole_pct < 6:
        return score, signals, None

    flag      = df.iloc[-6:]
    flag_high = float(flag["high"].max())
    flag_low  = float(flag["low"].min())
    flag_range = (flag_high - flag_low) / flag_low * 100

    if flag_range > 6:
        return score, signals, None

    flag_drift = (float(flag.iloc[-1]["close"]) - float(flag.iloc[0]["close"])) \
                 / float(flag.iloc[0]["close"]) * 100
    if flag_drift < -2:
        return score, signals, None

    dist_to_breakdown = (close - flag_low) / flag_low * 100

    if dist_to_breakdown < 0:
        score -= 5
        signals.append(
            f"Bear Flag — breakdown from flag (pole -{pole_pct:.1f}%, "
            f"flag range {flag_range:.1f}%, drift {flag_drift:.1f}%)"
        )
    elif dist_to_breakdown < 1.5:
        score -= 3
        signals.append(
            f"Bear Flag — approaching breakdown level ${flag_low:.2f} "
            f"(pole -{pole_pct:.1f}%, flag {flag_range:.1f}% tight)"
        )
    else:
        return score, signals, None

    return score, signals, flag_low


# ── Symmetrical Triangle (bonus) ──────────────────────────────────────────────

def detect_symmetrical_triangle(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    """
    Converging lower highs + higher lows → coiling, breakout imminent.
    Direction confirmed by breakout candle.
    """
    score, signals = 0, []
    if len(df) < 25:
        return score, signals, None

    lb    = df.tail(30)
    highs = lb["high"].to_numpy(float)
    lows  = lb["low"].to_numpy(float)
    close = float(df.iloc[-1]["close"])

    slope_h = _linear_slope(highs)
    slope_l = _linear_slope(lows)

    # Highs falling AND lows rising → converging
    if not (slope_h < -0.0002 and slope_l > 0.0002):
        return score, signals, None

    # Width must be narrowing by at least 20%
    width_start = highs[:5].mean() - lows[:5].mean()
    width_end   = highs[-5:].mean() - lows[-5:].mean()
    if width_start <= 0 or width_end / width_start > 0.80:
        return score, signals, None

    # Bias: if price is in upper 60% → bullish lean; lower 40% → bearish lean
    midpoint    = (highs[-5:].mean() + lows[-5:].mean()) / 2
    range_width = highs[-5:].mean() - lows[-5:].mean()
    rel_pos     = (close - midpoint) / (range_width / 2) if range_width > 0 else 0

    if rel_pos > 0.2:
        score += 2
        signals.append(
            f"Symmetrical Triangle — coiling near apex, bullish lean "
            f"(H slope {slope_h*100:.3f}%, L slope {slope_l*100:.3f}%)"
        )
    elif rel_pos < -0.2:
        score -= 2
        signals.append(
            f"Symmetrical Triangle — coiling near apex, bearish lean "
            f"(H slope {slope_h*100:.3f}%, L slope {slope_l*100:.3f}%)"
        )
    else:
        score += 1
        signals.append(
            f"Symmetrical Triangle — coiling toward apex, breakout imminent"
        )

    apex = (highs[-1] + lows[-1]) / 2
    return score, signals, float(apex)


# ══════════════════════════════════════════════════════════════════════════════
#  PATTERNS FROM PDF: "Identifying Chart Patterns" — Fidelity / Kirkpatrick
# ══════════════════════════════════════════════════════════════════════════════

# ── Triple Top ────────────────────────────────────────────────────────────────
# Three peaks at the same resistance level separated by two troughs.
# PDF: "Break occurs when price exceeds extreme of intermittent trough"
# Target: height from highest peak to lowest trough, subtracted from trough.

def detect_triple_top(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    score, signals = 0, []
    if len(df) < 40:
        return score, signals, None

    lb    = df.tail(70)
    highs = lb["high"].to_numpy(float)
    lows  = lb["low"].to_numpy(float)
    close = float(df.iloc[-1]["close"])

    sh = _swing_highs(highs, w=3)
    if len(sh) < 3:
        return score, signals, None

    # Find 3 peaks within 3% of each other, each ≥5 bars apart
    for i in range(len(sh) - 2):
        p1i, p2i, p3i = sh[i], sh[i + 1], sh[i + 2]
        if p2i - p1i < 5 or p3i - p2i < 5:
            continue
        p1, p2, p3 = highs[p1i], highs[p2i], highs[p3i]
        avg = (p1 + p2 + p3) / 3
        if max(_pct(p1, avg), _pct(p2, avg), _pct(p3, avg)) > 3.5:
            continue

        neckline = float(lows[p1i:p3i + 1].min())
        height   = avg - neckline
        target   = round(neckline - height, 2)   # PDF formula
        dist     = (close - neckline) / neckline * 100

        if dist < -0.5:
            score -= 7
            signals.append(
                f"Triple Top — breakdown below neckline ${neckline:.2f} "
                f"(peaks ${p1:.2f}/${p2:.2f}/${p3:.2f}) | Target ${target:.2f}"
            )
            return score, signals, neckline
        elif -0.5 <= dist <= 1.5:
            score -= 5
            signals.append(
                f"Triple Top — testing neckline ${neckline:.2f}, "
                f"3 peaks at ~${avg:.2f} | Target on break: ${target:.2f}"
            )
            return score, signals, neckline

    return score, signals, None


# ── Triple Bottom ─────────────────────────────────────────────────────────────
# Three troughs at same support separated by two peaks.
# PDF: "Best performance may be after a sustained decline"
# Target: height from peak to trough, added to highest peak.

def detect_triple_bottom(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    score, signals = 0, []
    if len(df) < 40:
        return score, signals, None

    lb   = df.tail(70)
    lows = lb["low"].to_numpy(float)
    highs = lb["high"].to_numpy(float)
    close = float(df.iloc[-1]["close"])

    sl = _swing_lows(lows, w=3)
    if len(sl) < 3:
        return score, signals, None

    for i in range(len(sl) - 2):
        b1i, b2i, b3i = sl[i], sl[i + 1], sl[i + 2]
        if b2i - b1i < 5 or b3i - b2i < 5:
            continue
        b1, b2, b3 = lows[b1i], lows[b2i], lows[b3i]
        avg = (b1 + b2 + b3) / 3
        if max(_pct(b1, avg), _pct(b2, avg), _pct(b3, avg)) > 3.5:
            continue

        neckline = float(highs[b1i:b3i + 1].max())
        height   = neckline - avg
        target   = round(neckline + height, 2)   # PDF formula
        dist     = (close - neckline) / neckline * 100

        if dist > 0.5:
            score += 7
            signals.append(
                f"Triple Bottom — breakout above neckline ${neckline:.2f} "
                f"(troughs ${b1:.2f}/${b2:.2f}/${b3:.2f}) | Target ${target:.2f}"
            )
            return score, signals, neckline
        elif -1.5 <= dist <= 0.5:
            score += 5
            signals.append(
                f"Triple Bottom — testing neckline ${neckline:.2f}, "
                f"3 troughs at ~${avg:.2f} | Target on break: ${target:.2f}"
            )
            return score, signals, neckline

    return score, signals, None


# ── Rectangle ─────────────────────────────────────────────────────────────────
# Horizontal trading range. PDF: watch for "shortfall" — price failing to
# reach the upper bound signals impending downside breakout.
# Target: height of range added/subtracted from breakout level.

def detect_rectangle(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    score, signals = 0, []
    if len(df) < 20:
        return score, signals, None

    lb    = df.tail(30)
    highs = lb["high"].to_numpy(float)
    lows  = lb["low"].to_numpy(float)
    close = float(df.iloc[-1]["close"])

    resistance = float(highs.max())
    support    = float(lows.min())
    height     = resistance - support
    if height / support * 100 < 3:              # need meaningful range
        return score, signals, None

    # At least 3 touches of resistance AND 3 touches of support
    res_touches = sum(1 for h in highs if _pct(h, resistance) <= 1.5)
    sup_touches = sum(1 for l in lows  if _pct(l, support)    <= 1.5)
    if res_touches < 3 or sup_touches < 3:
        return score, signals, None

    dist_res = (close - resistance) / resistance * 100
    dist_sup = (close - support)    / support    * 100

    # Shortfall: price is pulling back from resistance but not getting close
    last5_high = float(lb["high"].iloc[-5:].max())
    shortfall  = resistance - last5_high
    shortfall_pct = shortfall / resistance * 100

    if dist_res > 0.5:                          # breaking out upward
        target = round(resistance + height, 2)
        score += 4
        signals.append(
            f"Rectangle breakout UP — above ${resistance:.2f} "
            f"(range ${support:.2f}–${resistance:.2f}) | Target ${target:.2f}"
        )
        return score, signals, resistance

    elif dist_sup < -0.5:                       # breaking down
        target = round(support - height, 2)
        score -= 4
        signals.append(
            f"Rectangle breakdown DOWN — below ${support:.2f} "
            f"(range ${support:.2f}–${resistance:.2f}) | Target ${target:.2f}"
        )
        return score, signals, support

    elif shortfall_pct > 1.5:                   # shortfall = downside indicator
        score -= 2
        signals.append(
            f"Rectangle shortfall — price failing to reach resistance ${resistance:.2f} "
            f"(last 5-bar high ${last5_high:.2f}, shortfall {shortfall_pct:.1f}%) "
            f"— probable downside breakout below ${support:.2f}"
        )
        return score, signals, support

    return score, signals, None


# ── Pipe Bottom (Two-Bar Reversal) ────────────────────────────────────────────
# PDF: "One of the best upward signals"
# Two adjacent bars with above-average range at the end of a downtrend.
# First bar closes near the low; second closes in the upper half.
# Target: height of taller bar × 2, added to taller bar high.

def detect_pipe_bottom(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    score, signals = 0, []
    if len(df) < 20:
        return score, signals, None

    close    = float(df.iloc[-1]["close"])
    prev     = df.iloc[-2]
    curr     = df.iloc[-1]
    avg_rng  = float(df["range_avg20"].iloc[-1]) or 1

    p_range = float(prev["high"]) - float(prev["low"])
    c_range = float(curr["high"]) - float(curr["low"])

    # Both bars must have above-average ranges
    if p_range < avg_rng * 1.3 or c_range < avg_rng * 1.3:
        return score, signals, None

    # Must be in a downtrend context — close should be below SMA50 (if available)
    sma50 = df.iloc[-1].get("SMA_50")
    if sma50 and not pd.isna(sma50) and close > float(sma50) * 1.1:
        return score, signals, None    # not at bottom context

    # First bar closes near its low (bottom 25%)
    p_close_pos = (float(prev["close"]) - float(prev["low"])) / p_range
    if p_close_pos > 0.35:
        return score, signals, None

    # Second bar closes in upper half
    c_close_pos = (float(curr["close"]) - float(curr["low"])) / c_range
    if c_close_pos < 0.50:
        return score, signals, None

    taller     = max(p_range, c_range)
    taller_high = max(float(prev["high"]), float(curr["high"]))
    target     = round(taller_high + taller, 2)   # PDF formula

    score += 5
    signals.append(
        f"Pipe Bottom (Two-Bar Reversal) — two wide-range bars at low "
        f"(ranges {p_range:.2f}/{c_range:.2f} vs avg {avg_rng:.2f}) "
        f"| Target ${target:.2f}"
    )
    return score, signals, float(curr["low"])


# ── Inside Bar / Narrow Range ─────────────────────────────────────────────────
# PDF: "New trends often begin from periods of low volatility"
# NR4: current bar's range is narrower than previous 3 bars.
# Inside Bar: current bar's range is entirely within previous bar.
# Direction confirmed by breakout above/below the inside bar.

def detect_inside_bar_nr4(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    score, signals = 0, []
    if len(df) < 10:
        return score, signals, None

    curr  = df.iloc[-1]
    prev  = df.iloc[-2]
    close = float(curr["close"])

    c_high = float(curr["high"])
    c_low  = float(curr["low"])
    c_range = c_high - c_low

    p_high = float(prev["high"])
    p_low  = float(prev["low"])

    # ── Inside Bar: entirely within previous bar ─────────────────────────
    if c_high <= p_high and c_low >= p_low:
        # Breakout direction?
        if close > (p_high + p_low) / 2:
            score += 3
            signals.append(
                f"Inside Bar — tight consolidation inside ${p_low:.2f}–${p_high:.2f}; "
                f"close in upper half (${close:.2f}) — bullish breakout above ${p_high:.2f}"
            )
            return score, signals, p_high
        else:
            score -= 3
            signals.append(
                f"Inside Bar — tight consolidation inside ${p_low:.2f}–${p_high:.2f}; "
                f"close in lower half (${close:.2f}) — bearish breakout below ${p_low:.2f}"
            )
            return score, signals, p_low

    # ── NR4: current range < previous 3 bars ────────────────────────────
    prev3_ranges = [
        float(df.iloc[i]["high"]) - float(df.iloc[i]["low"])
        for i in range(-4, -1)
    ]
    if c_range < min(prev3_ranges):
        # Direction bias: close relative to midpoint
        mid = (c_high + c_low) / 2
        if close > mid:
            score += 2
            signals.append(
                f"NR4 (Narrow Range) — range {c_range:.2f} narrower than prior 3 bars "
                f"→ volatility contraction, breakout expected above ${c_high:.2f}"
            )
            return score, signals, c_high
        else:
            score -= 2
            signals.append(
                f"NR4 (Narrow Range) — range {c_range:.2f} narrower than prior 3 bars "
                f"→ volatility contraction, breakout expected below ${c_low:.2f}"
            )
            return score, signals, c_low

    return score, signals, None


# ── Gap (Explosion Gap Pivot) ─────────────────────────────────────────────────
# PDF method: gap up/down → wait for throwback → if throwback stops WITHOUT
# filling the gap → that pivot low is the buy entry signal.
# Here we detect continuation gaps that haven't been filled.

def detect_gap(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    score, signals = 0, []
    if len(df) < 10:
        return score, signals, None

    close  = float(df.iloc[-1]["close"])

    # Look for a gap in the last 5 bars
    for i in range(-5, -1):
        curr_open = float(df.iloc[i]["open"])
        prev_close = float(df.iloc[i - 1]["close"])
        gap_pct = (curr_open - prev_close) / prev_close * 100

        if abs(gap_pct) < 1.0:          # gap must be at least 1%
            continue

        gap_is_up = gap_pct > 0
        gap_low   = min(curr_open, prev_close)  # bottom of gap
        gap_high  = max(curr_open, prev_close)  # top of gap

        # Has the gap been filled?
        subsequent = df.iloc[i + 1:]
        if gap_is_up:
            filled = any(float(r["low"]) <= gap_low for _, r in subsequent.iterrows())
        else:
            filled = any(float(r["high"]) >= gap_high for _, r in subsequent.iterrows())

        if filled:
            continue   # gap filled → no longer valid

        # Gap is still open (unfilled) — check for pivot low/high pattern
        if gap_is_up:
            pivot_low = float(subsequent["low"].min()) if len(subsequent) else close
            # Throwback stopped above the gap — pivot low is buy point
            if pivot_low > gap_low and close > pivot_low:
                score += 3
                signals.append(
                    f"Explosion Gap UP (+{gap_pct:.1f}%) — unfilled, "
                    f"throwback pivot at ${pivot_low:.2f} | "
                    f"Buy stop above ${float(df.iloc[i]['high']):.2f}"
                )
                return score, signals, float(df.iloc[i]["high"])
        else:
            pivot_high = float(subsequent["high"].max()) if len(subsequent) else close
            if pivot_high < gap_high and close < pivot_high:
                score -= 3
                signals.append(
                    f"Explosion Gap DOWN ({gap_pct:.1f}%) — unfilled, "
                    f"rally pivot at ${pivot_high:.2f} | "
                    f"Sell stop below ${float(df.iloc[i]['low']):.2f}"
                )
                return score, signals, float(df.iloc[i]["low"])

    return score, signals, None


# ══════════════════════════════════════════════════════════════════════════════
#  CANDLESTICK PATTERNS (from PDF page 32-38)
#  PDF key rule: "Not complete until activated by breakout in a certain direction"
#  Best performance: reversal patterns after a correction in the prevailing trend.
# ══════════════════════════════════════════════════════════════════════════════

def _in_downtrend(df: pd.DataFrame, bars: int = 5) -> bool:
    """True if closing prices have been falling over the last N bars."""
    closes = df["close"].iloc[-bars:].to_numpy(float)
    return bool(np.polyfit(np.arange(len(closes)), closes, 1)[0] < 0)

def _in_uptrend(df: pd.DataFrame, bars: int = 5) -> bool:
    closes = df["close"].iloc[-bars:].to_numpy(float)
    return bool(np.polyfit(np.arange(len(closes)), closes, 1)[0] > 0)


def detect_doji(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    """
    PDF: open ≈ close, high/low roughly equidistant.
    Indicates market indecision — warning of price change.
    """
    score, signals = 0, []
    if len(df) < 6:
        return score, signals, None

    row      = df.iloc[-1]
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    body     = abs(c - o)
    total    = h - l
    avg_body = float(df["body_avg20"].iloc[-1]) or 1

    if total == 0 or body > avg_body * 0.15:     # body must be very small
        return score, signals, None

    upper_wick = h - max(c, o)
    lower_wick = min(c, o) - l

    # Roughly equal wicks
    if total > 0 and abs(upper_wick - lower_wick) / total > 0.5:
        return score, signals, None

    close = float(c)

    if _in_downtrend(df):
        score += 2
        signals.append(
            f"Doji — indecision after downtrend (body {body:.3f} vs avg {avg_body:.3f}) "
            f"— potential bullish reversal warning"
        )
    elif _in_uptrend(df):
        score -= 2
        signals.append(
            f"Doji — indecision after uptrend — potential bearish reversal warning"
        )

    return score, signals, close


def detect_harami(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    """
    PDF: large body + small opposite-color body inside first bar.
    Can break either way — confirmed only on subsequent breakout.
    """
    score, signals = 0, []
    if len(df) < 6:
        return score, signals, None

    prev = df.iloc[-2]
    curr = df.iloc[-1]
    avg_body = float(df["body_avg20"].iloc[-1]) or 1

    p_o, p_c = float(prev["open"]), float(prev["close"])
    c_o, c_c = float(curr["open"]), float(curr["close"])

    p_body = abs(p_c - p_o)
    c_body = abs(c_c - c_o)

    if p_body < avg_body * 1.5:      # first bar must be large
        return score, signals, None
    if c_body > p_body * 0.5:        # second bar must be small (spinning top)
        return score, signals, None

    p_top, p_bot = max(p_o, p_c), min(p_o, p_c)
    c_top, c_bot = max(c_o, c_c), min(c_o, c_c)

    if not (p_bot <= c_bot and c_top <= p_top):   # second body inside first
        return score, signals, None
    if (p_c > p_o) == (c_c > c_o):               # opposite colors required
        return score, signals, None

    close = float(curr["close"])
    if p_c < p_o and c_c > c_o:     # bearish → bullish (bottom harami)
        if _in_downtrend(df):
            score += 3
            signals.append(
                f"Bullish Harami — small bullish body inside large bearish bar "
                f"after downtrend — potential reversal"
            )
    else:                            # bullish → bearish (top harami)
        if _in_uptrend(df):
            score -= 3
            signals.append(
                f"Bearish Harami — small bearish body inside large bullish bar "
                f"after uptrend — potential reversal"
            )

    return score, signals, close


def detect_hammer_hanging_man(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    """
    PDF: small body at top of range, long lower wick (≥2× body).
    Hammer (bottom of downtrend) = potential bullish reversal.
    Hanging Man (top of uptrend) = potential bearish reversal.
    """
    score, signals = 0, []
    if len(df) < 6:
        return score, signals, None

    row = df.iloc[-1]
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    body      = abs(c - o)
    total     = h - l
    low_wick  = min(c, o) - l
    up_wick   = h - max(c, o)
    avg_body  = float(df["body_avg20"].iloc[-1]) or 1

    if total == 0 or body > avg_body * 0.8:
        return score, signals, None

    is_hammer_shape = (
        low_wick >= body * 2       # long lower wick
        and up_wick <= body * 0.5  # tiny upper wick
        and (c - l) / total >= 0.6 # closes in upper part of range
    )

    if not is_hammer_shape:
        return score, signals, None

    close = float(c)
    if _in_downtrend(df):
        score += 3
        signals.append(
            f"Hammer — long lower wick after downtrend "
            f"(wick {low_wick:.2f} = {low_wick/body:.1f}× body) — buyers defending lows"
        )
    elif _in_uptrend(df):
        score -= 3
        signals.append(
            f"Hanging Man — long lower wick at uptrend peak "
            f"(wick {low_wick:.2f} = {low_wick/body:.1f}× body) — bearish warning"
        )

    return score, signals, close


def detect_shooting_star(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    """
    PDF: small body at bottom of range, long upper wick.
    Shooting Star (top of uptrend) = bearish.
    Inverted Hammer (bottom of downtrend) = potential bullish.
    """
    score, signals = 0, []
    if len(df) < 6:
        return score, signals, None

    row = df.iloc[-1]
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    body     = abs(c - o)
    total    = h - l
    up_wick  = h - max(c, o)
    low_wick = min(c, o) - l
    avg_body = float(df["body_avg20"].iloc[-1]) or 1

    if total == 0 or body > avg_body * 0.8:
        return score, signals, None

    is_shooting_shape = (
        up_wick >= body * 2
        and low_wick <= body * 0.5
        and (h - c) / total >= 0.6
    )

    if not is_shooting_shape:
        return score, signals, None

    close = float(c)
    if _in_uptrend(df):
        score -= 4
        signals.append(
            f"Shooting Star — long upper wick rejected at ${h:.2f} after uptrend "
            f"(wick {up_wick:.2f} = {up_wick/max(body,0.001):.1f}× body) — sellers dominate"
        )
    elif _in_downtrend(df):
        score += 2
        signals.append(
            f"Inverted Hammer — upper wick after downtrend "
            f"(potential buyers testing higher prices at ${h:.2f})"
        )

    return score, signals, close


def detect_dark_cloud_piercing(df: pd.DataFrame) -> tuple[int, list[str], float | None]:
    """
    Dark Cloud Cover: bearish two-bar (bullish then bearish closing below midpoint).
    Piercing Line: bullish two-bar (bearish then bullish closing above midpoint).
    PDF: both confirmed only with subsequent breakout direction.
    """
    score, signals = 0, []
    if len(df) < 6:
        return score, signals, None

    prev = df.iloc[-2]
    curr = df.iloc[-1]
    avg_body = float(df["body_avg20"].iloc[-1]) or 1

    p_o, p_c = float(prev["open"]), float(prev["close"])
    c_o, c_c = float(curr["open"]), float(curr["close"])
    p_body   = abs(p_c - p_o)
    c_body   = abs(c_c - c_o)

    if p_body < avg_body or c_body < avg_body:   # both need meaningful bodies
        return score, signals, None

    # Dark Cloud Cover
    dark_cloud = (
        p_c > p_o                              # prev bullish
        and c_o > p_c                          # opens above prev close (gap up)
        and c_c < c_o                          # closes bearish
        and c_c < (p_o + p_c) / 2             # closes below midpoint of prev bar
        and c_c > p_o                          # but still within prev bar
    )

    # Piercing Line
    piercing = (
        p_c < p_o                              # prev bearish
        and c_o < p_c                          # opens below prev close (gap down)
        and c_c > c_o                          # closes bullish
        and c_c > (p_o + p_c) / 2             # closes above midpoint of prev bar
        and c_c < p_o                          # but still within prev bar
    )

    close = float(c_c)
    if dark_cloud and _in_uptrend(df):
        score -= 4
        signals.append(
            f"Dark Cloud Cover — bearish engulfing gap: opened ${c_o:.2f}, "
            f"closed ${c_c:.2f} (below midpoint ${(p_o+p_c)/2:.2f}) — reversal signal"
        )
        return score, signals, close

    if piercing and _in_downtrend(df):
        score += 4
        signals.append(
            f"Piercing Line — bullish recovery: opened ${c_o:.2f}, "
            f"closed ${c_c:.2f} (above midpoint ${(p_o+p_c)/2:.2f}) — reversal signal"
        )
        return score, signals, close

    return score, signals, None


# ── Public registry ───────────────────────────────────────────────────────────

PATTERN_DETECTORS: list[tuple[str, callable]] = [
    ("Double Top",             detect_double_top),
    ("Double Bottom",          detect_double_bottom),
    ("Head & Shoulders",       detect_head_and_shoulders),
    ("Inverse H&S",            detect_inverse_head_and_shoulders),
    ("Rising Wedge",           detect_rising_wedge),
    ("Falling Wedge",          detect_falling_wedge),
    ("Cup & Handle",           detect_cup_and_handle),
    ("Ascending Triangle",     detect_ascending_triangle),
    ("Descending Triangle",    detect_descending_triangle),
    ("Bull Flag",              detect_bull_flag),
    ("Bear Flag",              detect_bear_flag),
    ("Symmetrical Triangle",   detect_symmetrical_triangle),
    # ── PDF additions ─────────────────────────────────────────────────────
    ("Triple Top",             detect_triple_top),
    ("Triple Bottom",          detect_triple_bottom),
    ("Rectangle",              detect_rectangle),
    ("Pipe Bottom",            detect_pipe_bottom),
    ("Inside Bar / NR4",       detect_inside_bar_nr4),
    ("Gap",                    detect_gap),
    # ── Candlestick patterns (PDF pages 32-38) ────────────────────────────
    ("Doji",                   detect_doji),
    ("Harami",                 detect_harami),
    ("Hammer / Hanging Man",   detect_hammer_hanging_man),
    ("Shooting Star",          detect_shooting_star),
    ("Dark Cloud / Piercing",  detect_dark_cloud_piercing),
]
