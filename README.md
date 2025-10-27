# upbit-auto (ua)

업비트(Upbit) 자동매매·백테스트 CLI입니다. 전략 우선, 재현 가능한 백테스트, 안전한 실거래, 구조화 로깅을 지향합니다.

- CLI: `ua`
- 언어: Python 3.11+
- 버전/의존성: uv (pyproject + uv.lock)

## 빠른 시작

1) uv 설치 및 가상환경 구성

- macOS/Linux: https://docs.astral.sh/uv/
- 프로젝트 루트에서:

```
uv venv -p 3.11
source .venv/bin/activate
uv pip install -e .
./tools/gen-lock.sh  # 선택사항: uv.lock 생성(재현성)
```

2) CLI 확인

```
ua --help
ua backtest --strategy sma-crossover --csv data/sample/KRW-BTC_1m_sample.csv --capital 1000000 --fee 0.0005 --slippage 0.0005 --tz Asia/Seoul
```

3) 설정

- `config/example.toml` → `config/local.toml` 복사 후 API 키/리스크 한도 등 수정
- 환경변수 사용 가능 (`.env.example` 참고)

### 환경변수(.env) 사용법

- 위치: 프로젝트 루트에 `.env` 파일을 둡니다. `cp .env.example .env`로 시작하세요.
- 내용: 키=값 형식으로 작성합니다. 따옴표는 필요 없습니다.

```
UPBIT_ACCESS_KEY=YOUR_UPBIT_ACCESS_KEY
UPBIT_SECRET_KEY=YOUR_UPBIT_SECRET_KEY
# 선택: 수수료/슬리피지(파일/ENV/CLI 중 가장 높은 우선순위가 적용)
UA_FEE=0.0005
UA_SLIPPAGE=0.0005
```

- 자동 로드: `ua` 실행 시 `.env`를 자동으로 읽습니다. 별도 `export`나 `source .env`가 필요하지 않습니다.
- 실행 위치: `.env` 검색 기준은 현재 작업 디렉터리이므로, 프로젝트 루트에서 명령을 실행하는 것을 권장합니다.
  - 루트가 아닌 곳에서 실행한다면, 셸 환경변수로 직접 설정하세요: `export UPBIT_ACCESS_KEY=...` `export UPBIT_SECRET_KEY=...`
- 우선순위: `CLI > ENV(.env 포함) > TOML(config/local.toml) > 기본값` (ENV가 TOML을 덮어씁니다)
- 검증 방법: `ua accounts --ack-live` 실행 시 계정 JSON이 출력됩니다. 401/권한 오류가 나면 키를 다시 확인하세요.
- 보안 권장: `.env`에는 비밀 키가 들어가므로 저장소에 커밋하지 마세요(보통 `.gitignore`에 포함).

설정 상세(TOML/ENV)
- 파일: `config/local.toml`
  - `[api]` `upbit_access_key`, `upbit_secret_key`
  - `[risk]` `max_position_value`(0~1), `max_daily_loss`(0~1), `max_concurrent_positions`
  - `[trading]` `fee`(예: 0.0005), `slippage`(예: 0.0005)
- 환경변수: `UPBIT_ACCESS_KEY`, `UPBIT_SECRET_KEY`, `UA_FEE`, `UA_SLIPPAGE`
- 우선순위: CLI > ENV > TOML > 기본값

## 사용 명령 요약

- `ua fetch`: 캔들 수집(CSV 저장)
- `ua backtest`: 백테스트 실행(결과는 STDOUT JSON + 파일 저장)
  - 옵션: `--fee`, `--slippage`, `--tz`(표시 타임존), `--seed`(시뮬레이션 결정성), `--param key=value`(전략 파라미터)
- `ua trade`: 페이퍼/실거래 실행(안전장치 포함)
- `ua portfolio`: 다마켓 WS 자동매매(레짐 라우팅/시간필터/포트폴리오 스탑룰/ATR 트레일링/부분익절)
- `ua report`: 실행 결과 요약(JSON, log_summary 포함)
- `ua accounts`: 업비트 계정 조회(안전 확인 필요)
- `ua order`: 단일 주문 발주(강한 안전장치 필요)

설계 원칙: `.specify/memory/constitution.md`

## 내장 전략 목록

