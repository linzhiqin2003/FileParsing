"""VLM provider — unified OpenAI-compatible API client with usage tracking."""

from __future__ import annotations

import httpx

from file_parse_engine.models import VLMUsage
from file_parse_engine.utils.image import resize_if_needed, to_base64
from file_parse_engine.utils.logger import get_logger
from file_parse_engine.vlm.prompts import SYSTEM_PROMPT

logger = get_logger("vlm.providers")


class VLMError(Exception):
    """Raised when a VLM API call fails."""

    def __init__(self, message: str, provider: str, status_code: int | None = None):
        self.provider = provider
        self.status_code = status_code
        super().__init__(message)


class VLMProvider:
    """Generic VLM provider using the OpenAI-compatible chat/completions API.

    Works with OpenRouter, SiliconFlow, and any other provider that
    exposes the same endpoint shape.
    """

    def __init__(
        self,
        *,
        name: str,
        api_key: str,
        model: str,
        base_url: str,
        max_tokens: int = 8192,
        temperature: float = 0.1,
        input_price: float = 0.0,
        output_price: float = 0.0,
    ):
        self.name = name
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.input_price = input_price
        self.output_price = output_price

    async def extract(
        self,
        image_bytes: bytes | list[bytes],
        prompt: str,
        *,
        timeout: int = 60,
    ) -> tuple[str, VLMUsage]:
        """Send one or more images to the VLM and return (text, usage)."""
        # Support single image or list of images
        if isinstance(image_bytes, list):
            images = image_bytes
        else:
            images = [image_bytes]

        content: list[dict] = []
        for img in images:
            img = resize_if_needed(img)
            b64 = to_base64(img)
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            })
        content.append({"type": "text", "text": prompt})

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            logger.debug(
                "%s request: model=%s, image=%.1fKB",
                self.name, self.model, len(image_bytes) / 1024,
            )
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
            )

            if resp.status_code != 200:
                raise VLMError(
                    f"{self.name} API error: {resp.status_code} - {resp.text}",
                    provider=self.name,
                    status_code=resp.status_code,
                )

            data = resp.json()
            text = data["choices"][0]["message"]["content"]

            # Parse token usage from response (OpenAI-compatible)
            raw_usage = data.get("usage", {})
            usage = VLMUsage(
                input_tokens=raw_usage.get("prompt_tokens", 0),
                output_tokens=raw_usage.get("completion_tokens", 0),
                input_price=self.input_price,
                output_price=self.output_price,
            )

            logger.debug(
                "%s usage: %d in + %d out = %d tokens (~$%.6f)",
                self.name,
                usage.input_tokens,
                usage.output_tokens,
                usage.total_tokens,
                usage.estimated_cost,
            )

            return text, usage

    def __repr__(self) -> str:
        return f"VLMProvider(name={self.name!r}, model={self.model!r})"
