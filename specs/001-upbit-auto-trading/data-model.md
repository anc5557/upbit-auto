# Data Model — Upbit 자동매매

## Entities

- Candle
  - timestamp (UTC), Open, High, Low, Close, Volume
  - source (csv/rest/ws), market, timeframe
- Strategy
  - id, name, params(schema), version
- Signal
  - strategy_id, run_id, side(buy/sell/hold), confidence, reason, ts
- Order
  - order_id, run_id, market, side, type(market/limit), qty, price, status, idempotency_key, ts
- Fill
  - fill_id, order_id, qty, price, fee, ts
- Position
  - position_id, market, direction, qty, entry_price, pnl_unrealized, pnl_realized, status, ts_open, ts_close
- Portfolio
  - run_id, cash, equity, risk_limits
- Run
  - run_id, mode(backtest/paper/live), strategy_id, params, started_at, ended_at, outputs_path
- Metrics
  - return_pct, mdd_pct, win_rate_pct, trades, sharpe, avg_trade_pct, costs_pct

## Event Log (JSON Lines)

- Common keys: run_id, strategy_id, event_type, ts
- Types: signal, order_submitted, order_filled, position_opened/closed, risk_violation, report_generated

## Contracts (summary)

- fetch: input { market, unit, count, out } → CSV file
- backtest: input { strategy, csv|dataset, capital, fee } → metrics.json, logs
- trade: input { strategy, market, live=false } → JSONL logs, reports
- report: input { run_dir } → metrics summary(JSON), report.md

