# Contract — ua trade

## Input

- strategy: string
- live: boolean flag (default false). Live requires 2-step confirmation
- market: string (default KRW-BTC)
- csv: path to candle CSV (required for paper mode MVP)
- cooldown_bars: integer (bar-based re-entry cooldown)
- ws: boolean (use WebSocket live loop)

## Output

- STDOUT: JSON metrics summary
- File(s): logs as JSON Lines under `runs/` (event stream)
- Events: signal, order_submitted, order_filled, position_opened/closed, risk_violation
 - Files: `metrics.json`, `report.md` in run directory

## Validation & Limits

- Prior to orders, the system queries `/v1/orders/chance` to fetch `price_unit` and `min_total` and adjusts/validates budgets accordingly.
- If `budget < min_total` for market-buy (price type), the order is skipped with a warning.

## Live (WebSocket)

- Subscribes to `trade` channel for the specified market, aggregates 1-minute candles, computes signals, and places orders.
- Heartbeat/timeout handling: ping/pong and reconnect with exponential backoff.

## Exit Codes

- 0: success (paper mode run started and exited cleanly)
- 1: runtime error / live not implemented
- 2: invalid input or missing confirmations for live mode
- ack_live: boolean (first confirmation step)
- confirm_live: string (must equal `I UNDERSTAND`) — second confirmation step
