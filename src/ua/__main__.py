from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import typer
import structlog

from ua.config import load_config
from ua.data.simulate import make_random_walk_ohlcv
from ua.data.upbit import fetch_range_minutes, save_csv, fetch_latest_minutes
from ua.engine.backtest import run_backtest
from ua.engine.paper import run_paper
from ua.live.ws_loop import run_live_ws
from ua.live.portfolio_ws import run_portfolio_ws
from ua.logging import init_logging, add_file_json_logger
import logging
from ua.reporting.report import write_json
from ua.strategy.base import get_strategy
from ua.strategy.params import parse_kv_params, apply_params
import ua.strategy.examples.sma_cross  # register
import ua.strategy.examples.ema_rsi  # register
import ua.strategy.examples.macd_vwap  # register
import ua.strategy.examples.bb_rsi  # register
import ua.strategy.composites.regime_router  # register
import ua.strategy.composites.regime_router_5m_btc  # register
from zoneinfo import ZoneInfo
from ua.broker.upbit import UpbitBroker, OrderRequest


app = typer.Typer(help="Upbit 자동매매/백테스트 CLI")


@app.callback()
def main(
    json: bool = typer.Option(True, "--json/--no-json", help="구조화 로그(JSON) 사용 여부"),
    log_level: str = typer.Option("info", "--log-level", help="로그 레벨(debug, info, warning, error)"),
):
    lvl_map = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }
    level = lvl_map.get(str(log_level).lower(), logging.INFO)
    init_logging(json=json, level=level)


@app.command()
def fetch(
    market: str = typer.Option("KRW-BTC", help="마켓 심볼"),
    unit: int = typer.Option(1, help="분봉 단위 (1,3,5,15,30,60,240)"),
    candles: int = typer.Option(500, help="가져올 봉 개수(최대 누적)"),
    out: Path = typer.Option(Path("data/krw-btc_1m.csv"), help="저장 경로(CSV)"),
):
    """Upbit 분봉 캔들 데이터를 CSV로 저장."""
    log = structlog.get_logger()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path("runs") / f"fetch_{market}_{unit}m_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    add_file_json_logger(run_dir / "log.jsonl")
    log.info("fetch.start", market=market, unit=unit, candles=candles, out=str(out), run_dir=str(run_dir))
    try:
        if unit not in {1, 3, 5, 15, 30, 60, 240}:
            log.error("fetch.invalid_unit", unit=unit)
            raise typer.Exit(code=2)
        df = asyncio.run(fetch_range_minutes(market=market, unit=unit, max_candles=candles))
    except Exception as e:  # pragma: no cover
        log.error("fetch.error", error=str(e))
        raise typer.Exit(code=1)
    save_csv(df, out)
    log.info("fetch.done", rows=len(df), path=str(out), run_dir=str(run_dir))


