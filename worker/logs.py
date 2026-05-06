import logging
import uuid
from contextvars import ContextVar
from typing import Any

import structlog

_correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


def new_correlation_id() -> str:
    cid = str(uuid.uuid4())
    _correlation_id_var.set(cid)
    return cid


def bind_correlation_id(cid: str) -> None:
    _correlation_id_var.set(cid)


def get_correlation_id() -> str:
    return _correlation_id_var.get("")


def _inject_correlation_id(logger: Any, method_name: str, event_dict: dict) -> dict:
    cid = _correlation_id_var.get("")
    if cid:
        event_dict.setdefault("correlation_id", cid)
    return event_dict


def _mask_sensitive(logger: Any, method_name: str, event_dict: dict) -> dict:
    # Remove Authorization from top-level and from nested headers dict
    if "Authorization" in event_dict:
        event_dict["Authorization"] = "***"
    headers = event_dict.get("headers")
    if isinstance(headers, dict) and "Authorization" in headers:
        headers["Authorization"] = "***"

    # Mask telefone — exibe apenas últimos 4 dígitos (LGPD)
    # Callers devem usar logger.debug() para payloads brutos do Evolution
    tel = event_dict.get("telefone")
    if isinstance(tel, str) and len(tel) > 4:
        event_dict["telefone"] = "****" + tel[-4:]

    return event_dict


def configure_logging(log_level: str = "INFO") -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        level=level,
        handlers=[logging.StreamHandler()],
        force=True,
    )

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _inject_correlation_id,
            _mask_sensitive,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = __name__) -> structlog.BoundLogger:
    return structlog.get_logger(name)
