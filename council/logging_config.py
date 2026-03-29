"""
Structured logging configuration for TheCouncil.

Provides JSON-formatted logs with correlation IDs for request tracing.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from typing import Any

# Create a correlation ID for request tracing
_correlation_id: str = ""


def get_correlation_id() -> str:
    """Get or create a correlation ID for the current request."""
    global _correlation_id
    if not _correlation_id:
        _correlation_id = str(uuid.uuid4())[:8]
    return _correlation_id


def set_correlation_id(cid: str) -> None:
    """Set correlation ID for the current request context."""
    global _correlation_id
    _correlation_id = cid


class StructuredFormatter(logging.Formatter):
    """JSON-formatted log output with correlation IDs."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }

        # Add extra fields if present
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


def configure_logging(level: str = "INFO") -> None:
    """Configure structured logging for the application."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create structured console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(StructuredFormatter())
    root_logger.addHandler(console_handler)

    # Suppress verbose third-party logs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("redis").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with structured logging support."""
    return logging.getLogger(name)
