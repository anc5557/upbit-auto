from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
import os
import tomllib
try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore


class ApiConfig(BaseModel):
    upbit_access_key: Optional[str] = Field(default=None)
    upbit_secret_key: Optional[str] = Field(default=None)


class RiskConfig(BaseModel):
    max_position_value: float = Field(default=0.2, description="fraction of capital")
    max_daily_loss: float = Field(default=0.05, description="fraction of capital")
    max_concurrent_positions: int = 1


class AppConfig(BaseModel):
    language: str = "ko"
    timezone: str = "Asia/Seoul"
    data_dir: str = "data"


class Settings(BaseModel):
    api: ApiConfig = Field(default_factory=ApiConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    app: AppConfig = Field(default_factory=AppConfig)
    class TradingConfig(BaseModel):
        fee: float = 0.0005
        slippage: float = 0.0005

    trading: "Settings.TradingConfig" = Field(default_factory=lambda: Settings.TradingConfig())


def _read_toml(path: Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


def load_config(path: Optional[Path] = None) -> Settings:
    """Load configuration from TOML and env.

    - Looks for explicit `path`, then `config/local.toml`, then `config/example.toml`.
    - Merges environment variables if present.
    """
    # Load .env (if available) so environment overlay can pick them up
    if load_dotenv:
        try:
            load_dotenv()
        except Exception:
            pass

    candidates = []
    if path is not None:
        candidates.append(path)
    candidates.append(Path("config/local.toml"))
    candidates.append(Path("config/example.toml"))

    data: dict = {}
    for p in candidates:
        if p.exists():
            data = _read_toml(p)
            break

    # overlay env
    access = os.getenv("UPBIT_ACCESS_KEY")
    secret = os.getenv("UPBIT_SECRET_KEY")
    if access or secret:
        data.setdefault("api", {})
        if access:
            data["api"]["upbit_access_key"] = access
        if secret:
            data["api"]["upbit_secret_key"] = secret

    fee = os.getenv("UA_FEE")
    slp = os.getenv("UA_SLIPPAGE")
    if fee or slp:
        data.setdefault("trading", {})
        if fee:
            try:
                data["trading"]["fee"] = float(fee)
            except ValueError:
                pass
        if slp:
            try:
                data["trading"]["slippage"] = float(slp)
            except ValueError:
                pass

    return Settings.model_validate(data)
