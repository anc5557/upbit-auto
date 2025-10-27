from __future__ import annotations

import numpy as np
import pandas as pd


def make_random_walk_ohlcv(
    n: int = 500,
    start_price: float = 1_000_000.0,
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    steps = rng.normal(loc=0.0, scale=0.003, size=n)
    prices = start_price * np.exp(np.cumsum(steps))
    close = prices
    open_ = np.r_[start_price, close[:-1]]
    high = np.maximum(open_, close) * (1 + rng.normal(0, 0.001, size=n).clip(-0.002, 0.002))
    low = np.minimum(open_, close) * (1 - rng.normal(0, 0.001, size=n).clip(-0.002, 0.002))
    vol = rng.integers(1, 10_000, size=n).astype(float)

    df = pd.DataFrame(
        {
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": vol,
        }
    )
    return df

