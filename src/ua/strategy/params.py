from __future__ import annotations

from typing import Any, Dict


def parse_kv_params(items: list[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"잘못된 파라미터 형식: {item}. key=value 형태여야 합니다.")
        k, v = item.split("=", 1)
        k = k.strip()
        v = v.strip()
        # try int -> float -> bool -> str
        if v.isdigit():
            out[k] = int(v)
            continue
        try:
            out[k] = float(v)
            continue
        except Exception:
            pass
        if v.lower() in {"true", "false"}:
            out[k] = v.lower() == "true"
        else:
            out[k] = v
    return out


def apply_params(strategy: Any, params: Dict[str, Any]) -> Any:
    """Apply params to a strategy instance.

    If the strategy has a nested `Params` pydantic model, use it for validation
    and to get normalized values; otherwise set attributes directly when present.
    """
    schema = getattr(strategy, "Params", None)
    normalized = {}
    if schema is not None:
        try:
            model = schema(**params)
            normalized = model.model_dump()
        except Exception as e:
            raise ValueError(f"전략 파라미터 검증 실패: {e}") from e
    else:
        normalized = params

    for k, v in normalized.items():
        if hasattr(strategy, k):
            setattr(strategy, k, v)
    return strategy

