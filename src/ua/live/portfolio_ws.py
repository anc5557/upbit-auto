from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone, time as dt_time
from typing import Any, Dict, Optional, List, Tuple

import structlog
import websockets
import pandas as pd

from ua.broker.upbit import UpbitBroker, OrderRequest
from ua.data.aggregator import CandleAggregator
from ua.data.upbit import fetch_range_minutes
from ua.strategy.base import get_strategy
from ua.strategy.indicators import atr as _atr


WS_ENDPOINT = "wss://api.upbit.com/websocket/v1"


def _parse_hours_windows(spec: Optional[str]) -> List[Tuple[dt_time, dt_time]]:
    if not spec:
        return []
    out: List[Tuple[dt_time, dt_time]] = []
    parts = [p.strip() for p in str(spec).split(",") if p.strip()]
    for p in parts:
        try:
            s, e = [x.strip() for x in p.split("-")]
            sh, sm = [int(x) for x in s.split(":")]
            eh, em = [int(x) for x in e.split(":")]
            out.append((dt_time(sh, sm), dt_time(eh, em)))
        except Exception:
            continue
    return out


def _in_windows(ts: datetime, windows: List[Tuple[dt_time, dt_time]], tz: str | None = None) -> bool:
    if not windows:
        return True
    try:
        if tz:
            from zoneinfo import ZoneInfo
            ts = ts.astimezone(ZoneInfo(tz))
    except Exception:
        pass
    t = ts.time()
    for s, e in windows:
        if s <= e:
            if s <= t <= e:
                return True
        else:  # crosses midnight
            if t >= s or t <= e:
                return True
    return False


def _parse_trade(msg: Any) -> Optional[tuple[str, datetime, float, float]]:
    """Parse Upbit trade message into (market, ts, price, volume)."""
    try:
        market = str(msg.get("code"))
        price = float(msg.get("trade_price"))
        vol = float(msg.get("trade_volume", 0.0))
        ts_ms = int(msg.get("timestamp", msg.get("trade_timestamp")))
        ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        return market, ts, price, vol
    except Exception:
        return None


@dataclass
class MarketState:
    market: str
    currency: str
    agg: CandleAggregator
    df: pd.DataFrame
    bars: int = 0
    last_trade_bar: int = -10**9
    last_signal: int = 0
    coin_qty: float = 0.0
    entry_price: float = 0.0
    trail_stop: Optional[float] = None
    partial_done: bool = False
    price_unit: Optional[float] = None
    min_total: Optional[float] = None


