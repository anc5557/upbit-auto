# Tasks: Upbit 자동매매 — 전략·백테스트·자동매매·로깅

**Input**: specs/001-upbit-auto-trading/
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

## Phase 1: Setup (Shared Infrastructure)

- [ ] T001 [P] uv 락 파일 생성 및 커밋 준비 (`uv pip compile` 등) — 재현성 확보
- [ ] T002 [P] README.md 퀵스타트 보강(수수료/슬리피지 기본값, 보고서 경로) — `README.md`
- [ ] T003 [P] 샘플 데이터 추가 — `data/sample/KRW-BTC_1m_sample.csv` (소형 1m 캔들 1k행 내)

---

## Phase 2: Foundational (Blocking Prerequisites)

- [ ] T010 수수료/슬리피지 기본값 정렬 (총 0.1%) — `src/ua/__main__.py` (`backtest --fee` 기본값 0.001로)
- [ ] T011 [P] 비용 파라미터 설정화 — `src/ua/config.py` (fee, slippage 추가·로드)
- [ ] T012 [P] Upbit fetch 재시도/백오프 추가 — `src/ua/data/upbit.py` (`fetch_range_minutes` 루프에 429/5xx 처리)
- [ ] T013 [P] fetch 단위 검증(1/3/5/15/60/240) — `src/ua/__main__.py` (`fetch` 옵션 유효성)
- [ ] T014 실행 아티팩트 디렉터리 표준화 — `runs/backtest_*` 하위에 `metrics.json`, `report.md` 위치 규약 문서화 및 생성
- [ ] T015 구조화 로그 JSONL 파일 출력 — `src/ua/logging.py`/`src/ua/__main__.py` (run 디렉터리에 파일 핸들러 추가)

- [ ] T016 [P] STDOUT 출력 계약 준수 — `ua backtest`/`ua report` 결과를 STDOUT(JSON)으로 출력 (파일 저장은 부가)
- [ ] T017 공통 엔진 도입 — `src/ua/engine/common.py` (백테스트/페이퍼 공유 코드 경로), `src/ua/engine/backtest.py` 리팩터


Checkpoint: Backtest 결과가 결정적이며 지표 파일/로그가 표준 위치에 생성됨

---

## Phase 3: User Story 1 — 전략 설계·백테스트·전략 선택 (P1)

- [ ] T020 [US1] backtest 지표 키 표준화 — `src/ua/engine/backtest.py` (수익률/MDD/승률/거래수/평균거래/샤프)
- [ ] T021 [US1] metrics.json 저장 및 스키마 문서화 — `src/ua/__main__.py`, `specs/.../contracts/backtest.md`
- [ ] T022 [US1] Markdown 요약 생성 — `src/ua/reporting/report.py` (새 함수 `write_markdown`), `ua backtest`에서 생성
- [ ] T023 [US1] determinism 보장 — 무작위 시드/입력 고정 검증 경로 반영
- [ ] T024 [P] [US1] 결정성 통합 테스트 — `tests/integration/test_backtest_determinism.py` (동일 입력 두 번 → 동일 지표)
- [ ] T025 [P] [US1] CSV 파서 견고화 — 대소문자/여분 컬럼 무시, 필수 컬럼 검증 강화 (`src/ua/__main__.py`)

- [ ] T026 [US1] 타임존 처리(UTC 저장/Asia-Seoul 표시) — `specs/.../contracts/backtest.md` 문서화 + 코드 옵션 추가 (FR-011)
- [ ] T027 [US1] 데이터 스냅샷 버전/프로버넌스 태깅 — 입력 파일/범위/해시 저장 (FR-012)


Checkpoint: CSV 또는 샘플 데이터로 backtest 실행 → metrics.json + report.md 생성, 재현성 확인

---

## Phase 4: User Story 2 — 자동매매 실행(페이퍼→라이브) (P2)

- [ ] T030 [US2] 리스크 한도 모듈 — `src/ua/engine/risk.py` (포지션 비중, 일간 손실, 동시 포지션, 쿨다운)
- [ ] T031 [US2] 페이퍼 트레이딩 루프 — `src/ua/engine/paper.py` (신호→주문→체결 시뮬)
- [ ] T032 [US2] trade 명령 페이퍼 모드 연동 — `src/ua/__main__.py` (`ua trade`에서 paper 실행, 로그 JSONL 기록)
- [ ] T033 [P] [US2] 위험 한도 위반 테스트 — `tests/integration/test_risk_limits.py`
- [ ] T034 [US2] 라이브 모드 가드 — `--live` 이중 확인/경고/즉시 중단 경로 정리 (`src/ua/__main__.py`)
- [ ] T035 [US2] 업비트 브로커 스텁 확장 — `src/ua/broker/upbit.py` (서명/주문 인터페이스 설계만)

- [ ] T036 [US2] 실패 시 안전 정지/재시작 상태 저장 — 러닝 상태 파일/리커버리 훅 (FR-013)
- [ ] T037 [US2] 전략 파라미터 스키마(pydantic)와 검증 — CLI 플래그→스키마 매핑 (FR-014)


Checkpoint: 페이퍼 모드에서 리스크 가드 동작·이벤트 로그 생성 확인

---

## Phase 5: User Story 3 — 로깅·리포트 (P3)

- [ ] T040 [US3] 리포트 집계 — `ua report`가 `runs/**/metrics.json`을 수집해 표준 요약 출력 (`src/ua/__main__.py`)
- [ ] T041 [US3] Markdown 리포트 생성 — `src/ua/reporting/report.py` (표/요약/파라미터·기간 정보 포함)
- [ ] T042 [P] [US3] 다중 실행 비교 요약 — 전략/기간별 비교 테이블 생성

---

## Phase X: Config & Compliance

- [ ] T060 구성 계층 우선순위 테스트/문서화 — CLI > ENV > TOML > 기본 (FR-010)
- [ ] T061 업비트 거래 API 준수 작업 — 인증/서명, 속도 제한, 오류 매핑/재시도 정책 문서화 및 스텁 구현 (FR-009 확장)

---

## Phase N: Polish & Cross-Cutting

- [ ] T050 문서 정리 — `specs/.../quickstart.md`와 `README.md` 싱크
- [ ] T051 코드 포맷/린트 구성(black/ruff) — pyproject.toml
- [ ] T052 성능 점검 — 5만 캔들 기준 시간 측정, 병목 완화 노트
- [ ] T053 오류 메시지 한국어 정비, 로그 키 영문 스네이크케이스 유지

## Dependencies & Order

- Phase 1 → Phase 2 완료 후 US1 진행
- US1 완료 후 US2/US3 병행 가능
- 테스트 태스크(T024, T033)는 해당 스토리 구현 직후 작성·검증
