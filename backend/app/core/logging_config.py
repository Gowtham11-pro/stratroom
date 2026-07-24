"""Enterprise structured logging configuration.

Provides JSON-formatted logs with correlation IDs, request context,
and configurable log levels per module.
"""
import json
import logging
import sys
import time
import contextvars

correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="")
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
user_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("user_id", default="")


class StructuredFormatter(logging.Formatter):
    """JSON structured log formatter with correlation context."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        corr = correlation_id_var.get("")
        if corr:
            log_entry["correlation_id"] = corr

        req = request_id_var.get("")
        if req:
            log_entry["request_id"] = req

        uid = user_id_var.get("")
        if uid:
            log_entry["user_id"] = uid

        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)

        extra = getattr(record, "extra_fields", None)
        if extra and isinstance(extra, dict):
            log_entry.update(extra)

        return json.dumps(log_entry, default=str, ensure_ascii=False)


class HumanReadableFormatter(logging.Formatter):
    """Compact human-readable format for development."""

    FORMATS = {
        logging.DEBUG: "%(asctime)s DBG  %(name)s %(message)s",
        logging.INFO: "%(asctime)s INFO %(name)s %(message)s",
        logging.WARNING: "%(asctime)s WARN %(name)s %(message)s",
        logging.ERROR: "%(asctime)s ERR  %(name)s %(message)s",
        logging.CRITICAL: "%(asctime)s CRIT %(name)s %(message)s",
    }

    def format(self, record: logging.LogRecord) -> str:
        fmt = self.FORMATS.get(record.levelno, self.FORMATS[logging.INFO])
        formatter = logging.Formatter(fmt, datefmt="%H:%M:%S")
        base = formatter.format(record)

        parts = [base]
        corr = correlation_id_var.get("")
        if corr:
            parts.append(f"[corr={corr[:8]}]")
        req = request_id_var.get("")
        if req:
            parts.append(f"[req={req[:8]}]")

        return " ".join(parts)


def setup_logging(level: str = "INFO", json_mode: bool = False, module_overrides: dict | None = None):
    """Configure application-wide logging.

    Args:
        level: Root log level (DEBUG, INFO, WARNING, ERROR).
        json_mode: True for JSON structured logs, False for human-readable.
        module_overrides: Dict of module_name -> level for fine-grained control.
            Example: {"stratroom.ai.llm": "WARNING", "sqlalchemy.engine": "WARNING"}
    """
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    if json_mode:
        formatter = StructuredFormatter()
    else:
        formatter = HumanReadableFormatter()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root.addHandler(handler)

    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    overrides = module_overrides or {}
    defaults = {
        "stratroom": logging.INFO,
        "stratroom.ai": logging.INFO,
        "stratroom.ai.llm": logging.WARNING,
        "stratroom.ai.agents": logging.INFO,
        "stratroom.ai.guardrails": logging.WARNING,
        "stratroom.ai.memory": logging.WARNING,
        "stratroom.ai.metrics": logging.WARNING,
        "stratroom.ai.enhancer": logging.WARNING,
        "stratroom.config": logging.INFO,
        "stratroom.documents": logging.INFO,
        "uvicorn": logging.WARNING,
        "uvicorn.error": logging.INFO,
        "uvicorn.access": logging.WARNING,
        "sqlalchemy.engine": logging.WARNING,
    }
    defaults.update(overrides)
    for mod, lvl in defaults.items():
        logging.getLogger(mod).setLevel(lvl)

