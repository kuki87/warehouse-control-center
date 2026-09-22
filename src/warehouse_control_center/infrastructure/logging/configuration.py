"""Idempotent rotating application logging."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler

from warehouse_control_center.config.settings import Settings

LOGGER_NAME = "warehouse_control_center"
_MANAGED_HANDLER_ATTRIBUTE = "_warehouse_control_center_managed"
_SENSITIVE_KEYS = r"(?:temporary_)?password(?:_hash)?|passwd|secret|token|authorization|api[_-]?key"
_QUOTED_SENSITIVE_VALUE = re.compile(
    rf"(?P<key_quote>['\"]?)(?P<key>\b(?:{_SENSITIVE_KEYS})\b)(?P=key_quote)"
    r"(?P<separator>\s*[:=]\s*)"
    r"(?P<value>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')",
    flags=re.IGNORECASE | re.DOTALL,
)
_AUTHORIZATION_VALUE = re.compile(
    r"(?i)(?P<key>\bauthorization\b)(?P<separator>\s*[:=]\s*)"
    r"(?P<value>(?:bearer|basic)\s+[^\s,;}\]]+)"
)
_UNQUOTED_SENSITIVE_VALUE = re.compile(
    rf"(?i)(?P<key>\b(?:{_SENSITIVE_KEYS})\b)(?P<separator>\s*[:=]\s*)"
    r"(?P<value>[^,;}\]]+)"
)


def _redact(value: str) -> str:
    value = _QUOTED_SENSITIVE_VALUE.sub(
        lambda match: (
            f"{match['key_quote']}{match['key']}{match['key_quote']}"
            f"{match['separator']}{match['value'][0]}<redacted>{match['value'][-1]}"
        ),
        value,
    )
    value = _AUTHORIZATION_VALUE.sub(
        lambda match: f"{match['key']}{match['separator']}<redacted>", value
    )
    return _UNQUOTED_SENSITIVE_VALUE.sub(
        lambda match: f"{match['key']}{match['separator']}<redacted>", value
    )


class RedactingFilter(logging.Filter):
    """Redact common secret assignments as a final defensive layer."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact(record.getMessage())
        record.args = ()
        if record.exc_info is not None:
            record.exc_text = _redact(logging.Formatter().formatException(record.exc_info))
        if record.stack_info is not None:
            record.stack_info = _redact(record.stack_info)
        return True


class UTCFormatter(logging.Formatter):
    """Render unambiguous ISO-8601 UTC log timestamps."""

    def formatTime(
        self,
        record: logging.LogRecord,
        datefmt: str | None = None,
    ) -> str:
        del datefmt
        return datetime.fromtimestamp(record.created, UTC).isoformat(timespec="seconds")


def configure_logging(settings: Settings) -> logging.Logger:
    """Configure one managed rotating handler and return the application logger."""
    settings.log_directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    logger.disabled = False
    logger.setLevel(_log_level(settings.log_level))
    logger.propagate = False
    _remove_managed_handlers(logger)

    handler = RotatingFileHandler(
        settings.log_directory / "app.log",
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    setattr(handler, _MANAGED_HANDLER_ATTRIBUTE, True)
    handler.setLevel(_log_level(settings.log_level))
    handler.setFormatter(UTCFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(RedactingFilter())
    logger.addHandler(handler)
    return logger


def shutdown_logging(logger: logging.Logger) -> None:
    """Flush and close handlers installed by this application."""
    _remove_managed_handlers(logger)


def _remove_managed_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, _MANAGED_HANDLER_ATTRIBUTE, False):
            logger.removeHandler(handler)
            handler.close()


def _log_level(value: str) -> int:
    level = logging.getLevelName(value.upper())
    if not isinstance(level, int):
        raise ValueError(f"Unknown log level: {value}")
    return level
