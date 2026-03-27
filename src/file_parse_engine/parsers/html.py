"""HTML/XML parser — extracts main content using readability + BeautifulSoup."""

from __future__ import annotations

import re
from pathlib import Path

from file_parse_engine.models import ParsedDocument, ParsedPage
from file_parse_engine.parsers import register
from file_parse_engine.parsers.base import BaseParser
from file_parse_engine.utils.logger import get_logger

logger = get_logger("parsers.html")


def _html_to_markdown(html: str) -> str:
    """Convert HTML to Markdown using BeautifulSoup tree walking."""
    from bs4 import BeautifulSoup, NavigableString, Tag

    soup = BeautifulSoup(html, "lxml")

    # Remove script, style, nav, footer
    for tag in soup.find_all(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    parts: list[str] = []

    def _walk(element: Tag | NavigableString, depth: int = 0) -> None:
        if isinstance(element, NavigableString):
            text = str(element).strip()
            if text:
                parts.append(text)
            return

        tag_name = element.name

        # Headings
        if tag_name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag_name[1])
            text = element.get_text(strip=True)
            if text:
                parts.append(f"\n{'#' * level} {text}\n")
            return

        # Paragraphs
        if tag_name == "p":
            text = element.get_text(strip=True)
            if text:
                parts.append(f"\n{text}\n")
            return

        # Lists
        if tag_name in ("ul", "ol"):
            for i, li in enumerate(element.find_all("li", recursive=False), 1):
                text = li.get_text(strip=True)
                if text:
                    prefix = f"{i}." if tag_name == "ol" else "-"
                    parts.append(f"{prefix} {text}")
            parts.append("")
            return

        # Tables
        if tag_name == "table":
            rows: list[list[str]] = []
            for tr in element.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if cells:
                    rows.append(cells)

            if rows:
                col_count = max(len(r) for r in rows)
                rows = [r + [""] * (col_count - len(r)) for r in rows]

                parts.append("")
                parts.append("| " + " | ".join(rows[0]) + " |")
                parts.append("| " + " | ".join("---" for _ in rows[0]) + " |")
                for row in rows[1:]:
                    parts.append("| " + " | ".join(row) + " |")
                parts.append("")
            return

        # Pre/code blocks
        if tag_name == "pre":
            code = element.get_text()
            parts.append(f"\n```\n{code}\n```\n")
            return

        # Images
        if tag_name == "img":
            alt = element.get("alt", "image")
            src = element.get("src", "")
            parts.append(f"![{alt}]({src})")
            return

        # Bold / italic
        if tag_name in ("strong", "b"):
            text = element.get_text(strip=True)
            if text:
                parts.append(f"**{text}**")
            return

        if tag_name in ("em", "i"):
            text = element.get_text(strip=True)
            if text:
                parts.append(f"*{text}*")
            return

        # Links
        if tag_name == "a":
            text = element.get_text(strip=True)
            href = element.get("href", "")
            if text and href:
                parts.append(f"[{text}]({href})")
            elif text:
                parts.append(text)
            return

        # Blockquote
        if tag_name == "blockquote":
            text = element.get_text(strip=True)
            if text:
                lines = text.split("\n")
                parts.append("\n".join(f"> {line}" for line in lines))
            return

        # Horizontal rule
        if tag_name == "hr":
            parts.append("\n---\n")
            return

        # Line break
        if tag_name == "br":
            parts.append("\n")
            return

        # Generic: recurse into children
        for child in element.children:
            _walk(child, depth + 1)

    body = soup.body or soup
    _walk(body)

    result = "\n".join(parts)
    # Collapse excessive blank lines
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


@register("html", "htm", "xhtml")
class HTMLParser(BaseParser):
    """HTML parser: readability extraction + BeautifulSoup → Markdown."""

    file_type = "html"

    @property
    def needs_vlm(self) -> bool:
        return False

    async def to_markdown_direct(self, path: Path) -> ParsedDocument:
        raw_html = path.read_text(encoding="utf-8", errors="replace")

        # Try readability first for article extraction
        try:
            from readability import Document as ReadabilityDoc

            readable = ReadabilityDoc(raw_html)
            title = readable.title()
            content_html = readable.summary()
        except Exception:
            logger.debug("Readability extraction failed, falling back to full HTML")
            title = ""
            content_html = raw_html

        md = _html_to_markdown(content_html)
        if title and not md.startswith(f"# {title}"):
            md = f"# {title}\n\n{md}"

        logger.info("HTML: %s (%d chars → %d chars MD)", path.name, len(raw_html), len(md))

        return ParsedDocument(
            source_path=str(path),
            file_type="html",
            pages=[ParsedPage(page_number=1, markdown=md)],
        )

    def extract_metadata(self, path: Path) -> dict:
        from bs4 import BeautifulSoup

        raw = path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(raw, "lxml")

        title = soup.title.string if soup.title else ""
        meta_desc = ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        if meta_tag and meta_tag.get("content"):
            meta_desc = meta_tag["content"]

        return {"title": title or "", "description": meta_desc}


@register("xml")
class XMLParser(HTMLParser):
    """XML parser: reuses HTML parser logic."""

    file_type = "xml"
