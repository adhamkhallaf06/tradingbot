import pandas as pd
import pandas_ta as ta
from config import RSI_OVERSOLD, RSI_OVERBOUGHT


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.ta.rsi(length=14, append=True)
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    df.ta.bbands(length=20, std=2, append=True)
    df.ta.sma(length=20, append=True)
    df.ta.sma(length=50, append=True)
    df.ta.sma(length=200, append=True)
    df.ta.ema(length=21, append=True)
    df.ta.ema(length=50, append=True)   # needed for EMA Pullback strategy
    df.ta.atr(length=14, append=True)

    # Derived columns used by strategy detectors
    df["body"]       = (df["close"] - df["open"]).abs()
    df["body_avg20"] = df["body"].rolling(20).mean()
    df["range"]      = df["high"] - df["low"]
    df["range_avg20"] = df["range"].rolling(20).mean()

    return df


def get_atr(df: pd.DataFrame) -> float | None:
    col = "ATRr_14"
    if col in df.columns:
        v = df.iloc[-1].get(col)
        return float(v) if v is not None and not pd.isna(v) else None
    return None


def get_rsi(df: pd.DataFrame) -> float | None:
    col = "RSI_14"
    if col in df.columns:
        v = df.iloc[-1].get(col)
        return float(v) if v is not None and not pd.isna(v) else None
    return None
