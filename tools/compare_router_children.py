from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

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
    ap = argparse.ArgumentParser(description="Compare baseline vs improved child params for RegimeRouter")
    ap.add_argument("csv", type=Path, help="Input OHLCV CSV")
    ap.add_argument("--capital", type=float, default=1_000_000.0)
    ap.add_argument("--fee", type=float, default=0.0005)
    ap.add_argument("--slippage", type=float, default=0.0005)
    ap.add_argument("--outdir", type=Path, default=Path("runs"))
    # fixed regime params from user's top combo
    ap.add_argument("--adx", type=float, default=18.0)
    ap.add_argument("--ema", type=int, default=50)
    ap.add_argument("--slope_window", type=int, default=20)
    ap.add_argument("--slope_thresh", type=float, default=0.0)
    ap.add_argument("--bb_period", type=int, default=20)
    ap.add_argument("--bb_k", type=float, default=2.0)
    ap.add_argument("--bb_percentiles", type=str, default="20,80")

    args = ap.parse_args()
    df = load_csv(args.csv)
    stats = compute_bb_width_percentiles(df, period=args.bb_period, k=args.bb_k)
    p_low, p_high = [int(x) for x in args.bb_percentiles.split(",")]
    bb_width_low = stats[f"p{p_low}"] / 100.0
    bb_width_high = stats[f"p{p_high}"] / 100.0

    # Define child profiles
    baseline_trend = {}
    baseline_range = {}

    trend_A = {
        "ema_fast": 12,
        "ema_slow": 26,
        "rsi_period": 14,
        "rsi_buy_threshold": 30.0,
        "rsi_sell_threshold": 70.0,
        "tp_pct": 0.010,  # 1.0%
        "sl_pct": 0.008,  # 0.8%
        "require_pullback": True,
        "pullback_window": 5,
    }
    trend_B = {
        "ema_fast": 20,
        "ema_slow": 50,
        "rsi_period": 20,
        "rsi_buy_threshold": 35.0,
        "rsi_sell_threshold": 65.0,
        "tp_pct": 0.015,  # 1.5%
        "sl_pct": 0.008,  # 0.8%
        "require_pullback": True,
        "pullback_window": 5,
    }
    trend_C = {
        "ema_fast": 12,
        "ema_slow": 26,
        "rsi_period": 14,
        "rsi_buy_threshold": 25.0,
        "rsi_sell_threshold": 75.0,
        "tp_pct": 0.010,
        "sl_pct": 0.010,
        "require_pullback": True,
        "pullback_window": 5,
    }

    range_A = {
        "rsi_period": 6,
        "rsi_buy_level": 20.0,
        "rsi_sell_level": 80.0,
        "exit_to_mid": True,
        "use_atr_sl": True,
        "atr_period": 14,
        "atr_mult": 1.5,
        "bb_k": 2.0,
        "bb_period": 20,
    }
    range_B = {
        "rsi_period": 8,
        "rsi_buy_level": 15.0,
        "rsi_sell_level": 85.0,
        "exit_to_mid": True,
        "use_atr_sl": True,
        "atr_period": 14,
        "atr_mult": 2.0,
        "bb_k": 2.1,
        "bb_period": 20,
    }
    range_C = {
        "rsi_period": 10,
        "rsi_buy_level": 25.0,
        "rsi_sell_level": 75.0,
        "exit_to_mid": False,
        "use_atr_sl": True,
        "atr_period": 14,
        "atr_mult": 1.5,
        "bb_k": 2.0,
        "bb_period": 20,
    }

    scenarios = [
        ("baseline", baseline_trend, baseline_range),
        ("trendA_rangeA", trend_A, range_A),
        ("trendB_rangeB", trend_B, range_B),
        ("trendC_rangeC", trend_C, range_C),
        ("trendA_rangeBaseline", trend_A, baseline_range),
        ("trendBaseline_rangeA", baseline_trend, range_A),
    ]

    rows: List[Dict[str, Any]] = []
    for name, t_params, r_params in scenarios:
        strat = RegimeRouter(
            trend_strategy="ema-rsi",
            range_strategy="bb-rsi",
            adx_thresh=args.adx,
            ema_trend_period=args.ema,
            slope_window=args.slope_window,
            slope_thresh=args.slope_thresh,
            bb_width_low=bb_width_low,
            bb_width_high=bb_width_high,
            trend_params=t_params if t_params else None,
            range_params=r_params if r_params else None,
        )
        res = run_backtest(df, strat, cash=args.capital, fee=args.fee, slippage=args.slippage)
        rows.append({
            "scenario": name,
            "trend_params": t_params,
            "range_params": r_params,
            **res.metrics,
        })

    # Sort by Return then Sharpe
    rows.sort(key=lambda x: (x.get("Return [%]", 0.0), x.get("Sharpe Ratio", 0.0)), reverse=True)

    outdir = args.outdir / "sweeps"
    outdir.mkdir(parents=True, exist_ok=True)
    base = args.csv.stem
    csv_path = outdir / f"compare_children_{base}.csv"
    json_path = outdir / f"compare_children_{base}.json"
    dist_path = outdir / f"bb_width_stats_{base}.json"
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    write_json(json_path, {"results": rows, "total": len(rows)})
    write_json(dist_path, stats)

    print(json.dumps({
        "bb_width_low": bb_width_low,
        "bb_width_high": bb_width_high,
        "top": rows[:5],
        "out_csv": str(csv_path),
        "out_json": str(json_path),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

