from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from ua.engine.backtest import run_backtest
from ua.strategy.base import get_strategy
from ua.strategy.composites.regime_router import RegimeRouter
from ua.reporting.report import write_json

# ensure example strategies are registered
import ua.strategy.examples.ema_rsi  # noqa: F401
import ua.strategy.examples.bb_rsi  # noqa: F401
import ua.strategy.examples.macd_vwap  # noqa: F401
import ua.strategy.examples.sma_cross  # noqa: F401


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
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
    needed = {"Open", "High", "Low", "Close", "Volume"}
    missing = needed - set(df.columns)
    if missing:
        raise SystemExit(f"CSV missing columns: {sorted(missing)}")
    return df


def main():
    ap = argparse.ArgumentParser(description="Backtest multiple strategy combinations including regime-router child swaps")
    ap.add_argument("csv", type=Path, help="Input OHLCV CSV")
    ap.add_argument("--capital", type=float, default=1_000_000.0)
    ap.add_argument("--fee", type=float, default=0.0005)
    ap.add_argument("--slippage", type=float, default=0.0005)
    ap.add_argument("--outdir", type=Path, default=Path("runs"))
    # router params
    ap.add_argument("--adx", type=float, default=20.0)
    ap.add_argument("--ema", type=int, default=50)
    ap.add_argument("--slope_window", type=int, default=20)
    ap.add_argument("--slope_thresh", type=float, default=0.0001)
    ap.add_argument("--bb_width_low", type=float, default=0.0028707)
    ap.add_argument("--bb_width_high", type=float, default=0.0074038)
    # model lists
    ap.add_argument(
        "--trend_list",
        type=str,
        default="ema-rsi,macd-vwap,sma-crossover",
        help="Comma-separated trend strategy names",
    )
    ap.add_argument(
        "--range_list",
        type=str,
        default="bb-rsi",
        help="Comma-separated range strategy names",
    )
    ap.add_argument(
        "--include_baselines",
        action="store_true",
        help="Also run single-strategy baselines for each listed name",
    )

    args = ap.parse_args()
    df = load_csv(args.csv)

    trend_names = [s for s in args.trend_list.split(",") if s]
    range_names = [s for s in args.range_list.split(",") if s]

    rows: List[Dict[str, Any]] = []
    # Sweep router combinations
    for t_name, r_name in itertools.product(trend_names, range_names):
        strat = RegimeRouter(
            trend_strategy=t_name,
            range_strategy=r_name,
            adx_thresh=args.adx,
            ema_trend_period=args.ema,
            slope_window=args.slope_window,
            slope_thresh=args.slope_thresh,
            bb_width_low=args.bb_width_low,
            bb_width_high=args.bb_width_high,
        )
        res = run_backtest(df, strat, cash=args.capital, fee=args.fee, slippage=args.slippage)
        rows.append(
            {
                "mode": "router",
                "trend": t_name,
                "range": r_name,
                **res.metrics,
                "adx_thresh": args.adx,
                "ema_trend_period": args.ema,
                "slope_window": args.slope_window,
                "slope_thresh": args.slope_thresh,
                "bb_width_low": args.bb_width_low,
                "bb_width_high": args.bb_width_high,
            }
        )

    # Optional baselines
    if args.include_baselines:
        uniq_names = sorted(set(trend_names + range_names))
        for name in uniq_names:
            cls = get_strategy(name)
            strat = cls()
            res = run_backtest(df, strat, cash=args.capital, fee=args.fee, slippage=args.slippage)
            rows.append({"mode": "single", "name": name, **res.metrics})

    # Sort by Return then Sharpe
    rows.sort(key=lambda x: (x.get("Return [%]", 0.0), x.get("Sharpe Ratio", 0.0)), reverse=True)

    outdir = args.outdir / "sweeps"
    outdir.mkdir(parents=True, exist_ok=True)
    base = args.csv.stem
    csv_path = outdir / f"sweep_models_{base}.csv"
    json_path = outdir / f"sweep_models_{base}.json"
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    write_json(json_path, {"results": rows[:50], "total": len(rows)})

    print(
        json.dumps(
            {
                "top5": rows[:5],
                "out_csv": str(csv_path),
                "out_json": str(json_path),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

