"""Spreadsheet parsers (XLSX / CSV / TSV) — direct conversion to Markdown tables."""

from __future__ import annotations

import csv
from pathlib import Path

from file_parse_engine.models import ParsedDocument, ParsedPage
from file_parse_engine.parsers import register
from file_parse_engine.parsers.base import BaseParser
from file_parse_engine.utils.logger import get_logger

logger = get_logger("parsers.spreadsheet")


def _rows_to_markdown_table(rows: list[list[str]], *, title: str = "") -> str:
    """Convert a 2D list of strings to a Markdown table."""
    if not rows:
        return ""

    parts: list[str] = []
    if title:
        parts.append(f"## {title}")
        parts.append("")

    # Determine column count from widest row
    col_count = max(len(r) for r in rows)

    # Pad rows to uniform width
    normalized = [r + [""] * (col_count - len(r)) for r in rows]

    # Header (first row)
    header = normalized[0]
    parts.append("| " + " | ".join(header) + " |")
    parts.append("| " + " | ".join("---" for _ in header) + " |")

    # Data rows
    for row in normalized[1:]:
        parts.append("| " + " | ".join(row) + " |")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# XLSX Parser
# ---------------------------------------------------------------------------


@register("xlsx", "xls")
class XLSXParser(BaseParser):
    """XLSX parser: openpyxl → Markdown tables (no VLM needed)."""

    file_type = "xlsx"

    @property
    def needs_vlm(self) -> bool:
        return False

    async def to_markdown_direct(self, path: Path) -> ParsedDocument:
        from openpyxl import load_workbook

        wb = load_workbook(str(path), read_only=True, data_only=True)
        pages: list[ParsedPage] = []

        for sheet_num, sheet_name in enumerate(wb.sheetnames, 1):
            ws = wb[sheet_name]
            rows: list[list[str]] = []

            for row in ws.iter_rows(values_only=True):
                cells = [str(cell) if cell is not None else "" for cell in row]
                # Skip completely empty rows
                if any(c.strip() for c in cells):
                    rows.append(cells)

            if rows:
                md = _rows_to_markdown_table(rows, title=sheet_name)
                pages.append(ParsedPage(page_number=sheet_num, markdown=md))
                logger.debug("Sheet '%s': %d rows", sheet_name, len(rows))

        wb.close()
        logger.info("XLSX: %s (%d sheet(s))", path.name, len(pages))

        return ParsedDocument(
            source_path=str(path),
            file_type="xlsx",
            pages=pages,
        )

    def extract_metadata(self, path: Path) -> dict:
        from openpyxl import load_workbook

        wb = load_workbook(str(path), read_only=True)
        meta = {
            "sheet_names": wb.sheetnames,
            "sheet_count": len(wb.sheetnames),
        }
        wb.close()
        return meta


# ---------------------------------------------------------------------------
# CSV / TSV Parser
# ---------------------------------------------------------------------------


@register("csv", "tsv")
class CSVParser(BaseParser):
    """CSV/TSV parser: direct conversion to Markdown table."""

    file_type = "csv"

    @property
    def needs_vlm(self) -> bool:
        return False

    async def to_markdown_direct(self, path: Path) -> ParsedDocument:
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","

        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f, delimiter=delimiter)
            rows = [row for row in reader if any(cell.strip() for cell in row)]

        md = _rows_to_markdown_table(rows, title=path.stem)
        logger.info("CSV: %s (%d rows)", path.name, len(rows))

        return ParsedDocument(
            source_path=str(path),
            file_type="csv",
            pages=[ParsedPage(page_number=1, markdown=md)],
        )

    def extract_metadata(self, path: Path) -> dict:
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","

        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f, delimiter=delimiter)
            row_count = sum(1 for _ in reader)

        return {"row_count": row_count, "delimiter": delimiter}
