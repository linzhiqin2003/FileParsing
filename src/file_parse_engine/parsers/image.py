"""Image parser — sends images directly to VLM or returns placeholder in fast mode."""

from __future__ import annotations

from pathlib import Path

from file_parse_engine.models import PageImage, ParsedDocument, ParsedPage
from file_parse_engine.parsers import register
from file_parse_engine.parsers.base import BaseParser
from file_parse_engine.utils.image import to_png_bytes
from file_parse_engine.utils.logger import get_logger

logger = get_logger("parsers.image")


@register("png", "jpg", "jpeg", "tiff", "tif", "bmp", "webp")
class ImageParser(BaseParser):
    """Image parser: VLM extraction or basic placeholder for fast mode."""

    file_type = "image"

    async def to_page_images(self, path: Path) -> list[PageImage]:
        raw = path.read_bytes()
        png_bytes, width, height = to_png_bytes(raw)

        logger.info("Image: %s (%dx%d, %.1fKB)", path.name, width, height, len(png_bytes) / 1024)

        return [PageImage(
            page_number=1,
            image_bytes=png_bytes,
            width=width,
            height=height,
        )]

    async def to_markdown_direct(self, path: Path) -> ParsedDocument:
        """Fast mode: return an image reference without VLM description."""
        meta = self.extract_metadata(path)
        desc = f"{path.name} ({meta.get('width', '?')}x{meta.get('height', '?')}, {meta.get('format', '?')})"
        return ParsedDocument(
            source_path=str(path),
            file_type="image",
            pages=[ParsedPage(
                page_number=1,
                markdown=f"![{desc}]({path.name})",
                provider="local",
            )],
        )

    def extract_metadata(self, path: Path) -> dict:
        from PIL import Image as PILImage

        img = PILImage.open(path)
        return {
            "format": img.format or path.suffix.upper().lstrip("."),
            "width": img.width,
            "height": img.height,
            "mode": img.mode,
        }
