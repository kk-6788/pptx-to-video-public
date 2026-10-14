"""
Google Gemini Provider — wraps the Gemini API for image generation.

Supports:
- Text → Image via Imagen models (``imagen-3.0-generate-001``, ``imagen-2.0``)

Video generation is not supported by Gemini Imagen — calling
:meth:`generate_video` raises a :class:`ProviderError`.

Configuration
-------------
Set ``GEMINI_API_KEY`` env var or pass ``api_key`` to the constructor.
Optional env vars:

- ``GEMINI_BASE_URL`` (default: ``https://generativelanguage.googleapis.com/v1beta``)
- ``GEMINI_IMAGE_MODEL`` (default: ``imagen-3.0-generate-001``)

Reference
---------
- https://ai.google.dev/api/imagen
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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_DEFAULT_IMAGE_MODEL = "imagen-3.0-generate-001"

_SUPPORTED_IMAGE_MODELS = [
    "imagen-3.0-generate-001",
    "imagen-3.0-fast-generate-001",
    "imagen-2.0",
]

_RETRY_MAX = 3
_RETRY_BASE_DELAY = 1.0


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
                    "gemini",
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
            raise ProviderError(f"{label} network failure: {exc}", "gemini") from exc
        except httpx.TimeoutException as exc:
            last_exc = exc
            if attempt < _RETRY_MAX:
                delay = _RETRY_BASE_DELAY * (2**attempt)
                logger.warning("%s timeout – retrying %.1fs: %s", label, delay, exc)
                await asyncio.sleep(delay)
                continue
            raise ProviderError(f"{label} timed out: {exc}", "gemini") from exc
    assert last_exc is not None
    raise last_exc


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class GeminiProvider(GenerationProvider):
    """Google Gemini / Imagen image generation provider.

    Uses the Google Imagen API (``:predict`` endpoint) to generate images
    from text prompts.  Video generation is **not supported**.
    """

    def __init__(self, api_key: str = "", **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        base_url = kwargs.get("base_url") or os.getenv("GEMINI_BASE_URL", _DEFAULT_BASE_URL)
        self._image_model = kwargs.get("image_model") or os.getenv("GEMINI_IMAGE_MODEL", _DEFAULT_IMAGE_MODEL)

        resolved_key = api_key or os.getenv("GEMINI_API_KEY", "")
        if not resolved_key:
            logger.warning(
                "No GEMINI_API_KEY set — requests will fail unless the "
                "Gemini API key is provided at runtime."
            )

        self._api_key = resolved_key
        self._base_url = base_url.rstrip("/")

        # The Gemini API uses query-param auth (?key=...), not Bearer headers.
        # We set up a client without auth headers.
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(60.0, connect=15.0),
        )

    # ── Capabilities ─────────────────────────────────────────────────────

    @classmethod
    def capabilities(cls) -> ProviderCapabilities:
        return ProviderCapabilities(
            name="gemini",
            display_name="Google Gemini",
            capabilities={
                ProviderCapability.TEXT_TO_IMAGE,
                ProviderCapability.SYNCHRONOUS,
            },
            default_image_model=_DEFAULT_IMAGE_MODEL,
            default_video_model="",
            supported_image_models=list(_SUPPORTED_IMAGE_MODELS),
            supported_video_models=[],
            max_prompt_length=4096,
            requires_api_key=True,
            configurable_base_url=True,
            description="Google Gemini / Imagen image generation. "
            "Supports Imagen 3.0 and Imagen 2.0 models via "
            "https://ai.google.dev. Video generation is not supported.",
        )

    # ── Image generation ─────────────────────────────────────────────────

    async def generate_image(
        self,
        prompt: str,
        *,
        model: str = "",
        size: str = "1280x720",
        **kwargs: Any,
    ) -> GenerationResult:
        """Generate an image via the Google Imagen API.

        Uses the ``:predict`` endpoint with the configured Imagen model.

        Args:
            prompt: Text description of the desired image.
            model: Imagen model name (e.g. ``imagen-3.0-generate-001``).
                Falls back to ``GEMINI_IMAGE_MODEL`` env var or the default.
            size: Output size in ``"WxH"`` format (e.g. ``"1280x720"``).
                Note: Imagen supports specific aspect ratios; very custom
                sizes may be clamped by the API.

        Returns:
            GenerationResult with the image bytes.

        Raises:
            ProviderError: On API errors, auth failures, or parsing failures.
        """
        model_name = model or self._image_model

        # Validate model
        if model_name not in _SUPPORTED_IMAGE_MODELS:
            logger.warning(
                "Unknown Imagen model %r — supported: %s",
                model_name,
                ", ".join(_SUPPORTED_IMAGE_MODELS),
            )

        # Parse size into aspect ratio if needed
        aspect_ratio = _size_to_aspect_ratio(size)

        payload: dict[str, Any] = {
            "instances": [
                {
                    "prompt": prompt,
                }
            ],
            "parameters": {
                "sampleCount": 1,
                "aspectRatio": aspect_ratio,
            },
        }

        logger.info(
            "Generating image (model=%s, aspect=%s) for prompt: %s...",
            model_name,
            aspect_ratio,
            prompt[:80],
        )

        endpoint = f"/models/{model_name}:predict"
        response = await _retry_request(
            lambda: self._client.post(
                endpoint,
                params={"key": self._api_key},
                json=payload,
            ),
            label="gemini image generation",
        )

        data = response.json()

        # Parse predictions
        image_bytes = self._extract_image(data, model_name)

        return GenerationResult(
            data=image_bytes,
            mime_type="image/png",
            metadata={
                "model": model_name,
                "size": size,
                "aspect_ratio": aspect_ratio,
            },
        )

    # ── Video (not supported) ───────────────────────────────────────────

    async def generate_video(
        self,
        prompt: str,
        image_data: Optional[bytes] = None,
        *,
        model: str = "",
        size: str = "1280x720",
        duration: int = 5,
        **kwargs: Any,
    ) -> GenerationResult:
        """Video generation is not supported by the Gemini provider.

        Raises:
            ProviderError: Always — Gemini Imagen does not support video.
        """
        raise ProviderError(
            "Google Gemini / Imagen does not support video generation. "
            "Use a different provider (e.g. siliconflow, agnes, kling) "
            "for video tasks.",
            "gemini",
        )

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
        raise ProviderError(
            "Google Gemini / Imagen does not support image-to-video generation.",
            "gemini",
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
        raise ProviderError(
            "Google Gemini / Imagen does not support text-to-video generation.",
            "gemini",
        )

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def close(self) -> None:
        await self._client.aclose()
        logger.debug("Gemini HTTP client closed")

    # ── Internal helpers ─────────────────────────────────────────────────

    @staticmethod
    def _extract_image(data: dict, model_name: str) -> bytes:
        """Extract image bytes from the Gemini predict response."""
        if not isinstance(data, dict):
            raise ProviderError(
                f"Unexpected response type: {type(data).__name__}",
                "gemini",
            )

        # Check for API errors
        error = data.get("error")
        if error:
            message = error.get("message", str(error))
            code = error.get("code", 0)
            raise ProviderError(
                f"Gemini API error (code={code}): {message}",
                "gemini",
            )

        predictions = data.get("predictions")
        if not predictions or not isinstance(predictions, list) or len(predictions) == 0:
            raise ProviderError(
                f"No predictions in Gemini response: {json.dumps(data)[:500]}",
                "gemini",
            )

        first = predictions[0]
        if not isinstance(first, dict):
            raise ProviderError(
                f"Unexpected prediction format: {type(first).__name__}",
                "gemini",
            )

        # Imagen returns bytesBase64Encoded or mimeType + bytesBase64Encoded
        b64 = first.get("bytesBase64Encoded")
        if not b64:
            # Try alternative field names
            b64 = first.get("b64_json") or first.get("image") or first.get("encodedImage")

        if not b64:
            raise ProviderError(
                f"No base64 image data in prediction: {json.dumps(first)[:300]}",
                "gemini",
            )

        # Strip data-URI prefix if present
        if isinstance(b64, str) and b64.startswith("data:"):
            b64 = b64.split(",", 1)[1]

        try:
            raw = base64.b64decode(b64)
        except Exception as exc:
            raise ProviderError(
                f"Failed to decode base64 image data: {exc}",
                "gemini",
            ) from exc

        logger.info("Image generated (%d bytes, model=%s)", len(raw), model_name)
        return raw


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _size_to_aspect_ratio(size: str) -> str:
    """Convert a ``"WxH"`` size string to a Gemini-compatible aspect ratio.

    Gemini Imagen supports: ``"1:1"``, ``"3:4"``, ``"4:3"``, ``"9:16"``,
    ``"16:9"``.  If the ratio doesn't match exactly, the closest match
    is used.
    """
    known_ratios = {
        (1, 1): "1:1",
        (3, 4): "3:4",
        (4, 3): "4:3",
        (9, 16): "9:16",
        (16, 9): "16:9",
    }

    try:
        parts = size.lower().split("x")
        if len(parts) != 2:
            return "16:9"
        w = int(parts[0])
        h = int(parts[1])
    except (ValueError, IndexError):
        return "16:9"

    if w <= 0 or h <= 0:
        return "16:9"

    # Exact match
    for (rw, rh), ratio in known_ratios.items():
        if w * rh == h * rw:
            return ratio

    # Closest match by minimizing absolute difference in aspect ratio
    target_ratio = w / h
    best = "16:9"
    best_diff = float("inf")
    for (rw, rh), ratio in known_ratios.items():
        diff = abs(target_ratio - rw / rh)
        if diff < best_diff:
            best_diff = diff
            best = ratio

    return best
