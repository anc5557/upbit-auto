from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, Field, field_validator

from ua.strategy.base import register
from ua.strategy.indicators import ema, rsi


@register("ema-rsi")
class EmaRsiStrategy:
    """EMA(9/21) crossover + RSI(14) confirmation with TP/SL exits.

    - Buy: EMA_fast crosses above EMA_slow AND RSI crosses up through 30
    - Exit: TP reached, or RSI >= 70, or EMA_fast crosses below EMA_slow, or SL hit
    Note: Engine is long-only; a short signal is treated as an exit.
    """

    ema_fast: int = 9
    ema_slow: int = 21
    rsi_period: int = 14
    rsi_buy_threshold: float = 30.0
    rsi_sell_threshold: float = 70.0
    # Allow RSI buy-cross to happen within recent N bars before EMA cross
    confirm_window: int = 3
    tp_pct: float = 0.0075  # 0.75%
    sl_pct: float = 0.01  # 1% fallback if swing low unavailable
    swing_lookback: int = 14
    stop_buffer_pct: float = 0.001
    use_rsi_exit: bool = True
    use_crossover_exit: bool = True
    # Pullback confirmation: require price to have pulled back to/below slow EMA within last N bars
    require_pullback: bool = False
    pullback_window: int = 5
    pullback_buffer_pct: float = 0.0

    def __init__(
        self,
        ema_fast: int | None = None,
        ema_slow: int | None = None,
        rsi_period: int | None = None,
        rsi_buy_threshold: float | None = None,
        rsi_sell_threshold: float | None = None,
        tp_pct: float | None = None,
        sl_pct: float | None = None,
        swing_lookback: int | None = None,
        stop_buffer_pct: float | None = None,
        use_rsi_exit: bool | None = None,
        use_crossover_exit: bool | None = None,
        confirm_window: int | None = None,
        require_pullback: bool | None = None,
        pullback_window: int | None = None,
        pullback_buffer_pct: float | None = None,
    ):
        if ema_fast is not None:
            self.ema_fast = int(ema_fast)
        if ema_slow is not None:
            self.ema_slow = int(ema_slow)
        if rsi_period is not None:
            self.rsi_period = int(rsi_period)
        if rsi_buy_threshold is not None:
            self.rsi_buy_threshold = float(rsi_buy_threshold)
        if rsi_sell_threshold is not None:
            self.rsi_sell_threshold = float(rsi_sell_threshold)
        if tp_pct is not None:
            self.tp_pct = float(tp_pct)
        if sl_pct is not None:
            self.sl_pct = float(sl_pct)
        if swing_lookback is not None:
            self.swing_lookback = int(swing_lookback)
        if stop_buffer_pct is not None:
            self.stop_buffer_pct = float(stop_buffer_pct)
        if use_rsi_exit is not None:
            self.use_rsi_exit = bool(use_rsi_exit)
        if use_crossover_exit is not None:
            self.use_crossover_exit = bool(use_crossover_exit)
        if confirm_window is not None:
            self.confirm_window = max(1, int(confirm_window))
        if require_pullback is not None:
            self.require_pullback = bool(require_pullback)
        if pullback_window is not None:
            self.pullback_window = max(1, int(pullback_window))
        if pullback_buffer_pct is not None:
            self.pullback_buffer_pct = float(pullback_buffer_pct)

    def signals(self, df: pd.DataFrame) -> pd.Series:
        close = pd.Series(df["Close"]).astype(float)
        low = pd.Series(df["Low"]).astype(float)
        f = ema(close, self.ema_fast)
        s = ema(close, self.ema_slow)
        r = rsi(close, self.rsi_period)

        cross_up = (f > s) & (f.shift(1) <= s.shift(1))
        cross_dn = (f < s) & (f.shift(1) >= s.shift(1))
        rsi_up = (r > self.rsi_buy_threshold) & (r.shift(1) <= self.rsi_buy_threshold)
        rsi_dn = (r < self.rsi_sell_threshold) & (r.shift(1) >= self.rsi_sell_threshold)

        sig = pd.Series(0, index=close.index)
        in_pos = False
        entry = 0.0
        tp = 0.0
        sl = 0.0

        last_rsi_up_idx = None
        for i in range(len(close)):
            c = float(close.iat[i])
            # track last RSI upward cross index
            if bool(rsi_up.iat[i]):
                last_rsi_up_idx = i
            # try to compute swing low based on prior bars
            if i > 0:
                lb = max(0, i - self.swing_lookback)
                swing_low = float(low.iloc[lb:i].min()) if i - lb > 0 else c * (1.0 - self.sl_pct)
            else:
                swing_low = c * (1.0 - self.sl_pct)

            if not in_pos:
                rsi_recent = (last_rsi_up_idx is not None) and (i - last_rsi_up_idx <= int(self.confirm_window))
                pullback_ok = True
                if self.require_pullback:
                    w = int(self.pullback_window)
                    j0 = max(0, i - w)
                    # require low within window to have touched or fallen below slow EMA (with optional buffer)
                    s_prev = float(s.iat[i-1]) if i-1 >= 0 and not pd.isna(s.iat[i-1]) else None
                    if s_prev is None:
                        pullback_ok = False
                    else:
                        lb_min = float(low.iloc[j0:i].min()) if i - j0 > 0 else float('inf')
                        thresh = s_prev * (1.0 - float(self.pullback_buffer_pct))
                        pullback_ok = lb_min <= thresh
                if bool(cross_up.iat[i]) and rsi_recent and pullback_ok:
                    sig.iat[i] = 1
                    in_pos = True
                    entry = c
                    tp = entry * (1.0 + float(self.tp_pct))
                    sl = min(entry * (1.0 - float(self.sl_pct)), swing_low * (1.0 - float(self.stop_buffer_pct)))
            else:
                exit_cond = False
                if c >= tp:
                    exit_cond = True
                if self.use_rsi_exit and bool(r.iat[i] >= self.rsi_sell_threshold):
                    exit_cond = True
                if self.use_crossover_exit and bool(cross_dn.iat[i]):
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
        f = ema(close, self.ema_fast)
        s = ema(close, self.ema_slow)
        r = rsi(close, self.rsi_period)
        last = {
            "ema_fast": float(f.iat[-1]) if not pd.isna(f.iat[-1]) else None,
            "ema_slow": float(s.iat[-1]) if not pd.isna(s.iat[-1]) else None,
            "rsi": float(r.iat[-1]) if not pd.isna(r.iat[-1]) else None,
        }
        if last["ema_fast"] is not None and last["ema_slow"] is not None:
            last["trend"] = "bull" if last["ema_fast"] > last["ema_slow"] else "bear"
        return last

    def required_bars(self) -> int:
        return int(max(self.ema_slow, self.rsi_period) + 2)

    class Params(BaseModel):
        ema_fast: int = Field(9, ge=1)
        ema_slow: int = Field(21, gt=1)
        rsi_period: int = Field(14, ge=2)
        rsi_buy_threshold: float = Field(30.0, ge=0.0, le=100.0)
        rsi_sell_threshold: float = Field(70.0, ge=0.0, le=100.0)
        confirm_window: int = Field(3, ge=1, le=50)
        tp_pct: float = Field(0.0075, ge=0.0, le=0.1)
        sl_pct: float = Field(0.01, ge=0.0, le=0.1)
        swing_lookback: int = Field(14, ge=1)
        stop_buffer_pct: float = Field(0.001, ge=0.0, le=0.05)
        use_rsi_exit: bool = Field(True)
        use_crossover_exit: bool = Field(True)
        require_pullback: bool = Field(False)
        pullback_window: int = Field(5, ge=1, le=100)
        pullback_buffer_pct: float = Field(0.0, ge=0.0, le=0.05)

        @field_validator("ema_slow")
        @classmethod
        def _check_order(cls, v: int, info):
            fast = info.data.get("ema_fast", 9)
            if v <= fast:
                raise ValueError("ema_slow 는 ema_fast 보다 커야 합니다.")
            return v
