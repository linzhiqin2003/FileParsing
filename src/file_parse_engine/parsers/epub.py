"""EPUB parser — extracts HTML chapters via ebooklib, converts to Markdown."""

from __future__ import annotations

from pathlib import Path

from file_parse_engine.models import ParsedDocument, ParsedPage
from file_parse_engine.parsers import register
from file_parse_engine.parsers.base import BaseParser
from file_parse_engine.parsers.html import _html_to_markdown
from file_parse_engine.utils.logger import get_logger

logger = get_logger("parsers.epub")


@register("epub")
class EPUBParser(BaseParser):
    """EPUB parser: ebooklib extracts chapters as HTML → convert to Markdown."""

    file_type = "epub"

    @property
    def needs_vlm(self) -> bool:
        return False

    async def to_markdown_direct(self, path: Path) -> ParsedDocument:
        import ebooklib
        from ebooklib import epub

        book = epub.read_epub(str(path), options={"ignore_ncx": True})
        pages: list[ParsedPage] = []
        chapter_num = 0

        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            html_content = item.get_content().decode("utf-8", errors="replace")
            md = _html_to_markdown(html_content)

            if md.strip():
                chapter_num += 1
                pages.append(ParsedPage(page_number=chapter_num, markdown=md))

        logger.info("EPUB: %s (%d chapter(s))", path.name, len(pages))

        return ParsedDocument(
            source_path=str(path),
            file_type="epub",
            pages=pages,
        )

    def extract_metadata(self, path: Path) -> dict:
        from ebooklib import epub

        book = epub.read_epub(str(path), options={"ignore_ncx": True})

        title = ""
        author = ""
        language = ""

        for meta in book.get_metadata("DC", "title"):
            title = meta[0]
            break
        for meta in book.get_metadata("DC", "creator"):
            author = meta[0]
            break
        for meta in book.get_metadata("DC", "language"):
            language = meta[0]
            break

        return {
            "title": title,
            "author": author,
            "language": language,
        }
