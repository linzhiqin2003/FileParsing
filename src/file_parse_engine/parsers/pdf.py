"""PDF parser — three extraction strategies powered by PyMuPDF.

Strategies
----------
- **fast**   : Pure PyMuPDF text / table / image-placeholder extraction. Zero cost.
- **hybrid** : PyMuPDF text + send embedded images to VLM for rich descriptions.
- **vlm**    : Render every page to an image and send it to a VLM (original path).
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from statistics import median

import fitz  # PyMuPDF

from file_parse_engine.config import get_settings
from file_parse_engine.models import PageImage, ParsedDocument, ParsedPage, VisualElement
from file_parse_engine.parsers import register
from file_parse_engine.parsers.base import BaseParser
from file_parse_engine.utils.logger import get_logger

logger = get_logger("parsers.pdf")

# Minimum text length per page to consider the page as "text-bearing"
_MIN_TEXT_LEN = 30


def _get_image_y_position(page: fitz.Page, xref: int, fallback_idx: int) -> float:
    """Get the Y-position of an image on the page by matching xref in page blocks."""
    page_dict = page.get_text("dict")
    img_block_idx = 0
    for block in page_dict.get("blocks", []):
        if block.get("type") == 1:  # image block
            if img_block_idx == fallback_idx:
                return block["bbox"][1]  # y0
            img_block_idx += 1
    # Fallback: distribute evenly
    return fallback_idx * 100.0


@register("pdf")
class PDFParser(BaseParser):
    """PDF parser supporting fast / hybrid / vlm strategies."""

    file_type = "pdf"

    # ------------------------------------------------------------------
    # VLM path (strategy="vlm")
    # ------------------------------------------------------------------

    async def to_page_images(self, path: Path) -> list[PageImage]:
        """Render every page to a PNG image for full-VLM extraction."""
        settings = get_settings()
        dpi = settings.image_dpi
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)

        doc = fitz.open(str(path))
        pages: list[PageImage] = []

        logger.debug("Rendering PDF: %s (%d pages, %d DPI)", path.name, len(doc), dpi)

        for idx in range(len(doc)):
            page = doc[idx]
            pix = page.get_pixmap(matrix=matrix)

            buf = io.BytesIO()
            buf.write(pix.tobytes("png"))
            image_bytes = buf.getvalue()

            pages.append(PageImage(
                page_number=idx + 1,
                image_bytes=image_bytes,
                width=pix.width,
                height=pix.height,
            ))
            logger.debug("  Page %d: %dx%d (%.1fKB)", idx + 1, pix.width, pix.height, len(image_bytes) / 1024)

        doc.close()
        return pages

    # ------------------------------------------------------------------
    # Direct path (strategy="fast")
    # ------------------------------------------------------------------

    async def to_markdown_direct(self, path: Path) -> ParsedDocument:
        """Pure-PyMuPDF extraction — zero API cost."""
        doc = fitz.open(str(path))
        pages: list[ParsedPage] = []

        logger.debug("Fast-extracting PDF: %s (%d pages)", path.name, len(doc))

        for idx in range(len(doc)):
            page = doc[idx]
            md = self._extract_page_markdown(page)
            pages.append(ParsedPage(
                page_number=idx + 1,
                markdown=md,
                provider="pymupdf",
            ))

        doc.close()
        return ParsedDocument(
            source_path=str(path),
            file_type="pdf",
            pages=pages,
        )

    # ------------------------------------------------------------------
    # Hybrid helpers — visuals for VLM enrichment
    # ------------------------------------------------------------------

    async def extract_visual_elements(self, path: Path) -> list[VisualElement]:
        """Extract embedded images from the PDF for VLM processing.

        Returns a list of :class:`VisualElement` whose ``placeholder_id``
        values match markers emitted by :meth:`_extract_page_markdown`.
        """
        doc = fitz.open(str(path))
        visuals: list[VisualElement] = []

        for idx in range(len(doc)):
            page = doc[idx]
            page_num = idx + 1

            img_list = page.get_images(full=True)
            for img_idx, img_info in enumerate(img_list):
                xref = img_info[0]
                try:
                    base_image = doc.extract_image(xref)
                    if base_image and base_image.get("image"):
                        image_bytes = base_image["image"]
                        # Convert to PNG if needed
                        if base_image.get("ext", "").lower() not in ("png",):
                            image_bytes = self._to_png(image_bytes)

                        placeholder = f"<!-- FPE_IMG:p{page_num}_{img_idx} -->"
                        visuals.append(VisualElement(
                            page_number=page_num,
                            element_type="image",
                            image_bytes=image_bytes,
                            placeholder_id=placeholder,
                        ))
                except Exception:
                    logger.debug("Failed to extract image xref=%d on page %d", xref, page_num)

        doc.close()
        logger.debug("Extracted %d visual element(s) for hybrid processing", len(visuals))
        return visuals

    # ------------------------------------------------------------------
    # Image export (--extract-images)
    # ------------------------------------------------------------------

    @staticmethod
    def export_images(
        pdf_path: Path,
        output_dir: Path,
    ) -> dict[int, list[tuple[float, str]]]:
        """Extract and save all embedded images from a PDF.

        Returns ``{page_number: [(y_position, relative_path), ...]}``
        where relative_path is relative to output_dir (e.g. ``images/doc_p1_0.png``).
        """
        images_dir = output_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(pdf_path))
        stem = pdf_path.stem
        result: dict[int, list[tuple[float, str]]] = {}

        for idx in range(len(doc)):
            page = doc[idx]
            page_num = idx + 1
            page_images: list[tuple[float, str]] = []

            img_list = page.get_images(full=True)
            for img_idx, img_info in enumerate(img_list):
                xref = img_info[0]
                try:
                    base_image = doc.extract_image(xref)
                    if not base_image or not base_image.get("image"):
                        continue

                    image_bytes = base_image["image"]
                    ext = base_image.get("ext", "png").lower()
                    if ext not in ("png", "jpg", "jpeg"):
                        # Convert to PNG
                        from file_parse_engine.utils.image import to_png_bytes
                        image_bytes, _, _ = to_png_bytes(image_bytes)
                        ext = "png"

                    filename = f"{stem}_p{page_num}_{img_idx}.{ext}"
                    filepath = images_dir / filename
                    filepath.write_bytes(image_bytes)

                    # Get Y-position of this image on the page
                    # Use image bbox from page blocks for position
                    y_pos = _get_image_y_position(page, xref, img_idx)

                    rel_path = f"images/{filename}"
                    page_images.append((y_pos, rel_path))

                except Exception:
                    logger.debug("Failed to export image xref=%d on page %d", xref, page_num)

            if page_images:
                result[page_num] = page_images

        doc.close()
        logger.debug("Exported images: %d page(s) with images", len(result))
        return result

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def extract_metadata(self, path: Path) -> dict:
        doc = fitz.open(str(path))
        meta = doc.metadata or {}
        page_count = len(doc)
        doc.close()

        return {
            "title": meta.get("title", ""),
            "author": meta.get("author", ""),
            "subject": meta.get("subject", ""),
            "creator": meta.get("creator", ""),
            "producer": meta.get("producer", ""),
            "page_count": page_count,
        }

    # ==================================================================
    # Internal helpers
    # ==================================================================

    def _extract_page_markdown(self, page: fitz.Page) -> str:
        """Convert a single PDF page to Markdown using PyMuPDF structures."""
        page_dict = page.get_text("dict", sort=True)

        # --- links ------------------------------------------------
        links = self._extract_link_map(page)

        # --- tables ------------------------------------------------
        tab_finder = page.find_tables()
        tables = list(tab_finder.tables) if tab_finder else []
        table_rects = [fitz.Rect(t.bbox) for t in tables]

        # --- heading detection via font sizes ----------------------
        font_sizes = self._collect_font_sizes(page_dict)
        heading_thresholds = self._heading_thresholds(font_sizes)

        # --- collect elements by vertical position -----------------
        elements: list[tuple[float, str]] = []

        for block in page_dict.get("blocks", []):
            if block["type"] == 1:  # image block
                img_idx = sum(1 for _, t in elements if t.startswith("<!-- FPE_IMG"))
                placeholder = f"<!-- FPE_IMG:p{page.number + 1}_{img_idx} -->"
                elements.append((block["bbox"][1], f"{placeholder}\n\n![Image](image)"))
                continue

            if block["type"] != 0:
                continue

            block_rect = fitz.Rect(block["bbox"])
            if any(block_rect.intersects(tr) for tr in table_rects):
                continue

            md = self._text_block_to_md(block, heading_thresholds, links)
            if md.strip():
                elements.append((block["bbox"][1], md))

        # --- tables ------------------------------------------------
        for table in tables:
            md_table = self._table_to_md(table)
            if md_table.strip():
                elements.append((table.bbox[1], md_table))

        # Sort by vertical position and assemble
        elements.sort(key=lambda x: x[0])
        return "\n\n".join(el[1] for el in elements if el[1].strip())

    # -- font / heading analysis -----------------------------------

    @staticmethod
    def _collect_font_sizes(page_dict: dict) -> list[float]:
        """Collect all font sizes used in text spans."""
        sizes: list[float] = []
        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if text:
                        sizes.append(span["size"])
        return sizes

    @staticmethod
    def _heading_thresholds(font_sizes: list[float]) -> dict[int, float]:
        """Compute font-size thresholds for heading levels 1-3.

        Returns ``{1: min_size_h1, 2: min_size_h2, 3: min_size_h3}``.
        """
        if not font_sizes:
            return {}

        med = median(font_sizes)
        max_size = max(font_sizes)

        # Guard: if all text is the same size → no headings
        if max_size - med < 1.0:
            return {}

        return {
            1: med * 1.8,  # H1 ≈ 1.8× body
            2: med * 1.4,  # H2 ≈ 1.4× body
            3: med * 1.15, # H3 ≈ 1.15× body
        }

    # -- link extraction -------------------------------------------

    @staticmethod
    def _extract_link_map(page: fitz.Page) -> list[tuple[fitz.Rect, str]]:
        """Extract URI links from a page as (rect, uri) pairs."""
        link_map: list[tuple[fitz.Rect, str]] = []
        for link in page.get_links():
            if link.get("kind") == fitz.LINK_URI and link.get("uri"):
                link_map.append((fitz.Rect(link["from"]), link["uri"]))
        return link_map

    @staticmethod
    def extract_page_links(path, page_number: int) -> list[tuple[str, str]]:
        """Extract (anchor_text, uri) pairs for a given page.

        Used by the link enrichment post-processor to inject real URLs
        into VLM/OCR output.
        """
        doc = fitz.open(str(path))
        page = doc[page_number - 1]
        results: list[tuple[str, str]] = []

        for link in page.get_links():
            if link.get("kind") != fitz.LINK_URI or not link.get("uri"):
                continue
            rect = fitz.Rect(link["from"])
            # Slightly expand rect to avoid clipping edge characters
            rect.x0 -= 2
            rect.y0 -= 2
            rect.x1 += 2
            rect.y1 += 2
            anchor = page.get_text("text", clip=rect).strip()
            if anchor:
                # Normalize whitespace (multi-line anchor → single line)
                anchor = " ".join(anchor.split())
                results.append((anchor, link["uri"]))

        doc.close()
        return results

    @staticmethod
    def extract_all_links(path) -> dict[int, list[tuple[str, str]]]:
        """Extract links for ALL pages. Returns {page_number: [(anchor, uri), ...]}."""
        doc = fitz.open(str(path))
        result: dict[int, list[tuple[str, str]]] = {}

        for idx in range(len(doc)):
            page = doc[idx]
            page_links: list[tuple[str, str]] = []

            for link in page.get_links():
                if link.get("kind") != fitz.LINK_URI or not link.get("uri"):
                    continue
                rect = fitz.Rect(link["from"])
                anchor = page.get_text("text", clip=rect).strip()
                if anchor:
                    anchor = " ".join(anchor.split())
                    page_links.append((anchor, link["uri"]))

            if page_links:
                result[idx + 1] = page_links

        doc.close()
        return result

    @staticmethod
    def _find_link_for_span(
        span_rect: fitz.Rect,
        links: list[tuple[fitz.Rect, str]],
    ) -> str | None:
        """Find the URI that covers a text span (by intersection)."""
        for link_rect, uri in links:
            if span_rect.intersects(link_rect):
                return uri
        return None

    # -- text block → markdown -------------------------------------

    @staticmethod
    def _text_block_to_md(
        block: dict,
        thresholds: dict[int, float],
        links: list[tuple[fitz.Rect, str]] | None = None,
    ) -> str:
        """Convert a PyMuPDF text block to Markdown."""
        lines_md: list[str] = []

        for line in block.get("lines", []):
            spans_text: list[str] = []
            line_size = 0.0
            is_bold = False

            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text:
                    continue
                line_size = max(line_size, span["size"])
                flags = span.get("flags", 0)
                bold = bool(flags & (1 << 4))  # bit 4 = bold
                italic = bool(flags & (1 << 1))  # bit 1 = italic
                is_bold = is_bold or bold

                chunk = text
                if bold and italic:
                    chunk = f"***{text.strip()}***"
                elif bold:
                    chunk = f"**{text.strip()}**"
                elif italic:
                    chunk = f"*{text.strip()}*"

                # Check if this span is a hyperlink
                if links:
                    span_rect = fitz.Rect(span["bbox"])
                    uri = PDFParser._find_link_for_span(span_rect, links)
                    if uri:
                        chunk = f"[{chunk}]({uri})"

                spans_text.append(chunk)

            line_text = " ".join(spans_text).strip()
            if not line_text:
                continue

            # Check heading level
            if thresholds:
                for level in (1, 2, 3):
                    if line_size >= thresholds.get(level, 9999):
                        clean = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", line_text)
                        line_text = f"{'#' * level} {clean}"
                        break

            lines_md.append(line_text)

        return "\n".join(lines_md)

    # -- table → markdown ------------------------------------------

    @staticmethod
    def _table_to_md(table) -> str:
        """Convert a PyMuPDF ``Table`` object to a Markdown table."""
        rows = table.extract()
        if not rows:
            return ""

        # Sanitise cell content
        def _cell(val) -> str:
            if val is None:
                return ""
            return str(val).replace("\n", " ").strip()

        header = [_cell(c) for c in rows[0]]
        md_lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join("---" for _ in header) + " |",
        ]
        for row in rows[1:]:
            cells = [_cell(c) for c in row]
            # Pad to header width
            while len(cells) < len(header):
                cells.append("")
            md_lines.append("| " + " | ".join(cells[:len(header)]) + " |")

        return "\n".join(md_lines)

    # -- image conversion ------------------------------------------

    @staticmethod
    def _to_png(image_bytes: bytes) -> bytes:
        """Convert arbitrary image bytes to PNG."""
        from file_parse_engine.utils.image import to_png_bytes
        png, _w, _h = to_png_bytes(image_bytes)
        return png
