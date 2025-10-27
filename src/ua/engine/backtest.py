from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol

import pandas as pd

from ua.engine.common import simulate_long_only, SimResult


class SignalStrategy(Protocol):
    def signals(self, df: pd.DataFrame) -> pd.Series:  # returns 1/-1/0 per bar
        ...


@dataclass
class BacktestResult:
    metrics: Dict[str, Any]
    equity_curve: pd.Series | None = None


def run_backtest(
    df: pd.DataFrame,
    strategy: SignalStrategy,
    cash: float,
    fee: float,
    slippage: float,
) -> BacktestResult:
    """Run a backtest using the shared simulation engine (constitution-aligned).

    Expects df columns: Open, High, Low, Close, Volume
    """
    sig = strategy.signals(df)
    sim: SimResult = simulate_long_only(df, sig, cash=cash, fee=fee, slippage=slippage)
    return BacktestResult(metrics=sim.metrics, equity_curve=sim.equity_curve)
