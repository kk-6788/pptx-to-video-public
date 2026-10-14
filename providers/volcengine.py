"""
火山引擎 (Volcengine/Doubao) provider — 豆包大模型 / 火山方舟 API.

支持：
- Text → Image（豆包文生图，OpenAI 兼容接口）
- Image → Video（Seed 视频生成，异步轮询）

配置
----
环境变量 ``VOLC_API_KEY``（或构造参数 ``api_key``）
可选: ``VOLC_BASE_URL``（默认 ``https://ark.cn-beijing.volces.com/api/v3``）
      ``VOLC_IMAGE_MODEL``（默认 ``doubao-vision-pro-32k``）
      ``VOLC_VIDEO_MODEL``（默认 ``seed-video-v1``）

注意：火山方舟需要先在工作台开通对应模型才能使用。
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

_DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
_DEFAULT_IMAGE_MODEL = "doubao-vision-pro-32k"
_DEFAULT_VIDEO_MODEL = "seed-video-v1"
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
                    f"{label}: {response.status_code} {response.text[:200]}", "volcengine",
                )
                if attempt < _RETRY_MAX:
                    delay = _RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        "%s returned %d – retrying %.1fs (attempt %d/%d)",
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
            raise ProviderError(f"{label} network failure: {exc}", "volcengine") from exc
    assert last_exc is not None
    raise last_exc


class VolcengineProvider(GenerationProvider):
    """火山引擎 — 豆包/Seed 系列图像及视频生成."""

    def __init__(self, api_key: str = "", **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        base_url = kwargs.get("base_url") or os.getenv("VOLC_BASE_URL", _DEFAULT_BASE_URL)
        self._image_model = kwargs.get("image_model") or os.getenv("VOLC_IMAGE_MODEL", _DEFAULT_IMAGE_MODEL)
        self._video_model = kwargs.get("video_model") or os.getenv("VOLC_VIDEO_MODEL", _DEFAULT_VIDEO_MODEL)

        resolved_key = api_key or os.getenv("VOLC_API_KEY", "")
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {resolved_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(60.0, connect=15.0),
        )

    @classmethod
    def capabilities(cls) -> ProviderCapabilities:
        return ProviderCapabilities(
            name="volcengine",
            display_name="火山引擎 (豆包/Seed)",
            capabilities={
                ProviderCapability.TEXT_TO_IMAGE,
                ProviderCapability.IMAGE_TO_VIDEO,
                ProviderCapability.POLLING_STATUS,
            },
            default_image_model="seedream-5.0",
            default_video_model="seedance-2.0",
            supported_image_models=[
                "seedream-5.0",
                "seedream-3.0",
                "seedream-2.5",
                "seedream-2.0",
            ],
            supported_video_models=[
                "seedance-2.0",
                "seedance-1.5",
                "seedance-1.0",
            ],
            max_prompt_length=4000,
            requires_api_key=True,
            configurable_base_url=True,
            description="火山引擎 — Seedream 5.0 文生图 + Seedance 2.0 视频生成。"
                        "需在火山方舟开通模型。https://console.volcengine.com/ark",
        )

    async def generate_image(
        self,
        prompt: str,
        *,
        model: str = "",
        size: str = "1280x720",
        **kwargs: Any,
    ) -> GenerationResult:
        """生成图像（OpenAI 兼容接口）。"""
        model_name = model or self._image_model
        w, h = map(int, size.split("x"))

        # Map to supported sizes
        img_size = self._pick_size(w, h)

        payload: dict[str, Any] = {
            "model": model_name,
            "prompt": prompt,
            "n": 1,
            "size": img_size,
            "response_format": "b64_json",
        }

        logger.info("Volcengine: generating image (model=%s, size=%s)...", model_name, img_size)
        response = await _retry_request(
            lambda: self._client.post("/images/generations", json=payload),
            label="volcengine image generation",
        )
        data = response.json()

        image_b64: Optional[str] = None
        if isinstance(data, dict):
            img_list = data.get("data", [])
            if img_list and isinstance(img_list[0], dict):
                image_b64 = img_list[0].get("b64_json") or img_list[0].get("b64")
                if not image_b64 and img_list[0].get("url"):
                    url = img_list[0]["url"]
                    dl = await download_media(self._client, url)
                    dl.raise_for_status()
                    image_b64 = base64.b64encode(dl.content).decode("ascii")

        if not image_b64:
            logger.error("Unexpected Volcengine image response: %s", json.dumps(data)[:500])
            raise ProviderError("Failed to extract image from Volcengine response", "volcengine")

        if image_b64.startswith("data:"):
            image_b64 = image_b64.split(",", 1)[1]

        raw = base64.b64decode(image_b64)
        logger.info("Volcengine: image generated (%d bytes)", len(raw))
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
        """Seed 图生视频 — 提交任务并轮询。"""
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
        """Seed 文生视频 — 提交任务并轮询。"""
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
        """提交视频生成任务并轮询完成。"""
        w, h = map(int, size.split("x"))

        input_data: dict[str, Any] = {
            "prompt": prompt,
            "size": f"{w}x{h}",
            "duration": duration,
        }
        if image_b64:
            input_data["image"] = image_b64

        payload: dict[str, Any] = {
            "model": model,
            "input": input_data,
        }

        logger.info("Volcengine: submitting video task (model=%s)...", model)

        # Try video submission endpoint — different providers use different paths
        response = await _retry_request(
            lambda: self._client.post("/video/submit", json=payload),
            label="volcengine video submit",
        )
        data = response.json()

        task_id: Optional[str] = None
        if isinstance(data, dict):
            task_id = (
                data.get("task_id") or data.get("id")
                or data.get("data", {}).get("task_id")
                or data.get("data", {}).get("id")
            )

        if not task_id:
            logger.error("Unexpected Volcengine submit response: %s", json.dumps(data)[:500])
            raise ProviderError("Failed to get task_id from Volcengine video submit", "volcengine")

        logger.info("Volcengine: video task submitted – task_id=%s", task_id)

        # Poll
        start = time.monotonic()
        while True:
            elapsed = time.monotonic() - start
            if elapsed > _POLL_TIMEOUT:
                raise ProviderError(f"Volcengine task {task_id} timed out", "volcengine")

            resp = await _retry_request(
                lambda: self._client.get("/video/status", params={"task_id": task_id}),
                label=f"volcengine video status ({task_id[:12]}...)",
            )
            status_data = resp.json()

            if isinstance(status_data, dict):
                sd = status_data.get("data", status_data)
                status = (sd.get("status") or "").lower()

                if status in ("succeed", "success", "completed", "done", "finished"):
                    logger.info("Volcengine: task %s completed after %.0fs", task_id, elapsed)
                    video_url = (
                        sd.get("video_url") or sd.get("url")
                        or sd.get("output", {}).get("video_url")
                        or sd.get("output", {}).get("url")
                        or sd.get("result", {}).get("video_url")
                    )
                    if not video_url:
                        raise ProviderError(
                            f"No video URL in Volcengine response: {json.dumps(sd)[:300]}",
                            "volcengine",
                        )
                    dl = await download_media(self._client, video_url, headers={"Accept": "*/*"})
                    dl.raise_for_status()
                    dur = float(sd.get("duration", duration))
                    logger.info("✓ Volcengine video downloaded (%.1fs, %d bytes)", dur, len(dl.content))
                    return GenerationResult(
                        data=dl.content, mime_type="video/mp4",
                        metadata={"duration": dur},
                    )

                if status in ("failed", "error", "cancelled"):
                    err_msg = sd.get("error", sd.get("message", "unknown"))
                    raise ProviderError(f"Volcengine task {task_id} failed: {err_msg}", "volcengine")

            await asyncio.sleep(_POLL_INTERVAL)

    async def close(self) -> None:
        await self._client.aclose()
        logger.debug("Volcengine HTTP client closed")

    @staticmethod
    def _pick_size(width: int, height: int) -> str:
        """Volcengine images API 只支持特定尺寸."""
        sizes = {
            (1024, 1024): "1024x1024",
            (1024, 768): "1024x768",
            (768, 1024): "768x1024",
            (1280, 720): "1280x720",
            (720, 1280): "720x1280",
        }
        best = "1024x1024"
        best_dist = float("inf")
        for (sw, sh), label in sizes.items():
            dist = (sw - width) ** 2 + (sh - height) ** 2
            if dist < best_dist:
                best_dist = dist
                best = label
        return best
