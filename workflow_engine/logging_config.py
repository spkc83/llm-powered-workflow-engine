"""Structured logging configuration with correlation ID support.

Provides JSON-formatted structured logging for production and
human-readable text logging for development.
"""

import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Optional

# Context variable for request correlation
correlation_id_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)
session_id_var: ContextVar[Optional[str]] = ContextVar("session_id", default=None)
user_id_var: ContextVar[Optional[str]] = ContextVar("user_id", default=None)


def generate_correlation_id() -> str:
    """Generate a unique correlation ID for request tracing."""
    return str(uuid.uuid4())


class StructuredFormatter(logging.Formatter):
    """JSON-formatted log output for production environments."""

    def format(self, record: logging.LogRecord) -> str:
        import json

        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add correlation context
        cid = correlation_id_var.get()
        if cid:
            log_entry["correlation_id"] = cid
        sid = session_id_var.get()
        if sid:
            log_entry["session_id"] = sid
        uid = user_id_var.get()
        if uid:
            log_entry["user_id"] = uid

        # Add extra fields from record
        if hasattr(record, "extra_data"):
            log_entry.update(record.extra_data)

        # Add exception info
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
            }

        # Add source location for errors
        if record.levelno >= logging.ERROR:
            log_entry["source"] = {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName,
            }

        return json.dumps(log_entry, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable log output for development."""

    def format(self, record: logging.LogRecord) -> str:
        cid = correlation_id_var.get()
        cid_str = f" [{cid[:8]}]" if cid else ""
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        msg = f"{ts} {record.levelname:<8}{cid_str} {record.name}: {record.getMessage()}"
        if record.exc_info and record.exc_info[1]:
            msg += f"\n  Exception: {record.exc_info[1]}"
        return msg


def setup_logging(log_level: str = "INFO", log_format: str = "json", log_file: Optional[str] = None) -> None:
    """Configure application logging.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_format: Output format - 'json' for structured, 'text' for human-readable.
        log_file: Optional file path. None for stdout only.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Choose formatter
    formatter: logging.Formatter
    if log_format == "json":
        formatter = StructuredFormatter()
    else:
        formatter = TextFormatter()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Optional file handler
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(StructuredFormatter())  # Always JSON for files
        root_logger.addHandler(file_handler)

    # Quiet noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger instance."""
    return logging.getLogger(f"workflow_engine.{name}")


class LogContext:
    """Context manager that sets correlation/session/user context vars for logging."""

    def __init__(
        self,
        correlation_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ):
        self._cid = correlation_id or generate_correlation_id()
        self._sid = session_id
        self._uid = user_id
        self._tokens: list = []

    def __enter__(self):
        self._tokens.append(correlation_id_var.set(self._cid))
        if self._sid:
            self._tokens.append(session_id_var.set(self._sid))
        if self._uid:
            self._tokens.append(user_id_var.set(self._uid))
        return self

    def __exit__(self, *args):
        for token in self._tokens:
            # Reset is not available in all Python versions; use set with default
            try:
                token.var.reset(token)
            except Exception:
                pass
