"""Indikator teknikal. Semua fungsi menerima/mengembalikan pandas Series."""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False, min_periods=window).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """RSI Wilder."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    # Kalau tidak pernah turun dalam periode itu, RSI = 100.
    return out.where(avg_loss != 0, 100.0).where(avg_gain.notna())


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    line = ema(series, fast) - ema(series, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    return pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()


def bollinger(series: pd.Series, window: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    mid = sma(series, window)
    std = series.rolling(window, min_periods=window).std()
    upper, lower = mid + num_std * std, mid - num_std * std
    width = (upper - lower) / mid.replace(0, np.nan)
    pct_b = (series - lower) / (upper - lower).replace(0, np.nan)
    return pd.DataFrame({"mid": mid, "upper": upper, "lower": lower,
                         "width": width, "pct_b": pct_b})


def stochastic(
    high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14, smooth: int = 3
) -> pd.DataFrame:
    lowest = low.rolling(window, min_periods=window).min()
    highest = high.rolling(window, min_periods=window).max()
    k = 100 * (close - lowest) / (highest - lowest).replace(0, np.nan)
    return pd.DataFrame({"k": k, "d": k.rolling(smooth, min_periods=smooth).mean()})


def money_flow_index(
    high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, window: int = 14
) -> pd.Series:
    typical = (high + low + close) / 3
    raw_flow = typical * volume
    direction = typical.diff()
    pos = raw_flow.where(direction > 0, 0.0).rolling(window, min_periods=window).sum()
    neg = raw_flow.where(direction < 0, 0.0).rolling(window, min_periods=window).sum()
    ratio = pos / neg.replace(0, np.nan)
    return (100 - 100 / (1 + ratio)).where(neg != 0, 100.0)


def pct_change_n(series: pd.Series, periods: int) -> pd.Series:
    """Return dalam persen untuk n hari bursa ke belakang."""
    return series.pct_change(periods) * 100