- `sma-crossover`: 단순 이동평균 크로스 예시(`fast`, `slow`)
- `ema-rsi`: EMA(9/21) + RSI(14) 크로스 확인 + TP/SL
  - 주요 파라미터: `ema_fast`(기본 9), `ema_slow`(21), `rsi_period`(14), `confirm_window`(3: RSI 상향돌파가 최근 N봉 이내면 유효), `tp_pct`(0.0075=0.75%), `sl_pct`(0.01=1%), `swing_lookback`(14)
  - 진입: EMA_fast 상향 교차 AND RSI 30 상향 이탈
  - 퇴출: TP/SL 또는 RSI 70 도달 또는 EMA 하향 교차
- `macd-vwap`: MACD(12,26,9) + VWAP(세션 리셋)
  - 주요 파라미터: `vwap_session`(기본 "D"=UTC 일별), `tp_pct`(기본 0), `sl_pct`(0.01), `min_hist_ratio`(히스토그램 절대값/가격 최소 비율), `min_vwap_dev`(VWAP 이격 최소 비율), `signal_cooldown_bars`(재진입 쿨다운)
  - 진입: 종가 VWAP 상향 이탈 AND MACD 라인 신호선 상향 교차(히스토그램 양수) + 필터(min_hist_ratio, min_vwap_dev, 쿨다운)
  - 퇴출: 히스토그램 음전환 또는 종가 VWAP 하향 이탈 또는 TP/SL
- `bb-rsi`: 볼린저밴드(20,2) + RSI(4) 역추세 단타
  - 주요 파라미터: `require_strong_candle`(기본 true), `bb_k`(밴드 폭 스케일), `tp_pct`(기본 0), `sl_pct`(0.01), `exit_to_mid`(중앙선 도달 시 익절), `use_atr_sl`(ATR 기반 손절), `atr_period`, `atr_mult`
  - 진입: 하단 밴드 터치/이탈 AND RSI 20 상향 이탈(강한 양봉 확인 옵션)
  - 퇴출: 상단 밴드 도달 또는 RSI 80 진입 또는 TP/SL
- `regime-router`: 레짐(트렌드/횡보) 별로 하위 전략 라우팅
  - 지표: ADX(14), Bollinger 폭(20,2), EMA200, EMA200 기울기
  - 기본: 트렌드=ema-rsi, 횡보=bb-rsi
  - 주요 파라미터: `adx_thresh`(20), `bb_width_low`(0.015), `bb_width_high`(0.03), `ema_trend_period`(200), `slope_window`(10), `slope_thresh`(0.0)
  - 비고: `trend_params`, `range_params`(dict)로 하위 전략 파라미터 주입 가능(현재 CLI 직렬화는 추후 지원)

## 백테스트 사용법

- 예시
  - `ua backtest -s sma-crossover --csv data/sample/KRW-BTC_1m_sample.csv --capital 1000000 --fee 0.0005 --slippage 0.0005 --tz Asia/Seoul`
  - 전략 파라미터: `--param fast=5 --param slow=20` 처럼 여러 번 지정 가능(유효성 검사 포함)
- 출력
  - STDOUT: JSON metrics
  - Files under `runs/backtest_<strategy>_<ts>/`: `metrics.json`, `report.md`, `log.jsonl`
  - 메트릭: Return/MDD/Win Rate/#Trades/Avg Trade/Sharpe + `params`, `provenance`, `display_timezone`
- 결정성
  - Simulation path supports `--seed`; same input/params → same metrics

## 데이터 수집(fetch)

- 예시: `ua fetch --market KRW-BTC --unit 1 --candles 500 --out data/krw-btc_1m.csv`
- Behavior: 200개 단위 페이징, 역순→정순 변환, 429/5xx 재시도/백오프
- 출력: CSV 컬럼 `Open,High,Low,Close,Volume[,timestamp]`

## 페이퍼 트레이딩

- 예시: `ua trade --strategy sma-crossover --market KRW-BTC --csv data/krw-btc_1m.csv --cooldown-bars 3`
- 리스크: `max_position_value`, `max_daily_loss`, `cooldown_bars`
- 출력: STDOUT JSON; `runs/trade_paper_<...>/{metrics.json,report.md,log.jsonl,state.json}`

## 라이브 트레이딩