@app.command()
def backtest(
    strategy: str = typer.Option("sma-crossover", "--strategy", "-s", help="전략 이름"),
    csv: Optional[Path] = typer.Option(None, help="캔들 CSV 경로(없으면 시뮬레이션)"),
    capital: float = typer.Option(1_000_000.0, help="초기 자본(원)", min=0),
    fee: Optional[float] = typer.Option(None, help="수수료(비율, 예: 0.0005=0.05%) — 생략 시 설정값 사용", min=0.0, max=0.01),
    slippage: Optional[float] = typer.Option(None, help="슬리피지(비율, 예: 0.0005=0.05%) — 생략 시 설정값 사용", min=0.0, max=0.02),
    tz: str = typer.Option("Asia/Seoul", help="표시 타임존(저장은 UTC)"),
    seed: Optional[int] = typer.Option(None, help="시뮬레이션 데이터 시드(결정성)", min=0),
    outdir: Path = typer.Option(Path("runs"), help="결과 저장 디렉터리"),
    param: list[str] = typer.Option(None, "--param", help="전략 파라미터 key=value (여러 번 지정 가능)"),
):
    """CSV 또는 시뮬레이션 데이터로 백테스트 실행."""
    log = structlog.get_logger()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = outdir / f"backtest_{strategy}_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    add_file_json_logger(run_dir / "log.jsonl")
    log.info("backtest.start", strategy=strategy, csv=str(csv) if csv else None, run_dir=str(run_dir))

    if csv and csv.exists():
        df = pd.read_csv(csv)
        # Try to map flexible column names
        rename_map = {
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
            "time": "timestamp",
            "date": "timestamp",
        }
        cols = {c: rename_map.get(c.lower(), c) for c in df.columns}
        df = df.rename(columns=cols)
        needed = {"Open", "High", "Low", "Close", "Volume"}
        missing = needed - set(df.columns)
        if missing:
            log.error("backtest.columns_missing", missing=sorted(missing))
            raise typer.Exit(code=2)
        # Parse timestamp if present and sort ascending, normalize UTC
        if "timestamp" in df.columns:
            try:
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
                df = df.sort_values("timestamp", ascending=True).reset_index(drop=True)
            except Exception:
                pass
        # Ensure numeric types and drop NA rows
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"]).reset_index(drop=True)
    else:
        df = make_random_walk_ohlcv(n=600, seed=seed if seed is not None else 42)

    # Resolve fee/slippage from config if omitted
    cfg = load_config()
    fee_val = fee if fee is not None else cfg.trading.fee
    slippage_val = slippage if slippage is not None else cfg.trading.slippage

    try:
        strat_cls = get_strategy(strategy)
        strat = strat_cls()  # default
        if param:
            kv = parse_kv_params(param)
            strat = apply_params(strat, kv)
        result = run_backtest(df, strat, cash=capital, fee=fee_val, slippage=slippage_val)
    except Exception as e:
        log.error("backtest.error", error=str(e))
        raise typer.Exit(code=1)

    # Build provenance snapshot
    provenance = {
        "source": "csv" if csv and csv.exists() else "simulated",
        "rows": int(len(df)),
        "timezone": "UTC",
    }
    if "timestamp" in df.columns:
        try:
            start = df["timestamp"].iloc[0]
            end = df["timestamp"].iloc[-1]
            if getattr(start, "tzinfo", None) is None:
                start = start.replace(tzinfo=timezone.utc)
            if getattr(end, "tzinfo", None) is None:
                end = end.replace(tzinfo=timezone.utc)
            provenance["start"] = start.isoformat()
            provenance["end"] = end.isoformat()
            # Also include local display times
            try:
                z = ZoneInfo(tz)
                provenance["start_local"] = start.astimezone(z).isoformat()
                provenance["end_local"] = end.astimezone(z).isoformat()
            except Exception:
                pass
        except Exception:
            pass
    if csv and csv.exists():
        try:
            import hashlib
            h = hashlib.sha256()
            with open(csv, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            provenance["dataset_hash"] = f"sha256:{h.hexdigest()}"
            provenance["path"] = str(csv)
        except Exception:
            pass
    # expose effective params (after validation)
    eff = {}
    for key in dir(strat):
        if key.startswith("_"):
            continue
        if key in ("signals", "Params"):
            continue
        try:
            val = getattr(strat, key)
        except Exception:
            continue
        if isinstance(val, (int, float, str, bool)):
            eff[key] = val
    params = {
        "strategy": strategy,
        "capital": capital,
        "fee": fee_val,
        "slippage": slippage_val,
        "strategy_params": eff,
    }
    result.metrics["provenance"] = provenance
    result.metrics["params"] = params
    result.metrics["display_timezone"] = tz
    write_json(run_dir / "metrics.json", result.metrics)
    # Also emit a Markdown summary next to metrics.json
    from ua.reporting.report import write_markdown as _write_md
    _write_md(run_dir / "report.md", f"Backtest — {strategy}", result.metrics)
    # Primary result to STDOUT (JSON) per CLI contract
    try:
        import orjson

        print(orjson.dumps(result.metrics).decode())
    except Exception:
        import json as _json

        print(_json.dumps(result.metrics, ensure_ascii=False))
    log.info("backtest.done", out=str(run_dir))


@app.command()
def trade(
    strategy: str = typer.Option("sma-crossover", help="전략 이름"),
    live: bool = typer.Option(False, "--live", help="실거래 모드 (기본: 페이퍼)"),
    market: str = typer.Option("KRW-BTC", help="마켓"),
    csv: Optional[Path] = typer.Option(None, help="캔들 CSV 경로(페이퍼 루프 입력)"),
    cooldown_bars: int = typer.Option(0, help="재진입 쿨다운(바 단위)", min=0),
    ack_live: bool = typer.Option(False, "--ack-live", help="실거래 위험 고지 확인 (1단계)"),
    confirm_live: Optional[str] = typer.Option(None, "--confirm-live", help='실거래 최종 확인 문구 입력 (2단계): I UNDERSTAND'),
    unit: int = typer.Option(1, help="분봉 단위 (라이브)"),
    poll_interval: float = typer.Option(5.0, help="폴링 간격(초)"),
    ws: bool = typer.Option(False, "--ws/--no-ws", help="웹소켓 기반 라이브 루프 사용"),
    ws_tick_interval: Optional[float] = typer.Option(None, help="WS 틱 로그 간격(초). 미지정 시 로그 레벨 기준: debug=1초, 그 외=60초"),
    prefetch: bool = typer.Option(True, "--prefetch/--no-prefetch", help="WS 시작 전 REST로 최소 바 개수 프리패치"),
    prefetch_bars: Optional[int] = typer.Option(None, help="프리패치 바 개수(지정 없으면 전략 요구치 사용)"),
    param: list[str] = typer.Option(None, "--param", help="전략 파라미터 key=value (여러 번 지정 가능)"),
):
    """실거래/페이퍼 트레이딩 실행."""
    log = structlog.get_logger()
    cfg = load_config()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    mode = "live" if live else "paper"
    run_dir = Path("runs") / f"trade_{mode}_{strategy}_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    add_file_json_logger(run_dir / "log.jsonl")
    try:
        # Bind shared context for structured logs (picked up by all loggers)
        structlog.contextvars.bind_contextvars(
            run_id=run_dir.name,
            mode=mode,
            strategy=strategy,
            market=market,
        )
    except Exception:
        pass
    log.info("trade.start", mode=mode, strategy=strategy, market=market, run_dir=str(run_dir))

    if live:
        if not ack_live or confirm_live != "I UNDERSTAND":
            log.error(
                "trade.live_guard",
                note="실거래 시작 전 2단계 확인이 필요합니다.",
                how="--ack-live 와 --confirm-live 'I UNDERSTAND' 를 함께 지정하세요.",
            )
            raise typer.Exit(code=2)
        # Live loop: WebSocket or REST polling
        br = UpbitBroker(cfg.api.upbit_access_key, cfg.api.upbit_secret_key)
        strat_cls = get_strategy(strategy)
        strat = strat_cls()
        if param:
            try:
                kv = parse_kv_params(param)
                strat = apply_params(strat, kv)
            except Exception as e:
                log.error("trade.param_error", error=str(e))
                raise typer.Exit(code=2)
        risk = cfg.risk
        if ws:
            try:
                eff_level = logging.getLogger().getEffectiveLevel()
                default_tick = 1.0 if eff_level <= logging.DEBUG else 60.0
                tick_iv = float(ws_tick_interval) if ws_tick_interval is not None else default_tick
                log.info("ws.tick_config", interval_s=tick_iv)
                # Log prefetch intent and strategy requirement if any
                req_bars = None
                try:
                    rb = getattr(strat, "required_bars", None)
                    req_bars = int(rb()) if callable(rb) else None
                except Exception:
                    req_bars = None
                log.info("prefetch.config", enabled=prefetch, override=prefetch_bars, strategy_required=req_bars)
                result = asyncio.run(
                    run_live_ws(
                        market=market,
                        strategy=strat,
                        broker=br,
                        max_fraction=float(risk.max_position_value),
                        max_daily_loss=float(risk.max_daily_loss),
                        cooldown_bars=cooldown_bars,
                        run_dir=str(run_dir),
                        tick_log_interval=tick_iv,
                        prefetch=prefetch,
                        prefetch_bars=prefetch_bars,
                    )
                )
            except Exception as e:
                log.error("trade.live_ws_error", error=str(e))
                raise typer.Exit(code=1)
            write_json(run_dir / "metrics.json", result)
            try:
                log.info("trade.summary", **result)
            except Exception:
                pass
            # state.json for live
            state = {
                "mode": mode,
                "strategy": strategy,
                "market": market,
                "risk": {
                    "max_fraction": float(risk.max_position_value),
                    "max_daily_loss": float(risk.max_daily_loss),
                    "cooldown_bars": cooldown_bars,
                },
                "stopped_reason": result.get("stopped"),
                "completed": result.get("stopped") is None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            write_json(run_dir / "state.json", state)
            from ua.reporting.report import write_markdown as _write_md
            _write_md(run_dir / "report.md", f"Trade Live WS — {strategy}", result)
            try:
                import orjson
                print(orjson.dumps(result).decode())
            except Exception:
                import json as _json
                print(_json.dumps(result, ensure_ascii=False))
            log.info("trade.done", mode=mode, run_dir=str(run_dir))
            return
        else:
            # fallback to REST polling MVP (existing logic moved to function was here)
            # To keep patch concise, WS path is primary; REST path retained above previously.
            log.error("trade.rest_polling_disabled", note="--ws 를 사용하여 WS 기반 루프를 실행하세요.")
            raise typer.Exit(code=2)

    # Paper mode
    if csv and csv.exists():
        df = pd.read_csv(csv)
        rename_map = {
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
            "time": "timestamp",
            "date": "timestamp",
        }
        cols = {c: rename_map.get(c.lower(), c) for c in df.columns}
        df = df.rename(columns=cols)
        needed = {"Open", "High", "Low", "Close", "Volume"}
        missing = needed - set(df.columns)
        if missing:
            log.error("trade.columns_missing", missing=sorted(missing))
            raise typer.Exit(code=2)
        # Clean types
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"]).reset_index(drop=True)
    else:
        log.error("trade.input_required", note="페이퍼 모드에는 --csv 입력이 필요합니다.")
        raise typer.Exit(code=2)

    strat_cls = get_strategy(strategy)
    strat = strat_cls()

    fee = cfg.trading.fee
    slippage = cfg.trading.slippage
    risk = cfg.risk
    metrics = run_paper(
        df,
        strat,
        cash=1_000_000.0,  # paper default capital
        fee=fee,
        slippage=slippage,
        max_fraction=float(risk.max_position_value),
        max_daily_loss=float(risk.max_daily_loss),
        cooldown_bars=cooldown_bars,
        run_id=str(run_dir.name),
        market=market,
    ).metrics

    write_json(run_dir / "metrics.json", metrics)
    # persist state snapshot (MVP)
    state = {
        "mode": mode,
        "strategy": strategy,
        "market": market,
        "risk": {
            "max_fraction": float(risk.max_position_value),
            "max_daily_loss": float(risk.max_daily_loss),
            "cooldown_bars": cooldown_bars,
        },
        "stopped_reason": metrics.get("StoppedReason"),
        "completed": metrics.get("StoppedReason") == "completed",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(run_dir / "state.json", state)
    from ua.reporting.report import write_markdown as _write_md
    _write_md(run_dir / "report.md", f"Trade Paper — {strategy}", metrics)
    # STDOUT metrics
    try:
        import orjson

        print(orjson.dumps(metrics).decode())
    except Exception:
        import json as _json
        print(_json.dumps(metrics, ensure_ascii=False))
    log.info("trade.done", mode=mode, run_dir=str(run_dir))


@app.command()
def report(
    run_dir: Path = typer.Argument(Path("runs"), help="실행 디렉터리 또는 루트"),
):
    """로그/메트릭을 수집해 간단한 요약을 출력 (stub)."""
    log = structlog.get_logger()
    metrics_files = sorted(run_dir.rglob("metrics.json"))
    if not metrics_files:
        log.warning("report.none", note="요약할 metrics.json 이 없습니다.")
        return
    import json as _json
    summary = []
    for f in metrics_files:
        try:
            data = _json.loads(Path(f).read_text())
        except Exception:
            data = {"_error": "invalid_json"}
        # enrich with log summary if present
        from ua.reporting.report import summarize_log as _sumlog
        log_path = Path(f).with_name("log.jsonl")
        log_summary = _sumlog(log_path) if log_path.exists() else {"events": {}, "errors": []}
        summary.append({"path": str(f), **data, "log_summary": log_summary})
    # STDOUT summary
    try:
        import orjson

        print(orjson.dumps(summary).decode())
    except Exception:
        print(_json.dumps(summary, ensure_ascii=False))
    # future: also write Markdown next to metrics.json


@app.command()
def portfolio(
    strategy: str = typer.Option("regime-router", help="전략 이름(포트폴리오 공통)"),
    live: bool = typer.Option(False, "--live", help="실거래 모드 (기본: 페이퍼 — 현재는 WS 실거래만 지원)"),
    market: list[str] = typer.Option(["KRW-BTC"], "--market", "-m", help="대상 마켓(여러 번 지정)"),
    unit: int = typer.Option(1, help="프리패치 분봉 단위"),
    cooldown_bars: int = typer.Option(0, help="재진입 쿨다운(바 단위)", min=0),
    allowed_hours: str = typer.Option("", help="거래 허용 시간대(KST) 예: 22:00-02:00[,HH:MM-HH:MM]"),
    ws_tick_interval: Optional[float] = typer.Option(None, help="WS 틱 로그 간격(초)"),
    prefetch: bool = typer.Option(True, "--prefetch/--no-prefetch", help="WS 시작 전 REST로 프리패치"),
    prefetch_bars: Optional[int] = typer.Option(None, help="프리패치 바 개수(미지정 시 전략 요구치)"),
    # Portfolio-level enhancements
    atr_trailing_mult: float = typer.Option(0.0, help="ATR 트레일링 배수(0=비활성)"),
    atr_period: int = typer.Option(14, help="ATR 기간"),
    partial_tp_pct: float = typer.Option(0.0, help="부분익절 트리거 수익률(0=비활성)", min=0.0),
    partial_tp_ratio: float = typer.Option(0.5, help="부분익절 비중(0~1)", min=0.0, max=1.0),
    ack_live: bool = typer.Option(False, "--ack-live", help="실거래 위험 고지 확인 (1단계)"),
    confirm_live: Optional[str] = typer.Option(None, "--confirm-live", help='실거래 최종 확인 문구 입력: I UNDERSTAND'),
    param: list[str] = typer.Option(None, "--param", help="전략 파라미터 key=value (여러 번 지정 가능)"),
):
    """여러 마켓을 동시에 WS로 자동매매 (레짐 라우팅/시간필터/포트폴리오 스탑룰/ATR 트레일링/부분익절)."""
    log = structlog.get_logger()
    cfg = load_config()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    mode = "live" if live else "paper"
    run_dir = Path("runs") / f"portfolio_{mode}_{strategy}_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    add_file_json_logger(run_dir / "log.jsonl")
    try:
        structlog.contextvars.bind_contextvars(run_id=run_dir.name, mode=mode, strategy=strategy)
    except Exception:
        pass
    log.info("portfolio.start", mode=mode, markets=market, run_dir=str(run_dir))

    if live:
        if not ack_live or confirm_live != "I UNDERSTAND":
            log.error("portfolio.live_guard", note="실거래 시작 전 2단계 확인이 필요합니다.")
            raise typer.Exit(code=2)
    br = UpbitBroker(cfg.api.upbit_access_key, cfg.api.upbit_secret_key)
    # Prepare strategy params
    strat_params = {}
    if param:
        try:
            kv = parse_kv_params(param)
            strat_params = kv
        except Exception as e:
            log.error("portfolio.param_error", error=str(e))
            raise typer.Exit(code=2)
    # Tick log interval
    eff_level = logging.getLogger().getEffectiveLevel()
    default_tick = 1.0 if eff_level <= logging.DEBUG else 60.0
    tick_iv = float(ws_tick_interval) if ws_tick_interval is not None else default_tick
    log.info("ws.tick_config", interval_s=tick_iv)

    # Risk params
    risk = cfg.risk
    try:
        result = asyncio.run(
            run_portfolio_ws(
                markets=market,
                strategy_name=strategy,
                strategy_params=strat_params,
                broker=br,
                unit=unit,
                prefetch=prefetch,
                prefetch_bars=prefetch_bars,
                max_fraction=float(risk.max_position_value),
                max_daily_loss=float(risk.max_daily_loss),
                cooldown_bars=cooldown_bars,
                allowed_hours=allowed_hours or "",
                tz_display=cfg.app.timezone,
                atr_trailing_mult=atr_trailing_mult,
                atr_period=atr_period,
                partial_tp_pct=partial_tp_pct,
                partial_tp_ratio=partial_tp_ratio,
            )
        )
    except Exception as e:
        log.error("portfolio.error", error=str(e))
        raise typer.Exit(code=1)
    from ua.reporting.report import write_json
    write_json(run_dir / "metrics.json", result)
    try:
        import orjson
        print(orjson.dumps(result).decode())
    except Exception:
        import json as _json
        print(_json.dumps(result, ensure_ascii=False))
    log.info("portfolio.done", out=str(run_dir))

@app.command()
def accounts(
    ack_live: bool = typer.Option(False, "--ack-live", help="API 키 사용 동의(안전 확인)"),
):
    """Upbit 계정 정보 조회(안전 확인 필요)."""
    log = structlog.get_logger()
    if not ack_live:
        log.error("accounts.guard", note="--ack-live 플래그로 키 사용을 명시적으로 허용하세요.")
        raise typer.Exit(code=2)
    cfg = load_config()
    br = UpbitBroker(cfg.api.upbit_access_key, cfg.api.upbit_secret_key)
    try:
        data = br.get_accounts()
    except Exception as e:
        log.error("accounts.error", error=str(e))
        raise typer.Exit(code=1)
    try:
        import orjson

        print(orjson.dumps(data).decode())
    except Exception:
        import json as _json
        print(_json.dumps(data, ensure_ascii=False))


@app.command()
def order(
    market: str = typer.Option(..., help="마켓(예: KRW-BTC)"),
    side: str = typer.Option(..., help="buy 또는 sell"),
    ord_type: str = typer.Option(..., help="limit | price(시장가 매수) | market(시장가 매도)"),
    price: Optional[float] = typer.Option(None, help="limit/price 주문용 가격(원)"),
    volume: Optional[float] = typer.Option(None, help="limit/market 주문용 수량"),
    ack_live: bool = typer.Option(False, "--ack-live", help="실거래 위험 고지 확인 (1단계)"),
    confirm_live: Optional[str] = typer.Option(None, "--confirm-live", help='실거래 최종 확인 문구 입력: I UNDERSTAND'),
):
    """Upbit 단일 주문 발주(강한 안전장치 필요)."""
    log = structlog.get_logger()
    if not ack_live or confirm_live != "I UNDERSTAND":
        log.error(
            "order.live_guard",
            note="주문 전 2단계 확인이 필요합니다.",
            how="--ack-live 와 --confirm-live 'I UNDERSTAND' 를 함께 지정하세요.",
        )
        raise typer.Exit(code=2)
    cfg = load_config()
    br = UpbitBroker(cfg.api.upbit_access_key, cfg.api.upbit_secret_key)
    # Pre-validate with orders/chance to get price_unit/mins
    try:
        chance = br.get_order_chance(market, side)
    except Exception as e:
        log.error("order.chance_error", error=str(e))
        raise typer.Exit(code=1)
    price_unit = None
    try:
        price_unit = float(((chance.get("market") or {}).get("bid") or {}).get("price_unit") or ((chance.get("market") or {}).get("ask") or {}).get("price_unit"))
    except Exception:
        price_unit = None
    if ord_type == "limit" and price is not None and price_unit:
        q_price = UpbitBroker.quantize_price(price, price_unit)
        if q_price != price:
            log.warning("order.price_adjusted", requested=price, adjusted=q_price, unit=price_unit)
            price = q_price
    req = OrderRequest(
        side=side,
        market=market,
        size=volume,
        price=price,
        order_type=ord_type,
    )
    try:
        resp = br.place_order(req)
    except Exception as e:
        log.error("order.error", error=str(e))
        raise typer.Exit(code=1)
    try:
        import orjson

        print(orjson.dumps(resp).decode())
    except Exception:
        import json as _json
        print(_json.dumps(resp, ensure_ascii=False))


if __name__ == "__main__":
    app()