async def run_portfolio_ws(
    markets: List[str],
    strategy_name: str,
    strategy_params: Dict[str, Any],
    broker: UpbitBroker,
    *,
    unit: int,
    prefetch: bool,
    prefetch_bars: Optional[int],
    max_fraction: float,
    max_daily_loss: float,
    cooldown_bars: int,
    allowed_hours: Optional[str],
    tz_display: str,
    atr_trailing_mult: float = 0.0,
    atr_period: int = 14,
    partial_tp_pct: float = 0.0,
    partial_tp_ratio: float = 0.5,
) -> dict:
    log = structlog.get_logger().bind(component="portfolio_ws")

    # Instantiate strategy once (shared params)
    strat_cls = get_strategy(strategy_name)
    strat = strat_cls()
    # Apply params
    try:
        from ua.strategy.params import apply_params
        strat = apply_params(strat, strategy_params)
    except Exception:
        pass

    # Accounts snapshot
    accts = broker.get_accounts()
    def _bal_cur(code: str) -> float:
        a = next((x for x in accts if x.get("currency") == code), None)
        return float(a.get("balance", 0)) if a else 0.0
    krw_bal = _bal_cur("KRW")
    start_equity = krw_bal
    # prepare per-market state
    states: Dict[str, MarketState] = {}
    for m in markets:
        cur = m.split("-")[-1]
        qty = _bal_cur(cur)
        st = MarketState(market=m, currency=cur, agg=CandleAggregator(), df=pd.DataFrame(columns=["timestamp","Open","High","Low","Close","Volume"]), coin_qty=qty)
        # market limits
        try:
            limits = broker.get_market_limits(m)
            st.price_unit = limits.get("price_unit")
            st.min_total = limits.get("min_total")
        except Exception:
            pass
        states[m] = st

    # Prefetch per market
    if prefetch:
        req_bars = None
        try:
            rb = getattr(strat, "required_bars", None)
            req_bars = int(rb()) if callable(rb) else None
        except Exception:
            req_bars = None
        want = int(prefetch_bars) if prefetch_bars is not None else (req_bars if req_bars is not None else 300)
        want = max(0, min(want, 2000))
        for m in markets:
            try:
                log.info("prefetch.start", market=m, unit=unit, requested=want)
                if want > 0:
                    df = await fetch_range_minutes(market=m, unit=unit, max_candles=want)
                    states[m].df = df
                    log.info("prefetch.done", market=m, rows=len(df))
            except Exception as e:
                log.error("prefetch.error", market=m, error=str(e))

    hours_windows = _parse_hours_windows(allowed_hours)

    # WebSocket loop
    backoff = 0.5
    while True:
        try:
            async with websockets.connect(WS_ENDPOINT, ping_interval=20, ping_timeout=20) as ws:
                log.info("ws.connected", endpoint=WS_ENDPOINT, markets=markets)
                payload = [
                    {"ticket": "ua_portfolio"},
                    {"type": "trade", "codes": markets, "isOnlyRealtime": True},
                ]
                await ws.send(json.dumps(payload))
                log.info("ws.subscribed", markets=markets)
                backoff = 0.5
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    except asyncio.TimeoutError:
                        try:
                            await ws.ping()
                        except Exception:
                            raise
                        continue
                    data = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
                    parsed = _parse_trade(data)
                    if not parsed:
                        continue
                    mkt, ts, price, vol = parsed
                    st = states.get(mkt)
                    if st is None:
                        continue
                    row = st.agg.update(ts, price, vol)

                    # Approximate portfolio equity from KRW + sum coin holdings * last price (per tick)
                    # Minimal track: only this coin updated → rough eq update
                    equity = krw_bal
                    try:
                        equity += sum(s.coin_qty * (price if s.market == mkt else (float(s.df["Close"].iat[-1]) if len(s.df) > 0 else 0.0)) for s in states.values())
                    except Exception:
                        pass
                    if start_equity > 0 and max_daily_loss > 0 and (equity - start_equity) / start_equity <= -float(max_daily_loss):
                        log.warning("risk.violation", type="max_daily_loss", drawdown=float((equity - start_equity)/start_equity))
                        return {"stopped": "risk", "equity": equity}

                    if row is not None:
                        # append finalized minute bar for this market
                        if st.df.empty:
                            st.df = row.reset_index(drop=True)
                        else:
                            st.df = pd.concat([st.df, row], ignore_index=True)
                        if len(st.df) > 2000:
                            st.df = st.df.iloc[-2000:].reset_index(drop=True)
                        st.bars += 1

                        # allowed hours gate — only block entries, not exits
                        within = _in_windows(row["timestamp"].iat[-1], hours_windows, tz_display)

                        # compute last signal from strategy
                        s_series = strat.signals(st.df)
                        s_val = int(s_series.iat[-1]) if len(s_series) else 0
                        if s_val != st.last_signal:
                            st.last_signal = s_val
                            try:
                                r = st.df.iloc[-1]
                                log.info("signal.changed", market=mkt, signal=s_val, open=float(r["Open"]), close=float(r["Close"]))
                            except Exception:
                                log.info("signal.changed", market=mkt, signal=s_val)

                        # ATR trailing stop (optional)
                        if st.coin_qty > 0.0 and atr_trailing_mult > 0:
                            try:
                                atr = _atr(st.df["High"], st.df["Low"], st.df["Close"], period=atr_period)
                                last_atr = float(atr.iat[-1]) if not pd.isna(atr.iat[-1]) else None
                                if last_atr is not None:
                                    new_trail = float(st.df["Close"].iat[-1]) - float(atr_trailing_mult) * last_atr
                                    st.trail_stop = max(st.trail_stop or 0.0, new_trail)
                            except Exception:
                                pass

                        # Exits first: trailing or strategy sell
                        try:
                            close_px = float(st.df["Close"].iat[-1])
                        except Exception:
                            close_px = price

                        do_exit = False
                        if st.coin_qty > 0.0:
                            if st.trail_stop is not None and close_px <= st.trail_stop:
                                do_exit = True
                            if s_val == -1:
                                do_exit = True
                        if do_exit:
                            try:
                                resp = broker.place_order(OrderRequest(side="sell", market=mkt, price=None, size=st.coin_qty, order_type="market"))
                                log.info("order.submitted", market=mkt, side="sell", type="market", uuid=resp.get("uuid"))
                                accts = broker.get_accounts()
                                krw_bal = next((float(a.get("balance",0)) for a in accts if a.get("currency")=="KRW"), krw_bal)
                                st.coin_qty = next((float(a.get("balance",0)) for a in accts if a.get("currency")==st.currency), 0.0)
                                st.entry_price = 0.0
                                st.trail_stop = None
                                st.partial_done = False
                                st.last_trade_bar = st.bars
                            except Exception as e:
                                log.error("order.error", market=mkt, error=str(e))
                            continue

                        # Partial TP (optional) — only if in position and no sell signal
                        if st.coin_qty > 0.0 and partial_tp_pct > 0 and s_val >= 0:
                            target = st.entry_price * (1.0 + float(partial_tp_pct)) if st.entry_price > 0 else None
                            if target and close_px >= target and not st.partial_done:
                                size = st.coin_qty * float(partial_tp_ratio)
                                try:
                                    resp = broker.place_order(OrderRequest(side="sell", market=mkt, price=None, size=size, order_type="market"))
                                    log.info("order.submitted", market=mkt, side="sell", type="market", partial=True, uuid=resp.get("uuid"), size=size)
                                    accts = broker.get_accounts()
                                    krw_bal = next((float(a.get("balance",0)) for a in accts if a.get("currency")=="KRW"), krw_bal)
                                    st.coin_qty = next((float(a.get("balance",0)) for a in accts if a.get("currency")==st.currency), st.coin_qty - size)
                                    st.partial_done = True
                                except Exception as e:
                                    log.error("order.error", market=mkt, error=str(e))

                        # Entries
                        if s_val == 1 and st.coin_qty == 0.0 and within and (st.bars - st.last_trade_bar) >= cooldown_bars:
                            budget = krw_bal * float(max_fraction)
                            # respect min_total and price unit
                            if st.min_total and budget < float(st.min_total):
                                log.info("order.skipped", market=mkt, reason="budget_too_small", budget=budget, min_total=st.min_total)
                            else:
                                try:
                                    if st.price_unit:
                                        budget = UpbitBroker.quantize_price(budget, st.price_unit)
                                    resp = broker.place_order(OrderRequest(side="buy", market=mkt, price=budget, size=None, order_type="price"))
                                    log.info("order.submitted", market=mkt, side="buy", type="price", uuid=resp.get("uuid"), funds=budget)
                                    accts = broker.get_accounts()
                                    krw_bal = next((float(a.get("balance",0)) for a in accts if a.get("currency")=="KRW"), krw_bal)
                                    st.coin_qty = next((float(a.get("balance",0)) for a in accts if a.get("currency")==st.currency), st.coin_qty)
                                    st.entry_price = close_px
                                    st.trail_stop = None
                                    st.partial_done = False
                                    st.last_trade_bar = st.bars
                                except Exception as e:
                                    log.error("order.error", market=mkt, error=str(e))

        except Exception as e:
            log.error("ws.error", error=str(e))
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, 8.0)

