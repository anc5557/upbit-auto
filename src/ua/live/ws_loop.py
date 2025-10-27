from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
import time
from typing import Any, Optional

import structlog
import websockets

import pandas as pd

from ua.data.aggregator import CandleAggregator
from ua.data.upbit import fetch_range_minutes
from ua.broker.upbit import UpbitBroker, OrderRequest


WS_ENDPOINT = "wss://api.upbit.com/websocket/v1"


async def _subscribe(ws, market: str) -> None:
    payload = [
        {"ticket": "ua_live"},
        {"type": "trade", "codes": [market], "isOnlyRealtime": True},
    ]
    await ws.send(json.dumps(payload))


async def _get_order_async(broker: UpbitBroker, uuid_str: str) -> dict:
    """Non-blocking wrapper for broker.get_order via thread offload."""
    return await asyncio.to_thread(broker.get_order, uuid_str)


async def _get_accounts_async(broker: UpbitBroker) -> list:
    """Non-blocking wrapper for broker.get_accounts via thread offload."""
    return await asyncio.to_thread(broker.get_accounts)


def _parse_trade(msg: Any) -> Optional[tuple[datetime, float, float]]:
    """Parse Upbit trade message into (ts, price, volume)."""
    try:
        price = float(msg.get("trade_price"))
        vol = float(msg.get("trade_volume", 0.0))
        ts_ms = int(msg.get("timestamp", msg.get("trade_timestamp")))
        ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        return ts, price, vol
    except Exception:
        return None


