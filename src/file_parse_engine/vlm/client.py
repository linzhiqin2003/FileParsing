"""Unified VLM client with route-based provider selection, concurrency control, and cost tracking."""

from __future__ import annotations

import asyncio

from file_parse_engine.config import Settings, get_settings
from file_parse_engine.models import PageImage, ParsedPage, VLMUsage
from file_parse_engine.utils.logger import get_logger
from file_parse_engine.vlm.providers import VLMError, VLMProvider
from file_parse_engine.vlm.routes import RouteConfig, load_routes

logger = get_logger("vlm.client")


class VLMClient:
    """Unified VLM client with primary / fallback provider, rate limiting, and cost tracking."""

    def __init__(
        self,
        primary: VLMProvider,
        fallback: VLMProvider | None = None,
        *,
        concurrency: int = 5,
        timeout: int = 60,
    ):
        self.primary = primary
        self.fallback = fallback
        self.timeout = timeout
        self._semaphore = asyncio.Semaphore(concurrency)
        self._usage_log: list[VLMUsage] = []

    # -- usage properties -------------------------------------------

    @property
    def total_input_tokens(self) -> int:
        return sum(u.input_tokens for u in self._usage_log)

    @property
    def total_output_tokens(self) -> int:
        return sum(u.output_tokens for u in self._usage_log)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def total_cost(self) -> float:
        """Estimated total cost in USD (summed per-request to handle mixed pricing)."""
        return sum(u.estimated_cost for u in self._usage_log)

    @property
    def request_count(self) -> int:
        return len(self._usage_log)

    def reset_usage(self) -> None:
        self._usage_log.clear()

    # -- extraction -------------------------------------------------

    async def extract_page(self, page: PageImage, prompt: str) -> ParsedPage:
        """Extract content from a single page image with rate limiting and failover."""
        async with self._semaphore:
            provider_used = self.primary.name
            try:
                logger.debug(
                    "Extracting page %d (%.1fKB) via %s",
                    page.page_number, page.size_kb, self.primary.name,
                )
                text, usage = await self.primary.extract(
                    page.image_bytes, prompt, timeout=self.timeout,
                )
            except VLMError as exc:
                if self.fallback is None:
                    raise

                logger.warning(
                    "Primary [%s] failed for page %d: %s — falling back to [%s]",
                    self.primary.name, page.page_number, exc, self.fallback.name,
                )
                provider_used = self.fallback.name
                text, usage = await self.fallback.extract(
                    page.image_bytes, prompt, timeout=self.timeout,
                )

            self._usage_log.append(usage)

            logger.debug(
                "Page %d extracted via %s (%d chars, %d tokens)",
                page.page_number, provider_used, len(text), usage.total_tokens,
            )
            return ParsedPage(
                page_number=page.page_number,
                markdown=text,
                provider=provider_used,
            )

    async def extract_multi_page(
        self, pages: list[PageImage], prompt: str,
    ) -> list[ParsedPage]:
        """Send multiple page images in a single VLM request.

        Returns one ParsedPage per page, split by page markers in the output.
        """
        async with self._semaphore:
            provider_used = self.primary.name
            images = [p.image_bytes for p in pages]
            try:
                text, usage = await self.primary.extract(
                    images, prompt, timeout=self.timeout,
                )
            except VLMError as exc:
                if self.fallback is None:
                    raise
                provider_used = self.fallback.name
                text, usage = await self.fallback.extract(
                    images, prompt, timeout=self.timeout,
                )

            self._usage_log.append(usage)

        # Split output by page separator (--- or explicit page markers)
        import re
        parts = re.split(r"\n---+\s*\n", text)

        results: list[ParsedPage] = []
        for i, page in enumerate(pages):
            md = parts[i].strip() if i < len(parts) else ""
            results.append(ParsedPage(
                page_number=page.page_number,
                markdown=md,
                provider=provider_used,
            ))

        return results

    async def extract_pages(
        self,
        pages: list[PageImage],
        prompt: str,
        *,
        on_page: callable | None = None,
    ) -> list[ParsedPage]:
        """Extract content from multiple pages concurrently.

        Args:
            on_page: Optional callback ``(page_number, total_pages)`` called
                     after each page completes.
        """
        total = len(pages)
        completed = 0

        async def _extract_and_report(page: PageImage) -> ParsedPage:
            nonlocal completed
            result = await self.extract_page(page, prompt)
            completed += 1
            if on_page:
                on_page(completed, total)
            return result

        tasks = [_extract_and_report(page) for page in pages]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        parsed: list[ParsedPage] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("Failed to extract page %d: %s", pages[i].page_number, result)
                parsed.append(ParsedPage(
                    page_number=pages[i].page_number,
                    markdown=f"<!-- Extraction failed: {result} -->",
                    provider="error",
                ))
            else:
                parsed.append(result)

        return sorted(parsed, key=lambda p: p.page_number)

    async def extract_pages_with_prompts(
        self,
        pages: list[PageImage],
        prompts: list[str],
        *,
        on_page: callable | None = None,
    ) -> list[ParsedPage]:
        """Extract pages with per-page prompts (e.g. for image numbering hints)."""
        total = len(pages)
        completed = 0

        async def _extract_and_report(page: PageImage, prompt: str) -> ParsedPage:
            nonlocal completed
            result = await self.extract_page(page, prompt)
            completed += 1
            if on_page:
                on_page(completed, total)
            return result

        tasks = [_extract_and_report(p, pr) for p, pr in zip(pages, prompts)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        parsed: list[ParsedPage] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("Failed to extract page %d: %s", pages[i].page_number, result)
                parsed.append(ParsedPage(
                    page_number=pages[i].page_number,
                    markdown=f"<!-- Extraction failed: {result} -->",
                    provider="error",
                ))
            else:
                parsed.append(result)

        return sorted(parsed, key=lambda p: p.page_number)


# ------------------------------------------------------------------
# Factory
# ------------------------------------------------------------------

def _build_provider(routes: RouteConfig, model_name: str) -> VLMProvider | None:
    """Create a :class:`VLMProvider` from route config for *model_name*."""
    model = routes.models.get(model_name)
    if model is None:
        return None

    prov_cfg = routes.get_provider_for_model(model)
    if prov_cfg is None or not prov_cfg.is_configured:
        return None

    return VLMProvider(
        name=f"{prov_cfg.name}/{model.name}",
        api_key=prov_cfg.api_key,
        model=model.model_id,
        base_url=prov_cfg.base_url,
        max_tokens=model.max_tokens,
        temperature=model.temperature,
        input_price=model.input_price,
        output_price=model.output_price,
    )


def create_vlm_client(settings: Settings | None = None) -> VLMClient:
    """Factory: build a :class:`VLMClient` from routes YAML + env settings."""
    if settings is None:
        settings = get_settings()

    routes = load_routes(settings.vlm_routes_file)

    # CLI --model override: use specified model as primary, no fallback
    if settings.vlm_model_override:
        override = settings.vlm_model_override
        primary = _build_provider(routes, override)
        if primary is None:
            available = ", ".join(routes.models.keys())
            raise ValueError(
                f"Model '{override}' not found or not configured.\n"
                f"Available models: {available}"
            )
        return VLMClient(
            primary=primary,
            fallback=None,
            concurrency=settings.vlm_concurrency,
            timeout=settings.vlm_timeout,
        )

    # Default: use routes primary/fallback
    primary = _build_provider(routes, routes.primary)
    fallback = _build_provider(routes, routes.fallback) if routes.fallback else None

    # If primary is unavailable, promote fallback
    if primary is None:
        if fallback is not None:
            logger.warning("Primary provider not configured, promoting fallback")
            primary = fallback
            fallback = None
        else:
            raise ValueError(
                "No VLM provider configured.  "
                "Set the required API key env var (see vlm_routes.yaml)."
            )

    return VLMClient(
        primary=primary,
        fallback=fallback,
        concurrency=settings.vlm_concurrency,
        timeout=settings.vlm_timeout,
    )