- 안전장치: `--ack-live` 및 `--confirm-live "I UNDERSTAND"` 필수
- WebSocket 모드(권장)
  - `ua trade --live --ws -s sma-crossover --market KRW-BTC --ack-live --confirm-live "I UNDERSTAND"`
  - WS `trade` 스트림 → 1분 집계 → 전략 → 주문
  - 사전 검증: `/v1/orders/chance`의 `price_unit`, `min_total`로 보정/검증
  - 재시도/재연결: HTTP(429/5xx) 자동 재시도+지터, WS 백오프 재접속
  - 프리패치(기본): WS 시작 전 REST로 최근 분봉을 사전 로드해 지표 워밍업 없이 즉시 시작
    - 전략이 `required_bars()`를 제공하면 해당 개수 이상을 자동으로 수집
    - CLI로 제어: `--prefetch/--no-prefetch`(기본 on), `--prefetch-bars N`(강제 개수 지정)
- 출력: STDOUT JSON; `runs/trade_live_ws_<...>/{metrics.json,report.md,log.jsonl,state.json}`

## 포트폴리오 라이브(여러 마켓 동시 운용)

- 명령: `ua portfolio`
- 기능: 하나의 전략(예: `regime-router`)을 여러 마켓에 동시에 적용
  - 시간 필터: `--allowed-hours "22:00-02:00[,HH:MM-HH:MM]"` (KST 기준)
  - 포트폴리오 스탑룰: `max_daily_loss` 기준 총 손실 도달 시 전체 중지
  - ATR 트레일링 스톱: `--atr-trailing-mult 1.5` `--atr-period 14`
  - 부분익절: `--partial-tp-pct 0.004 --partial-tp-ratio 0.5`
- 예시
```
.venv/bin/ua portfolio --live \
  -m KRW-BTC -m KRW-ETH -m KRW-XRP \
  -s regime-router --allowed-hours "22:00-02:00" \
  --ack-live --confirm-live "I UNDERSTAND" \
  --param adx_thresh=22 --param bb_width_thresh=0.02 \
  --atr-trailing-mult 1.5 --partial-tp-pct 0.004 --partial-tp-ratio 0.5
```

### 로깅 레벨/WS 틱 로그

- 전역 로그 레벨: `--log-level {debug|info|warning|error}` (기본: info)
  - debug에서는 `ws.tick`이 1초 간격, 그 외 레벨에서는 60초 간격
- 수동 제어: `--ws-tick-interval <초>`로 간격 강제(0 이하면 비활성화)
- 항상 기록되는 핵심 이벤트: `bar.closed`, `order.*`, `accounts.*`, `risk.violation`

## 계정/주문

- 계정: `ua accounts --ack-live` → `/v1/accounts` JSON 출력
- 주문: `ua order --market KRW-BTC --side buy --ord-type price --price 100000 --ack-live --confirm-live "I UNDERSTAND"`
  - ord_type: `limit`(지정가: price+volume), `price`(시장가 매수: 원화 금액), `market`(시장가 매도: 수량)
  - 가격 보정: `price_unit` 최소 호가 단위로 보정, 시장가 매수는 `min_total` 미만 시 스킵

## 로깅/리포트

- 실행별 `log.jsonl`(구조화 이벤트 예: `ws.connected/subscribed/tick`, `bar.closed`, `signal.changed/inspect`, `order.submitted/status/filled/cancelled`, `accounts.snapshot/update`, `risk.violation`)
- `ua report runs` → 각 실행의 metrics + `log_summary`(이벤트 카운트/에러 목록) JSON 출력

## 테스트

- 결정성: `tests/integration/test_backtest_determinism.py`
- 리스크 정지: `tests/integration/test_risk_limits.py`
- 구성 우선순위: `tests/unit/test_config_precedence.py`

## 안전 안내

- 실거래는 손실 위험이 있습니다. 반드시 소액으로 검증하세요.
- API 키/설정과 거래소 규칙(최소 금액/호가 단위/속도 제한)을 확인하세요.
- 본 프로젝트는 안전장치를 제공하지만, 사용 책임은 사용자에게 있습니다.

## 문서

- 상세 가이드는 `docs/README.md`를 참고하세요.
  - 전략 개발자는 최소 필요 바 수(`required_bars`) 정의와 프리패치 동작을 확인하세요.
