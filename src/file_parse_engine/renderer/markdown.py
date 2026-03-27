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
