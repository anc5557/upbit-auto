from __future__ import annotations

import logging
import sys
import structlog
from pathlib import Path


def init_logging(json: bool = True, level: int | None = None) -> None:
    """Configure structured logging.

    - Logs go to stderr per CLI contract
    - JSON or key-value console renderer
    """

    handlers = [logging.StreamHandler(sys.stderr)]

    logging.basicConfig(
        level=(level if level is not None else logging.INFO),
        handlers=handlers,
        format="%(message)s",
    )

    shared_processors = [
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.contextvars.merge_contextvars,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            *shared_processors,
            renderer,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def add_file_json_logger(path: Path) -> None:
    """Add a JSONL file handler for structlog/stdlib logger."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.addHandler(fh)
