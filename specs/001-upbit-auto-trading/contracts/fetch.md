# Contract — ua fetch

## Input

- market: string (e.g., "KRW-BTC")
- unit: number in {1,3,5,15,30,60,240}
- candles: number (max total to fetch)
- out: file path (CSV)

## Output

- STDOUT: human-readable summary or JSON (future)
- File: CSV at `out` with columns: Open,High,Low,Close,Volume,(timestamp optional)
- STDERR: errors; non-zero exit on failure

## Exit Codes

- 0: success
- 1: network/api error
- 2: invalid arguments

