# Implementation Plan: Upbit 자동매매 — 전략·백테스트·자동매매·로깅

**Branch**: `001-upbit-auto-trading` | **Date**: 2025-10-26 | **Spec**: specs/001-upbit-auto-trading/spec.md
**Input**: Feature specification from `/specs/001-upbit-auto-trading/spec.md`

## Summary

- Goal: 전략을 설계/백테스트하고, 선택한 전략으로 페이퍼→라이브 자동매매를 실행하며, 로그/리포트로 성과를 가시화한다.
- Approach: Python 3.11 + uv. CLI(Typer) 중심. 데이터 입수(Upbit REST/WS), 백테스트(backtesting.py), 구조화 로깅(structlog), 설정(pydantic+TOML), 보고(JSON+Markdown). 초기 범위는 KRW-BTC, 1/3/5/15/60분봉, 총 비용 0.1%(수수료 0.05% + 슬리피지 0.05%).

## Technical Context

- Language/Version: Python 3.11+
- Primary Dependencies: typer, httpx, websockets, pandas, numpy, backtesting.py, pydantic, structlog, orjson
- Storage: 파일 기반 CSV/JSONL(데이터 캐시, 실행 로그, 리포트)
- Testing: pytest 권장(단위/통합 분리). 백테스트 결정성 테스트 포함
- Target Platform: 콘솔/CLI, Linux/macOS
- Project Type: Single CLI project
- Performance Goals: 백테스트 5만 캔들 기준 체감 60초 내(기본 환경), 실시간 처리 지연 최소화
- Constraints: 업비트 속도 제한 준수, 신뢰성/재시작 가능, 리스크 한도 강제
- Scale/Scope: 초기 단일 마켓(KRW-BTC), 이후 다마켓 확장 고려

## Constitution Check

- 전략·백테스트 우선: 구현 흐름이 백테스트 합격→실거래로 이어지도록 설계 PASS
- 라이브러리 우선 모듈화: src/ua/* 모듈 분리 PASS
- CLI 인터페이스: 모든 기능을 CLI 노출 PASS
- 안정성·리스크·안전장치: 페이퍼 우선, 라이브는 명시 플래그/이중 확인 PASS(라이브는 후속 구현)
- 관측 가능성/버전(uv)/단순성: JSONL 로깅, uv 사용, 단순 데이터 모델 PASS

## Project Structure

### Documentation (this feature)

```text
specs/001-upbit-auto-trading/
├── plan.md              # 이 파일
├── research.md          # Phase 0: 외부 제약/엔드포인트/리스크 노트
├── data-model.md        # Phase 1: 엔티티/이벤트/계약 요약
├── quickstart.md        # Phase 1: 사용자/개발자 빠른 시작
└── contracts/           # Phase 1: CLI 계약 (입력/출력)
    ├── fetch.md
    ├── backtest.md
    ├── trade.md
    └── report.md
```

### Source Code (repository root)

```text
src/ua/
├── __main__.py          # CLI 엔트리(typer): fetch/backtest/trade/report
├── logging.py           # 구조화 로깅 초기화
├── config.py            # TOML+ENV 설정 로더
├── data/
│   ├── upbit.py         # REST 캔들 수집(비동기), CSV 저장
│   └── simulate.py      # 랜덤 워크 시뮬레이션 캔들
├── engine/
│   └── backtest.py      # backtesting.py 래퍼, 지표 추출
├── strategy/
│   ├── base.py          # 전략 레지스트리/발견
│   └── examples/
│       └── sma_cross.py # 예시 전략
├── broker/
│   └── upbit.py         # 브로커 어댑터(stub)
└── reporting/
    └── report.py        # 리포트 유틸(JSON/향후 MD)

config/
└── example.toml         # 구성 예시
```

**Structure Decision**: Single project 구조 선택. 기능 단위 모듈화로 헌장 준수.

## Phase 0 — Research Highlights

- 업비트 분봉 캔들 REST: 최대 batch 200, 역순 반환 → 누적 페이징 구현 필요
- 속도 제한/오류: 재시도/백오프, 429/5xx 처리, 시간 파라미터 `to` 사용 시 UTC ISO8601
- 시세 실시간(후속): 웹소켓 구독/재연결, 지연/중복 프레임 처리 가이드 필요
- 거래 규칙: 최소 주문 수량/가격 단위 라운딩, 시장/지정가 차이, 체결 수수료 반영

## Phase 1 — Design and Contracts

- 데이터 모델: Candle/Signal/Order/Fill/Position/Portfolio/Run/Metrics 정의(별도 파일)
- 계약(Contracts): CLI 명령별 입력/출력 스키마와 종료코드 명세(contracts/*.md)
- 구성: 기본값 + TOML + ENV + CLI 플래그 병합 순서 고정
- 비용 모델: 기본 수수료 0.05% + 슬리피지 0.05% (총 0.1%)
- 마켓/타임프레임: KRW-BTC, 1/3/5/15/60분봉

## Phase 2 — Implementation Steps (high-level)

1) Fetch: KRW-BTC 분봉 CSV 수집(1/3/5/15/60). 재시도/백오프/중단-재개 토대
2) Backtest: 공통 엔진(실거래/페이퍼와 동일 코드 경로)로 CSV 입력→지표 출력(JSON). 결정성 테스트 추가. 기본 비용 0.1%
3) Report: JSON 지표→Markdown 요약 생성. 실행 디렉터리 집계 지원
4) Trade Paper: 신호→주문→체결 시뮬레이션, 리스크 한도(일간 손실/포지션 사이즈/동시 포지션/쿨다운)
5) Trade Live (stub→MVP): 인증/서명, 주문 발주/취소, 멱등키/재시도, 안전 정지

## Test Plan (selected)

- 단위: 전략 신호 계산, 리스크 한도 로직, CSV 파서
- 통합: 백테스트 결정성(동일 입력→동일 결과), fetch 페이징 200단위 수집, 리포트 생성
- 회귀: 비용 파라미터 변경 시 지표 변동이 예상 범위 내인지 체크

## Risks & Mitigations

- API Rate Limit/429: 지수 백오프, 헤더/응답 기반 대기, 재시도 상한
- 결정성 훼손: 랜덤 시드 고정, 데이터 스냅샷 버전 태깅
- 실거래 안전: 기본 페이퍼, 라이브는 --live + 2단계 확인. 실패 시 안전 정지

## Rollout

- Alpha: 백테스트+리포트(로컬)
- Beta: 페이퍼 트레이딩(WS 구독 포함)
- GA: 제한된 라이브(안전장치 충족, 리스크 승인)
