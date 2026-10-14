"""
Custom API provider — connects to any OpenAI-compatible image / video API.

Useful for:
- Your own API proxy
- Third-party providers that support OpenAI-compatible endpoints
- Self-hosted inference endpoints

Configuration
-------------
Set these env vars or pass as constructor kwargs:

- ``CUSTOM_API_BASE_URL`` — REQUIRED, e.g. ``https://api.example.com/v1``
- ``CUSTOM_API_KEY`` — API key (optional, depends on your endpoint)
- ``CUSTOM_API_IMAGE_MODEL`` — model name for image generation
- ``CUSTOM_API_VIDEO_MODEL`` — model name for video generation
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Optional

import httpx

from providers.media import download_media

from providers.base import (
    GenerationProvider,
    GenerationResult,
    ProviderCapabilities,
    ProviderCapability,
    ProviderError,
)

logger = logging.getLogger(__name__)


class CustomApiProvider(GenerationProvider):
    """Generic OpenAI-compatible API provider."""

    def __init__(self, api_key: str = "", **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        self._base_url = (
            kwargs.get("base_url")
            or os.getenv("CUSTOM_API_BASE_URL", "")
        ).rstrip("/")
        if not self._base_url:
            raise ValueError(
                "CustomApiProvider requires a base_url (set CUSTOM_API_BASE_URL env var)"
            )

        resolved_key = api_key or os.getenv("CUSTOM_API_KEY", "")
        self._image_model = kwargs.get("image_model") or os.getenv("CUSTOM_API_IMAGE_MODEL", "dall-e-3")
        self._video_model = kwargs.get("video_model") or os.getenv("CUSTOM_API_VIDEO_MODEL", "")

        headers = {"Content-Type": "application/json"}
        if resolved_key:
            headers["Authorization"] = f"Bearer {resolved_key}"

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=httpx.Timeout(60.0, connect=15.0),
        )

    @classmethod
    def capabilities(cls) -> ProviderCapabilities:
        return ProviderCapabilities(
            name="custom_api",
            display_name="自定义API (OpenAI兼容)",
            capabilities={
                ProviderCapability.TEXT_TO_IMAGE,
                # Video depends on the specific endpoint — minimal by default
            },
            default_image_model="",
            default_video_model="",
            supported_image_models=["*"],
            supported_video_models=["*"],
            max_prompt_length=4000,
            requires_api_key=False,
            configurable_base_url=True,
            description="连接任意 OpenAI 兼容的 API 端点，支持自定义模型名称和基础 URL。",
        )

    async def generate_image(
        self,
        prompt: str,
        *,
        model: str = "",
        size: str = "1280x720",
        **kwargs: Any,
    ) -> GenerationResult:
        """Generate image using the OpenAI images endpoint."""
        model_name = model or self._image_model

        # Map our size format (1280x720) to DALL-E format (1792x1024 / 1024x1024)
        w, h = map(int, size.split("x"))
        # Pick the closest DALL-E size
        dalle_size = self._pick_dalle_size(w, h)

        payload: dict[str, Any] = {
            "model": model_name,
            "prompt": prompt,
            "n": 1,
            "size": dalle_size,
            "response_format": "b64_json",
        }

        logger.info("Custom API: generating image (model=%s, size=%s)...", model_name, dalle_size)

        response = await self._client.post("/images/generations", json=payload)
        response.raise_for_status()
        data = response.json()

        image_b64: Optional[str] = None
        if isinstance(data, dict):
            img_data = data.get("data", [{}])[0]
            image_b64 = img_data.get("b64_json") or img_data.get("b64")
            if not image_b64 and img_data.get("url"):
                url = img_data["url"]
                dl = await download_media(self._client, url)
                dl.raise_for_status()
                image_b64 = base64.b64encode(dl.content).decode("ascii")

        if not image_b64:
            logger.error("Unexpected response: %s", json.dumps(data)[:500])
            raise ProviderError("Failed to extract image data", "custom_api")

        if image_b64.startswith("data:"):
            image_b64 = image_b64.split(",", 1)[1]

        raw = base64.b64decode(image_b64)
        logger.info("Custom API: image generated (%d bytes)", len(raw))
        return GenerationResult(data=raw, mime_type="image/png")

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
        """Image → video via custom API (if the endpoint supports it)."""
        model_name = model or self._video_model
        if not model_name:
            raise ProviderError(
                "No video model configured for Custom API. "
                "Set CUSTOM_API_VIDEO_MODEL env var or pass 'model'.",
                "custom_api",
            )

        # Try common video endpoints — this is intentionally generic
        image_b64 = base64.b64encode(image_data).decode("ascii")
        payload: dict[str, Any] = {
            "model": model_name,
            "input": {
                "image": image_b64,
                "prompt": prompt,
                "size": size,
                "duration": duration,
            },
        }

        logger.info("Custom API: submitting video (model=%s)...", model_name)
        response = await self._client.post("/video/generations", json=payload)
        response.raise_for_status()
        data = response.json()

        # Try to extract video from response
        video_b64: Optional[str] = None
        if isinstance(data, dict):
            # Direct data
            video_b64 = data.get("b64_json") or data.get("video") or data.get("data", {}).get("b64_json")
            # URL
            video_url = data.get("url") or data.get("video_url") or data.get("data", {}).get("url")
            if not video_b64 and video_url:
                dl = await download_media(self._client, video_url)
                dl.raise_for_status()
                video_b64 = base64.b64encode(dl.content).decode("ascii")

        if not video_b64:
            logger.error("Unexpected video response: %s", json.dumps(data)[:500])
            raise ProviderError("Failed to extract video data", "custom_api")

        if video_b64.startswith("data:"):
            video_b64 = video_b64.split(",", 1)[1]

        raw = base64.b64decode(video_b64)
        return GenerationResult(data=raw, mime_type="video/mp4")

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
            "Text-to-video is not supported by the generic Custom API provider. "
            "Use an image first, then image→video.",
            "custom_api",
        )

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _pick_dalle_size(width: int, height: int) -> str:
        """Map our WxH to the closest DALL-E 3 supported size."""
        sizes = {
            (1024, 1024): "1024x1024",
            (1792, 1024): "1792x1024",
            (1024, 1792): "1024x1792",
        }
        # Find the closest
        best = "1024x1024"
        best_dist = float("inf")
        for (sw, sh), label in sizes.items():
            dist = (sw - width) ** 2 + (sh - height) ** 2
            if dist < best_dist:
                best_dist = dist
                best = label
        return best
