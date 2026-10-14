"""
可灵AI (Kling) provider — 快手可灵视频生成 API.

支持：
- Text → Image (可灵图像生成)
- Image → Video (可灵图生视频，异步轮询)
- Text → Video (可灵文生视频)

API 文档: https://docs.klingai.com

配置
----
环境变量 ``KLING_API_KEY``（或构造参数 ``api_key``）
可选: ``KLING_BASE_URL``（默认 ``https://api.klingai.com``）
      ``KLING_IMAGE_MODEL``（默认 ``kling-v1``）
      ``KLING_VIDEO_MODEL``（默认 ``kling-v1``）
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
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

_DEFAULT_BASE_URL = "https://api.klingai.com"
_DEFAULT_IMAGE_MODEL = "kling-v1"
_DEFAULT_VIDEO_MODEL = "kling-v1"
_RETRY_MAX = 3
_RETRY_BASE_DELAY = 1.0
_POLL_INTERVAL = 3.0
_POLL_TIMEOUT = 600.0


async def _retry_request(coro_factory, label: str) -> httpx.Response:
    last_exc: Optional[Exception] = None
    for attempt in range(_RETRY_MAX + 1):
        try:
            response = await coro_factory()
            if response.status_code in (429, 500, 502, 503, 504):
                last_exc = ProviderError(
                    f"{label}: {response.status_code} {response.text[:200]}", "kling",
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
            raise ProviderError(f"{label} network failure: {exc}", "kling") from exc
    assert last_exc is not None
    raise last_exc


class KlingProvider(GenerationProvider):
    """可灵AI (Kling) image + video generation provider."""

    def __init__(self, api_key: str = "", **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        base_url = kwargs.get("base_url") or os.getenv("KLING_BASE_URL", _DEFAULT_BASE_URL)
        self._image_model = kwargs.get("image_model") or os.getenv("KLING_IMAGE_MODEL", _DEFAULT_IMAGE_MODEL)
        self._video_model = kwargs.get("video_model") or os.getenv("KLING_VIDEO_MODEL", _DEFAULT_VIDEO_MODEL)

        resolved_key = api_key or os.getenv("KLING_API_KEY", "")
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {resolved_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    @classmethod
    def capabilities(cls) -> ProviderCapabilities:
        return ProviderCapabilities(
            name="kling",
            display_name="可灵AI (Kling)",
            capabilities={
                ProviderCapability.TEXT_TO_IMAGE,
                ProviderCapability.IMAGE_TO_VIDEO,
                ProviderCapability.TEXT_TO_VIDEO,
                ProviderCapability.POLLING_STATUS,
            },
            default_image_model="kling-image-v1-6",
            default_video_model="kling-video-v1-6",
            supported_image_models=[
                "kling-image-v1-6",
                "kling-image-v1-5",
                "kling-image-v1",
            ],
            supported_video_models=[
                "kling-video-v1-6",
                "kling-v1-6",
                "kling-video-v1-5",
                "kling-v1-5",
                "kling-video-v1",
                "kling-v1",
            ],
            max_prompt_length=2000,
            requires_api_key=True,
            configurable_base_url=True,
            description="快手可灵AI — 支持文生图、图生视频、文生视频。"
                        "API Key 申请: https://klingai.com",
        )

    async def generate_image(
        self,
        prompt: str,
        *,
        model: str = "",
        size: str = "1280x720",
        **kwargs: Any,
    ) -> GenerationResult:
        model_name = model or self._image_model
        w, h = map(int, size.split("x"))

        payload: dict[str, Any] = {
            "model": model_name,
            "prompt": prompt,
            "n": 1,
            "size": f"{w}x{h}",
        }

        logger.info("Kling: generating image (model=%s)...", model_name)
        response = await _retry_request(
            lambda: self._client.post("/v1/images/generations", json=payload),
            label="kling image generation",
        )
        data = response.json()

        # Parse Kling response
        image_b64: Optional[str] = None
        if isinstance(data, dict):
            if data.get("code") == 0:
                img_data = data.get("data", {})
                images = img_data.get("images", []) if isinstance(img_data, dict) else []
                if images and isinstance(images[0], dict):
                    image_b64 = images[0].get("b64_json") or images[0].get("b64")
                    if not image_b64 and images[0].get("url"):
                        url = images[0]["url"]
                        dl = await download_media(self._client, url)
                        dl.raise_for_status()
                        image_b64 = base64.b64encode(dl.content).decode("ascii")
            else:
                err_msg = data.get("message", json.dumps(data)[:200])
                raise ProviderError(f"Kling image error: {err_msg}", "kling")

        if not image_b64:
            logger.error("Unexpected Kling image response: %s", json.dumps(data)[:500])
            raise ProviderError("Failed to extract image from Kling response", "kling")

        if image_b64.startswith("data:"):
            image_b64 = image_b64.split(",", 1)[1]

        raw = base64.b64decode(image_b64)
        logger.info("Kling: image generated (%d bytes)", len(raw))
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
        return await self._submit_and_poll(
            model=model or self._video_model,
            prompt=prompt,
            image_b64=base64.b64encode(image_data).decode("ascii"),
            size=size,
            duration=duration,
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
        return await self._submit_and_poll(
            model=model or self._video_model,
            prompt=prompt,
            image_b64=None,
            size=size,
            duration=duration,
        )

    async def _submit_and_poll(
        self,
        model: str,
        prompt: str,
        image_b64: Optional[str],
        size: str,
        duration: int,
    ) -> GenerationResult:
        w, h = map(int, size.split("x"))
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "size": f"{w}x{h}",
            "duration": duration,
        }
        if image_b64:
            payload["image"] = image_b64

        logger.info("Kling: submitting video task (model=%s)...", model)
        response = await _retry_request(
            lambda: self._client.post("/v1/videos/generations", json=payload),
            label="kling video submit",
        )
        data = response.json()

        task_id: Optional[str] = None
        if isinstance(data, dict):
            if data.get("code") == 0:
                task_data = data.get("data", {})
                task_id = task_data.get("task_id") or task_data.get("id")
            else:
                err_msg = data.get("message", json.dumps(data)[:200])
                raise ProviderError(f"Kling video submit error: {err_msg}", "kling")

        if not task_id:
            logger.error("Unexpected Kling submit response: %s", json.dumps(data)[:500])
            raise ProviderError("Failed to get task_id from Kling", "kling")

        logger.info("Kling: task submitted – task_id=%s", task_id)

        # Poll
        start = time.monotonic()
        while True:
            elapsed = time.monotonic() - start
            if elapsed > _POLL_TIMEOUT:
                raise ProviderError(f"Kling task {task_id} timed out", "kling")

            resp = await _retry_request(
                lambda: self._client.get(f"/v1/videos/generations/{task_id}"),
                label=f"kling video status ({task_id[:12]}...)",
            )
            status_data = resp.json()

            if isinstance(status_data, dict) and status_data.get("code") == 0:
                sd = status_data.get("data", status_data)
                status = (sd.get("status") or "").lower()

                if status in ("succeed", "success", "completed", "done", "finished"):
                    logger.info("Kling: task %s completed after %.0fs", task_id, elapsed)

                    # Extract video URL
                    video_url = (
                        sd.get("video_url") or sd.get("url")
                        or sd.get("video", {}).get("url")
                        or sd.get("output", {}).get("video_url")
                    )
                    if not video_url and "video" in sd:
                        video_url = sd["video"].get("url")

                    if not video_url:
                        raise ProviderError(f"No video URL in Kling response: {json.dumps(sd)[:300]}", "kling")

                    dl = await download_media(self._client, video_url, headers={"Accept": "*/*"})
                    dl.raise_for_status()
                    dur = float(sd.get("duration", duration))
                    logger.info("✓ Kling video downloaded (%.1fs, %d bytes)", dur, len(dl.content))
                    return GenerationResult(
                        data=dl.content, mime_type="video/mp4",
                        metadata={"duration": dur},
                    )

                if status in ("failed", "error", "cancelled"):
                    err_msg = sd.get("error", sd.get("message", "unknown"))
                    raise ProviderError(f"Kling task {task_id} failed: {err_msg}", "kling")

            await asyncio.sleep(_POLL_INTERVAL)

    async def close(self) -> None:
        await self._client.aclose()
        logger.debug("Kling HTTP client closed")
