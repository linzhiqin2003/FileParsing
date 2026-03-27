"""Core parsing engine — strategy-aware orchestrator."""

from __future__ import annotations

import asyncio
from pathlib import Path

from file_parse_engine.config import ParseStrategy, Settings, get_settings
from file_parse_engine.models import PageImage, ParsedDocument, ParsedPage, VisualElement
from file_parse_engine.parsers import get_parser, supported_extensions
from file_parse_engine.renderer.markdown import clean_markdown
from file_parse_engine.utils.logger import get_logger
from file_parse_engine.vlm.client import VLMClient, create_vlm_client
from file_parse_engine.vlm.prompts import get_prompt

logger = get_logger("engine")


class FileParseEngine:
    """Main parsing engine — also the library API entry point.

    Usage::

        engine = FileParseEngine()
        result = await engine.parse("document.pdf")
        print(result.to_markdown())
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._vlm: VLMClient | None = None

    @property
    def strategy(self) -> ParseStrategy:
        return self.settings.strategy

    @property
    def vlm(self) -> VLMClient:
        """Lazy-init VLM client (only created when first needed)."""
        if self._vlm is None:
            self._vlm = create_vlm_client(self.settings)
        return self._vlm

    def _vlm_available(self) -> bool:
        """Check whether a VLM client can be created without raising."""
        try:
            _ = self.vlm
            return True
        except ValueError:
            return False

    @property
    def vlm_total_cost(self) -> float:
        """Estimated total VLM cost in USD (0.0 if VLM was never used)."""
        return self._vlm.total_cost if self._vlm else 0.0

    @property
    def vlm_total_tokens(self) -> tuple[int, int]:
        """(input_tokens, output_tokens) — (0, 0) if VLM was never used."""
        if self._vlm is None:
            return 0, 0
        return self._vlm.total_input_tokens, self._vlm.total_output_tokens

    @property
    def vlm_request_count(self) -> int:
        return self._vlm.request_count if self._vlm else 0

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def parse(
        self,
        file_path: str | Path,
        *,
        on_page: callable | None = None,
    ) -> ParsedDocument:
        """Parse a single file using the configured strategy.

        Args:
            on_page: Optional callback ``(page_number, total_pages)`` for
                     per-page progress reporting (OCR / VLM strategies).
        """
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        parser = get_parser(path)
        metadata = parser.extract_metadata(path)
        strategy = self.strategy

        logger.debug(
            "Parsing [%s]: %s (parser=%s, strategy=%s)",
            parser.file_type, path.name, parser.__class__.__name__, strategy,
        )

        # Parsers that never need VLM always take the direct path
        # EXCEPT: DOCX/PPTX without LibreOffice + vlm/hybrid → LLM text refine
        if not parser.needs_vlm:
            if (
                strategy in ("vlm", "hybrid")
                and parser.file_type in ("docx", "pptx")
                and self._vlm_available()
            ):
                doc = await self._parse_llm_refine(parser, path)
            else:
                doc = await parser.to_markdown_direct(path)
            doc.metadata = metadata
            for page in doc.pages:
                page.markdown = clean_markdown(page.markdown)
            return doc

        # Strategy-based routing for VLM-capable parsers
        if strategy == "fast":
            doc = await self._parse_fast(parser, path)
        elif strategy == "ocr":
            doc = await self._parse_ocr(parser, path, on_page=on_page)
        elif strategy == "hybrid":
            doc = await self._parse_hybrid(parser, path, on_page=on_page)
        else:  # "vlm"
            doc = await self._parse_vlm(parser, path, on_page=on_page)

        doc.metadata = metadata
        for page in doc.pages:
            page.markdown = clean_markdown(page.markdown)

        # Enrichment passes (PDF only)
        if parser.file_type == "pdf":
            if self.settings.extract_images:
                doc = self._enrich_images(doc, path)
            if self.settings.enrich_links:
                doc = self._enrich_links(doc, path)

        # Store rendering options in metadata for save()/to_markdown()
        doc.metadata["_page_tags"] = self.settings.page_tags

        return doc

    # ------------------------------------------------------------------
    # Link enrichment
    # ------------------------------------------------------------------

    def _enrich_images(self, doc: ParsedDocument, path: Path) -> ParsedDocument:
        """Export embedded PDF images and inject references into Markdown.

        Strategy-specific behavior:
        - **fast**: Replace ``<!-- FPE_IMG:pN_M -->`` placeholders with ``![](images/...)``
        - **vlm**: Match ``![desc](figure)`` markers 1:1 with exported images (by order)
        - **ocr**: Insert ``![](images/...)`` at correct positions using Y-coordinates
        """
        import re
        from file_parse_engine.parsers.pdf import PDFParser

        output_dir = Path(self.settings.output_dir)
        exported = PDFParser.export_images(path, output_dir)
        if not exported:
            return doc

        total_exported = sum(len(v) for v in exported.values())
        logger.debug("Image enrichment: exported %d image(s)", total_exported)

        for page in doc.pages:
            page_imgs = exported.get(page.page_number)
            if not page_imgs:
                continue

            md = page.markdown

            # --- Strategy 1: fast mode placeholders ---
            # Replace <!-- FPE_IMG:pN_M --> ... ![Image](image) with real path
            fpe_pattern = re.compile(
                r"<!-- FPE_IMG:p\d+_(\d+) -->\s*\n*!\[.*?\]\(image\)"
            )
            img_idx = 0
            def _replace_fast_placeholder(m):
                nonlocal img_idx
                if img_idx < len(page_imgs):
                    _, rel_path = page_imgs[img_idx]
                    img_idx += 1
                    return f"![Image]({rel_path})"
                return m.group(0)

            new_md = fpe_pattern.sub(_replace_fast_placeholder, md)

            if new_md != md:
                # fast mode — placeholders replaced
                page.markdown = new_md
                continue

            # --- Strategy 2: VLM mode markers ---
            # Numbered: ![desc](figure_0), ![desc](figure_1) — match by index
            vlm_numbered = re.compile(r"!\[([^\]]*)\]\(figure_(\d+)\)")
            def _replace_vlm_numbered(m):
                desc = m.group(1)
                idx = int(m.group(2))
                if idx < len(page_imgs):
                    _, rel_path = page_imgs[idx]
                    return f"![{desc}]({rel_path})"
                return m.group(0)

            new_md = vlm_numbered.sub(_replace_vlm_numbered, md)

            # Also handle un-numbered ![desc](figure) as fallback (sequential)
            if new_md == md:
                vlm_plain = re.compile(r"!\[([^\]]*)\]\(figure\)")
                _seq_idx = 0
                def _replace_vlm_seq(m):
                    nonlocal _seq_idx
                    desc = m.group(1)
                    if _seq_idx < len(page_imgs):
                        _, rel_path = page_imgs[_seq_idx]
                        _seq_idx += 1
                        return f"![{desc}]({rel_path})"
                    return m.group(0)
                new_md = vlm_plain.sub(_replace_vlm_seq, md)

            if new_md != md:
                page.markdown = new_md
                continue

            # --- Strategy 3: OCR / no markers ---
            # Insert image references at correct positions using Y-coordinates
            # Split markdown into lines, estimate each line's Y-position,
            # then insert image refs at the right gaps
            lines = md.split("\n")
            if not lines:
                continue

            # Estimate line Y-positions (evenly distributed)
            page_height = 842.0  # A4 default
            line_height = page_height / max(len(lines), 1)

            # Build insertion map: line_index → [image_paths]
            insertions: dict[int, list[str]] = {}
            for y_pos, rel_path in page_imgs:
                # Find the line index closest to this Y-position
                target_line = min(
                    int(y_pos / line_height),
                    len(lines) - 1,
                )
                target_line = max(0, target_line)
                insertions.setdefault(target_line, []).append(rel_path)

            # Rebuild markdown with images inserted
            result_lines: list[str] = []
            for i, line in enumerate(lines):
                if i in insertions:
                    for rel_path in insertions[i]:
                        result_lines.append(f"\n![Image]({rel_path})\n")
                result_lines.append(line)

            page.markdown = "\n".join(result_lines)

        return doc

    @staticmethod
    def _enrich_links(doc: ParsedDocument, path: Path) -> ParsedDocument:
        """Inject real PDF hyperlinks into parsed Markdown pages.

        Steps:
        1. Strip any fabricated markdown links from VLM output
        2. Find anchor text in the markdown (fuzzy substring match)
        3. Wrap matched text with real URI
        """
        import re
        from file_parse_engine.parsers.pdf import PDFParser

        all_links = PDFParser.extract_all_links(path)
        if not all_links:
            return doc

        for page in doc.pages:
            page_links = all_links.get(page.page_number)
            if not page_links:
                continue

            md = page.markdown

            # Step 1: strip any fabricated links — [text](url) → text
            md = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", md)

            # Step 2: inject real links by matching anchor text
            for anchor, uri in page_links:
                if len(anchor) < 2:
                    continue

                # Find anchor (or trimmed version) in the markdown
                match_text = anchor
                found_idx = md.find(match_text)

                # If not found, progressively trim edges (PyMuPDF clip imprecision)
                if found_idx == -1:
                    for trim in range(1, min(4, len(anchor) // 2)):
                        candidate = anchor[trim:]
                        if len(candidate) < 3:
                            break
                        found_idx = md.find(candidate)
                        if found_idx != -1:
                            match_text = candidate
                            break

                if found_idx == -1:
                    continue

                # Expand to word boundaries (handles partial clip like "ress@" → "press@")
                start = found_idx
                end = found_idx + len(match_text)
                while start > 0 and md[start - 1] not in " \n\t([*":
                    start -= 1
                while end < len(md) and md[end] not in " \n\t.,;:!?)]*":
                    end += 1
                full_text = md[start:end]

                # Inject link
                md = md[:start] + f"[{full_text}]({uri})" + md[end:]

            page.markdown = md

        logger.debug("Link enrichment: injected links for %d page(s)", len(all_links))
        return doc

    @staticmethod
    def _count_pdf_images_per_page(path: Path) -> dict[int, int]:
        """Count embedded images per page (lightweight, no extraction)."""
        import fitz

        doc = fitz.open(str(path))
        counts: dict[int, int] = {}
        for idx in range(len(doc)):
            page = doc[idx]
            n = len(page.get_images(full=True))
            if n > 0:
                counts[idx + 1] = n
        doc.close()
        return counts

    # ------------------------------------------------------------------
    # Strategy implementations
    # ------------------------------------------------------------------

    async def _parse_fast(self, parser, path: Path) -> ParsedDocument:
        """Fast strategy: pure local extraction, zero API cost."""
        if hasattr(parser, "to_markdown_direct"):
            try:
                return await parser.to_markdown_direct(path)
            except NotImplementedError:
                pass

        # Fallback: return minimal placeholder for formats without direct support
        logger.warning("No direct extraction for %s; returning placeholder", parser.file_type)
        return ParsedDocument(
            source_path=str(path),
            file_type=parser.file_type,
            pages=[ParsedPage(
                page_number=1,
                markdown=f"*[File: {path.name} — direct extraction not supported for this format]*",
                provider="local",
            )],
        )

    async def _parse_llm_refine(self, parser, path: Path) -> ParsedDocument:
        """Extract raw text programmatically, then send to LLM for restructuring.

        Used for DOCX/PPTX when LibreOffice is unavailable but VLM/hybrid
        strategy is requested. Much cheaper than image-based VLM (text-only tokens).
        """
        from file_parse_engine.vlm.prompts import REFINE_DOCUMENT_PROMPT, REFINE_SLIDE_PROMPT

        # Step 1: extract raw text via python-docx/pptx
        doc = await parser.to_markdown_direct(path)

        # Step 2: pick the refine prompt
        refine_prompt = REFINE_SLIDE_PROMPT if parser.file_type == "pptx" else REFINE_DOCUMENT_PROMPT

        # Step 3: send each page's raw text to LLM for restructuring
        for page in doc.pages:
            raw = page.markdown.strip()
            if not raw:
                continue

            refined, _usage = await self.vlm.refine_text(raw, refine_prompt)
            page.markdown = refined
            page.provider = f"{self.vlm.primary.name}/refine"

        return doc

    async def _parse_ocr(
        self,
        parser,
        path: Path,
        on_page: callable | None = None,
    ) -> ParsedDocument:
        """OCR strategy: local PP-OCRv5 extraction, zero API cost.

        Args:
            on_page: Optional callback ``(page_number, total_pages)`` called
                     after each page is processed (for progress display).
        """
        from file_parse_engine.ocr import OCREngine, ocr_available

        if not ocr_available():
            raise ImportError(
                "OCR strategy requires RapidOCR. Install with:\n"
                "  uv pip install 'rapidocr>=3.7' onnxruntime"
            )

        ocr = OCREngine.get_instance()

        page_images = await parser.to_page_images(path)
        total = len(page_images)
        if on_page:
            on_page(0, total)  # init progress bar immediately

        pages: list[ParsedPage] = []
        for page_img in page_images:
            md = ocr.extract_markdown(page_img.image_bytes)
            pages.append(ParsedPage(
                page_number=page_img.page_number,
                markdown=md,
                provider="pp-ocrv5",
            ))
            if on_page:
                on_page(page_img.page_number, total)

        return ParsedDocument(
            source_path=str(path),
            file_type=parser.file_type,
            pages=pages,
        )

    async def _parse_hybrid(
        self,
        parser,
        path: Path,
        on_page: callable | None = None,
    ) -> ParsedDocument:
        """Hybrid strategy: local text + VLM for visual elements."""
        # Step 1: get the direct markdown (same as fast)
        doc = await self._parse_fast(parser, path)

        # Step 2: if the parser can extract visuals, send them to VLM
        if not hasattr(parser, "extract_visual_elements"):
            return doc

        visuals: list[VisualElement] = await parser.extract_visual_elements(path)
        if not visuals:
            return doc

        if not self._vlm_available():
            logger.warning("Hybrid mode: no VLM configured — visual placeholders kept as-is")
            return doc

        # Step 3: send each visual to VLM concurrently
        logger.debug("Hybrid: sending %d visual element(s) to VLM", len(visuals))
        prompt = get_prompt("image")

        page_imgs = [
            PageImage(
                page_number=vis.page_number,
                image_bytes=vis.image_bytes,
                width=0,
                height=0,
            )
            for vis in visuals
        ]
        parsed_results = await self.vlm.extract_pages(page_imgs, prompt, on_page=on_page)

        # Map placeholder_id → description
        for vis, result in zip(visuals, parsed_results):
            vis.description = result.markdown

        # Step 4: replace placeholders in pages
        for page in doc.pages:
            for vis in visuals:
                if vis.page_number == page.page_number and vis.placeholder_id in page.markdown:
                    # Replace the placeholder + its fallback image text
                    old = f"{vis.placeholder_id}\n\n![Image](image)"
                    if old in page.markdown:
                        page.markdown = page.markdown.replace(old, vis.description)
                    else:
                        page.markdown = page.markdown.replace(vis.placeholder_id, vis.description)

        return doc

    async def _parse_vlm(
        self,
        parser,
        path: Path,
        on_page: callable | None = None,
    ) -> ParsedDocument:
        """VLM strategy: full-page rendering → VLM extraction."""
        page_images = await parser.to_page_images(path)
        if on_page:
            on_page(0, len(page_images))  # init progress bar immediately

        from file_parse_engine.vlm.prompts import (
            SNIPPET_CROSS_PAGE_TABLE,
            SNIPPET_IMAGE_NUMBERING,
        )

        base_prompt = get_prompt(parser.file_type)

        # Always inject cross-page table markers for VLM strategy
        # (merge_cross_page_tables() in to_markdown() handles the merge)
        base_prompt += SNIPPET_CROSS_PAGE_TABLE

        # Pre-scan image counts (for -i flag)
        page_image_counts: dict[int, int] = {}
        if self.settings.extract_images and parser.file_type == "pdf":
            page_image_counts = self._count_pdf_images_per_page(path)

        # Build per-page prompts
        prompts: list[str] = []
        for pi in page_images:
            n_imgs = page_image_counts.get(pi.page_number, 0)
            if n_imgs > 0:
                prompts.append(base_prompt + SNIPPET_IMAGE_NUMBERING.format(n_images=n_imgs))
            else:
                prompts.append(base_prompt)

        # Use per-page prompts
        parsed_pages = await self.vlm.extract_pages_with_prompts(
            page_images, prompts, on_page=on_page,
        )

        return ParsedDocument(
            source_path=str(path),
            file_type=parser.file_type,
            pages=parsed_pages,
        )

    # ------------------------------------------------------------------
    # Batch / collect
    # ------------------------------------------------------------------

    async def parse_batch(
        self,
        paths: list[str | Path],
        *,
        max_concurrent_files: int = 3,
    ) -> list[ParsedDocument]:
        """Parse multiple files with controlled concurrency."""
        semaphore = asyncio.Semaphore(max_concurrent_files)

        async def _parse_one(p: str | Path) -> ParsedDocument:
            async with semaphore:
                return await self.parse(p)

        tasks = [_parse_one(p) for p in paths]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        docs: list[ParsedDocument] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("Failed to parse %s: %s", paths[i], result)
            else:
                docs.append(result)

        return docs

    @staticmethod
    def collect_files(
        directory: str | Path,
        *,
        recursive: bool = True,
    ) -> list[Path]:
        """Collect all supported files from a directory."""
        directory = Path(directory)
        exts = supported_extensions()

        files: list[Path] = []
        pattern_fn = directory.rglob if recursive else directory.glob
        for ext in exts:
            files.extend(pattern_fn(f"*.{ext}"))

        return sorted(set(files))
