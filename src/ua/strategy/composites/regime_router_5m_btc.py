from __future__ import annotations

from typing import Any, Dict, Optional

from ua.strategy.base import register
from ua.strategy.composites.regime_router import RegimeRouter


@register("regime-router-5m-btc")
class RegimeRouter5mBTC(RegimeRouter):
    """RegimeRouter tuned for KRW-BTC 5m (p20/p80 BB width, range tweaks).

    Defaults derived from backtests on KRW-BTC 5m 10k bars:
    - Regime: ADX=18, EMA trend=50, slope_window=20, slope_thresh=0.0
    - BB width thresholds: low=0.0028707 (p20), high=0.0074038 (p80)
    - Range(bb-rsi): rsi_period=8, levels=22/78, exit_to_mid=True, ATR SL(1.5x)

    All defaults can be overridden via CLI --param flags.
    """

    # Router defaults
    adx_thresh: float = 18.0
    ema_trend_period: int = 50
    slope_window: int = 20
    slope_thresh: float = 0.0
    bb_width_low: float = 0.0028707
    bb_width_high: float = 0.0074038
    trend_strategy: str = "ema-rsi"
    range_strategy: str = "bb-rsi"

    def __init__(
        self,
        # allow overriding router params
        adx_thresh: Optional[float] = None,
        ema_trend_period: Optional[int] = None,
        slope_window: Optional[int] = None,
        slope_thresh: Optional[float] = None,
        bb_width_low: Optional[float] = None,
        bb_width_high: Optional[float] = None,
        trend_strategy: Optional[str] = None,
        range_strategy: Optional[str] = None,
        # allow overriding child params
        trend_params: Optional[Dict[str, Any]] = None,
        range_params: Optional[Dict[str, Any]] = None,
    ):
        # Pre-fill tuned range params; allow caller to override/extend
        tuned_range = {
            "rsi_period": 8,
            "rsi_buy_level": 22.0,
            "rsi_sell_level": 78.0,
            "exit_to_mid": True,
            "use_atr_sl": True,
            "atr_period": 14,
            "atr_mult": 1.5,
            "bb_k": 2.0,
            "bb_period": 20,
        }
        if isinstance(range_params, dict):
            tuned_range.update(range_params)

        super().__init__(
            trend_strategy=trend_strategy or self.trend_strategy,
            range_strategy=range_strategy or self.range_strategy,
            adx_period=None,
            adx_thresh=adx_thresh if adx_thresh is not None else self.adx_thresh,
            bb_period=20,
            bb_k=2.0,
            bb_width_low=bb_width_low if bb_width_low is not None else self.bb_width_low,
            bb_width_high=bb_width_high if bb_width_high is not None else self.bb_width_high,
            ema_trend_period=ema_trend_period if ema_trend_period is not None else self.ema_trend_period,
            slope_window=slope_window if slope_window is not None else self.slope_window,
            slope_thresh=slope_thresh if slope_thresh is not None else self.slope_thresh,
            trend_params=trend_params,
            range_params=tuned_range,
        )

