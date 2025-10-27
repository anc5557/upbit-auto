from __future__ import annotations

import argparse
import itertools
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from ua.engine.backtest import run_backtest
from ua.strategy.composites.regime_router import RegimeRouter
# ensure child strategies are registered
import ua.strategy.examples.ema_rsi  # noqa: F401
import ua.strategy.examples.bb_rsi  # noqa: F401
from ua.reporting.report import write_json
# Support running as a script from repo root
try:
    from tools.bb_width_distribution import compute_bb_width_percentiles  # type: ignore
except Exception:
    import sys
    from pathlib import Path as _P
    sys.path.append(str(_P(__file__).resolve().parent))
    from bb_width_distribution import compute_bb_width_percentiles  # type: ignore


@dataclass
class SweepResult:
    params: Dict[str, Any]
    metrics: Dict[str, Any]


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
    ap = argparse.ArgumentParser(description="Sweep RegimeRouter parameters over a grid")
    ap.add_argument("csv", type=Path, help="Input OHLCV CSV (e.g., data/krw-btc_5m_10k.csv)")
    ap.add_argument("--capital", type=float, default=1_000_000.0)
    ap.add_argument("--fee", type=float, default=0.0005)
    ap.add_argument("--slippage", type=float, default=0.0005)
    ap.add_argument("--outdir", type=Path, default=Path("runs"))
    # grids
    ap.add_argument("--adx", type=str, default="18,20,22,24,26,28,30")
    ap.add_argument("--ema", type=str, default="50,100,120,200")
    ap.add_argument("--slope_window", type=str, default="10,20")
    ap.add_argument("--slope_thresh", type=str, default="0.0,0.0001")
    ap.add_argument("--bb_period", type=int, default=20)
    ap.add_argument("--bb_k", type=float, default=2.0)
    ap.add_argument(
        "--bb_percentiles",
        type=str,
        default="20,80",
        help="Low,High percentiles for BB width (percent scale)",
    )

    args = ap.parse_args()
    df = load_csv(args.csv)

    # Compute BB width distribution once and choose thresholds by percentiles
    stats = compute_bb_width_percentiles(df, period=args.bb_period, k=args.bb_k)
    p_low, p_high = [int(x) for x in args.bb_percentiles.split(",")]
    bb_width_low = stats[f"p{p_low}"] / 100.0  # convert back to ratio units
    bb_width_high = stats[f"p{p_high}"] / 100.0

    adx_vals = [float(x) for x in args.adx.split(",") if x]
    ema_vals = [int(x) for x in args.ema.split(",") if x]
    slope_w_vals = [int(x) for x in args.slope_window.split(",") if x]
    slope_t_vals = [float(x) for x in args.slope_thresh.split(",") if x]

    combos: List[Tuple[float, int, int, float]] = list(
        itertools.product(adx_vals, ema_vals, slope_w_vals, slope_t_vals)
    )

    results: List[SweepResult] = []
    for adx_th, ema_p, sl_w, sl_t in combos:
        strat = RegimeRouter(
            adx_thresh=adx_th,
            ema_trend_period=ema_p,
            slope_window=sl_w,
            slope_thresh=sl_t,
            bb_period=args.bb_period,
            bb_k=args.bb_k,
            bb_width_low=bb_width_low,
            bb_width_high=bb_width_high,
        )
        r = run_backtest(df, strat, cash=args.capital, fee=args.fee, slippage=args.slippage)
        params = {
            "adx_thresh": adx_th,
            "ema_trend_period": ema_p,
            "slope_window": sl_w,
            "slope_thresh": sl_t,
            "bb_width_low": bb_width_low,
            "bb_width_high": bb_width_high,
            "bb_period": args.bb_period,
            "bb_k": args.bb_k,
        }
        results.append(SweepResult(params=params, metrics=r.metrics))

    # Sort by Return [%] then Sharpe as tiebreaker
    results.sort(key=lambda x: (x.metrics.get("Return [%]", 0.0), x.metrics.get("Sharpe Ratio", 0.0)), reverse=True)

    # Emit CSV and JSON summary
    rows = []
    for i, s in enumerate(results, start=1):
        row = {**s.params, **s.metrics}
        row["rank"] = i
        rows.append(row)
    outdir = args.outdir / "sweeps"
    outdir.mkdir(parents=True, exist_ok=True)
    base = args.csv.stem
    csv_path = outdir / f"sweep_regime_router_{base}.csv"
    json_path = outdir / f"sweep_regime_router_{base}.json"
    dist_path = outdir / f"bb_width_stats_{base}.json"

    pd.DataFrame(rows).to_csv(csv_path, index=False)
    write_json(json_path, {"results": rows[:50], "total": len(rows)})
    write_json(dist_path, stats)

    # Print concise top-5 to STDOUT
    top5 = rows[:5]
    print(json.dumps({
        "bb_width_stats": stats,
        "bb_width_low_ratio": bb_width_low,
        "bb_width_high_ratio": bb_width_high,
        "top5": top5,
        "out_csv": str(csv_path),
        "out_json": str(json_path),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
