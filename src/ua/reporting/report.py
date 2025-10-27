from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import json
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import List


@dataclass
class Summary:
    items: Dict[str, Any]


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def write_markdown(path: Path, title: str, metrics: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {title}", ""]
    # Metrics core
    lines += ["## Metrics", ""]
    core_keys = [
        "Return [%]",
        "Max Drawdown [%]",
        "Win Rate [%]",
        "# Trades",
        "Avg Trade [%]",
        "Sharpe Ratio",
        "Equity Final [$]",
    ]
    for k in core_keys:
        if k in metrics:
            lines.append(f"- {k}: {metrics[k]}")
    # Params
    if isinstance(metrics.get("params"), dict):
        lines += ["", "## Params", ""]
        for k, v in metrics["params"].items():
            lines.append(f"- {k}: {v}")
    # Provenance
    if isinstance(metrics.get("provenance"), dict):
        lines += ["", "## Data Provenance", ""]
        prov = metrics["provenance"]
        for k in ["source", "path", "rows", "timezone", "start", "end", "dataset_hash"]:
            if k in prov:
                lines.append(f"- {k}: {prov[k]}")
        # Local times if available
        tz = metrics.get("display_timezone")
        if tz and "start" in prov and "end" in prov:
            try:
                z = ZoneInfo(tz)
                s = datetime.fromisoformat(prov["start"])  # assume ISO UTC
                e = datetime.fromisoformat(prov["end"])  # assume ISO UTC
                if s.tzinfo is None:
                    s = s.replace(tzinfo=ZoneInfo("UTC"))
                if e.tzinfo is None:
                    e = e.replace(tzinfo=ZoneInfo("UTC"))
                lines.append(f"- start_local[{tz}]: {s.astimezone(z).isoformat()}")
                lines.append(f"- end_local[{tz}]: {e.astimezone(z).isoformat()}")
            except Exception:
                pass
    path.write_text("\n".join(lines))


def summarize_log(path: Path) -> Dict[str, Any]:
    """Summarize JSONL log into event counts and error stats.

    Expects each line to be a JSON object possibly containing `event` and `error` keys.
    """
    counts: Dict[str, int] = {}
    errors: List[str] = []
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            evt = obj.get("event")
            if evt:
                counts[evt] = counts.get(evt, 0) + 1
            err = obj.get("error") or obj.get("message") if obj.get("level") == "error" else None
            if err:
                errors.append(str(err))
    except FileNotFoundError:
        return {"events": {}, "errors": []}
    return {"events": counts, "errors": errors}
