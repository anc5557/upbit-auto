from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

import numpy as np
import pandas as pd


@dataclass
class SimResult:
    metrics: Dict[str, Any]
    equity_curve: pd.Series


def _max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = (equity - peak) / peak
    return float(dd.min() * 100.0) if len(dd) else 0.0


def simulate_long_only(
    df: pd.DataFrame,
    signals: Iterable[int],
    cash: float,
    fee: float,
    slippage: float,
    max_fraction: float = 1.0,
    cooldown_bars: int = 0,
    stop_drawdown: Optional[float] = None,
    log: Optional[Any] = None,
    run_id: Optional[str] = None,
    market: Optional[str] = None,
) -> SimResult:
    """Very simple long-only bar-by-bar simulator.

    - signals: 1=buy, -1=sell, 0=hold
    - prices: use Close; trade prices adjusted by slippage
    - commission (fee) applied on both buy and sell notionals
    """
    close = pd.Series(df["Close"]).astype(float).reset_index(drop=True)
    signals = pd.Series(list(signals), index=close.index).fillna(0).astype(int)

    equity_curve = []
    position = 0.0
    entry_price = 0.0
    trades = []  # percent returns per closed trade
    wins = 0
    cash_bal = float(cash)
    last_trade_bar = -10**9

    stopped_reason = None
    for i, price in enumerate(close):
        sig = signals.iat[i]
        # mark-to-market
        equity_curve.append(cash_bal + position * price)

        # stop on drawdown if configured
        if stop_drawdown is not None and len(equity_curve) > 0:
            eq = equity_curve[-1]
            if cash > 0 and (eq - cash) / cash <= -float(stop_drawdown):
                if log is not None:
                    log.warning(
                        "risk.violation",
                        event="risk_violation",
                        type="max_daily_loss",
                        drawdown=float((eq - cash) / cash),
                        threshold=float(-stop_drawdown),
                        run_id=run_id,
                        market=market,
                        bar=i,
                    )
                stopped_reason = "risk_violation"
                break

        if sig == 1 and position == 0.0 and (i - last_trade_bar) >= cooldown_bars:
            buy_price = price * (1.0 + slippage)
            if buy_price <= 0:
                continue
            budget = cash_bal * float(max_fraction)
            qty = budget / buy_price
            notional = qty * buy_price
            fee_amt = notional * fee
            if qty > 0:
                position = qty
                cash_bal = cash_bal - notional - fee_amt
                entry_price = buy_price
                last_trade_bar = i
                if log is not None:
                    log.info(
                        "order.submitted",
                        event="order_submitted",
                        side="buy",
                        price=buy_price,
                        qty=qty,
                        fee=fee_amt,
                        run_id=run_id,
                        market=market,
                        bar=i,
                    )
                    log.info(
                        "order.filled",
                        event="order_filled",
                        side="buy",
                        price=buy_price,
                        qty=qty,
                        fee=fee_amt,
                        run_id=run_id,
                        market=market,
                        bar=i,
                    )
                    log.info(
                        "position.opened",
                        event="position_opened",
                        direction="long",
                        qty=qty,
                        entry_price=entry_price,
                        run_id=run_id,
                        market=market,
                        bar=i,
                    )
        elif sig == -1 and position > 0.0 and (i - last_trade_bar) >= cooldown_bars:
            sell_price = price * (1.0 - slippage)
            notional = position * sell_price
            fee_amt = notional * fee
            proceeds = notional - fee_amt
            # trade return in percent relative to entry
            trade_ret = (sell_price - entry_price) / entry_price * 100.0 - (fee * 100.0 + fee * 100.0)
            trades.append(trade_ret)
            if trade_ret > 0:
                wins += 1
            cash_bal = cash_bal + proceeds
            position = 0.0
            entry_price = 0.0
            last_trade_bar = i
            if log is not None:
                log.info(
                    "order.submitted",
                    event="order_submitted",
                    side="sell",
                    price=sell_price,
                    qty=notional / sell_price if sell_price else 0.0,
                    fee=fee_amt,
                    run_id=run_id,
                    market=market,
                    bar=i,
                )
                log.info(
                    "order.filled",
                    event="order_filled",
                    side="sell",
                    price=sell_price,
                    qty=notional / sell_price if sell_price else 0.0,
                    fee=fee_amt,
                    run_id=run_id,
                    market=market,
                    bar=i,
                )
                log.info(
                    "position.closed",
                    event="position_closed",
                    direction="long",
                    exit_price=sell_price,
                    pnl_pct=trade_ret,
                    run_id=run_id,
                    market=market,
                    bar=i,
                )

    # close any open position at last price
    if position > 0.0 and len(close) > 0:
        price = float(close.iat[-1])
        sell_price = price * (1.0 - slippage)
        notional = position * sell_price
        fee_amt = notional * fee
        proceeds = notional - fee_amt
        trade_ret = (sell_price - entry_price) / entry_price * 100.0 - (fee * 100.0 + fee * 100.0)
        trades.append(trade_ret)
        if trade_ret > 0:
            wins += 1
        cash_bal = cash_bal + proceeds
        position = 0.0
        entry_price = 0.0
        equity_curve.append(cash_bal)

    equity = pd.Series(equity_curve)
    equity_final = float(equity.iat[-1]) if len(equity) else cash
    ret_pct = (equity_final - cash) / cash * 100.0 if cash > 0 else 0.0
    mdd_pct = _max_drawdown(equity)
    num_trades = int(len(trades))
    win_rate = float(wins) / num_trades * 100.0 if num_trades > 0 else 0.0
    avg_trade = float(np.mean(trades)) if trades else 0.0

    # naive sharpe: daily-ish per bar returns; avoid overfitting
    if len(equity) > 1:
        r = equity.pct_change().dropna()
        sharpe = float(np.sqrt(252) * r.mean() / (r.std() + 1e-12))
    else:
        sharpe = 0.0

    metrics = {
        "Equity Final [$]": equity_final,
        "Return [%]": ret_pct,
        "Max Drawdown [%]": mdd_pct,
        "Win Rate [%]": win_rate,
        "# Trades": num_trades,
        "Avg Trade [%]": avg_trade,
        "Sharpe Ratio": sharpe,
        "StoppedReason": stopped_reason or "completed",
    }
    return SimResult(metrics=metrics, equity_curve=equity)