async def run_live_ws(
    market: str,
    strategy: Any,
    broker: UpbitBroker,
    *,
    max_fraction: float,
    max_daily_loss: float,
    cooldown_bars: int,
    run_dir: str,
    tick_log_interval: float = 60.0,
    prefetch: bool = True,
    prefetch_bars: Optional[int] = None,
) -> dict:
    log = structlog.get_logger().bind(component="ws")
    agg = CandleAggregator()
    df = pd.DataFrame(columns=["timestamp", "Open", "High", "Low", "Close", "Volume"])

    # Starting balances
    accts = broker.get_accounts()
    currency = market.split("-")[-1]
    krw = next((a for a in accts if a.get("currency") == "KRW"), None)
    coin = next((a for a in accts if a.get("currency") == currency), None)
    krw_bal = float(krw.get("balance", 0)) if krw else 0.0
    coin_qty = float(coin.get("balance", 0)) if coin else 0.0
    start_equity = krw_bal  # assume no initial coin; if any, can add coin valuation on first price

    # Log initial account snapshot
    try:
        log.info(
            "accounts.snapshot",
            market=market,
            krw_balance=krw_bal,
            coin_currency=currency,
            coin_balance=coin_qty,
            accounts=len(accts),
        )
    except Exception:
        # logging should never break the loop
        pass

    price_unit = None
    min_total = None
    try:
        limits = broker.get_market_limits(market)
        price_unit = limits.get("price_unit")
        min_total = limits.get("min_total")
    except Exception:
        price_unit = None
        min_total = None
    # Log market limits
    log.info("market.limits", market=market, price_unit=price_unit, min_total=min_total)

    backoff = 0.5
    bars = 0
    last_trade_bar = -10**9
    last_signal = 0
    # throttle for tick logging (avoid every tick)
    try:
        tick_log_interval = float(tick_log_interval)
    except Exception:
        tick_log_interval = 60.0
    last_tick_log_at = 0.0

    # Optional REST prefetch to warm up indicators before WS
    if prefetch:
        # Ask strategy for its minimal required bars; allow CLI override
        req_bars = None
        try:
            rb = getattr(strategy, "required_bars", None)
            req_bars = int(rb()) if callable(rb) else None
        except Exception:
            req_bars = None
        want = int(prefetch_bars) if prefetch_bars is not None else (req_bars if req_bars is not None else 300)
        want = max(0, min(want, 2000))  # simple safety cap
        try:
            log.info("prefetch.start", market=market, unit=1, requested=want, required=req_bars)
            if want > 0:
                pdf = await fetch_range_minutes(market=market, unit=1, max_candles=want)
                if not pdf.empty:
                    # Ensure correct column ordering/types
                    pdf = pdf[["timestamp", "Open", "High", "Low", "Close", "Volume"]].copy()
                    pdf["timestamp"] = pd.to_datetime(pdf["timestamp"], utc=True)
                    pdf = pdf.sort_values("timestamp", ascending=True).reset_index(drop=True)
                    df = pdf
                    bars = len(df)
                    try:
                        start = df["timestamp"].iloc[0]
                        end = df["timestamp"].iloc[-1]
                        log.info("prefetch.done", rows=bars, start=str(start), end=str(end))
                    except Exception:
                        log.info("prefetch.done", rows=bars)
        except Exception as e:
            log.warning("prefetch.error", error=str(e))

    while True:
        try:
            async with websockets.connect(WS_ENDPOINT, ping_interval=20, ping_timeout=20) as ws:
                log.info("ws.connected", endpoint=WS_ENDPOINT)
                await _subscribe(ws, market)
                log.info("ws.subscribed", market=market)
                backoff = 0.5
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    except asyncio.TimeoutError:
                        try:
                            log.info("ws.ping")
                            await ws.ping()
                        except Exception:
                            raise
                        continue
                    if isinstance(raw, (bytes, bytearray)):
                        data = json.loads(raw.decode("utf-8"))
                    else:
                        data = json.loads(raw)
                    parsed = _parse_trade(data)
                    if not parsed:
                        continue
                    ts, price, vol = parsed
                    # Occasional tick log (1/sec)
                    now = time.time()
                    if tick_log_interval > 0 and (now - last_tick_log_at) >= tick_log_interval:
                        log.info(
                            "ws.tick",
                            ts=ts.isoformat(),
                            price=price,
                            volume=vol,
                        )
                        last_tick_log_at = now
                    row = agg.update(ts, price, vol)
                    # approximate equity update when any trade happens
                    equity = krw_bal + coin_qty * price
                    if start_equity > 0 and max_daily_loss > 0 and (equity - start_equity) / start_equity <= -float(max_daily_loss):
                        dd = (equity - start_equity) / start_equity
                        log.warning(
                            "risk.violation",
                            type="max_daily_loss",
                            drawdown=float(dd),
                            threshold=float(-max_daily_loss),
                            equity=equity,
                            price=price,
                        )
                        return {"bars": bars, "krw": krw_bal, "coin_qty": coin_qty, "stopped": "risk"}
                    if row is not None:
                        # finalize previous minute → append
                        # Avoid concatenating with an empty DataFrame to prevent pandas FutureWarning
                        if df.empty:
                            df = row.reset_index(drop=True)
                        else:
                            df = pd.concat([df, row], ignore_index=True)
                        if len(df) > 600:
                            df = df.iloc[-600:].reset_index(drop=True)
                        bars += 1
                        # Log bar close
                        try:
                            r = df.iloc[-1]
                            log.info(
                                "bar.closed",
                                ts=str(r["timestamp"]),
                                open=float(r["Open"]),
                                high=float(r["High"]),
                                low=float(r["Low"]),
                                close=float(r["Close"]),
                                volume=float(r["Volume"]),
                                bars=bars,
                            )
                        except Exception:
                            pass
                        sig = strategy.signals(df)
                        s = int(sig.iat[-1]) if len(sig) else 0
                        # Log signal change for strategy analysis
                        if s != last_signal:
                            try:
                                r = df.iloc[-1]
                                log.info(
                                    "signal.changed",
                                    signal=s,
                                    prev=last_signal,
                                    close=float(r["Close"]),
                                    bars=bars,
                                )
                            except Exception:
                                log.info("signal.changed", signal=s, prev=last_signal, bars=bars)
                            last_signal = s
                        # Optional strategy-provided inspection payload
                        inspector = getattr(strategy, "inspect", None)
                        if callable(inspector):
                            try:
                                details = inspector(df)
                                if isinstance(details, dict):
                                    log.info("signal.inspect", **details)
                            except Exception:
                                pass
                        try:
                            # Decision gating logs
                            cooldown_ready = (bars - last_trade_bar) >= cooldown_bars
                            if s == 1 and coin_qty > 0.0:
                                log.info("order.skipped", reason="already_in_position", side="buy", coin_qty=coin_qty)
                            if s == -1 and coin_qty == 0.0:
                                log.info("order.skipped", reason="no_position", side="sell", coin_qty=coin_qty)
                            if s == 1 and coin_qty == 0.0 and cooldown_ready:
                                budget = krw_bal * float(max_fraction)
                                if price_unit:
                                    # quantize budget to price unit
                                    q = broker.quantize_price(budget, price_unit)
                                    budget = q if q > 0 else budget
                                if min_total and budget < float(min_total):
                                    log.info("order.skipped", reason="budget_too_small", budget=budget, min_total=min_total)
                                    continue
                                resp = broker.place_order(
                                    OrderRequest(side="buy", market=market, price=budget, size=None, order_type="price")
                                )
                                log.info("order.submitted", side="buy", type="price", uuid=resp.get("uuid"), state=resp.get("state"), funds=resp.get("price"))
                                # Poll order status briefly to confirm fill
                                uuid_str = resp.get("uuid")
                                if uuid_str:
                                    log.info("order.status_check_start", uuid=uuid_str)
                                    try:
                                        # poll up to 10 times with 0.5s interval (max ~5s)
                                        for i in range(10):
                                            od = await _get_order_async(broker, uuid_str)
                                            state = od.get("state")
                                            log.info(
                                                "order.status",
                                                uuid=uuid_str,
                                                state=state,
                                                remaining=od.get("remaining_volume"),
                                                executed=od.get("executed_volume"),
                                                paid_fee=od.get("paid_fee"),
                                                trades=len(od.get("trades", [])) if isinstance(od.get("trades"), list) else None,
                                                attempt=i + 1,
                                            )
                                            if state in ("done", "cancel", "cancelled"):
                                                break
                                            await asyncio.sleep(0.5)
                                        if state == "done":
                                            log.info("order.filled", uuid=uuid_str)
                                        elif state in ("cancel", "cancelled"):
                                            log.info("order.cancelled", uuid=uuid_str)
                                        log.info("order.status_check_done", uuid=uuid_str, final_state=state)
                                    except Exception as e:
                                        log.error("order.status_check_error", uuid=uuid_str, error=str(e))
                                last_trade_bar = bars
                                # refresh balances non-blocking
                                accts = await _get_accounts_async(broker)
                                krw = next((a for a in accts if a.get("currency") == "KRW"), None)
                                coin = next((a for a in accts if a.get("currency") == currency), None)
                                krw_bal = float(krw.get("balance", 0)) if krw else krw_bal
                                coin_qty = float(coin.get("balance", 0)) if coin else coin_qty
                                log.info("accounts.update", krw_balance=krw_bal, coin_currency=currency, coin_balance=coin_qty)
                            elif s == -1 and coin_qty > 0.0 and (bars - last_trade_bar) >= cooldown_bars:
                                resp = broker.place_order(
                                    OrderRequest(side="sell", market=market, price=None, size=coin_qty, order_type="market")
                                )
                                log.info("order.submitted", side="sell", type="market", uuid=resp.get("uuid"), state=resp.get("state"), volume=resp.get("volume"))
                                uuid_str = resp.get("uuid")
                                if uuid_str:
                                    log.info("order.status_check_start", uuid=uuid_str)
                                    try:
                                        for i in range(10):
                                            od = await _get_order_async(broker, uuid_str)
                                            state = od.get("state")
                                            log.info(
                                                "order.status",
                                                uuid=uuid_str,
                                                state=state,
                                                remaining=od.get("remaining_volume"),
                                                executed=od.get("executed_volume"),
                                                paid_fee=od.get("paid_fee"),
                                                trades=len(od.get("trades", [])) if isinstance(od.get("trades"), list) else None,
                                                attempt=i + 1,
                                            )
                                            if state in ("done", "cancel", "cancelled"):
                                                break
                                            await asyncio.sleep(0.5)
                                        if state == "done":
                                            log.info("order.filled", uuid=uuid_str)
                                        elif state in ("cancel", "cancelled"):
                                            log.info("order.cancelled", uuid=uuid_str)
                                        log.info("order.status_check_done", uuid=uuid_str, final_state=state)
                                    except Exception as e:
                                        log.error("order.status_check_error", uuid=uuid_str, error=str(e))
                                last_trade_bar = bars
                                accts = await _get_accounts_async(broker)
                                krw = next((a for a in accts if a.get("currency") == "KRW"), None)
                                coin = next((a for a in accts if a.get("currency") == currency), None)
                                krw_bal = float(krw.get("balance", 0)) if krw else krw_bal
                                coin_qty = float(coin.get("balance", 0)) if coin else 0.0
                                log.info("accounts.update", krw_balance=krw_bal, coin_currency=currency, coin_balance=coin_qty)
                        except Exception as e:
                            log.error("order.error", error=str(e))
        except Exception as e:
            log.error("ws.error", error=str(e))
            await asyncio.sleep(backoff)
            log.info("ws.reconnect", backoff=backoff)
            backoff = min(backoff * 2.0, 8.0)
