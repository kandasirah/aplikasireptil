"""Logging terstruktur REPTIL (structlog JSON) + correlation_id.

`correlation_id` mengalir dari request API → handler → (nanti) Celery task, lalu
otomatis disertakan di setiap baris log. Di produksi keluaran JSON; di dev,
console berwarna agar enak dibaca.
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar

import structlog

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def set_correlation_id(value: str | None = None) -> str:
    """Set correlation_id untuk konteks saat ini; kembalikan nilainya."""
    cid = value or new_correlation_id()
    _correlation_id.set(cid)
    return cid


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def _add_correlation_id(
    _logger: object, _method: str, event_dict: dict[str, object]
) -> dict[str, object]:
    cid = get_correlation_id()
    if cid:
        event_dict.setdefault("correlation_id", cid)
    return event_dict


def configure_logging(*, json_logs: bool = True, level: int = logging.INFO) -> None:
    """Konfigurasi structlog. Panggil sekali saat bootstrap aplikasi."""
    logging.basicConfig(format="%(message)s", level=level)

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_correlation_id,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
