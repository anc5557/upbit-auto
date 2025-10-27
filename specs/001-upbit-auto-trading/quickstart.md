# Quickstart — Upbit 자동매매

## Prerequisites

- Python 3.11+
- uv 설치 후 가상환경 구성

```bash
uv venv -p 3.11
source .venv/bin/activate
uv pip install -e .
```

## Backtest (시뮬레이션 or CSV)

```bash
ua backtest --strategy sma-crossover --capital 1000000 --fee 0.0005 --slippage 0.0005 --tz Asia/Seoul --seed 42  # 총 비용 0.1%
# 또는 CSV로
ua backtest --strategy sma-crossover --csv data/krw-btc_1m.csv --capital 1000000 --fee 0.0005 --slippage 0.0005
```

## Fetch (KRW-BTC 분봉)

```bash
ua fetch --market KRW-BTC --unit 1 --candles 500 --out data/krw-btc_1m.csv
```

## Report (요약)

```bash
ua report runs
```

## Trade (페이퍼)

```bash
ua trade --strategy sma-crossover --market KRW-BTC
```

라이브는 후속 단계에서 `--live` + 2단계 확인으로 활성화됩니다.
