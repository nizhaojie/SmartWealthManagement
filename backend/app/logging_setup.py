from __future__ import annotations

import logging
from pathlib import Path

from app.tracing import get_trace_id

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


class MultilineTraceFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        trace_id = getattr(record, "trace_id", "-")
        marker = f"trace_id={trace_id}"
        lines = formatted.splitlines()
        return "\n".join(line if marker in line else f"[trace_id={trace_id}] {line}" for line in lines)


class TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id() or "-"
        return True


class BelowErrorFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < logging.ERROR


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if getattr(root, "_wealth_configured", False):
        return

    root.setLevel(logging.INFO)
    formatter = MultilineTraceFormatter(
        "%(asctime)s %(levelname)s [trace_id=%(trace_id)s] %(message)s"
    )
    trace_filter = TraceIdFilter()

    info_handler = logging.FileHandler(LOG_DIR / "info.log", encoding="utf-8")
    info_handler.setLevel(logging.INFO)
    info_handler.addFilter(trace_filter)
    info_handler.addFilter(BelowErrorFilter())
    info_handler.setFormatter(formatter)

    error_handler = logging.FileHandler(LOG_DIR / "error.log", encoding="utf-8")
    error_handler.setLevel(logging.ERROR)
    error_handler.addFilter(TraceIdFilter())
    error_handler.setFormatter(formatter)

    root.addHandler(info_handler)
    root.addHandler(error_handler)
    root._wealth_configured = True  # type: ignore[attr-defined]
