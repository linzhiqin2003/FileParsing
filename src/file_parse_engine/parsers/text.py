"""Plain text / Markdown / RST parser — direct passthrough."""

from __future__ import annotations

from pathlib import Path

from file_parse_engine.models import ParsedDocument, ParsedPage
from file_parse_engine.parsers import register
from file_parse_engine.parsers.base import BaseParser
from file_parse_engine.utils.logger import get_logger

logger = get_logger("parsers.text")


@register("txt", "text", "md", "markdown", "rst")
class TextParser(BaseParser):
    """Plain text parser: reads content as-is."""

    file_type = "text"

    @property
    def needs_vlm(self) -> bool:
        return False

    async def to_markdown_direct(self, path: Path) -> ParsedDocument:
        content = path.read_text(encoding="utf-8", errors="replace")
        logger.info("Text: %s (%d chars)", path.name, len(content))

        return ParsedDocument(
            source_path=str(path),
            file_type="text",
            pages=[ParsedPage(page_number=1, markdown=content)],
        )

    def extract_metadata(self, path: Path) -> dict:
        stat = path.stat()
        return {
            "size_bytes": stat.st_size,
            "encoding": "utf-8",
        }
