"""Tests for engine strategy routing."""

import pytest

from file_parse_engine.config import Settings, reset_settings
from file_parse_engine.engine import FileParseEngine


@pytest.fixture(autouse=True)
def _reset():
    reset_settings()
    yield
    reset_settings()


@pytest.mark.asyncio
class TestFastStrategy:
    """Fast strategy should use direct extraction (no VLM)."""

    async def test_parse_txt_fast(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello from fast strategy")

        settings = Settings(strategy="fast")
        engine = FileParseEngine(settings)

        result = await engine.parse(f)
        assert "Hello from fast strategy" in result.to_markdown()

    async def test_parse_pdf_fast(self, tmp_path):
        import fitz

        pdf_path = tmp_path / "test.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Fast PDF content", fontsize=14)
        doc.save(str(pdf_path))
        doc.close()

        settings = Settings(strategy="fast")
        engine = FileParseEngine(settings)

        result = await engine.parse(pdf_path)
        assert result.page_count == 1
        assert "Fast PDF" in result.to_markdown()
        assert result.pages[0].provider == "pymupdf"

    async def test_parse_csv_fast(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("A,B\n1,2\n3,4")

        settings = Settings(strategy="fast")
        engine = FileParseEngine(settings)

        result = await engine.parse(f)
        md = result.to_markdown()
        assert "A" in md
        assert "|" in md  # table format


@pytest.mark.asyncio
class TestOCRStrategy:
    """OCR strategy routing."""

    async def test_ocr_strategy_accepted(self):
        """Verify 'ocr' is a valid strategy value."""
        settings = Settings(strategy="ocr")
        assert settings.strategy == "ocr"

    async def test_ocr_available_check(self):
        from file_parse_engine.ocr import ocr_available
        assert isinstance(ocr_available(), bool)


@pytest.mark.asyncio
class TestStrategyDefault:
    """Default strategy should be fast."""

    async def test_default_is_fast(self):
        settings = Settings()
        assert settings.strategy == "fast"

    async def test_engine_uses_default(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("default strategy test")

        engine = FileParseEngine(Settings())
        result = await engine.parse(f)
        assert "default strategy" in result.to_markdown()
