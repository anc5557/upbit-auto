# upbit-auto 문서 (상세 가이드)

이 문서는 upbit-auto(ua) 사용과 확장을 위한 상세 가이드입니다.

- 대상 독자: 전략 개발자, 운영자(트레이더), 시스템 통합자
- 목적: 안전하고 재현 가능한 방식으로 전략을 설계/검증/운영

### CLI 전역 옵션

- `--json/--no-json`: 구조화(JSON) 로그 출력(기본: on)
- `--log-level {debug|info|warning|error}`: 로그 레벨 지정(기본: info)

## 1. 설치와 환경

- Python 3.11+, uv 권장
- 기본 설치
```
uv venv -p 3.11
source .venv/bin/activate
uv pip install -e .
./tools/gen-lock.sh  # uv.lock 생성(선택)
```

## 2. 설정(Configurations)

- 파일: `config/local.toml`
- 섹션
  - `[api]`: `upbit_access_key`, `upbit_secret_key`
  - `[risk]`: `max_position_value`, `max_daily_loss`, `max_concurrent_positions`
  - `[trading]`: `fee`, `slippage`
- 환경변수 오버라이드: `UPBIT_ACCESS_KEY`, `UPBIT_SECRET_KEY`, `UA_FEE`, `UA_SLIPPAGE`
- 우선순위: CLI > ENV > TOML > 기본값
- 예제: `config/example.toml` 참고

### 2.1 .env 사용법(ENV 로드)

- 루트에 `.env` 파일을 두면 `ua` 실행 시 자동으로 로드됩니다.
- 시작: `cp .env.example .env`
- 예시 내용

```
UPBIT_ACCESS_KEY=YOUR_UPBIT_ACCESS_KEY
UPBIT_SECRET_KEY=YOUR_UPBIT_SECRET_KEY
UA_FEE=0.0005
UA_SLIPPAGE=0.0005
```

- 권장 실행: 프로젝트 루트에서 명령 실행(현재 작업 디렉터리 기준으로 `.env`를 찾음)
- 대안: 다른 위치에서 실행할 경우 셸에서 직접 `export` 하거나, 프로세스 매니저(systemd/Docker 등) 환경변수로 주입
- 충돌 시 우선순위: `CLI > ENV(.env) > TOML(config/local.toml) > 기본값`
- 보안: `.env`는 커밋하지 마세요(민감 정보 포함)

## 3. 데이터 수집(ua fetch)

- 예시: `ua fetch --market KRW-BTC --unit 1 --candles 500 --out data/krw-btc_1m.csv`
- 특징
  - 200개 단위 페이징, 역순→정순 변환
  - 429/5xx 및 네트워크 오류 재시도/백오프
  - 유효 단위: 1/3/5/15/30/60/240

## 4. 백테스트(ua backtest)

- 예시
```
ua backtest -s sma-crossover --csv data/sample/KRW-BTC_1m_sample.csv \
  --capital 1000000 --fee 0.0005 --slippage 0.0005 --tz Asia/Seoul \
  --param fast=5 --param slow=20
```
- 출력
  - STDOUT: JSON 메트릭
  - 파일: `runs/backtest_<strategy>_<ts>/metrics.json`, `report.md`, `log.jsonl`
  - 메트릭: Return/MDD/WinRate/#Trades/AvgTrade/Sharpe + `params`, `provenance`, `display_timezone`
- 결정성
  - `--seed` 옵션(시뮬레이션 데이터 사용 시)으로 재현성 보장
- CSV 파싱
  - 컬럼 매핑(Open/High/Low/Close/Volume, time/date→timestamp), 숫자형 강제, NA 제거, UTC 정렬

## 5. 전략 개발 가이드

- 전략 인터페이스
  - `signals(df: pd.DataFrame) -> pd.Series[int]` (1=매수, -1=매도, 0=유지)
  - 전략 등록: `@register("strategy-name")`
- 최소 필요 바 수(required_bars)
  - 라이브(WS) 시작 시 프리패치(REST)로 지표 워밍업 없이 즉시 신호 계산을 하기 위해, 전략은 최소 필요 바 수를 선언하는 것을 권장합니다.
  - 선택적 훅: `required_bars(self) -> int` 를 구현하세요. 미구현 시 기본 0이며, CLI 지정이 없으면 300개를 프리패치합니다.
  - 설정 가이드: 윈도우형 지표의 경우 가장 긴 윈도우 길이 + 여유 1~2개를 권장합니다.
    - 예: SMA 크로스(fast=10, slow=20) → `max(10,20)+1 = 21`
  - 샘플 구현: `src/ua/strategy/examples/sma_cross.py:1`
    - `def required_bars(self) -> int: return max(self.fast, self.slow) + 1`
