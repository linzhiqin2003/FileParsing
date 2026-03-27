"""Tests for parser registry and format detection."""

from pathlib import Path

import pytest

from file_parse_engine.parsers import get_parser, supported_extensions
from file_parse_engine.parsers.pdf import PDFParser
from file_parse_engine.parsers.image import ImageParser
from file_parse_engine.parsers.office import DOCXParser, PPTXParser
from file_parse_engine.parsers.spreadsheet import XLSXParser, CSVParser
from file_parse_engine.parsers.html import HTMLParser
from file_parse_engine.parsers.text import TextParser
from file_parse_engine.parsers.epub import EPUBParser
from file_parse_engine.parsers.rtf import RTFParser


class TestParserRegistry:
    """Test parser registration and lookup."""

    def test_supported_extensions(self):
        exts = supported_extensions()
        assert "pdf" in exts
        assert "docx" in exts
        assert "png" in exts
        assert "html" in exts
        assert "csv" in exts
        assert "txt" in exts
        assert "epub" in exts
        assert "rtf" in exts

    @pytest.mark.parametrize("ext,parser_cls", [
        ("pdf", PDFParser),
        ("docx", DOCXParser),
        ("pptx", PPTXParser),
        ("xlsx", XLSXParser),
        ("csv", CSVParser),
        ("png", ImageParser),
        ("jpg", ImageParser),
        ("jpeg", ImageParser),
        ("html", HTMLParser),
        ("htm", HTMLParser),
        ("txt", TextParser),
        ("md", TextParser),
        ("epub", EPUBParser),
        ("rtf", RTFParser),
        ("xml", type(get_parser(Path("test.xml")))),
    ])
    def test_get_parser(self, ext, parser_cls):
        parser = get_parser(Path(f"test.{ext}"))
        assert isinstance(parser, parser_cls)

    def test_unsupported_extension(self):
        with pytest.raises(ValueError, match="Unsupported file type"):
            get_parser(Path("test.xyz"))

    def test_no_extension(self):
        with pytest.raises(ValueError, match="Cannot determine"):
            get_parser(Path("noext"))


class TestParserNeedsVLM:
    """Test needs_vlm property for each parser type."""

    def test_text_no_vlm(self):
        assert TextParser().needs_vlm is False

    def test_csv_no_vlm(self):
        assert CSVParser().needs_vlm is False

    def test_xlsx_no_vlm(self):
        assert XLSXParser().needs_vlm is False

    def test_html_no_vlm(self):
        assert HTMLParser().needs_vlm is False

    def test_epub_no_vlm(self):
        assert EPUBParser().needs_vlm is False

    def test_rtf_no_vlm(self):
        assert RTFParser().needs_vlm is False

    def test_pdf_needs_vlm(self):
        assert PDFParser().needs_vlm is True

    def test_image_needs_vlm(self):
        assert ImageParser().needs_vlm is True


class TestParserDirectPath:
    """Verify parsers that support fast (direct) extraction."""

    def test_pdf_has_direct(self):
        parser = PDFParser()
        assert hasattr(parser, "to_markdown_direct")

    def test_image_has_direct(self):
        parser = ImageParser()
        assert hasattr(parser, "to_markdown_direct")
