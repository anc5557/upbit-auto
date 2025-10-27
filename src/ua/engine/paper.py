from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import pandas as pd
import structlog

from ua.engine.common import simulate_long_only, SimResult


@dataclass
class PaperResult:
    metrics: Dict[str, Any]


def run_paper(
    df: pd.DataFrame,
    strategy: Any,
    cash: float,
    fee: float,
    slippage: float,
    *,
    max_fraction: float,
    max_daily_loss: float,
    cooldown_bars: int,
    run_id: Optional[str] = None,
    market: Optional[str] = None,
) -> PaperResult:
    log = structlog.get_logger()
    sig = strategy.signals(df)
    sim: SimResult = simulate_long_only(
        df,
        sig,
        cash=cash,
        fee=fee,
        slippage=slippage,
        max_fraction=max_fraction,
        cooldown_bars=cooldown_bars,
        stop_drawdown=max_daily_loss,
        log=log,
        run_id=run_id,
        market=market,
    )
    return PaperResult(metrics=sim.metrics)

