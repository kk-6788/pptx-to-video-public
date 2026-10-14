"""
OpenAI provider — wraps the OpenAI DALL-E image generation API.

Supports:
- Text → Image via DALL-E 3 / DALL-E 2

Configuration
-------------
Set ``OPENAI_API_KEY`` env var or pass ``api_key`` to the constructor.
Optional env vars:

- ``OPENAI_BASE_URL`` (default: ``https://api.openai.com/v1``)
- ``OPENAI_IMAGE_MODEL`` (default: ``dall-e-3``)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from typing import Any, Optional

import httpx

from providers.base import (
    GenerationProvider,
    GenerationResult,
    ProviderCapabilities,
    ProviderCapability,
    ProviderError,
)

logger = logging.getLogger(__name__)

# Defaults
_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_IMAGE_MODEL = "dall-e-3"

_RETRY_MAX = 3
_RETRY_BASE_DELAY = 1.0

# Valid parameters for each model
_DALLE3_SIZES = {"1024x1024", "1792x1024", "1024x1792"}
_DALLE2_SIZES = {"256x256", "512x512", "1024x1024"}
_DALLE3_QUALITY = {"standard", "hd"}
_DALLE3_STYLE = {"vivid", "natural"}


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------


async def _retry_request(coro_factory, label: str) -> httpx.Response:
    """Execute *coro_factory()* with exponential backoff on transient errors."""
    last_exc: Optional[Exception] = None
    for attempt in range(_RETRY_MAX + 1):
        try:
            response = await coro_factory()
            if response.status_code in (429, 500, 502, 503, 504):
                last_exc = ProviderError(
                    f"{label}: {response.status_code} {response.text[:200]}",
                    "openai",
                )
                if attempt < _RETRY_MAX:
                    delay = _RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        "%s returned %d – retrying in %.1fs (attempt %d/%d)",
                        label, response.status_code, delay, attempt + 1, _RETRY_MAX,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise last_exc
            response.raise_for_status()
            return response
        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as exc:
            last_exc = exc
            if attempt < _RETRY_MAX:
                delay = _RETRY_BASE_DELAY * (2**attempt)
                logger.warning("%s network error – retrying %.1fs: %s", label, delay, exc)
                await asyncio.sleep(delay)
                continue
            raise ProviderError(f"{label} network failure: {exc}", "openai") from exc
    assert last_exc is not None
    raise last_exc


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class OpenAIProvider(GenerationProvider):
    """OpenAI DALL-E image generation provider."""

    def __init__(self, api_key: str = "", **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        base_url = kwargs.get("base_url") or os.getenv("OPENAI_BASE_URL", _DEFAULT_BASE_URL)
        self._image_model = kwargs.get("image_model") or os.getenv("OPENAI_IMAGE_MODEL", _DEFAULT_IMAGE_MODEL)

        resolved_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {resolved_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(60.0, connect=15.0),
        )

    @classmethod
    def capabilities(cls) -> ProviderCapabilities:
        return ProviderCapabilities(
            name="openai",
            display_name="OpenAI",
            capabilities={
                ProviderCapability.TEXT_TO_IMAGE,
                ProviderCapability.SYNCHRONOUS,
            },
            default_image_model=_DEFAULT_IMAGE_MODEL,
            default_video_model="",
            supported_image_models=[
                "dall-e-3",
                "dall-e-2",
            ],
            supported_video_models=[],
            max_prompt_length=4000,
            requires_api_key=True,
            configurable_base_url=True,
            description="OpenAI DALL-E 3 / DALL-E 2 image generation. "
            "Supports quality (standard/hd), style (vivid/natural), "
            "and flexible sizes. Does NOT support video generation.",
        )

    # ── Image ──────────────────────────────────────────────────────────

    async def generate_image(
        self,
        prompt: str,
        *,
        model: str = "",
        size: str = "1024x1024",
        quality: str = "standard",
        style: str = "vivid",
        **kwargs: Any,
    ) -> GenerationResult:
        """Generate an image via DALL-E.

        Args:
            prompt: Text description of the desired image.
            model: Model name (``dall-e-3`` or ``dall-e-2``; defaults to configured model).
            size: Output size. DALL-E 3 supports ``1024x1024``, ``1792x1024``, ``1024x1792``.
                  DALL-E 2 supports ``256x256``, ``512x512``, ``1024x1024``.
            quality: DALL-E 3 only — ``standard`` or ``hd``.
            style: DALL-E 3 only — ``vivid`` or ``natural``.
            **kwargs: Additional OpenAI API parameters (e.g. ``user=...``).

        Returns:
            A :class:`GenerationResult` with the image bytes.

        Raises:
            ProviderError: On generation failure.
        """
        model_name = model or self._image_model
        payload: dict[str, Any] = {
            "model": model_name,
            "prompt": prompt,
            "n": 1,
            "size": self._validate_size(model_name, size),
            "response_format": "b64_json",
        }

        # DALL-E 3 supports quality and style; DALL-E 2 does not
        is_dalle3 = model_name == "dall-e-3"
        if is_dalle3:
            payload["quality"] = self._validate_quality(quality)
            payload["style"] = self._validate_style(style)

        # Pass through any extra kwargs (e.g. user)
        extra_params = {"user"}
        for key in extra_params:
            if key in kwargs:
                payload[key] = kwargs[key]

        logger.info(
            "Generating image (model=%s, size=%s, quality=%s, style=%s) for prompt: %s...",
            model_name, payload["size"], payload.get("quality", "N/A"),
            payload.get("style", "N/A"), prompt[:80],
        )

        response = await _retry_request(
            lambda: self._client.post("/images/generations", json=payload),
            label="openai image generation",
        )
        data = response.json()

        # Extract base64 image data from OpenAI response format
        # { created, data: [{ b64_json, revised_prompt }] }
        image_b64: Optional[str] = None
        revised_prompt: Optional[str] = None

        if isinstance(data, dict):
            images = data.get("data") or []
            if isinstance(images, list) and images:
                first = images[0]
                if isinstance(first, dict):
                    image_b64 = first.get("b64_json")
                    revised_prompt = first.get("revised_prompt")

        if not image_b64:
            logger.error("Unexpected image response: %s", json.dumps(data)[:500])
            raise ProviderError("Failed to extract image data from OpenAI response", "openai")

        # Strip data-URI prefix if present
        if image_b64.startswith("data:"):
            image_b64 = image_b64.split(",", 1)[1]

        raw = base64.b64decode(image_b64)
        logger.info("Image generated (%d bytes)", len(raw))

        metadata: dict[str, Any] = {
            "model": model_name,
            "size": payload["size"],
        }
        if revised_prompt:
            metadata["revised_prompt"] = revised_prompt
        if is_dalle3:
            metadata["quality"] = payload["quality"]
            metadata["style"] = payload["style"]

        return GenerationResult(data=raw, mime_type="image/png", metadata=metadata)

    # ── Video (not supported) ──────────────────────────────────────────

    async def _image_to_video(
        self,
        prompt: str,
        image_data: bytes,
        *,
        model: str = "",
        size: str = "1280x720",
        duration: int = 5,
        **kwargs: Any,
    ) -> GenerationResult:
        """Not supported — raises ProviderError."""
        raise ProviderError(
            "Video generation not supported by OpenAI provider. "
            "Use a video-capable provider (e.g., SiliconFlow) for video.",
            "openai",
        )

    async def _text_to_video(
        self,
        prompt: str,
        *,
        model: str = "",
        size: str = "1280x720",
        duration: int = 5,
        **kwargs: Any,
    ) -> GenerationResult:
        """Not supported — raises ProviderError."""
        raise ProviderError(
            "Video generation not supported by OpenAI provider. "
            "Use a video-capable provider (e.g., SiliconFlow) for video.",
            "openai",
        )

    # ── Validation helpers ─────────────────────────────────────────────

    @staticmethod
    def _validate_size(model: str, size: str) -> str:
        """Validate and return the size, raising on invalid values."""
        is_dalle3 = model == "dall-e-3"
        valid_sizes = _DALLE3_SIZES if is_dalle3 else _DALLE2_SIZES
        if size not in valid_sizes:
            raise ProviderError(
                f"Invalid size '{size}' for {model}. "
                f"Valid sizes: {', '.join(sorted(valid_sizes))}",
                "openai",
            )
        return size

    @staticmethod
    def _validate_quality(quality: str) -> str:
        """Validate DALL-E 3 quality parameter."""
        if quality not in _DALLE3_QUALITY:
            raise ProviderError(
                f"Invalid quality '{quality}'. Valid values: {', '.join(sorted(_DALLE3_QUALITY))}",
                "openai",
            )
        return quality

    @staticmethod
    def _validate_style(style: str) -> str:
        """Validate DALL-E 3 style parameter."""
        if style not in _DALLE3_STYLE:
            raise ProviderError(
                f"Invalid style '{style}'. Valid values: {', '.join(sorted(_DALLE3_STYLE))}",
                "openai",
            )
        return style

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def close(self) -> None:
        await self._client.aclose()
        logger.debug("OpenAI HTTP client closed")
