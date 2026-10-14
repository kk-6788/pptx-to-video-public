"""
SiliconFlow provider — wraps the SiliconFlow image / video API.

Supports:
- Text → Image via ``seedream-250``
- Image → Video via ``seedance-2.0`` (polling-based)

Configuration
-------------
Set ``SILICONFLOW_API_KEY`` env var or pass ``api_key`` to the constructor.
Optional env vars:

- ``SILICONFLOW_BASE_URL`` (default: ``https://api.siliconflow.cn``)
- ``SILICONFLOW_IMAGE_MODEL`` (default: ``seedream-250``)
- ``SILICONFLOW_VIDEO_MODEL`` (default: ``seedance-2.0``)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

import aiofiles
import httpx

from providers.media import download_media

from providers.base import (
    GenerationProvider,
    GenerationResult,
    ProviderCapabilities,
    ProviderCapability,
    ProviderError,
    AcceptedTaskError,
)

logger = logging.getLogger(__name__)

# Defaults
_DEFAULT_BASE_URL = "https://api.siliconflow.cn"
_DEFAULT_IMAGE_MODEL = "Kwai-Kolors/Kolors"
_DEFAULT_VIDEO_MODEL = "Wan-AI/Wan2.2-I2V-A14B"

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
                    "siliconflow",
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
            raise ProviderError(f"{label} network failure: {exc}", "siliconflow") from exc
    assert last_exc is not None
    raise last_exc


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class SiliconFlowProvider(GenerationProvider):
    """SiliconFlow image + video generation provider."""

    def __init__(self, api_key: str = "", **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        base_url = kwargs.get("base_url") or os.getenv("SILICONFLOW_BASE_URL", _DEFAULT_BASE_URL)
        # Keep the resolved endpoint for the public cache_identity() contract.
        self.base_url = base_url
        self._image_model = kwargs.get("image_model") or os.getenv("SILICONFLOW_IMAGE_MODEL", _DEFAULT_IMAGE_MODEL)
        self._video_model = kwargs.get("video_model") or os.getenv("SILICONFLOW_VIDEO_MODEL", _DEFAULT_VIDEO_MODEL)

        resolved_key = api_key or os.getenv("SILICONFLOW_API_KEY", "")
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {resolved_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    @classmethod
    def capabilities(cls) -> ProviderCapabilities:
        return ProviderCapabilities(
            name="siliconflow",
            display_name="SiliconFlow",
            capabilities={
                ProviderCapability.TEXT_TO_IMAGE,
                ProviderCapability.IMAGE_TO_VIDEO,
                ProviderCapability.TEXT_TO_VIDEO,
                ProviderCapability.POLLING_STATUS,
            },
            default_image_model="Kwai-Kolors/Kolors",
            default_video_model="Wan-AI/Wan2.2-I2V-A14B",
            supported_image_models=[
                "Kwai-Kolors/Kolors",
                "pro/black-forest-labs/FLUX.1-pro",
                "black-forest-labs/FLUX.1-dev",
                "black-forest-labs/FLUX.1-schnell",
                "stabilityai/stable-diffusion-3-5-large",
                "stabilityai/stable-diffusion-3-5-medium",
                "ByteDance/SDXL-Lightning",
            ],
            supported_video_models=[
                "Wan-AI/Wan2.2-I2V-A14B",
                "Wan-AI/Wan2.2-T2V-A14B",
                "wan-2.1",
                "CogVideoX",
                "SVD",
                "Mochi-1",
            ],
            max_prompt_length=1024,
            requires_api_key=True,
            configurable_base_url=True,
            description="SiliconFlow AI cloud API — 汇集 FLUX / SD / Kolors / Wan2.1 等开源模型。"
                        "Free trial credits at https://cloud.siliconflow.cn",
        )

    # ── Image ──────────────────────────────────────────────────────────

    def cache_identity(self) -> dict:
        """Include the resolved endpoint + models in the public cache contract.

        The endpoint is stripped to scheme/host/port/path — no API key,
        userinfo or query parameters ever enter the cache key.
        """
        identity = super().cache_identity()
        parts = urlsplit(str(self.base_url))
        identity['endpoint'] = [parts.scheme, parts.hostname, parts.port, parts.path]
        identity['image_model'] = self._image_model
        identity['video_model'] = self._video_model
        return identity

    async def generate_image(
        self,
        prompt: str,
        *,
        model: str = "",
        size: str = "1280x720",
        **kwargs: Any,
    ) -> GenerationResult:
        """Generate an image via seedream-250 (or configured model)."""
        model_name = model or self._image_model
        payload: dict[str, Any] = {
            "model": model_name,
            "prompt": prompt,
            "n": 1,
            "size": size,
        }

        logger.info("Generating image (model=%s) for prompt: %s...", model_name, prompt[:80])

        response = await _retry_request(
            lambda: self._client.post("/v1/images/generations", json=payload),
            label="siliconflow image generation",
        )
        data = response.json()

        # Extract image bytes from various response shapes
        image_b64: Optional[str] = None
        if isinstance(data, dict):
            images = data.get("images") or data.get("data") or []
            if isinstance(images, list) and images:
                first = images[0]
                if isinstance(first, dict):
                    image_b64 = first.get("b64_json") or first.get("b64")
                    if not image_b64 and "url" in first:
                        url = first["url"]
                        img_resp = await download_media(self._client, url)
                        img_resp.raise_for_status()
                        image_b64 = base64.b64encode(img_resp.content).decode("ascii")
                elif isinstance(first, str):
                    image_b64 = first
            if not image_b64:
                image_b64 = data.get("image") or data.get("b64_json")
            if not image_b64 and "output" in data:
                image_b64 = data["output"].get("image") or data["output"].get("b64_json")

        if not image_b64:
            logger.error("Unexpected image response: %s", json.dumps(data)[:500])
            raise ProviderError("Failed to extract image data from response", "siliconflow")

        # Strip data-URI prefix if present
        if image_b64.startswith("data:"):
            image_b64 = image_b64.split(",", 1)[1]

        raw = base64.b64decode(image_b64)
        logger.info("Image generated (%d bytes)", len(raw))
        return GenerationResult(data=raw, mime_type="image/png")

    # ── Video (image→video) ────────────────────────────────────────────

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
        """Submit an image→video task and poll until done."""
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
        """Generate a video from text only (no input image)."""
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
        """Submit a video task and poll until completion via POST /v1/video/status.

        The official docs (https://docs.siliconflow.cn/docs/api/video-status-post)
        still list the status endpoint; the earlier "endpoint removed" assumption
        caused submitted tasks to be reported as failures and resubmitted by the
        caller, billing the same scene multiple times. Once a requestId exists the
        task is *accepted* — it must only ever be queried, never resubmitted.
        """
        submit_payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
        }
        if image_b64:
            submit_payload["image"] = image_b64
        if size:
            submit_payload["size"] = size
        if duration:
            submit_payload["duration"] = duration

        logger.info("Submitting video task (model=%s)...", model)

        response = await _retry_request(
            lambda: self._client.post("/v1/video/submit", json=submit_payload),
            label="siliconflow video submit",
        )
        data = response.json()

        # Check for business errors
        if isinstance(data, dict):
            code = data.get("code")
            msg = data.get("message", "")

            # 403 = insufficient balance
            if response.status_code == 403 or code == 30001:
                raise ProviderError(
                    f"SiliconFlow 账户余额不足，无法生成视频。\n"
                    f"请前往 https://cloud.siliconflow.cn 充值后重试。\n"
                    f"API 返回: {msg}",
                    "siliconflow",
                )

            if code and code != 0:
                raise ProviderError(
                    f"视频提交失败 (code={code}): {msg}",
                    "siliconflow",
                )

        # Extract request ID
        request_id: Optional[str] = None
        if isinstance(data, dict):
            request_id = (
                data.get("requestId") or data.get("request_id") or data.get("id")
            )
        if not request_id:
            logger.error("Unexpected submit response: %s", json.dumps(data, ensure_ascii=False)[:500])
            raise ProviderError(
                "无法获取视频任务 ID。SiliconFlow 接口返回格式异常。",
                "siliconflow",
            )

        # ── Task is now ACCEPTED (requestId held). Poll /v1/video/status only. ──
        logger.info("Video task submitted – requestId=%s; polling status...", request_id)
        try:
            return await self._poll_status(request_id, model)
        except AcceptedTaskError:
            raise
        except Exception as exc:
            # Includes malformed responses: an unknown outcome is not permission
            # to start another paid task at the scene-orchestration layer.
            raise AcceptedTaskError(
                f"任务 {request_id} 已受理，结果尚未取得；请查询原任务，勿重新提交。{exc}",
                "siliconflow", request_id=request_id, model=model,
            ) from exc

    async def _poll_status(
        self,
        request_id: str,
        model: str,
        *,
        max_attempts: int = 120,
        interval_seconds: float = 5.0,
        ) -> GenerationResult:
        """Poll POST /v1/video/status until Succeed/Failed (docs: video-status-post).

        Status outcomes: Succeed / InQueue / InProgress / Failed. Network errors
        while polling mean *unknown status* — keep polling, never resubmit.
        """
        import asyncio as _asyncio

        for attempt in range(1, max_attempts + 1):
            try:
                resp = await self._client.post(
                    "/v1/video/status",
                    json={"requestId": request_id},
                )
                data = resp.json()
            except httpx.HTTPError as exc:
                logger.warning(
                    "Status poll #%s for requestId=%s failed (%s); task remains "
                    "submitted – continuing to poll, NOT resubmitting.",
                    attempt, request_id, exc,
                )
                await _asyncio.sleep(interval_seconds)
                continue

            if isinstance(data, dict):
                code = data.get("code")
                if code and code != 0:
                    raise ProviderError(
                        f"视频状态查询失败 (requestId={request_id}, code={code}): "
                        f"{data.get('message', '')}",
                        "siliconflow",
                    )
                status = str(data.get("status") or "").lower()
                if status == "succeed":
                    results = data.get("results")
                    videos = results.get("videos") if isinstance(results, dict) else None
                    video_url = (videos[0].get("url") if isinstance(videos, list)
                                 and videos and isinstance(videos[0], dict) else None)
                    # Compatibility endpoints historically returned a top-level URL.
                    video_url = video_url or data.get("url") or data.get("video_url") or data.get("videoUrl")
                    if not isinstance(video_url, str):
                        video_url = ""
                    if not video_url:
                        raise ProviderError(
                            f"任务 {request_id} 状态为 Succeed 但响应中没有视频地址。",
                            "siliconflow",
                        )
                    logger.info("Video task %s succeeded – downloading result", request_id)
                    try:
                        download = await download_media(self._client, video_url)
                        download.raise_for_status()
                    except (httpx.HTTPError, ValueError) as exc:
                        raise AcceptedTaskError(
                            f"任务 {request_id} 已完成，但下载结果失败；请恢复此任务，勿重新提交: {exc}",
                            "siliconflow", request_id=request_id, model=model,
                            result_url=video_url,
                        ) from exc
                    result = GenerationResult(
                        data=download.content,
                        mime_type=download.headers.get("content-type", "video/mp4"),
                        metadata={"request_id": request_id, "model": model},
                    )
                    return result
                if status == "failed":
                    raise ProviderError(
                        f"视频任务 {request_id} 生成失败（任务已被受理，费用已产生）。"
                        f"详情: {data.get('message', '')}",
                        "siliconflow",
                    )
                # InQueue / InProgress / unknown → keep polling
                if attempt % 12 == 0:
                    logger.info("Video task %s still %s...", request_id, status or "unknown")
            else:
                logger.warning("Unexpected status payload for %s: %s",
                               request_id, str(data)[:300])

            await _asyncio.sleep(interval_seconds)

        raise ProviderError(
            f"视频任务 {request_id} 在等待时间内未完成（任务已受理，请勿重新提交；"
            f"请稍后通过 requestId 查询结果）。",
            "siliconflow",
        )

    async def close(self) -> None:
        await self._client.aclose()
        logger.debug("SiliconFlow HTTP client closed")
