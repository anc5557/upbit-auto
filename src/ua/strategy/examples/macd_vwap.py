from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, Field

from ua.strategy.base import register
from ua.strategy.indicators import macd as _macd, vwap as _vwap


@register("macd-vwap")
class MacdVwapStrategy:
    """MACD(12,26,9) + VWAP session strategy.

    - Buy: Close crosses above VWAP AND MACD line crosses above signal with histogram > 0
    - Exit: MACD histogram flips negative OR Close crosses below VWAP OR SL/TP
    """

    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    vwap_session: str = "D"  # reset per UTC day
    tp_pct: float = 0.0  # optional take profit
    sl_pct: float = 0.01
    swing_lookback: int = 10
    # Improvements/filters
    min_hist_ratio: float = 0.0  # require |hist|/price >= this
    signal_cooldown_bars: int = 0  # prevent re-entry within N bars after exit
    min_vwap_dev: float = 0.0  # require (close - vwap)/vwap >= this on entry

    def __init__(
        self,
        macd_fast: int | None = None,
        macd_slow: int | None = None,
        macd_signal: int | None = None,
        vwap_session: str | None = None,
        tp_pct: float | None = None,
        sl_pct: float | None = None,
        swing_lookback: int | None = None,
        min_hist_ratio: float | None = None,
        signal_cooldown_bars: int | None = None,
        min_vwap_dev: float | None = None,
    ):
        if macd_fast is not None:
            self.macd_fast = int(macd_fast)
        if macd_slow is not None:
            self.macd_slow = int(macd_slow)
        if macd_signal is not None:
            self.macd_signal = int(macd_signal)
        if vwap_session is not None:
            self.vwap_session = str(vwap_session)
        if tp_pct is not None:
            self.tp_pct = float(tp_pct)
        if sl_pct is not None:
            self.sl_pct = float(sl_pct)
        if swing_lookback is not None:
            self.swing_lookback = int(swing_lookback)
        if min_hist_ratio is not None:
            self.min_hist_ratio = float(min_hist_ratio)
        if signal_cooldown_bars is not None:
            self.signal_cooldown_bars = max(0, int(signal_cooldown_bars))
        if min_vwap_dev is not None:
            self.min_vwap_dev = float(min_vwap_dev)

    def signals(self, df: pd.DataFrame) -> pd.Series:
        close = pd.Series(df["Close"]).astype(float)
        low = pd.Series(df["Low"]).astype(float)
        macd_line, signal_line, hist = _macd(close, self.macd_fast, self.macd_slow, self.macd_signal)
        vw = _vwap(df, session=self.vwap_session)

        price_cross_up = (close > vw) & (close.shift(1) <= vw.shift(1))
        price_cross_dn = (close < vw) & (close.shift(1) >= vw.shift(1))
        macd_cross_up = (macd_line > signal_line) & (macd_line.shift(1) <= signal_line.shift(1))

        sig = pd.Series(0, index=close.index)
        in_pos = False
        entry = 0.0
        tp = 0.0
        sl = 0.0
        last_exit_idx = -10**9

        for i in range(len(close)):
            c = float(close.iat[i])
            if i > 0:
                lb = max(0, i - self.swing_lookback)
                swing_low = float(low.iloc[lb:i].min()) if i - lb > 0 else c * (1.0 - self.sl_pct)
            else:
                swing_low = c * (1.0 - self.sl_pct)

            if not in_pos:
                if bool(price_cross_up.iat[i]) and bool(macd_cross_up.iat[i]) and bool(hist.iat[i] > 0):
                    # Filters
                    if i - last_exit_idx < int(self.signal_cooldown_bars):
                        continue
                    dev = (c - float(vw.iat[i])) / (float(vw.iat[i]) + 1e-12)
                    if self.min_vwap_dev > 0 and dev < self.min_vwap_dev:
                        continue
                    ratio = abs(float(hist.iat[i])) / (c + 1e-12)
                    if self.min_hist_ratio > 0 and ratio < self.min_hist_ratio:
                        continue
                    sig.iat[i] = 1
                    in_pos = True
                    entry = c
                    tp = entry * (1.0 + float(self.tp_pct)) if self.tp_pct > 0 else float("inf")
                    sl = min(entry * (1.0 - float(self.sl_pct)), swing_low)
            else:
                exit_cond = False
                if hist.iat[i] < 0:
                    exit_cond = True
                if bool(price_cross_dn.iat[i]):
                    exit_cond = True
                if c <= sl:
                    exit_cond = True
                if c >= tp:
                    exit_cond = True
                if exit_cond:
                    sig.iat[i] = -1
                    in_pos = False
                    entry = tp = sl = 0.0
                    last_exit_idx = i

        return sig

    def inspect(self, df: pd.DataFrame) -> dict:
        if df.empty:
            return {}
        close = pd.Series(df["Close"]).astype(float)
        macd_line, signal_line, hist = _macd(close, self.macd_fast, self.macd_slow, self.macd_signal)
        vw = _vwap(df, session=self.vwap_session)
        return {
            "macd": float(macd_line.iat[-1]) if not pd.isna(macd_line.iat[-1]) else None,
            "signal": float(signal_line.iat[-1]) if not pd.isna(signal_line.iat[-1]) else None,
            "hist": float(hist.iat[-1]) if not pd.isna(hist.iat[-1]) else None,
            "vwap": float(vw.iat[-1]) if not pd.isna(vw.iat[-1]) else None,
        }

    def required_bars(self) -> int:
        return int(self.macd_slow + self.macd_signal + 1)

    class Params(BaseModel):
        macd_fast: int = Field(12, ge=1)
        macd_slow: int = Field(26, gt=1)
        macd_signal: int = Field(9, ge=1)
        vwap_session: str = Field("D")
        tp_pct: float = Field(0.0, ge=0.0, le=0.2)
        sl_pct: float = Field(0.01, ge=0.0, le=0.2)
        swing_lookback: int = Field(10, ge=1)
        min_hist_ratio: float = Field(0.0, ge=0.0, le=0.05)
        signal_cooldown_bars: int = Field(0, ge=0, le=200)
        min_vwap_dev: float = Field(0.0, ge=0.0, le=0.05)
