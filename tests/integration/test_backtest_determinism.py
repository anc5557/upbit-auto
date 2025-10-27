import json
from typer.testing import CliRunner

from ua.__main__ import app


runner = CliRunner()


def test_backtest_determinism_simulated_seed():
    # Run backtest twice with same seed; metrics should be identical
    args = [
        "backtest",
        "--strategy",
        "sma-crossover",
        "--capital",
        "1000000",
        "--fee",
        "0.0005",
        "--slippage",
        "0.0005",
        "--seed",
        "123",
        "--outdir",
        "runs",
    ]
    r1 = runner.invoke(app, args)
    assert r1.exit_code == 0, r1.output
    m1 = json.loads(r1.stdout.strip())

    r2 = runner.invoke(app, args)
    assert r2.exit_code == 0, r2.output
    m2 = json.loads(r2.stdout.strip())

    # Remove non-deterministic keys if any; metrics should match otherwise
    for m in (m1, m2):
        m.pop("provenance", None)  # provenance may include path/hash per run
    assert m1 == m2

