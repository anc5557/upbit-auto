from __future__ import annotations

import pandas as pd

from ua.strategy.base import register
from pydantic import BaseModel, Field, field_validator


@register("sma-crossover")
class SmaCrossStrategy:
    fast: int = 10
    slow: int = 20

    def __init__(self, fast: int | None = None, slow: int | None = None):
        if fast is not None:
            self.fast = int(fast)
        if slow is not None:
            self.slow = int(slow)

    def signals(self, df: pd.DataFrame) -> pd.Series:
        close = pd.Series(df["Close"]).astype(float)
        ma_f = close.rolling(self.fast, min_periods=self.fast).mean()
        ma_s = close.rolling(self.slow, min_periods=self.slow).mean()
        prev_f = ma_f.shift(1)
        prev_s = ma_s.shift(1)
        buy = (ma_f > ma_s) & (prev_f <= prev_s)
        sell = (ma_f < ma_s) & (prev_f >= prev_s)
        sig = pd.Series(0, index=close.index)
        sig[buy.fillna(False)] = 1
        sig[sell.fillna(False)] = -1
        return sig

    def inspect(self, df: pd.DataFrame) -> dict:
        """Optional debug info for logging/analysis.

        Returns last fast/slow MA and cross state.
        """
        if df.empty:
            return {}
        close = pd.Series(df["Close"]).astype(float)
        ma_f = close.rolling(self.fast, min_periods=self.fast).mean()
        ma_s = close.rolling(self.slow, min_periods=self.slow).mean()
        last_f = float(ma_f.iat[-1]) if not pd.isna(ma_f.iat[-1]) else None
        last_s = float(ma_s.iat[-1]) if not pd.isna(ma_s.iat[-1]) else None
        state = None
        if last_f is not None and last_s is not None:
            state = "above" if last_f > last_s else ("below" if last_f < last_s else "equal")
        return {"ma_fast": last_f, "ma_slow": last_s, "ma_relation": state}

    def required_bars(self) -> int:
        # Need at least slow window, plus one to compare prior bar for crossover
        return int(max(self.fast, self.slow) + 1)

    class Params(BaseModel):
        fast: int = Field(10, ge=1)
        slow: int = Field(20, gt=1)

        @field_validator("slow")
        @classmethod
        def _check_order(cls, v: int, info):
            fast = info.data.get("fast", 10)
            if v <= fast:
                raise ValueError("slow 는 fast 보다 커야 합니다.")
            return v
