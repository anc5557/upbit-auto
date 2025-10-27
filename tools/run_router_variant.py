from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from ua.engine.backtest import run_backtest
from ua.strategy.composites.regime_router import RegimeRouter
from ua.reporting.report import write_json

# ensure strategies are registered
import ua.strategy.examples.ema_rsi  # noqa: F401
import ua.strategy.examples.bb_rsi  # noqa: F401

try:
    from tools.bb_width_distribution import compute_bb_width_percentiles  # type: ignore
except Exception:
    import sys
    from pathlib import Path as _P
    sys.path.append(str(_P(__file__).resolve().parent))
    from bb_width_distribution import compute_bb_width_percentiles  # type: ignore


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
    ap = argparse.ArgumentParser(description="Run RegimeRouter with custom child params (baseline trend, custom range)")
    ap.add_argument("csv", type=Path)
    ap.add_argument("--capital", type=float, default=1_000_000.0)
    ap.add_argument("--fee", type=float, default=0.0005)
    ap.add_argument("--slippage", type=float, default=0.0005)
    ap.add_argument("--outdir", type=Path, default=Path("runs"))
    # regime
    ap.add_argument("--adx", type=float, default=18.0)
    ap.add_argument("--ema", type=int, default=50)
    ap.add_argument("--slope_window", type=int, default=20)
    ap.add_argument("--slope_thresh", type=float, default=0.0)
    ap.add_argument("--bb_percentiles", type=str, default="20,80")
    ap.add_argument("--bb_period", type=int, default=20)
    ap.add_argument("--bb_k", type=float, default=2.0)
    # range params
    ap.add_argument("--range_rsi_period", type=int, default=6)
    ap.add_argument("--range_buy", type=float, default=25.0)
    ap.add_argument("--range_sell", type=float, default=75.0)
    ap.add_argument("--exit_to_mid", action="store_true")
    ap.add_argument("--atr_period", type=int, default=14)
    ap.add_argument("--atr_mult", type=float, default=1.5)
    ap.add_argument("--range_bb_k", type=float, default=2.0)
    ap.add_argument("--range_bb_period", type=int, default=20)

    args = ap.parse_args()
    df = load_csv(args.csv)

    stats = compute_bb_width_percentiles(df, period=args.bb_period, k=args.bb_k)
    p_low, p_high = [int(x) for x in args.bb_percentiles.split(",")]
    bb_width_low = stats[f"p{p_low}"] / 100.0
    bb_width_high = stats[f"p{p_high}"] / 100.0

    trend_params: Dict[str, Any] = {}
    range_params: Dict[str, Any] = {
        "rsi_period": int(args.range_rsi_period),
        "rsi_buy_level": float(args.range_buy),
        "rsi_sell_level": float(args.range_sell),
        "exit_to_mid": bool(args.exit_to_mid),
        "use_atr_sl": True,
        "atr_period": int(args.atr_period),
        "atr_mult": float(args.atr_mult),
        "bb_k": float(args.range_bb_k),
        "bb_period": int(args.range_bb_period),
    }

    strat = RegimeRouter(
        trend_strategy="ema-rsi",
        range_strategy="bb-rsi",
        adx_thresh=args.adx,
        ema_trend_period=args.ema,
        slope_window=args.slope_window,
        slope_thresh=args.slope_thresh,
        bb_width_low=bb_width_low,
        bb_width_high=bb_width_high,
        trend_params=trend_params,
        range_params=range_params,
    )
    res = run_backtest(df, strat, cash=args.capital, fee=args.fee, slippage=args.slippage)

    outdir = args.outdir / "variants"
    outdir.mkdir(parents=True, exist_ok=True)
    base = args.csv.stem
    json_path = outdir / f"router_variant_{base}.json"
    write_json(json_path, {"metrics": res.metrics, "range_params": range_params, "regime": {
        "adx": args.adx,
        "ema": args.ema,
        "slope_window": args.slope_window,
        "slope_thresh": args.slope_thresh,
        "bb_width_low": bb_width_low,
        "bb_width_high": bb_width_high,
    }})

    print(json.dumps({
        "metrics": res.metrics,
        "range_params": range_params,
        "out_json": str(json_path),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

