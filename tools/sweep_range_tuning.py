from __future__ import annotations

import argparse
import itertools
import json
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
    ap = argparse.ArgumentParser(description="Sweep range-strategy params within RegimeRouter under fixed regime/trend settings")
    ap.add_argument("csv", type=Path, nargs="+", help="One or more OHLCV CSV paths")
    ap.add_argument("--capital", type=float, default=1_000_000.0)
    ap.add_argument("--fee", type=float, default=0.0005)
    ap.add_argument("--slippage", type=float, default=0.0005)
    ap.add_argument("--outdir", type=Path, default=Path("runs"))
    # fixed regime from top combo
    ap.add_argument("--adx", type=float, default=18.0)
    ap.add_argument("--ema", type=int, default=50)
    ap.add_argument("--slope_window", type=int, default=20)
    ap.add_argument("--slope_thresh", type=float, default=0.0)
    ap.add_argument("--bb_period", type=int, default=20)
    ap.add_argument("--bb_k", type=float, default=2.0)
    ap.add_argument("--bb_percentiles", type=str, default="20,80")
    # range grids
    ap.add_argument("--rsi_periods", type=str, default="6,8,10")
    ap.add_argument("--levels", type=str, default="20:80,22:78,24:76,25:75")
    ap.add_argument("--atr_mults", type=str, default="1.5,2.0")
    ap.add_argument("--exit_to_mid", action="store_true")

    args = ap.parse_args()

    rsi_periods = [int(x) for x in args.rsi_periods.split(",") if x]
    level_pairs = []
    for tok in args.levels.split(","):
        if not tok:
            continue
        a, b = tok.split(":")
        level_pairs.append((float(a), float(b)))
    atr_mults = [float(x) for x in args.atr_mults.split(",") if x]

    all_outputs: Dict[str, Any] = {}

    for csv_path in args.csv:
        df = load_csv(Path(csv_path))
        stats = compute_bb_width_percentiles(df, period=args.bb_period, k=args.bb_k)
        p_low, p_high = [int(x) for x in args.bb_percentiles.split(",")]
        bb_width_low = stats[f"p{p_low}"] / 100.0
        bb_width_high = stats[f"p{p_high}"] / 100.0

        rows: List[Dict[str, Any]] = []
        for rsi_p, (lvl_b, lvl_s), atr_m in itertools.product(rsi_periods, level_pairs, atr_mults):
            range_params = {
                "rsi_period": rsi_p,
                "rsi_buy_level": lvl_b,
                "rsi_sell_level": lvl_s,
                "exit_to_mid": bool(args.exit_to_mid),
                "use_atr_sl": True,
                "atr_period": 14,
                "atr_mult": atr_m,
                "bb_k": args.bb_k,
                "bb_period": args.bb_period,
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
                trend_params=None,
                range_params=range_params,
            )
            res = run_backtest(df, strat, cash=args.capital, fee=args.fee, slippage=args.slippage)
            rows.append({
                "rsi_period": rsi_p,
                "level_buy": lvl_b,
                "level_sell": lvl_s,
                "atr_mult": atr_m,
                **res.metrics,
            })

        rows.sort(key=lambda x: (x.get("Return [%]", 0.0), x.get("Sharpe Ratio", 0.0)), reverse=True)

        outdir = args.outdir / "sweeps"
        outdir.mkdir(parents=True, exist_ok=True)
        base = Path(csv_path).stem
        csv_out = outdir / f"sweep_range_{base}.csv"
        json_out = outdir / f"sweep_range_{base}.json"
        pd.DataFrame(rows).to_csv(csv_out, index=False)
        write_json(json_out, {"bb_width_low": bb_width_low, "bb_width_high": bb_width_high, "results": rows[:50], "total": len(rows)})
        all_outputs[base] = {
            "bb_width_low": bb_width_low,
            "bb_width_high": bb_width_high,
            "top5": rows[:5],
            "out_csv": str(csv_out),
            "out_json": str(json_out),
        }

    print(json.dumps(all_outputs, ensure_ascii=False))


if __name__ == "__main__":
    main()

