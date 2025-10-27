from __future__ import annotations

from typing import Dict, Type

import pandas as pd


_REGISTRY: Dict[str, Type] = {}


def register(name: str):
    def deco(cls):
        _REGISTRY[name] = cls
        return cls

    return deco


def get_strategy(name: str) -> Type:
    try:
        return _REGISTRY[name]
    except KeyError as e:  # pragma: no cover
        raise KeyError(f"알 수 없는 전략: {name}. 사용 가능: {', '.join(sorted(_REGISTRY))}") from e


class StrategyProtocol:
    """Lightweight strategy protocol for shared engine.

    A strategy implementation should implement:
    - signals(df: pd.DataFrame) -> pd.Series[int]
    """

    def signals(self, df: pd.DataFrame):  # pragma: no cover - protocol only
        raise NotImplementedError

    # Optional: strategies may declare minimal lookback bars needed
    # Default: 0 (no warmup requirement explicitly declared)
    def required_bars(self) -> int:  # pragma: no cover - optional protocol hook
        return 0