- 선택적 인스펙션 훅(로깅/분석용)
  - `inspect(df: pd.DataFrame) -> dict`
  - 반환된 dict는 라이브 모드에서 `signal.inspect` 이벤트로 기록되어, 내부 지표(MA, RSI 등)와 트리거 근거를 시각화/분석하는 데 활용할 수 있습니다.
- 파라미터 스키마(선택)
  - `class Params(BaseModel): ...` (Pydantic v2)
  - CLI `--param key=value` → Params 검증 → 인스턴스 속성에 반영
- 예시: SMA 크로스
  - 파일: `src/ua/strategy/examples/sma_cross.py`

## 6. 페이퍼 트레이딩(ua trade)

- 예시: `ua trade --strategy sma-crossover --market KRW-BTC --csv data/krw-btc_1m.csv --cooldown-bars 3`
- 리스크
  - `max_position_value`(자본 대비 비중), `max_daily_loss`(일간 손실 한도), `cooldown_bars`(재진입 쿨다운)
- 출력
  - STDOUT: JSON 메트릭
  - 파일: `runs/trade_paper_<...>/{metrics.json,report.md,log.jsonl,state.json}`
- 이벤트 로그(JSONL)
  - 표준 이벤트 명칭(페이퍼): `order.submitted`, `order.filled`, `position.opened/closed`, `risk.violation`

## 7. 라이브 트레이딩(ua trade --live)

- 안전장치
  - 필수: `--ack-live` + `--confirm-live "I UNDERSTAND"`
- WebSocket 모드(권장)
  - `--ws` 사용 시 WS `trade` 스트림 구독 → 1분 캔들 집계 → 신호 계산 → 주문 발주
  - `/v1/orders/chance`로 `price_unit`(최소 호가), `min_total`(최소 주문 금액) 사전 검증·보정
  - HTTP 재시도/백오프(429/5xx/네트워크), WS 재연결(핑/타임아웃)
  - `cooldown_bars` 적용(최근 체결 바 기준)
- 출력
  - STDOUT: JSON
  - 파일: `runs/trade_live_ws_<...>/{metrics.json,report.md,log.jsonl,state.json}`

## 7.5 포트폴리오 라이브(ua portfolio)

- 여러 마켓을 동시에 WebSocket으로 운용합니다. 공통 전략을 적용(기본: `regime-router`)하며, 시간 필터/포트폴리오 스탑룰/ATR 트레일링/부분익절을 제공합니다.
- 예시
```
ua portfolio --live -m KRW-BTC -m KRW-ETH -m KRW-XRP \
  -s regime-router --allowed-hours "22:00-02:00" \
  --ack-live --confirm-live "I UNDERSTAND" \
  --param adx_thresh=22 --param bb_width_thresh=0.02 \
  --atr-trailing-mult 1.5 --partial-tp-pct 0.004 --partial-tp-ratio 0.5
```
- 옵션
  - `--market/-m`: 다중 지정 가능
  - `--allowed-hours`: KST 기준 `HH:MM-HH:MM`(여러 구간은 `,`로 구분). 구간 외에는 신규 진입만 차단하고, 청산은 허용합니다.
  - `--atr-trailing-mult`, `--atr-period`: ATR 기반 트레일링 스톱
  - `--partial-tp-pct`, `--partial-tp-ratio`: 부분익절 트리거와 비율
  - `--param key=value`: 전략 파라미터(예: `regime-router`의 `adx_thresh`, `bb_width_thresh` 등)
  - 그 외 `--prefetch/--no-prefetch`, `--prefetch-bars`, `--cooldown-bars` 등은 단일 WS와 동일

### regime-router 전략(고급)

- 레짐(트렌드/횡보)을 판별해 하위 전략 신호를 라우팅합니다.
  - 지표: ADX(14), Bollinger 폭(20,2), EMA200, EMA200 기울기
  - 트렌드: ADX≥`adx_thresh` AND 종가>EMA200 AND EMA200 기울기>`slope_thresh` OR BB폭≥`bb_width_high`
  - 횡보: BB폭≤`bb_width_low` AND ADX<`adx_thresh` (그 외 구간은 직전 레짐 유지, 초기값=횡보)
  - 기본 매핑: 트렌드=ema-rsi, 횡보=bb-rsi
  - 주요 파라미터: `adx_thresh`(20), `bb_width_low`(0.015), `bb_width_high`(0.03), `ema_trend_period`(200), `slope_window`(10), `slope_thresh`(0.0)
  - 하위 전략 파라미터 주입: `trend_params`, `range_params`(dict) 지원. 현재 CLI에서 dict 직렬화는 제한적이며 코드/설정 확장을 통해 전달을 권장합니다.


