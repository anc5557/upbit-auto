import pandas as pd

from ua.engine.common import simulate_long_only


def test_risk_violation_triggers_stop():
    # Construct a simple dataset: flat then sharp drop
    prices = [100, 100, 100, 50]
    df = pd.DataFrame({
        "Open": prices,
        "High": prices,
        "Low": prices,
        "Close": prices,
        "Volume": [1, 1, 1, 1],
    })
    # Signals: buy at t=1, hold, then allow exit
    signals = [0, 1, 0, -1]
    res = simulate_long_only(
        df,
        signals,
        cash=1000.0,
        fee=0.0,
        slippage=0.0,
        max_fraction=1.0,
        cooldown_bars=0,
        stop_drawdown=0.3,  # 30% drawdown stop
    )
    assert res.metrics.get("StoppedReason") in {"risk_violation", "completed"}
    # Given a 50% drop, drawdown stop should trigger
    assert res.metrics.get("StoppedReason") == "risk_violation"

