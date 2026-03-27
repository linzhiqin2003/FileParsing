"""RapidOCR wrapper — local PP-OCRv5 with layout-aware Markdown output.

Uses RapidOCR v3.x + ONNX Runtime to run PP-OCRv5 models locally.
Models are auto-downloaded on first use (~20MB total).
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from PIL import Image

from file_parse_engine.utils.logger import get_logger

logger = get_logger("ocr.engine")

# ------------------------------------------------------------------
# Availability check
# ------------------------------------------------------------------

_OCR_AVAILABLE: bool | None = None


def ocr_available() -> bool:
    """Check whether RapidOCR v3+ is installed and importable."""
    global _OCR_AVAILABLE
    if _OCR_AVAILABLE is None:
        try:
            from rapidocr import RapidOCR  # noqa: F401

            _OCR_AVAILABLE = True
        except ImportError:
            _OCR_AVAILABLE = False
    return _OCR_AVAILABLE


# ------------------------------------------------------------------
# Data structures for layout analysis
# ------------------------------------------------------------------


@dataclass
class TextBlock:
    """A single detected text block with position and content."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float
    text: str
    confidence: float
    height: float = 0.0

    def __post_init__(self) -> None:
        self.height = self.y_max - self.y_min

    @property
    def center_y(self) -> float:
        return (self.y_min + self.y_max) / 2

    @property
    def center_x(self) -> float:
        return (self.x_min + self.x_max) / 2

    @property
    def width(self) -> float:
        return self.x_max - self.x_min


@dataclass
class TextLine:
    """A group of TextBlocks on the same visual line."""

    blocks: list[TextBlock] = field(default_factory=list)

    @property
    def y_min(self) -> float:
        return min(b.y_min for b in self.blocks)

    @property
    def y_max(self) -> float:
        return max(b.y_max for b in self.blocks)

    @property
    def avg_height(self) -> float:
        return sum(b.height for b in self.blocks) / len(self.blocks) if self.blocks else 0

    @property
    def text(self) -> str:
        sorted_blocks = sorted(self.blocks, key=lambda b: b.x_min)
        return " ".join(b.text for b in sorted_blocks)

    @property
    def avg_confidence(self) -> float:
        return sum(b.confidence for b in self.blocks) / len(self.blocks) if self.blocks else 0


# ------------------------------------------------------------------
# OCR Engine (Singleton)
# ------------------------------------------------------------------


class OCREngine:
    """RapidOCR v3 engine with PP-OCRv5 models.

    Singleton pattern — model loading is expensive, reuse across calls.
    Uses ONNX Runtime for inference; models are auto-downloaded on first use.
    """

    _instance: OCREngine | None = None

    def __init__(self) -> None:
        if not ocr_available():
            raise ImportError(
                "RapidOCR is not installed. Install with:\n"
                "  uv pip install 'rapidocr>=3.7' onnxruntime"
            )

        import logging as _logging

        # Suppress RapidOCR's verbose logs BEFORE import triggers model loading
        _rapidocr_logger = _logging.getLogger("RapidOCR")
        _rapidocr_logger.setLevel(_logging.WARNING)
        _rapidocr_logger.propagate = False
        # Also suppress its handlers if any exist
        _rapidocr_logger.handlers.clear()
        _null = _logging.NullHandler()
        _rapidocr_logger.addHandler(_null)

        from rapidocr import OCRVersion, RapidOCR

        logger.debug("Initializing RapidOCR PP-OCRv5 engine...")
        self._ocr = RapidOCR(params={
            "Det.ocr_version": OCRVersion.PPOCRV5,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
        })
        logger.debug("RapidOCR PP-OCRv5 engine ready")

    @classmethod
    def get_instance(cls) -> OCREngine:
        """Get or create the singleton OCR engine."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Release the singleton instance."""
        cls._instance = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_text(self, image_bytes: bytes) -> str:
        """Run OCR on image bytes and return plain text (reading order)."""
        blocks = self._detect(image_bytes)
        lines = self._group_into_lines(blocks)
        return "\n".join(line.text for line in lines)

    def extract_markdown(self, image_bytes: bytes) -> str:
        """Run OCR on image bytes and return layout-aware Markdown."""
        blocks = self._detect(image_bytes)
        if not blocks:
            return ""

        lines = self._group_into_lines(blocks)
        if not lines:
            return ""

        return self._lines_to_markdown(lines)

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def _detect(self, image_bytes: bytes) -> list[TextBlock]:
        """Run RapidOCR PP-OCRv5 and return structured TextBlock list."""
        import numpy as np

        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
        img_array = np.array(img)

        result = self._ocr(img_array)

        blocks: list[TextBlock] = []
        if result.boxes is None or result.txts is None:
            return blocks

        for box, text, score in zip(result.boxes, result.txts, result.scores):
            if not text.strip():
                continue

            # box: ndarray shape (4, 2) — 4 corner points
            xs = [pt[0] for pt in box]
            ys = [pt[1] for pt in box]
            blocks.append(TextBlock(
                x_min=min(xs),
                y_min=min(ys),
                x_max=max(xs),
                y_max=max(ys),
                text=text.strip(),
                confidence=float(score),
            ))

        logger.debug("PP-OCRv5 detected %d text block(s)", len(blocks))
        return blocks

    # ------------------------------------------------------------------
    # Layout analysis
    # ------------------------------------------------------------------

    def _group_into_lines(self, blocks: list[TextBlock]) -> list[TextLine]:
        """Group TextBlocks into visual lines based on vertical overlap."""
        if not blocks:
            return []

        sorted_blocks = sorted(blocks, key=lambda b: b.y_min)

        lines: list[TextLine] = []
        current_line = TextLine(blocks=[sorted_blocks[0]])

        for block in sorted_blocks[1:]:
            prev_center_y = current_line.blocks[-1].center_y
            prev_height = current_line.avg_height
            overlap_threshold = prev_height * 0.5

            if abs(block.center_y - prev_center_y) < overlap_threshold:
                current_line.blocks.append(block)
            else:
                lines.append(current_line)
                current_line = TextLine(blocks=[block])

        lines.append(current_line)
        lines.sort(key=lambda ln: ln.y_min)
        return lines

    def _lines_to_markdown(self, lines: list[TextLine]) -> str:
        """Convert TextLines to Markdown with heading and paragraph detection."""
        if not lines:
            return ""

        heights = [ln.avg_height for ln in lines]
        median_height = sorted(heights)[len(heights) // 2]

        heading_h1 = median_height * 1.8
        heading_h2 = median_height * 1.4
        heading_h3 = median_height * 1.15

        parts: list[str] = []
        prev_y_max = 0.0

        for line in lines:
            text = line.text.strip()
            if not text:
                continue

            gap = line.y_min - prev_y_max
            if prev_y_max > 0 and gap > median_height * 1.5:
                parts.append("")

            h = line.avg_height
            if h >= heading_h1 and len(text) < 100:
                parts.append(f"# {text}")
            elif h >= heading_h2 and len(text) < 100:
                parts.append(f"## {text}")
            elif h >= heading_h3 and len(text) < 100:
                parts.append(f"### {text}")
            else:
                parts.append(text)

            prev_y_max = line.y_max

        return "\n".join(parts)
