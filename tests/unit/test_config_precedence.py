import os
from pathlib import Path

from ua.config import load_config


def test_env_overrides_toml(tmp_path: Path, monkeypatch):
    toml = tmp_path / "local.toml"
    toml.write_text("""
[api]
upbit_access_key = "AAA"
upbit_secret_key = "BBB"

[trading]
fee = 0.0001
slippage = 0.0001
"""
    )

    monkeypatch.setenv("UPBIT_ACCESS_KEY", "ENV_AK")
    monkeypatch.setenv("UPBIT_SECRET_KEY", "ENV_SK")
    monkeypatch.setenv("UA_FEE", "0.0005")
    monkeypatch.setenv("UA_SLIPPAGE", "0.0005")

    cfg = load_config(toml)
    assert cfg.api.upbit_access_key == "ENV_AK"
    assert cfg.api.upbit_secret_key == "ENV_SK"
    assert abs(cfg.trading.fee - 0.0005) < 1e-9
    assert abs(cfg.trading.slippage - 0.0005) < 1e-9

