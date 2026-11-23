"""Logging with credential redaction.

Every record passes through :class:`RedactingFilter`, which masks Groq keys,
SerpAPI keys, ``api_key=`` query parameters, bearer tokens and any secret value
registered at runtime.
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_PATTERNS = [
    re.compile(r"gsk_[A-Za-z0-9]{10,}"),
    re.compile(r"(?i)(api_key=)[^&\s'\"]+"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"),
    re.compile(r"\b[a-f0-9]{64}\b"),
    re.compile(r"((?:postgres|postgresql)(?:\+\w+)?://[^:/@\s]+:)[^@\s]+(?=@)"),
]
_registered_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    if value and len(value) >= 8:
        _registered_secrets.add(value)


def redact(text: str) -> str:
    for secret in _registered_secrets:
        if secret in text:
            text = text.replace(secret, "***REDACTED***")
    for pattern in _PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda m: m.group(1) + "***REDACTED***", text)
        else:
            text = pattern.sub("***REDACTED***", text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        record.msg = redact(message)
        record.args = None
        if record.exc_info and record.exc_info[1] is not None:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


_configured = False


def configure_logging(level: str = "INFO", logs_dir: Path | None = None) -> None:
    global _configured
    root = logging.getLogger("shogun")
    root.setLevel(level)
    if _configured:
        return
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    stream.addFilter(RedactingFilter())
    root.addHandler(stream)
    if logs_dir is not None:
        try:
            logs_dir.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                logs_dir / "shogun.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            )
            file_handler.setFormatter(fmt)
            file_handler.addFilter(RedactingFilter())
            root.addHandler(file_handler)
        except OSError:  # pragma: no cover - read-only FS
            root.warning("File logging unavailable; continuing with console logging only")
    root.propagate = False
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"shogun.{name}")
