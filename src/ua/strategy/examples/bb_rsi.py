from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, Field

from ua.strategy.base import register
from ua.strategy.indicators import bollinger, rsi as _rsi, atr as _atr


@register("bb-rsi")
class BollingerRsiStrategy:
    """Bollinger Bands(20,2) + RSI(4) short-term mean reversion.

    - Buy: Price touches/breaks lower band AND RSI crosses up through 20; optional strong green candle confirmation
    - Exit: Price reaches upper band OR RSI >= 80 OR TP/SL
    """

    bb_period: int = 20
    bb_k: float = 2.0
    rsi_period: int = 4
    rsi_buy_level: float = 20.0
    rsi_sell_level: float = 80.0
    require_strong_candle: bool = True
    tp_pct: float = 0.0  # optional explicit TP
    sl_pct: float = 0.01  # fallback if ATR/swing not available
    swing_lookback: int = 10
    stop_buffer_pct: float = 0.001
    # Improvements
    exit_to_mid: bool = False  # exit when reaching mid band instead of upper
    use_atr_sl: bool = False
    atr_period: int = 14
    atr_mult: float = 1.5

    def __init__(
        self,
        bb_period: int | None = None,
        bb_k: float | None = None,
        rsi_period: int | None = None,
        rsi_buy_level: float | None = None,
        rsi_sell_level: float | None = None,
        require_strong_candle: bool | None = None,
        tp_pct: float | None = None,
        sl_pct: float | None = None,
        swing_lookback: int | None = None,
        stop_buffer_pct: float | None = None,
        exit_to_mid: bool | None = None,
        use_atr_sl: bool | None = None,
        atr_period: int | None = None,
        atr_mult: float | None = None,
    ):
        if bb_period is not None:
            self.bb_period = int(bb_period)
        if bb_k is not None:
            self.bb_k = float(bb_k)
        if rsi_period is not None:
            self.rsi_period = int(rsi_period)
        if rsi_buy_level is not None:
            self.rsi_buy_level = float(rsi_buy_level)
        if rsi_sell_level is not None:
            self.rsi_sell_level = float(rsi_sell_level)
        if require_strong_candle is not None:
            self.require_strong_candle = bool(require_strong_candle)
        if tp_pct is not None:
            self.tp_pct = float(tp_pct)
        if sl_pct is not None:
            self.sl_pct = float(sl_pct)
        if swing_lookback is not None:
            self.swing_lookback = int(swing_lookback)
        if stop_buffer_pct is not None:
            self.stop_buffer_pct = float(stop_buffer_pct)
        if exit_to_mid is not None:
            self.exit_to_mid = bool(exit_to_mid)
        if use_atr_sl is not None:
            self.use_atr_sl = bool(use_atr_sl)
        if atr_period is not None:
            self.atr_period = int(atr_period)
        if atr_mult is not None:
            self.atr_mult = float(atr_mult)

    def signals(self, df: pd.DataFrame) -> pd.Series:
        open_ = pd.Series(df["Open"]).astype(float)
        high = pd.Series(df["High"]).astype(float)
        low = pd.Series(df["Low"]).astype(float)
        close = pd.Series(df["Close"]).astype(float)
        lb, ma, ub = bollinger(close, self.bb_period, self.bb_k)
        atr = _atr(high, low, close, period=self.atr_period)
        r = _rsi(close, self.rsi_period)

        # Cross checks
        rsi_up = (r > self.rsi_buy_level) & (r.shift(1) <= self.rsi_buy_level)

        sig = pd.Series(0, index=close.index)
        in_pos = False
        entry = 0.0
        tp = 0.0
        sl = 0.0

        for i in range(len(close)):
            c = float(close.iat[i])
            l = float(low.iat[i])
            o = float(open_.iat[i])
            h = float(high.iat[i])
            band_low = float(lb.iat[i]) if not pd.isna(lb.iat[i]) else None
            band_upp = float(ub.iat[i]) if not pd.isna(ub.iat[i]) else None
            band_mid = float(ma.iat[i]) if not pd.isna(ma.iat[i]) else None

            if i > 0:
                lbk = max(0, i - self.swing_lookback)
                swing_low = float(low.iloc[lbk:i].min()) if i - lbk > 0 else c * (1.0 - self.sl_pct)
            else:
                swing_low = c * (1.0 - self.sl_pct)

            strong_green = (c > o) and ((c - o) >= 0.5 * max(h - l, 1e-12))

            if not in_pos:
                touch_lower = band_low is not None and (c <= band_low or l <= band_low)
                cond = touch_lower and bool(rsi_up.iat[i])
                if self.require_strong_candle:
                    cond = cond and strong_green
                if cond:
                    sig.iat[i] = 1
                    in_pos = True
                    entry = c
                    tp = entry * (1.0 + float(self.tp_pct)) if self.tp_pct > 0 else ((band_mid if self.exit_to_mid else band_upp) if (band_mid if self.exit_to_mid else band_upp) is not None else float("inf"))
                    # Stop slightly below either swing low or current lower band
                    band_stop = band_low * (1.0 - float(self.stop_buffer_pct)) if band_low is not None else entry * (1.0 - float(self.sl_pct))
                    atr_stop = None
                    if self.use_atr_sl and not pd.isna(atr.iat[i]):
                        atr_stop = entry - float(self.atr_mult) * float(atr.iat[i])
                    candidates = [entry * (1.0 - float(self.sl_pct)), swing_low * (1.0 - float(self.stop_buffer_pct)), band_stop]
                    if atr_stop is not None:
                        candidates.append(atr_stop)
                    sl = min(candidates)
            else:
                exit_cond = False
                # target band
                target = band_mid if self.exit_to_mid else band_upp
                reach_target = target is not None and (c >= target or h >= target)
                if reach_target:
                    exit_cond = True
                if float(r.iat[i]) >= self.rsi_sell_level:
                    exit_cond = True
                if c >= tp:
                    exit_cond = True
                if c <= sl:
                    exit_cond = True
                if exit_cond:
                    sig.iat[i] = -1
                    in_pos = False
                    entry = tp = sl = 0.0

        return sig

    def inspect(self, df: pd.DataFrame) -> dict:
        if df.empty:
            return {}
        close = pd.Series(df["Close"]).astype(float)
        lb, ma, ub = bollinger(close, self.bb_period, self.bb_k)
        r = _rsi(close, self.rsi_period)
        return {
            "bb_lower": float(lb.iat[-1]) if not pd.isna(lb.iat[-1]) else None,
            "bb_mid": float(ma.iat[-1]) if not pd.isna(ma.iat[-1]) else None,
            "bb_upper": float(ub.iat[-1]) if not pd.isna(ub.iat[-1]) else None,
            "rsi": float(r.iat[-1]) if not pd.isna(r.iat[-1]) else None,
        }

    def required_bars(self) -> int:
        return int(max(self.bb_period, self.rsi_period, self.atr_period) + 2)

    class Params(BaseModel):
        bb_period: int = Field(20, ge=2)
        bb_k: float = Field(2.0, ge=0.5, le=5.0)
        rsi_period: int = Field(4, ge=2)
        rsi_buy_level: float = Field(20.0, ge=0.0, le=100.0)
        rsi_sell_level: float = Field(80.0, ge=0.0, le=100.0)
        require_strong_candle: bool = Field(True)
        tp_pct: float = Field(0.0, ge=0.0, le=0.2)
        sl_pct: float = Field(0.01, ge=0.0, le=0.2)
        swing_lookback: int = Field(10, ge=1)
        stop_buffer_pct: float = Field(0.001, ge=0.0, le=0.05)
        exit_to_mid: bool = Field(False)
        use_atr_sl: bool = Field(False)
        atr_period: int = Field(14, ge=2)
        atr_mult: float = Field(1.5, ge=0.1, le=10.0)
