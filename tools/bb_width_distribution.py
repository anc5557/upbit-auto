from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from ua.strategy.indicators import bollinger


def compute_bb_width_percentiles(
    df: pd.DataFrame, period: int = 20, k: float = 2.0
) -> dict:
    close = pd.Series(df["Close"]).astype(float)
    lb, mid, ub = bollinger(close, period=period, k=k)
    width = ((ub - lb) / (mid + 1e-12)).dropna()
    # percent scale for readability
    width_pct = width * 100.0
    percentiles = [5, 10, 20, 30, 50, 70, 80, 90, 95]
    result = {f"p{p}": float(width_pct.quantile(p / 100.0)) for p in percentiles}
    result.update(
        {
            "mean": float(width_pct.mean()),
            "std": float(width_pct.std()),
            "min": float(width_pct.min()) if len(width_pct) else None,
            "max": float(width_pct.max()) if len(width_pct) else None,
            "count": int(width_pct.count()),
            "period": int(period),
            "k": float(k),
        }
    )
    return result


def main():
    ap = argparse.ArgumentParser(
        description="Compute Bollinger Band width distribution (percent scales)."
    )
    ap.add_argument("csv", type=Path, help="Input OHLCV CSV path")
    ap.add_argument("--period", type=int, default=20)
    ap.add_argument("--k", type=float, default=2.0)
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional output JSON path (also prints to STDOUT)",
    )
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    rename_map = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
        "time": "timestamp",
        "date": "timestamp",
    }
    df = df.rename(columns={c: rename_map.get(c.lower(), c) for c in df.columns})
    for col in ["Open", "High", "Low", "Close"]:
        if col not in df.columns:
            raise SystemExit(f"Missing column: {col}")

    stats = compute_bb_width_percentiles(df, period=args.period, k=args.k)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(stats, ensure_ascii=False, indent=2))
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()

