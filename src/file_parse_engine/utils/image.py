"""Image processing utilities for VLM preparation."""

from __future__ import annotations

import base64
import io

from PIL import Image

from file_parse_engine.config import get_settings


def resize_if_needed(image_bytes: bytes) -> bytes:
    """Resize image if it exceeds max_size, preserving aspect ratio."""
    settings = get_settings()
    img = Image.open(io.BytesIO(image_bytes))

    max_dim = max(img.width, img.height)
    if max_dim <= settings.image_max_size:
        return image_bytes

    scale = settings.image_max_size / max_dim
    new_w = int(img.width * scale)
    new_h = int(img.height * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def to_png_bytes(image_bytes: bytes) -> tuple[bytes, int, int]:
    """Convert any image format to PNG bytes, return (bytes, width, height)."""
    img = Image.open(io.BytesIO(image_bytes))

    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
    else:
        img = img.convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), img.width, img.height


def to_base64(image_bytes: bytes) -> str:
    """Encode image bytes to base64 string."""
    return base64.b64encode(image_bytes).decode("utf-8")


def get_image_dimensions(image_bytes: bytes) -> tuple[int, int]:
    """Get (width, height) from image bytes."""
    img = Image.open(io.BytesIO(image_bytes))
    return img.width, img.height
