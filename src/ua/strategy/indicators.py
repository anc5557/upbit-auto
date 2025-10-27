from __future__ import annotations

import pandas as pd


def _to_series(x) -> pd.Series:
    return pd.Series(x).astype(float)


def ema(series: pd.Series, span: int) -> pd.Series:
    s = _to_series(series)
    return s.ewm(span=span, adjust=False, min_periods=span).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    s = _to_series(series)
    delta = s.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    # Wilder's smoothing via EMA with alpha=1/period
    roll_up = up.ewm(alpha=1 / float(period), adjust=False, min_periods=period).mean()
    roll_down = down.ewm(alpha=1 / float(period), adjust=False, min_periods=period).mean()
    rs = roll_up / (roll_down + 1e-12)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    s = _to_series(series)
    ema_f = ema(s, fast)
    ema_s = ema(s, slow)
    macd_line = ema_f - ema_s
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def bollinger(series: pd.Series, period: int = 20, k: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    s = _to_series(series)
    ma = s.rolling(period, min_periods=period).mean()
    sd = s.rolling(period, min_periods=period).std(ddof=0)
    upper = ma + k * sd
    lower = ma - k * sd
    return lower, ma, upper


def vwap(df: pd.DataFrame, session: str = "D") -> pd.Series:
    """Volume Weighted Average Price reset each session (default: daily).

    If timestamp is present and datetime-like, reset per session boundary using .dt.floor(session).
    Otherwise compute one cumulative VWAP over entire DataFrame.
    """
    if {"High", "Low", "Close", "Volume"} - set(df.columns):
        raise ValueError("VWAP requires High, Low, Close, Volume columns")
    typical = (pd.to_numeric(df["High"]) + pd.to_numeric(df["Low"]) + pd.to_numeric(df["Close"])) / 3.0
    vol = pd.to_numeric(df["Volume"]) + 0.0
    if "timestamp" in df.columns:
        try:
            ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            grp = ts.dt.floor(session)
            cum_pv = (typical * vol).groupby(grp).cumsum()
            cum_v = vol.groupby(grp).cumsum()
            return cum_pv / (cum_v + 1e-12)
        except Exception:
            pass
    # Fallback: single running VWAP
    cum_pv = (typical * vol).cumsum()
    cum_v = vol.cumsum()
    return cum_pv / (cum_v + 1e-12)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range (Wilder)."""
    h = _to_series(high)
    l = _to_series(low)
    c = _to_series(close)
    prev_close = c.shift(1)
    tr = pd.concat([
        (h - l).abs(),
        (h - prev_close).abs(),
        (l - prev_close).abs(),
    ], axis=1).max(axis=1)
    # Wilder's smoothing via EMA alpha=1/period
    return tr.ewm(alpha=1 / float(period), adjust=False, min_periods=period).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Average Directional Index (Wilder).

    Returns: (+DI, -DI, ADX)
    """
    h = _to_series(high)
    l = _to_series(low)
    c = _to_series(close)

    up_move = h.diff()
    down_move = -l.diff()
    plus_dm = ((up_move > down_move) & (up_move > 0)).astype(float) * up_move.clip(lower=0)
    minus_dm = ((down_move > up_move) & (down_move > 0)).astype(float) * down_move.clip(lower=0)

    tr = pd.concat([
        (h - l).abs(),
        (h - c.shift(1)).abs(),
        (l - c.shift(1)).abs(),
    ], axis=1).max(axis=1)

    atr_series = tr.ewm(alpha=1 / float(period), adjust=False, min_periods=period).mean()
    plus_di = 100.0 * (plus_dm.ewm(alpha=1 / float(period), adjust=False, min_periods=period).mean() / (atr_series + 1e-12))
    minus_di = 100.0 * (minus_dm.ewm(alpha=1 / float(period), adjust=False, min_periods=period).mean() / (atr_series + 1e-12))
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di + 1e-12)) * 100.0
    adx = dx.ewm(alpha=1 / float(period), adjust=False, min_periods=period).mean()
    return plus_di, minus_di, adx
