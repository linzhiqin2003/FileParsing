"""Core data models for the parsing pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PageImage:
    """A rendered page image ready for VLM extraction."""

    page_number: int
    image_bytes: bytes
    width: int
    height: int

    @property
    def size_kb(self) -> float:
        return len(self.image_bytes) / 1024


@dataclass
class VisualElement:
    """A visual element (image / table / figure) extracted during hybrid parsing.

    The parser produces these with a ``placeholder_id`` embedded in the page
    markdown.  The engine sends ``image_bytes`` to a VLM and replaces the
    placeholder with the returned description.
    """

    page_number: int
    element_type: str  # "image" | "table" | "figure"
    image_bytes: bytes
    placeholder_id: str  # unique marker in the markdown, e.g. <!-- FPE_IMG:p1_0 -->
    description: str = ""  # filled by VLM later


@dataclass
class VLMUsage:
    """Token usage and cost for a single VLM API call."""

    input_tokens: int = 0
    output_tokens: int = 0
    input_price: float = 0.0   # $/M tokens
    output_price: float = 0.0  # $/M tokens

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def estimated_cost(self) -> float:
        """Estimated cost in USD."""
        return (
            self.input_tokens * self.input_price
            + self.output_tokens * self.output_price
        ) / 1_000_000


@dataclass
class ParsedPage:
    """Extraction result for a single page."""

    page_number: int
    markdown: str
    provider: str = ""


@dataclass
class ParsedDocument:
    """Complete parsing result for a document."""

    source_path: str
    file_type: str
    pages: list[ParsedPage] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def to_markdown(self, *, page_tags: bool | None = None) -> str:
        """Assemble all pages into a single Markdown string.

        Args:
            page_tags: Insert ``<!-- page:N -->`` comments. If None, reads
                       from metadata (set by engine from Settings).
        """
        if page_tags is None:
            page_tags = self.metadata.get("_page_tags", False)
        from file_parse_engine.renderer.markdown import merge_cross_page_tables

        parts: list[str] = []

        for page in sorted(self.pages, key=lambda p: p.page_number):
            content = page.markdown.strip()
            if content:
                if page_tags:
                    parts.append(f"<!-- page:{page.page_number} -->\n{content}")
                else:
                    parts.append(content)

        # Merge cross-page tables
        parts = merge_cross_page_tables(parts)

        separator = "\n\n" if page_tags else "\n\n---\n\n"
        return separator.join(p for p in parts if p.strip())

    def save(self, output_dir: str | Path, *, page_tags: bool | None = None) -> Path:
        """Save the assembled Markdown to a file (atomic write)."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        source = Path(self.source_path)
        output_file = output_dir / f"{source.stem}.md"

        # Atomic write: write to temp file first, then rename
        # Prevents half-written files from being treated as checkpoints
        tmp_file = output_file.with_suffix(".md.tmp")
        tmp_file.write_text(self.to_markdown(page_tags=page_tags), encoding="utf-8")
        tmp_file.rename(output_file)
        return output_file
