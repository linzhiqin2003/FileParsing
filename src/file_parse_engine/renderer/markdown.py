"""Markdown post-processing and cleanup."""

from __future__ import annotations

import re


def clean_markdown(text: str) -> str:
    """Post-process VLM output to produce clean Markdown."""
    # Strip markdown code fences that some VLMs wrap output in
    text = _strip_code_fences(text)

    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Collapse excessive blank lines (3+ → 2)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Strip trailing whitespace per line
    text = "\n".join(line.rstrip() for line in text.split("\n"))

    # Ensure single trailing newline
    text = text.strip() + "\n"

    return text


def _strip_code_fences(text: str) -> str:
    """Remove wrapping ```markdown ... ``` fences if present."""
    text = text.strip()

    # Pattern: ```markdown\n...\n``` or ```\n...\n```
    pattern = r"^```(?:markdown|md)?\s*\n(.*?)```\s*$"
    match = re.match(pattern, text, re.DOTALL)
    if match:
        return match.group(1)

    return text


def assemble_pages(page_markdowns: list[str], *, separator: str = "\n\n---\n\n") -> str:
    """Assemble multiple page markdowns into a single document."""
    cleaned = [clean_markdown(md) for md in page_markdowns if md.strip()]
    return separator.join(cleaned)


# ------------------------------------------------------------------
# Cross-page table merging
# ------------------------------------------------------------------

_TABLE_CONTINUES = re.compile(r"<!--\s*TABLE_CONTINUES\s*:\s*columns\s*=\s*(\d+)\s*-->")
_TABLE_CONTINUED = re.compile(r"<!--\s*TABLE_CONTINUED\s*:\s*columns\s*=\s*(\d+)\s*-->")
_TABLE_ROW = re.compile(r"^\|.+\|$")
_TABLE_SEP = re.compile(r"^\|[\s\-:|]+\|$")


def merge_cross_page_tables(pages: list[str]) -> list[str]:
    """Merge tables that span across adjacent pages.

    Detects ``<!-- TABLE_CONTINUES:columns=N -->`` at page end and
    ``<!-- TABLE_CONTINUED:columns=N -->`` at next page start.
    When column counts match, merges the tables by appending data rows
    and removing duplicate headers.

    Also applies heuristic merging for fast/ocr output (no VLM markers):
    if page N ends with a table and page N+1 starts with a table of the
    same column count, merge them.
    """
    if len(pages) < 2:
        return pages

    result = list(pages)  # work on a copy

    i = 0
    while i < len(result) - 1:
        merged = _try_merge_pair(result[i], result[i + 1])
        if merged is not None:
            result[i], result[i + 1] = merged
            # Remove empty pages created by merge (table fully consumed)
            if not result[i + 1].strip():
                result.pop(i + 1)
            # Don't advance — the merged page might chain with the next
        else:
            i += 1

    return result


def _try_merge_pair(page_a: str, page_b: str) -> tuple[str, str] | None:
    """Try to merge a table spanning page_a → page_b.

    Returns ``(new_page_a, new_page_b)`` if merged, else ``None``.
    """
    # --- VLM marker-based detection ---
    # Either marker present → attempt merge (don't require both)
    cont_match = _TABLE_CONTINUES.search(page_a)
    contd_match = _TABLE_CONTINUED.search(page_b)

    if cont_match or contd_match:
        # If both present, validate column count
        if cont_match and contd_match:
            cols_a = int(cont_match.group(1))
            cols_b = int(contd_match.group(1))
            if cols_a != cols_b:
                return None  # column mismatch → don't merge
        return _merge_with_markers(page_a, page_b, cont_match, contd_match)

    # --- Heuristic detection (fast/ocr, no markers) ---
    return _merge_heuristic(page_a, page_b)


