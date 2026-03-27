"""Tests for text and CSV parsers."""

import pytest

from file_parse_engine.parsers.text import TextParser
from file_parse_engine.parsers.spreadsheet import CSVParser


@pytest.mark.asyncio
class TestTextParser:

    async def test_parse_txt(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello World\n\nSecond paragraph.")

        parser = TextParser()
        result = await parser.to_markdown_direct(f)

        assert result.file_type == "text"
        assert result.page_count == 1
        assert "Hello World" in result.to_markdown()
        assert "Second paragraph" in result.to_markdown()

    async def test_parse_md(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("# Title\n\n- item 1\n- item 2")

        parser = TextParser()
        result = await parser.to_markdown_direct(f)

        assert "# Title" in result.to_markdown()

    async def test_metadata(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("content")

        parser = TextParser()
        meta = parser.extract_metadata(f)
        assert "size_bytes" in meta


@pytest.mark.asyncio
class TestCSVParser:

    async def test_parse_csv(self, tmp_path):
        f = tmp_path / "test.csv"
        f.write_text("Name,Age,City\nAlice,30,NYC\nBob,25,LA")

        parser = CSVParser()
        result = await parser.to_markdown_direct(f)

        md = result.to_markdown()
        assert "Name" in md
        assert "Alice" in md
        assert "|" in md  # Table format

    async def test_parse_tsv(self, tmp_path):
        f = tmp_path / "test.tsv"
        f.write_text("Col1\tCol2\nA\tB")

        parser = CSVParser()
        result = await parser.to_markdown_direct(f)

        md = result.to_markdown()
        assert "Col1" in md
        assert "A" in md
