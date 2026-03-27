"""RTF parser — extracts plain text via striprtf."""

from __future__ import annotations

from pathlib import Path

from file_parse_engine.models import ParsedDocument, ParsedPage
from file_parse_engine.parsers import register
from file_parse_engine.parsers.base import BaseParser
from file_parse_engine.utils.logger import get_logger

logger = get_logger("parsers.rtf")


@register("rtf")
class RTFParser(BaseParser):
    """RTF parser: striprtf extracts plain text → Markdown."""

    file_type = "rtf"

    @property
    def needs_vlm(self) -> bool:
        return False

    async def to_markdown_direct(self, path: Path) -> ParsedDocument:
        from striprtf.striprtf import rtf_to_text

        raw = path.read_text(encoding="utf-8", errors="replace")
        text = rtf_to_text(raw)

        logger.info("RTF: %s (%d chars)", path.name, len(text))

        return ParsedDocument(
            source_path=str(path),
            file_type="rtf",
            pages=[ParsedPage(page_number=1, markdown=text)],
        )

    def extract_metadata(self, path: Path) -> dict:
        stat = path.stat()
        return {"size_bytes": stat.st_size}