def _merge_with_markers(
    page_a: str,
    page_b: str,
    cont_match: re.Match | None,
    contd_match: re.Match | None,
) -> tuple[str, str]:
    """Merge tables using VLM-emitted markers (either or both may be present)."""
    # Remove the CONTINUES marker from page_a (if present)
    a_text = page_a[:cont_match.start()].rstrip() if cont_match else page_a.rstrip()

    # Split page_b at the CONTINUED marker (if present)
    b_after_marker = page_b[contd_match.end():].lstrip("\n") if contd_match else page_b.lstrip("\n")

    # Extract the continuation table rows from page_b
    cont_lines = b_after_marker.split("\n")
    table_rows: list[str] = []
    rest_lines: list[str] = []
    in_table = True

    trailing_continues = ""  # chain marker for next page

    for line in cont_lines:
        if in_table:
            stripped = line.strip()
            # Check if this is a TABLE_CONTINUES marker (chain to next page)
            if _TABLE_CONTINUES.match(stripped):
                trailing_continues = line  # will be appended to merged_a
                in_table = False
                continue
            if _TABLE_ROW.match(stripped):
                table_rows.append(line)
            elif _TABLE_SEP.match(stripped):
                table_rows.append(line)  # keep separators for header detection
            elif not stripped:
                if table_rows:
                    in_table = False
                    rest_lines.append(line)
            else:
                in_table = False
                rest_lines.append(line)
        else:
            rest_lines.append(line)

    # Remove duplicate header from continuation rows
    table_rows = _remove_duplicate_header(table_rows)

    # Append continuation rows to page_a (+ chain marker if present)
    merged_a = a_text + "\n" + "\n".join(table_rows)
    if trailing_continues:
        merged_a += "\n" + trailing_continues

    # page_b becomes the rest (after the merged table)
    merged_b = "\n".join(rest_lines).strip()

    return merged_a, merged_b


def _merge_heuristic(page_a: str, page_b: str) -> tuple[str, str] | None:
    """Heuristic merge for fast/ocr output without VLM markers.

    Condition: page_a ends with a table, page_b starts with a table,
    same column count.
    """
    a_lines = page_a.rstrip().split("\n")
    b_lines = page_b.lstrip().split("\n")

    # Check page_a ends with table rows
    a_table_end = _find_trailing_table(a_lines)
    if a_table_end is None:
        return None

    # Check page_b starts with table rows
    b_table_start = _find_leading_table(b_lines)
    if b_table_start is None:
        return None

    a_start_idx, a_cols = a_table_end
    b_end_idx, b_cols = b_table_start

    if a_cols != b_cols:
        return None

    # Extract continuation rows, remove duplicate header
    cont_rows = [b_lines[j] for j in range(0, b_end_idx + 1) if _TABLE_ROW.match(b_lines[j].strip())]
    cont_rows = _remove_duplicate_header(cont_rows)

    # Merge
    merged_a = "\n".join(a_lines) + "\n" + "\n".join(cont_rows)
    merged_b = "\n".join(b_lines[b_end_idx + 1:]).strip()

    return merged_a, merged_b


def _find_trailing_table(lines: list[str]) -> tuple[int, int] | None:
    """Find a table at the end of lines. Returns (start_index, column_count) or None."""
    # Walk backwards to find the last table row
    last_table_idx = None
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if _TABLE_ROW.match(stripped) or _TABLE_SEP.match(stripped):
            last_table_idx = i
        elif stripped:  # non-empty non-table line
            break
        # skip blank lines

    if last_table_idx is None:
        return None

    # Count columns from the last table row
    cols = lines[last_table_idx].strip().count("|") - 1
    if cols < 1:
        return None

    return last_table_idx, cols


def _find_leading_table(lines: list[str]) -> tuple[int, int] | None:
    """Find a table at the start of lines. Returns (end_index, column_count) or None."""
    first_table_idx = None
    last_table_idx = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            if first_table_idx is not None:
                break  # blank line after table started → end
            continue

        if _TABLE_ROW.match(stripped) or _TABLE_SEP.match(stripped):
            if first_table_idx is None:
                first_table_idx = i
            last_table_idx = i
        else:
            if first_table_idx is not None:
                break  # non-table line after table → end
            else:
                return None  # non-table content before any table

    if first_table_idx is None or last_table_idx is None:
        return None

    cols = lines[first_table_idx].strip().count("|") - 1
    if cols < 1:
        return None

    return last_table_idx, cols


def _remove_duplicate_header(rows: list[str]) -> list[str]:
    """Remove header + separator if they appear at the start of continuation rows."""
    if len(rows) < 2:
        return rows

    # If second row is a separator (| --- | --- |), it's a header block → remove both
    if _TABLE_SEP.match(rows[1].strip()):
        return rows[2:]

    # If first row looks like a separator, remove just it
    if _TABLE_SEP.match(rows[0].strip()):
        return rows[1:]

    return rows