### 7.1 프리패치(REST + WS, 기본 활성)

- 목적: WS 시작 직전에 REST로 최근 분봉 캔들을 가져와 전략 지표가 즉시 계산되도록 워밍업 시간을 제거합니다.
- 전략 의존: 전략이 `required_bars()`를 구현하면 해당 최소 바 개수 이상을 자동 프리패치합니다.
- CLI 제어
  - `--prefetch/--no-prefetch`: 프리패치 on/off (기본 on)
  - `--prefetch-bars N`: 프리패치 바 개수 강제 지정(전략 요구치보다 우선)
  - `--ws-tick-interval <초>`: WS 틱 로그 샘플링 간격(기본: 로그 레벨에 따름)
- 동작 로그: `prefetch.start`, `prefetch.done`, 오류 시 `prefetch.error`
- 참고: 현재 라이브 집계는 1분봉 기준입니다. 다른 봉 단위 지원은 별도 확장 항목입니다.

### 7.2 로깅 레벨과 WS 틱 로그 조절

- 전역 로그 레벨: `--log-level {debug|info|warning|error}`
  - `debug`: 상세 로그(WS 틱 1초 간격)
  - 그 외: 일반 로그(WS 틱 60초 간격)
- WS 틱 로그 수동 제어: `--ws-tick-interval <초>`
  - 지정 시 로그 레벨과 무관하게 해당 간격으로 `ws.tick` 출력
  - `0` 또는 음수로 지정하면 `ws.tick` 비활성화
- 적용 로그
  - `ws.tick`: 틱 샘플링 로그(스로틀 적용)
  - `bar.closed`: 1분 캔들 마감 로그(항상 기록)
  - 설정 확인: `ws.tick_config` (선택된 간격 출력)

### 7.3 라이브 이벤트 명세(요약)

- WebSocket 라이프사이클: `ws.connected`, `ws.subscribed`, `ws.ping`, `ws.error`, `ws.reconnect`
- 시세/캔들: `ws.tick`, `bar.closed`
- 전략: `signal.changed`, `signal.inspect`(전략이 `inspect(df)->dict` 제공 시)
- 주문: `order.submitted`, `order.status`, `order.filled`, `order.cancelled`, `order.skipped`, `order.status_check_start/done/error`
- 계좌: `accounts.snapshot`, `accounts.update`
- 리스크: `risk.violation`(예: 일손실 한도 초과)

## 8. 리포트/로깅(ua report)

- 실행 디렉터리에서 `metrics.json`을 수집하여 요약(JSON) 출력
- `log.jsonl` 요약 포함: `log_summary.events` 카운트 및 `errors` 목록
- 사람이 읽기 쉬운 `report.md` 생성(핵심 지표/파라미터/데이터 출처)

### 8.1 전략 개선을 위한 로그 활용

- 트리거 확인: `signal.changed` 시점과 `bar.closed` 가격을 함께 보면 진입/청산 타이밍 분석 가능
- 특징량 점검: 전략이 `inspect(df)->dict`를 제공하면 `signal.inspect`로 내부 지표(MA 등) 기록
- 체결 추적: `order.submitted`→`order.status*`→`order.filled/cancelled`로 슬리피지/체결지연 파악
- 잔고 반영: `accounts.update`로 주문 이후 자산 변화 검증

## 9. 문제 해결(Troubleshooting)

- 401/403: API 키/권한 확인
- 429: 호출 빈도 초과 → 대기/백오프 필요
- 5xx/네트워크: 자동 재시도, 빈번 시 네트워크 상태 점검
- WS 타임아웃: 네트워크 안정성 확인, 방화벽/프록시 설정 점검
- 최소 주문 한도: `/v1/orders/chance`의 `min_total` 확인, 예산 상향 또는 전략 조정

## 10. 체크리스트(운영)

- [ ] 소액으로 실거래 검증
- [ ] API 키 범위/권한 점검
- [ ] 리스크 한도 설정 확인(`max_position_value`, `max_daily_loss`)
- [ ] 전략 파라미터와 데이터 기간 재현성 확인
- [ ] 로그/리포트 점검 및 이상 시 중지

---

문의/개선 제안은 이슈로 남겨주세요. 안전과 재현성을 최우선으로 운영하시길 권장드립니다.
