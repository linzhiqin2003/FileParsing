"""Tests for OCR engine layout analysis (no PaddleOCR required)."""

import pytest

from file_parse_engine.ocr.engine import TextBlock, TextLine, OCREngine, ocr_available


class TestTextBlock:
    """Test TextBlock geometry calculations."""

    def test_height(self):
        b = TextBlock(x_min=0, y_min=10, x_max=100, y_max=30, text="hello", confidence=0.95)
        assert b.height == 20

    def test_center(self):
        b = TextBlock(x_min=0, y_min=0, x_max=100, y_max=20, text="test", confidence=0.9)
        assert b.center_y == 10
        assert b.center_x == 50

    def test_width(self):
        b = TextBlock(x_min=10, y_min=0, x_max=60, y_max=20, text="t", confidence=0.9)
        assert b.width == 50


class TestTextLine:
    """Test TextLine grouping and text assembly."""

    def test_text_ordering(self):
        """Blocks should be joined left-to-right."""
        blocks = [
            TextBlock(x_min=200, y_min=0, x_max=300, y_max=20, text="world", confidence=0.9),
            TextBlock(x_min=0, y_min=0, x_max=100, y_max=20, text="hello", confidence=0.9),
        ]
        line = TextLine(blocks=blocks)
        assert line.text == "hello world"

    def test_avg_height(self):
        blocks = [
            TextBlock(x_min=0, y_min=0, x_max=50, y_max=20, text="a", confidence=0.9),
            TextBlock(x_min=60, y_min=0, x_max=100, y_max=30, text="b", confidence=0.9),
        ]
        line = TextLine(blocks=blocks)
        assert line.avg_height == 25.0  # (20 + 30) / 2


class TestLineGrouping:
    """Test _group_into_lines without PaddleOCR dependency."""

    @pytest.fixture
    def engine_cls(self):
        """Return the class to test static/instance methods via mock."""
        return OCREngine

    def test_same_line_grouping(self, engine_cls):
        """Blocks at similar Y positions should group into one line."""
        blocks = [
            TextBlock(x_min=0, y_min=100, x_max=50, y_max=120, text="hello", confidence=0.9),
            TextBlock(x_min=60, y_min=102, x_max=120, y_max=122, text="world", confidence=0.9),
        ]
        # Call the method directly via the unbound function
        lines = OCREngine._group_into_lines(None, blocks)
        assert len(lines) == 1
        assert lines[0].text == "hello world"

    def test_different_lines(self, engine_cls):
        """Blocks at different Y positions should be separate lines."""
        blocks = [
            TextBlock(x_min=0, y_min=0, x_max=100, y_max=20, text="line1", confidence=0.9),
            TextBlock(x_min=0, y_min=100, x_max=100, y_max=120, text="line2", confidence=0.9),
        ]
        lines = OCREngine._group_into_lines(None, blocks)
        assert len(lines) == 2
        assert lines[0].text == "line1"
        assert lines[1].text == "line2"

    def test_empty_blocks(self, engine_cls):
        lines = OCREngine._group_into_lines(None, [])
        assert lines == []


class TestMarkdownConversion:
    """Test _lines_to_markdown heading detection."""

    def test_heading_detection(self):
        """Taller lines should be detected as headings."""
        lines = [
            TextLine(blocks=[TextBlock(0, 0, 200, 40, "Title", 0.9)]),      # h=40 → heading
            TextLine(blocks=[TextBlock(0, 60, 200, 78, "Body text", 0.9)]),  # h=18 → body
            TextLine(blocks=[TextBlock(0, 90, 200, 108, "More text", 0.9)]), # h=18 → body
        ]
        md = OCREngine._lines_to_markdown(None, lines)
        assert md.startswith("# Title") or md.startswith("## Title")
        assert "Body text" in md

    def test_empty_lines(self):
        md = OCREngine._lines_to_markdown(None, [])
        assert md == ""

    def test_paragraph_breaks(self):
        """Large vertical gaps should produce paragraph breaks."""
        lines = [
            TextLine(blocks=[TextBlock(0, 0, 200, 18, "Para 1", 0.9)]),
            TextLine(blocks=[TextBlock(0, 100, 200, 118, "Para 2", 0.9)]),  # big gap
        ]
        md = OCREngine._lines_to_markdown(None, lines)
        assert "\n\n" in md  # paragraph break


class TestOCRAvailability:
    """Test availability check."""

    def test_ocr_available_returns_bool(self):
        result = ocr_available()
        assert isinstance(result, bool)
