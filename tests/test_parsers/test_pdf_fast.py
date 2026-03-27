"""Tests for PDF fast (PyMuPDF) extraction."""

import pytest

from file_parse_engine.parsers.pdf import PDFParser


@pytest.mark.asyncio
class TestPDFFastExtraction:
    """Test the direct (fast / zero-cost) PDF extraction path."""

    async def test_extract_simple_pdf(self, tmp_path):
        """Create a minimal PDF with text and verify extraction."""
        import fitz

        pdf_path = tmp_path / "simple.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Hello World", fontsize=24)
        page.insert_text((72, 120), "This is body text.", fontsize=12)
        doc.save(str(pdf_path))
        doc.close()

        parser = PDFParser()
        result = await parser.to_markdown_direct(pdf_path)

        assert result.file_type == "pdf"
        assert result.page_count == 1
        md = result.to_markdown()
        assert "Hello World" in md
        assert "body text" in md

    async def test_extract_multi_page(self, tmp_path):
        import fitz

        pdf_path = tmp_path / "multi.pdf"
        doc = fitz.open()
        for i in range(3):
            page = doc.new_page()
            page.insert_text((72, 72), f"Page {i + 1} content", fontsize=12)
        doc.save(str(pdf_path))
        doc.close()

        parser = PDFParser()
        result = await parser.to_markdown_direct(pdf_path)

        assert result.page_count == 3
        md = result.to_markdown()
        assert "Page 1" in md
        assert "Page 3" in md

    async def test_provider_is_pymupdf(self, tmp_path):
        import fitz

        pdf_path = tmp_path / "prov.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Test", fontsize=12)
        doc.save(str(pdf_path))
        doc.close()

        parser = PDFParser()
        result = await parser.to_markdown_direct(pdf_path)
        assert result.pages[0].provider == "pymupdf"

    async def test_metadata(self, tmp_path):
        import fitz

        pdf_path = tmp_path / "meta.pdf"
        doc = fitz.open()
        doc.new_page()
        doc.set_metadata({"title": "Test Title", "author": "Tester"})
        doc.save(str(pdf_path))
        doc.close()

        parser = PDFParser()
        meta = parser.extract_metadata(pdf_path)
        assert meta["title"] == "Test Title"
        assert meta["author"] == "Tester"
        assert meta["page_count"] == 1


class TestPDFTableToMarkdown:
    """Test the static table-to-markdown helper."""

    def test_basic_table(self):
        """Simulate a PyMuPDF table object."""

        class FakeTable:
            bbox = (0, 0, 100, 100)

            def extract(self):
                return [
                    ["Name", "Age"],
                    ["Alice", "30"],
                    ["Bob", "25"],
                ]

        md = PDFParser._table_to_md(FakeTable())
        assert "| Name | Age |" in md
        assert "| --- | --- |" in md
        assert "| Alice | 30 |" in md


class TestPDFHeadingDetection:
    """Test font-size-based heading detection."""

    def test_thresholds_uniform_sizes(self):
        """All same size → no headings detected."""
        sizes = [12.0, 12.0, 12.0, 12.0]
        thresholds = PDFParser._heading_thresholds(sizes)
        assert thresholds == {}

    def test_thresholds_varied_sizes(self):
        sizes = [12.0, 12.0, 12.0, 12.0, 24.0, 18.0]
        thresholds = PDFParser._heading_thresholds(sizes)
        assert 1 in thresholds
        assert 2 in thresholds
        assert 3 in thresholds
        assert thresholds[1] > thresholds[2] > thresholds[3]

    def test_empty_sizes(self):
        assert PDFParser._heading_thresholds([]) == {}
