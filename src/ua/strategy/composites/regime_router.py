from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional

from ua.strategy.base import register, get_strategy
from ua.strategy.indicators import ema, bollinger, adx


@register("regime-router")
class RegimeRouter:
    """Route signals to a trend or range strategy depending on regime.

    Regime logic (per bar):
    - Compute ADX(14) and BB width (k=2, period=20) and 200EMA trend side
    - trend regime if ADX >= adx_thresh and price above ema200 or BB width >= bb_width_thresh
    - otherwise range regime

    The router computes child strategy signals once and selects per bar.
    """

    trend_strategy: str = "ema-rsi"
    range_strategy: str = "bb-rsi"
    adx_period: int = 14
    adx_thresh: float = 20.0
    bb_period: int = 20
    bb_k: float = 2.0
    # refined width thresholds
    bb_width_low: float = 0.015
    bb_width_high: float = 0.03
    ema_trend_period: int = 200
    slope_window: int = 10
    slope_thresh: float = 0.0
    trend_params: Optional[Dict[str, Any]] = None
    range_params: Optional[Dict[str, Any]] = None

    def __init__(
        self,
        trend_strategy: str | None = None,
        range_strategy: str | None = None,
        adx_period: int | None = None,
        adx_thresh: float | None = None,
        bb_period: int | None = None,
        bb_k: float | None = None,
        bb_width_low: float | None = None,
        bb_width_high: float | None = None,
        ema_trend_period: int | None = None,
        slope_window: int | None = None,
        slope_thresh: float | None = None,
        trend_params: Optional[Dict[str, Any]] = None,
        range_params: Optional[Dict[str, Any]] = None,
    ):
        if trend_strategy is not None:
            self.trend_strategy = str(trend_strategy)
        if range_strategy is not None:
            self.range_strategy = str(range_strategy)
        if adx_period is not None:
            self.adx_period = int(adx_period)
        if adx_thresh is not None:
            self.adx_thresh = float(adx_thresh)
        if bb_period is not None:
            self.bb_period = int(bb_period)
        if bb_k is not None:
            self.bb_k = float(bb_k)
        if bb_width_low is not None:
            self.bb_width_low = float(bb_width_low)
        if bb_width_high is not None:
            self.bb_width_high = float(bb_width_high)
        if ema_trend_period is not None:
            self.ema_trend_period = int(ema_trend_period)
        if slope_window is not None:
            self.slope_window = int(slope_window)
        if slope_thresh is not None:
            self.slope_thresh = float(slope_thresh)

        # Instantiate child strategies
        self._trend_cls = get_strategy(self.trend_strategy)
        self._range_cls = get_strategy(self.range_strategy)
        from ua.strategy.params import apply_params as _apply
        self._trend = self._trend_cls()
        self._range = self._range_cls()
        if isinstance(trend_params, dict):
            try:
                self._trend = _apply(self._trend, trend_params)
            except Exception:
                pass
        if isinstance(range_params, dict):
            try:
                self._range = _apply(self._range, range_params)
            except Exception:
                pass

    def _regime(self, df: pd.DataFrame) -> pd.Series:
        close = pd.Series(df["Close"]).astype(float)
        high = pd.Series(df["High"]).astype(float)
        low = pd.Series(df["Low"]).astype(float)
        _, _, adx_val = adx(high, low, close, period=self.adx_period)
        lb, mid, ub = bollinger(close, self.bb_period, self.bb_k)
        width = ((ub - lb) / (mid + 1e-12)).fillna(0.0)
        ema200 = ema(close, self.ema_trend_period)
        ema_ref = ema200.shift(self.slope_window)
        slope = (ema200 - ema_ref) / (ema_ref + 1e-12)
        trend_base = (adx_val >= self.adx_thresh) & (close > ema200) & (slope > self.slope_thresh)
        trend_wide = width >= self.bb_width_high
        range_narrow = (width <= self.bb_width_low) & (adx_val < self.adx_thresh)

        reg = pd.Series(object, index=close.index)
        reg[:] = None
        reg[trend_base | trend_wide] = "trend"
        reg[range_narrow] = "range"
        reg = reg.ffill().fillna("range")
        return reg.map({"trend": 1, "range": 0}).astype(int)

    def signals(self, df: pd.DataFrame) -> pd.Series:
        if len(df) == 0:
            return pd.Series([], dtype=int)
        r = self._regime(df)
        sig_trend = self._trend.signals(df)
        sig_range = self._range.signals(df)
        # Select per bar
        sig = pd.Series(0, index=r.index)
        trend_idx = r == 1
        range_idx = r == 0
        sig.loc[trend_idx] = sig_trend.loc[trend_idx].astype(int)
        sig.loc[range_idx] = sig_range.loc[range_idx].astype(int)
        return sig

    def inspect(self, df: pd.DataFrame) -> dict:
        if len(df) == 0:
            return {}
        close = float(df["Close"].iloc[-1])
        high = pd.Series(df["High"]).astype(float)
        low = pd.Series(df["Low"]).astype(float)
        c = pd.Series(df["Close"]).astype(float)
        _, _, a = adx(high, low, c, period=self.adx_period)
        lb, mid, ub = bollinger(c, self.bb_period, self.bb_k)
        try:
            width = float(((ub.iat[-1] - lb.iat[-1]) / (mid.iat[-1] + 1e-12)))
        except Exception:
            width = None
        e = ema(c, self.ema_trend_period)
        er = e.shift(self.slope_window)
        try:
            sl = float((e.iat[-1] - er.iat[-1]) / (er.iat[-1] + 1e-12))
        except Exception:
            sl = None
        regime = int(self._regime(df).iat[-1])
        return {"close": close, "adx": float(a.iat[-1]) if not pd.isna(a.iat[-1]) else None, "bb_width": width, "ema200_slope": sl, "regime": "trend" if regime == 1 else "range"}

    def required_bars(self) -> int:
        return int(max(self.ema_trend_period, self.bb_period, self.adx_period) + 2)

    class Params(BaseModel):
        trend_strategy: str = Field("ema-rsi")
        range_strategy: str = Field("bb-rsi")
        adx_period: int = Field(14, ge=2)
        adx_thresh: float = Field(20.0, ge=0.0, le=100.0)
        bb_period: int = Field(20, ge=2)
        bb_k: float = Field(2.0, ge=0.5, le=5.0)
        bb_width_low: float = Field(0.015, ge=0.0, le=1.0)
        bb_width_high: float = Field(0.03, ge=0.0, le=1.0)
        ema_trend_period: int = Field(200, ge=10)
        slope_window: int = Field(10, ge=1)
        slope_thresh: float = Field(0.0)
        trend_params: Optional[Dict[str, Any]] = None
        range_params: Optional[Dict[str, Any]] = None
