"""Abstract base parser defining the parser interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from file_parse_engine.models import PageImage, ParsedDocument


class BaseParser(ABC):
    """Base class for all file format parsers.

    Each parser implements one of two extraction paths:
    - VLM path: to_page_images() converts file pages to images for VLM extraction
    - Direct path: to_markdown_direct() extracts content without VLM (text, spreadsheets)
    """

    file_type: str = ""

    @property
    def needs_vlm(self) -> bool:
        """Whether this parser requires VLM for content extraction."""
        return True

    async def to_page_images(self, path: Path) -> list[PageImage]:
        """Convert file to a list of page images for VLM extraction.

        Override this for formats that need VLM (PDF, images, Office docs).
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not support VLM extraction path")

    async def to_markdown_direct(self, path: Path) -> ParsedDocument:
        """Extract content directly to Markdown without VLM.

        Override this for formats that don't need VLM (text, spreadsheets).
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not support direct extraction path")

    @abstractmethod
    def extract_metadata(self, path: Path) -> dict:
        """Extract document metadata (title, author, page count, etc.)."""
