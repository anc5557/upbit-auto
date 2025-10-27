from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pandas as pd


def floor_minute(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.replace(second=0, microsecond=0)


@dataclass
class CandleBucket:
    start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class CandleAggregator:
    """Aggregate trade ticks into 1-minute OHLCV candles."""

    def __init__(self) -> None:
        self.bucket: Optional[CandleBucket] = None

    def update(self, ts: datetime, price: float, volume: float) -> Optional[pd.DataFrame]:
        ts = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        key = floor_minute(ts)
        if self.bucket is None:
            self.bucket = CandleBucket(start=key, open=price, high=price, low=price, close=price, volume=volume)
            return None
        # new minute → finalize previous
        if key > self.bucket.start:
            df = pd.DataFrame(
                {
                    "timestamp": [self.bucket.start],
                    "Open": [self.bucket.open],
                    "High": [self.bucket.high],
                    "Low": [self.bucket.low],
                    "Close": [self.bucket.close],
                    "Volume": [self.bucket.volume],
                }
            )
            # start new bucket
            self.bucket = CandleBucket(start=key, open=price, high=price, low=price, close=price, volume=volume)
            return df
        # same minute
        b = self.bucket
        b.high = max(b.high, price)
        b.low = min(b.low, price)
        b.close = price
        b.volume += volume
        return None

    def finalize(self) -> Optional[pd.DataFrame]:
        if self.bucket is None:
            return None
        b = self.bucket
        self.bucket = None
        return pd.DataFrame(
            {
                "timestamp": [b.start],
                "Open": [b.open],
                "High": [b.high],
                "Low": [b.low],
                "Close": [b.close],
                "Volume": [b.volume],
            }
        )

