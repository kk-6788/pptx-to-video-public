"""
Agnes AI Provider — free tier image, video, and text generation.

Three models, all free (as of 2026):
  - agnes-2.0-flash       (text / chat)
  - agnes-image-2.1-flash (text-to-image / image-to-image)
  - agnes-video-v2.0      (text-to-video / image-to-video / keyframes)

API base: https://apihub.agnes-ai.com
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import time
from typing import Any, Optional

import httpx

from providers.media import download_media, is_api_media_url

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

AGNES_BASE_URL = "https://apihub.agnes-ai.com"
AGNES_CHAT_ENDPOINT = "/v1/chat/completions"
AGNES_IMAGE_ENDPOINT = "/v1/images/generations"
AGNES_VIDEO_ENDPOINT = "/v1/videos"  # POST to create, GET /{task_id} to poll

TEXT_MODEL = "agnes-2.0-flash"
IMAGE_MODEL = "agnes-image-2.1-flash"
VIDEO_MODEL = "agnes-video-v2.0"

_POLL_INTERVAL = 3.0  # seconds between video status checks
_POLL_TIMEOUT: float = 600.0  # overridden by config.POLL_TIMEOUT below

# Override _POLL_TIMEOUT from config if available (caters for .env and env vars)
try:
    import config as _cfg
    _POLL_TIMEOUT = _cfg.POLL_TIMEOUT
except (ImportError, AttributeError):
    pass  # keep default

_MAX_RETRIES = 5
_RETRY_DELAY_BASE = 2.0
_RETRY_MAX_DELAY = 60.0


import random  # for jitter


# ---------------------------------------------------------------------------
# Provider class
# ---------------------------------------------------------------------------


class AgnesProvider(GenerationProvider):
    """Agnes AI provider — text, image, and video generation (all free)."""

    def __init__(self, api_key: str = "", **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        self._client: Optional[httpx.AsyncClient] = None
        self._base_url = kwargs.get("base_url", AGNES_BASE_URL)

    # ── HTTP client (lazy init) ──────────────────────────────────────────

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(60.0, connect=15.0),
            )
        return self._client

    # ── Capabilities ─────────────────────────────────────────────────────

    @classmethod
    def capabilities(cls) -> ProviderCapabilities:
        return ProviderCapabilities(
            name="agnes",
            display_name="Agnes AI (Free)",
            capabilities={
                ProviderCapability.TEXT_TO_IMAGE,
                ProviderCapability.IMAGE_TO_VIDEO,
                ProviderCapability.TEXT_TO_VIDEO,
                ProviderCapability.POLLING_STATUS,
            },
            default_image_model=IMAGE_MODEL,
            default_video_model=VIDEO_MODEL,
            supported_image_models=[IMAGE_MODEL],
            supported_video_models=[VIDEO_MODEL],
            max_prompt_length=4096,
            requires_api_key=True,
            configurable_base_url=True,
            description="Agnes AI free-tier models: text, image & video generation. "
            "All three models are currently free.",
        )

    # ── Deployment / env key ─────────────────────────────────────────────

    @staticmethod
    def env_key_name() -> str:
        return "AGNES_API_KEY"

    @staticmethod
    def env_key_help() -> str:
        return (
            "Get a free API key from https://agnes-ai.com\n"
            "Set AGNES_API_KEY in your .env file or pass --api-key."
        )

    # ── Chat (text) ──────────────────────────────────────────────────────

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str = TEXT_MODEL,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        tools: Optional[list[dict]] = None,
        **kwargs: Any,
    ) -> dict:
        """Send a chat completion request.

        Args:
            messages: List of ``{"role": ..., "content": ...}`` dicts.
            model: Model name (default ``agnes-2.0-flash``).
            temperature: Sampling temperature (0.0–2.0).
            max_tokens: Max output tokens.
            stream: Enable streaming (not yet supported in this wrapper).
            tools: Tool definitions for function calling.

        Returns:
            The full API response dict.
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if stream:
            payload["stream"] = True
        if tools:
            payload["tools"] = tools

        response = await self._request("POST", AGNES_CHAT_ENDPOINT, json=payload)
        data = response.json()
        return data

    # ── Image generation ─────────────────────────────────────────────────

    async def generate_image(
        self,
        prompt: str,
        *,
        model: str = "",
        size: str = "1280x720",
        input_image_url: Optional[str] = None,
        **kwargs: Any,
    ) -> GenerationResult:
        """Generate an image from text (or transform an existing image).

        Args:
            prompt: Text description.
            model: Model name (default ``agnes-image-2.1-flash``).
            size: Output size (e.g. ``"1024x768"``).
            input_image_url: URL for image-to-image transformation.

        Returns:
            GenerationResult with the image bytes.
        """
        model = model or IMAGE_MODEL
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "size": size,
        }
        if input_image_url:
            payload.setdefault("extra_body", {})
            payload["extra_body"]["image"] = [input_image_url]
            payload["extra_body"]["response_format"] = "url"

        response = await self._request("POST", AGNES_IMAGE_ENDPOINT, json=payload)
        data = response.json()

        # Parse response - extract image URL or base64 data
        image_bytes = None
        if isinstance(data, dict):
            image_data_list = data.get("data", [])
            if image_data_list:
                first = image_data_list[0]
                if "url" in first:
                    # Download the image — URL is typically a signed GCS URL
                    # Use a clean client (no Agnes auth header) to avoid conflicts
                    dl_resp = await download_media(self.client, first["url"], timeout=5.0, authenticated=False)
                    if dl_resp.status_code == 401 and is_api_media_url(self.client, first["url"]):
                        # Retry with the Agnes auth (some endpoints need bearer)
                        dl_resp = await download_media(self.client, first["url"])
                    dl_resp.raise_for_status()
                    image_bytes = dl_resp.content
                elif "b64_json" in first:
                    image_bytes = base64.b64decode(first["b64_json"])

        if not image_bytes:
            raise ProviderError(
                f"Failed to extract image from Agnes response: {json.dumps(data)[:300]}",
                "agnes",
            )

        return GenerationResult(
            data=image_bytes,
            mime_type="image/png",
            metadata={"model": model, "size": size},
        )

    # ── Video generation ─────────────────────────────────────────────────

    async def _image_to_video(
        self,
        prompt: str,
        image_data: bytes,
        *,
        model: str = "",
        size: str = "1152x768",
        duration: int = 5,
        **kwargs: Any,
    ) -> GenerationResult:
        """Image → video via Agnes Video API."""
        model = model or VIDEO_MODEL

        # Upload the image to a temporary URL (or pass base64)
        # Agnes API expects a URL, so we upload via their image upload endpoint
        # or host the image. For simplicity, we encode as base64 data URL.
        image_b64 = base64.b64encode(image_data).decode("ascii")
        data_uri = f"data:image/png;base64,{image_b64}"

        # Agnes actually expects HTTP(S) URLs, not data URIs.
        # We need to either:
        #   1. Upload the image to a temporary hosting service, or
        #   2. Use a publicly accessible URL
        # For now, we'll try with the data URI, but if it fails, we fall back
        # to text-to-video (without reference image).
        try:
            return await self._submit_video(
                prompt=prompt,
                image_url=data_uri,
                model=model,
                size=size,
                duration=duration,
            )
        except ProviderError:
            logger.warning(
                "Image-to-video with data URI failed, "
                "falling back to text-to-video"
            )
            return await self._text_to_video(
                prompt, model=model, size=size, duration=duration
            )

    async def _text_to_video(
        self,
        prompt: str,
        *,
        model: str = "",
        size: str = "1152x768",
        duration: int = 5,
        **kwargs: Any,
    ) -> GenerationResult:
        """Text → video via Agnes Video API."""
        model = model or VIDEO_MODEL
        duration = int(round(duration))  # force int, prevent float

        # Calculate num_frames based on duration (must satisfy 8n+1, max 441)
        target_frames = duration * 24  # 24 fps, now duration is definitely int
        num_frames = self._clamp_frames(target_frames)

        height, width = self._parse_size(size)

        return await self._submit_video(
            prompt=prompt,
            model=model,
            height=height,
            width=width,
            num_frames=num_frames,
            frame_rate=24,
        )

    async def _submit_video(
        self,
        prompt: str,
        *,
        image_url: Optional[str] = None,
        model: str = VIDEO_MODEL,
        height: int = 768,
        width: int = 1152,
        num_frames: int = 121,
        frame_rate: int = 24,
        **kwargs: Any,
    ) -> GenerationResult:
        """Submit a video task and poll for completion."""
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "height": height,
            "width": width,
            "num_frames": num_frames,
            "frame_rate": frame_rate,
        }
        if image_url:
            payload["image"] = image_url

        logger.info("Submitting Agnes video task (model=%s) ...", model)
        response = await self._request("POST", AGNES_VIDEO_ENDPOINT, json=payload)
        data = response.json()

        task_id = None
        if isinstance(data, dict):
            task_id = data.get("id") or data.get("task_id")

        if not task_id:
            raise ProviderError(
                f"No task ID in Agnes video response: {json.dumps(data)[:300]}",
                "agnes",
            )

        logger.info("Video task submitted – task_id=%s", task_id)

        # Poll for completion
        start = time.monotonic()
        status_url = f"{AGNES_VIDEO_ENDPOINT}/{task_id}"

        while True:
            elapsed = time.monotonic() - start
            if elapsed > _POLL_TIMEOUT:
                raise ProviderError(
                    f"Video task {task_id} timed out after {_POLL_TIMEOUT:.0f}s",
                    "agnes",
                )

            await asyncio.sleep(_POLL_INTERVAL)
            status_resp = await self._request("GET", status_url)
            status_data = status_resp.json()

            if not isinstance(status_data, dict):
                continue

            status = (status_data.get("status") or "").lower()
            progress = status_data.get("progress", 0)

            logger.debug("Video task %s: status=%s progress=%d%%", task_id, status, progress)

            if status in ("completed", "success", "done"):
                # Extract video URL
                video_url = (
                    status_data.get("video_url")
                    or status_data.get("url")
                    or status_data.get("signed_url")
                    or status_data.get("download_url")
                    or status_data.get("remixed_from_video_id")
                )
                if not video_url:
                    raise ProviderError(
                        f"No video URL in completed response: {json.dumps(status_data)[:600]}",
                        "agnes",
                    )

                logger.info(
                    "Video completed. URL from API: %s ... | Full keys: %s",
                    video_url[:80], list(status_data.keys())
                )

                # ── Download the video with multiple strategies ──────────
                video_bytes: Optional[bytes] = None

                # Strategy 1: clean client (no auth – works for public GCS URLs)
                try:
                    resp1 = await download_media(self.client, video_url, timeout=60.0, authenticated=False)
                    if resp1.status_code == 200:
                        video_bytes = resp1.content
                    elif resp1.status_code == 401:
                        logger.info("Clean client got 401 on video URL")
                except Exception as e:
                    logger.warning("Clean client failed: %s", e)

                # Strategy 2: with Agnes auth only at its configured API origin
                if video_bytes is None and is_api_media_url(self.client, video_url):
                    try:
                        resp2 = await download_media(self.client, video_url)
                        if resp2.status_code == 200:
                            video_bytes = resp2.content
                        else:
                            logger.info("Auth client got HTTP %d on video URL", resp2.status_code)
                    except Exception as e:
                        logger.warning("Auth client failed: %s", e)

                # Strategy 3: download via Agnes API endpoint
                if video_bytes is None:
                    dl_endpoint = f"{AGNES_VIDEO_ENDPOINT}/{task_id}/download"
                    logger.info("Trying download via Agnes API: %s", dl_endpoint)
                    try:
                        resp3 = await self._request("GET", dl_endpoint)
                        if resp3.status_code == 200:
                            ct = resp3.headers.get("content-type", "")
                            if "video" in ct or len(resp3.content) > 1000:
                                video_bytes = resp3.content
                    except Exception as e:
                        logger.warning("API endpoint download failed: %s", e)

                # Strategy 4: try with ?alt=media (GCS convention)
                if video_bytes is None and "storage.googleapis.com" in video_url:
                    alt_url = video_url + "?alt=media"
                    logger.info("Trying GCS alt=media: %s", alt_url[:100])
                    try:
                        resp4 = await download_media(self.client, alt_url, timeout=60.0, authenticated=False)
                        if resp4.status_code == 200:
                            video_bytes = resp4.content
                    except Exception as e:
                        logger.warning("alt=media failed: %s", e)

                if video_bytes is None:
                    raise ProviderError(
                        f"Failed to download video (task={task_id}) — "
                        f"all download strategies returned non-200. "
                        f"URL: {video_url[:120]}",
                        "agnes",
                    )

                logger.info(
                    "✓ Video downloaded (%.1f MB)", len(video_bytes) / 1024 / 1024
                )
                # Calculate actual duration
                secs = float(status_data.get("seconds", num_frames / frame_rate))
                return GenerationResult(
                    data=video_bytes,
                    mime_type="video/mp4",
                    metadata={
                        "duration": secs,
                        "task_id": task_id,
                        "size": status_data.get("size", f"{width}x{height}"),
                    },
                )

            if status in ("failed", "error", "cancelled"):
                err_msg = status_data.get("error", status_data.get("message", "unknown"))
                raise ProviderError(
                    f"Video task {task_id} failed: {err_msg}", "agnes"
                )

    # ── Helpers ──────────────────────────────────────────────────────────

    async def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        """Make an HTTP request with intelligent retry logic.
        
        Uses exponential backoff with jitter for rate limiting (429)
        and transient server errors (5xx).
        """
        last_error = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self.client.request(method, path, **kwargs)
                
                # Check for business-level errors
                if response.status_code in (401, 403):
                    raise ProviderError(
                        f"Agnes API authentication failed (HTTP {response.status_code}). "
                        f"Check your AGNES_API_KEY.",
                        "agnes",
                    )
                if response.status_code == 429:
                    # Rate limited — use exponential backoff with jitter
                    delay = min(
                        _RETRY_DELAY_BASE * (2 ** attempt) + random.uniform(0, 1),
                        _RETRY_MAX_DELAY
                    )
                    logger.warning(
                        "Rate limited (429), retrying in %.1fs (%d/%d)...",
                        delay, attempt + 1, _MAX_RETRIES
                    )
                    await asyncio.sleep(delay)
                    continue
                    
                response.raise_for_status()
                return response
                
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code < 500:
                    raise ProviderError(
                        f"Agnes API error (HTTP {e.response.status_code}): "
                        f"{e.response.text[:300]}",
                        "agnes",
                    )
                # Server error (5xx) — retry with backoff
                delay = min(
                    _RETRY_DELAY_BASE * (2 ** attempt) + random.uniform(0, 1),
                    _RETRY_MAX_DELAY
                )
                logger.warning(
                    "Server error (HTTP %d), retrying in %.1fs (%d/%d)...",
                    e.response.status_code, delay, attempt + 1, _MAX_RETRIES
                )
                await asyncio.sleep(delay)
                
            except httpx.RequestError as e:
                last_error = e
                delay = min(
                    _RETRY_DELAY_BASE * (2 ** attempt) + random.uniform(0, 1),
                    _RETRY_MAX_DELAY
                )
                logger.warning(
                    "Request failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1, _MAX_RETRIES, e, delay
                )
                await asyncio.sleep(delay)

        raise ProviderError(
            f"Agnes request failed after {_MAX_RETRIES} attempts: {last_error}",
            "agnes"
        )

    @staticmethod
    def _clamp_frames(target: int) -> int:
        """Clamp frame count to satisfy 8n+1 ≤ 441."""
        target = int(target)  # ensure int, not float
        # Find n so that 8n+1 is closest to target
        n = max(1, (target - 1) // 8)
        frames = 8 * n + 1
        if frames > 441:
            frames = 441
        return frames

    @staticmethod
    def _parse_size(size: str) -> tuple[int, int]:
        """Parse 'WxH' string to (height, width)."""
        parts = size.lower().split("x")
        if len(parts) == 2:
            return int(parts[1]), int(parts[0])
        return 768, 1152  # default

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
