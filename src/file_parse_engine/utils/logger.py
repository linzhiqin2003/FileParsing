"""Structured logging configuration."""

from __future__ import annotations

import logging

_configured = False


def setup_logging(level: int = logging.INFO, *, verbose: bool = False) -> None:
    """Configure structured logging with Rich handler (CLI use).

    Library users can skip this and use standard ``logging`` configuration
    instead — the package logger (``file_parse_engine``) will respect
    whatever handlers they attach.
    """
    global _configured
    if _configured:
        return

    from rich.logging import RichHandler

    log_level = logging.DEBUG if verbose else level

    handler = RichHandler(
        show_time=True,
        show_path=verbose,
        rich_tracebacks=True,
        tracebacks_show_locals=verbose,
        markup=True,
    )
    handler.setLevel(log_level)

    root = logging.getLogger("file_parse_engine")
    root.setLevel(log_level)
    root.addHandler(handler)

    _suppress_noisy_loggers()

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Get a logger scoped under the package namespace."""
    return logging.getLogger(f"file_parse_engine.{name}")


def _suppress_noisy_loggers() -> None:
    """Suppress verbose third-party loggers."""
    for name in ("httpx", "httpcore", "pymupdf"):
        logging.getLogger(name).setLevel(logging.WARNING)


# Always add a NullHandler so library use never triggers
# "No handlers could be found for logger" warnings.
# This is Python logging best practice for libraries.
logging.getLogger("file_parse_engine").addHandler(logging.NullHandler())

# Suppress noisy third-party loggers even without setup_logging()
_suppress_noisy_loggers()
