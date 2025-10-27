# Contract — ua backtest

## Input

- strategy: string (e.g., "sma-crossover")
- csv: optional path to candle CSV; if absent, use simulated dataset
- capital: number (starting cash)
- fee: decimal fraction (commission, e.g., 0.0005 = 0.05%)
- slippage: decimal fraction (e.g., 0.0005 = 0.05%)
- tz: string (display timezone for report; storage is UTC). Default: Asia/Seoul
- seed: integer (simulation seed for determinism; used when CSV is not provided)
- outdir: directory to write outputs

## Output

- STDOUT: JSON metrics (primary output)
- File: `runs/backtest_<strategy>_<ts>/metrics.json` and `report.md`
  - keys: Return [%], Max Drawdown [%], Win Rate [%], # Trades, Avg Trade [%], Equity Final [$], Sharpe Ratio (if available)
  - params: { strategy, capital, fee, slippage }
  - provenance (optional): { source: csv|simulated, path, rows, timezone: UTC, start, end, dataset_hash }
- STDERR: structured logs (JSON) of start/end/errors; file log at `log.jsonl`

## Exit Codes

- 0: success
- 1: runtime or dependency error
- 2: invalid input (missing columns, etc.)
