from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

import httpx
import pandas as pd


UPBIT_API = "https://api.upbit.com/v1"


def _to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def candles_minutes_endpoint(unit: int) -> str:
    return f"{UPBIT_API}/candles/minutes/{unit}"


async def fetch_candles_minutes_async(
    market: str,
    unit: int = 1,
    count: int = 200,
    to: Optional[datetime] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict]:
    url = candles_minutes_endpoint(unit)
    params = {"market": market, "count": count}
    if to is not None:
        params["to"] = _to_iso(to)

    owns = False
    if client is None:
        client = httpx.AsyncClient(timeout=30)
        owns = True
    try:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()
    finally:
        if owns:
            await client.aclose()


def candles_to_df(payload: Iterable[dict]) -> pd.DataFrame:
    # Upbit returns reverse chronological order
    rows = list(payload)[::-1]
    df = pd.DataFrame(rows)
    # Map to OHLCV
    out = pd.DataFrame(
        {
            "Open": df["opening_price"].astype(float),
            "High": df["high_price"].astype(float),
            "Low": df["low_price"].astype(float),
            "Close": df["trade_price"].astype(float),
            "Volume": df["candle_acc_trade_volume"].astype(float),
            "timestamp": pd.to_datetime(df["timestamp"], unit="ms", utc=True),
        }
    )
    return out


async def fetch_range_minutes(
    market: str,
    unit: int,
    max_candles: int,
) -> pd.DataFrame:
    """Fetch up to `max_candles` candles in multiple requests (200 per call)."""
    remaining = max_candles
    to = None
    acc: list[dict] = []
    async with httpx.AsyncClient(timeout=30) as client:
        backoff = 0.5
        while remaining > 0:
            take = min(200, remaining)
            try:
                batch = await fetch_candles_minutes_async(
                    market=market, unit=unit, count=take, to=to, client=client
                )
            except httpx.HTTPStatusError as e:  # pragma: no cover
                status = e.response.status_code if e.response else None
                if status in (429, 500, 502, 503, 504):
                    retry_after = 0.0
                    try:
                        ra = e.response.headers.get("Retry-After") if e.response else None
                        if ra:
                            retry_after = float(ra)
                    except Exception:
                        retry_after = 0.0
                    await asyncio.sleep(max(backoff, retry_after))
                    backoff = min(backoff * 2.0, 8.0)
                    continue
                raise
            except httpx.RequestError:  # pragma: no cover
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 8.0)
                continue

            if not batch:
                break
            acc.extend(batch)
            to = datetime.fromtimestamp(batch[-1]["timestamp"] / 1000, tz=timezone.utc) - timedelta(milliseconds=1)
            remaining -= len(batch)
            backoff = 0.5
            await asyncio.sleep(0.05)

    return candles_to_df(acc)


def save_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def fetch_latest_minutes(market: str, unit: int = 1) -> pd.DataFrame:
    """Fetch the most recent minute candle for a market."""
    async def _one():
        rows = await fetch_candles_minutes_async(market=market, unit=unit, count=1)
        return candles_to_df(rows)

    return asyncio.run(_one())
