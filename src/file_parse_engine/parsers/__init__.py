"""Parser registry — auto-selects parser by file extension."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from file_parse_engine.parsers.base import BaseParser

# Extension → parser class name (lazy import to avoid circular deps)
_REGISTRY: dict[str, str] = {}
_PARSER_CACHE: dict[str, type[BaseParser]] = {}


def register(*extensions: str):
    """Decorator: register a parser class for given file extensions.

    Usage:
        @register(".pdf")
        class PDFParser(BaseParser): ...
    """

    def decorator(cls: type[BaseParser]) -> type[BaseParser]:
        module = cls.__module__
        qualname = cls.__qualname__
        for ext in extensions:
            ext = ext.lower().lstrip(".")
            _REGISTRY[ext] = f"{module}.{qualname}"
            _PARSER_CACHE[ext] = cls
        return cls

    return decorator


def get_parser(file_path: str | Path) -> BaseParser:
    """Get the appropriate parser instance for a file."""
    path = Path(file_path)
    ext = path.suffix.lower().lstrip(".")

    if not ext:
        raise ValueError(f"Cannot determine file type for: {path}")

    if ext not in _PARSER_CACHE:
        raise ValueError(
            f"Unsupported file type: .{ext}\n"
            f"Supported: {', '.join(sorted('.' + e for e in _PARSER_CACHE))}"
        )

    parser_cls = _PARSER_CACHE[ext]
    return parser_cls()


def supported_extensions() -> list[str]:
    """Return all supported file extensions."""
    return sorted(_REGISTRY.keys())


def _ensure_all_parsers_loaded() -> None:
    """Import all parser modules to trigger @register decorators."""
    from file_parse_engine.parsers import (  # noqa: F401
        epub,
        html,
        image,
        office,
        pdf,
        rtf,
        spreadsheet,
        text,
    )


# Auto-load on first import
_ensure_all_parsers_loaded()
