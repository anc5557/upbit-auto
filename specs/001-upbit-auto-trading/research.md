# Research Notes — Upbit 자동매매

## API Overview

- Candles (Minutes): GET /v1/candles/minutes/{unit}
  - Params: market, to (ISO8601 UTC), count (<=200)
  - Returns reverse chronological list → 정순 변환 필요
- Rate limiting: 429 응답 처리, 지수 백오프/대기. 오류(5xx, 네트워크) 재시도 상한
- WebSocket (후속): 시세 구독/재연결 전략 필요, 최신 시세 보장/중복 프레임 제거
- Auth (거래): 액세스/시크릿 키 보관 규칙, 서명/Nonce/idempotency 키 전략

## Data & Determinism

- 백테스트는 동일 데이터·동일 파라미터→동일 지표 보장
- 데이터 스냅샷 버전 태그, 실행 디렉터리에 metrics.json 저장
- 시간대: 저장은 UTC, 표시/CLI는 Asia/Seoul 옵션

## Costs & Slippage

- 기본 비용: 수수료 0.05% + 슬리피지 0.05% (총 0.1%)
- 백테스트 파라미터로 비용 주입 가능하도록 인터페이스 설계

## Risk Controls (Initial)

- 포지션 한도(자본 비율), 일간 손실 한도, 동시 포지션 수, 재진입 쿨다운
- 실패 시 안전 정지 및 재시작 가능 상태 저장

## Open Questions (tracked → resolved)

- 초기 마켓/타임프레임: KRW-BTC + 1/3/5/15/60분봉 (결정)
- 리포트 포맷: JSON + Markdown (결정)
- 비용 모델: 고정 0.1% (결정)

