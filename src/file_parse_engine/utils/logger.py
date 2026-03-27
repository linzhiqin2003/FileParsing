"""Structured logging configuration."""

from __future__ import annotations

import logging
import sys

from rich.logging import RichHandler

_configured = False


def setup_logging(level: int = logging.INFO, *, verbose: bool = False) -> None:
    """Configure structured logging with Rich handler."""
    global _configured
    if _configured:
        return

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

    # Suppress noisy third-party loggers
    for name in ("httpx", "httpcore", "pymupdf"):
        logging.getLogger(name).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Get a logger scoped under the package namespace."""
    return logging.getLogger(f"file_parse_engine.{name}")
