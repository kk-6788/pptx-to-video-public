"""
ComfyUI provider — connects to a local ComfyUI instance via its API.

This is the **free** option — runs entirely on your own hardware with
open-source models (Stable Diffusion, AnimateDiff, WAN, etc.).

Requirements
------------
- ComfyUI running locally (default: ``http://127.0.0.1:8188``)
- Appropriate workflow JSON files in the ``comfy_workflows/`` directory
- The ``websockets`` package (``pip install websockets``)

Configuration
-------------
Set these env vars or pass as constructor kwargs:

- ``COMFYUI_BASE_URL`` (default ``http://127.0.0.1:8188``)
- ``COMFYUI_IMAGE_WORKFLOW`` — path to the text→image workflow JSON
- ``COMFYUI_VIDEO_WORKFLOW`` — path to the image→video workflow JSON
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
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

_DEFAULT_BASE_URL = "http://127.0.0.1:8188"
_DEFAULT_IMAGE_WORKFLOW = "comfy_workflows/txt2img.json"
_DEFAULT_VIDEO_WORKFLOW = "comfy_workflows/img2video.json"
_POLL_INTERVAL = 1.0
_POLL_TIMEOUT = 600.0


class ComfyUIProvider(GenerationProvider):
    """Local ComfyUI image + video generation provider (free)."""

    def __init__(self, api_key: str = "", **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        self._base_url = (
            kwargs.get("base_url")
            or os.getenv("COMFYUI_BASE_URL", _DEFAULT_BASE_URL)
        ).rstrip("/")
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
        self._ws: Optional[Any] = None  # websocket, lazy-init'd

    @classmethod
    def capabilities(cls) -> ProviderCapabilities:
        return ProviderCapabilities(
            name="comfyui",
            display_name="ComfyUI (本地免费)",
            capabilities={
                ProviderCapability.TEXT_TO_IMAGE,
                ProviderCapability.IMAGE_TO_VIDEO,
                ProviderCapability.POLLING_STATUS,
            },
            default_image_model="sd3.5",
            default_video_model="wan2.1",
            supported_image_models=["sd3.5", "sdxl", "flux", "sd1.5"],
            supported_video_models=["wan2.1", "animatediff", "svd"],
            max_prompt_length=512,
            requires_api_key=False,
            configurable_base_url=True,
            description="本地 ComfyUI — 完全免费，依赖本地 GPU。支持 SD3.5 / FLUX / WAN2.1 等开源模型。"
                        "需预先安装 ComfyUI 并启动服务。",
        )

    async def generate_image(
        self,
        prompt: str,
        *,
        model: str = "",
        size: str = "1280x720",
        **kwargs: Any,
    ) -> GenerationResult:
        workflow_path = kwargs.get(
            "workflow",
            os.getenv("COMFYUI_IMAGE_WORKFLOW", _DEFAULT_IMAGE_WORKFLOW),
        )
        workflow = self._load_workflow(workflow_path)
        workflow = self._inject_prompt(workflow, prompt, size)

        logger.info("ComfyUI: submitting image workflow (%s)...", workflow_path)
        result = await self._run_workflow(workflow)
        logger.info("ComfyUI: image generated (%d bytes)", len(result))
        return GenerationResult(data=result, mime_type="image/png")

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
        workflow_path = kwargs.get(
            "workflow",
            os.getenv("COMFYUI_VIDEO_WORKFLOW", _DEFAULT_VIDEO_WORKFLOW),
        )
        workflow = self._load_workflow(workflow_path)
        workflow = self._inject_prompt(workflow, prompt, size)
        workflow = self._inject_image(workflow, image_data)

        logger.info("ComfyUI: submitting video workflow (%s)...", workflow_path)
        result = await self._run_workflow(workflow)
        logger.info("ComfyUI: video generated (%d bytes)", len(result))
        return GenerationResult(data=result, mime_type="video/mp4")

    async def _text_to_video(
        self,
        prompt: str,
        *,
        model: str = "",
        size: str = "1280x720",
        duration: int = 5,
        **kwargs: Any,
    ) -> GenerationResult:
        # Some ComfyUI workflows can do text→video directly (e.g. WAN T2V)
        workflow_path = kwargs.get(
            "workflow",
            os.getenv("COMFYUI_VIDEO_WORKFLOW", _DEFAULT_VIDEO_WORKFLOW),
        )
        workflow = self._load_workflow(workflow_path)
        workflow = self._inject_prompt(workflow, prompt, size)

        logger.info("ComfyUI: submitting text-to-video workflow...")
        result = await self._run_workflow(workflow)
        logger.info("ComfyUI: video generated (%d bytes)", len(result))
        return GenerationResult(data=result, mime_type="video/mp4")

    # ── Workflow helpers ────────────────────────────────────────────────

    @staticmethod
    def _load_workflow(path: str) -> dict[str, Any]:
        """Load a ComfyUI workflow JSON file."""
        p = Path(path)
        if not p.exists():
            # Try relative to the project root
            p = Path(__file__).resolve().parent.parent / path
        if not p.exists():
            raise ProviderError(
                f"ComfyUI workflow not found: {path}. "
                f"Please set COMFYUI_IMAGE_WORKFLOW / COMFYUI_VIDEO_WORKFLOW "
                f"env vars or create the workflow file.",
                "comfyui",
            )
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _inject_prompt(
        workflow: dict[str, Any],
        prompt: str,
        size: str,
    ) -> dict[str, Any]:
        """Find and replace the prompt node in the workflow."""
        w, h = map(int, size.split("x"))
        modified = 0
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs", {})
            if isinstance(inputs, dict):
                if "text" in inputs and isinstance(inputs["text"], str) and len(inputs["text"]) < len(prompt) + 50:
                    inputs["text"] = prompt
                    modified += 1
                    logger.debug("ComfyUI: injected prompt into node %s", node_id)
                if "width" in inputs and isinstance(inputs["width"], (int, float)):
                    inputs["width"] = w
                if "height" in inputs and isinstance(inputs["height"], (int, float)):
                    inputs["height"] = h
                # Also handle CLIPTextEncode style nodes
                if "clip" in inputs and isinstance(inputs, dict):
                    pass
        if modified == 0:
            logger.warning("ComfyUI: could not find a text input node in workflow — prompt may not be injected")
        return workflow

    @staticmethod
    def _inject_image(workflow: dict[str, Any], image_bytes: bytes) -> dict[str, Any]:
        """Inject image data into the workflow (for image→video)."""
        import base64
        b64 = base64.b64encode(image_bytes).decode("ascii")
        found = 0
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs", {})
            if isinstance(inputs, dict) and "image" in inputs and isinstance(inputs["image"], str):
                if inputs["image"].startswith("data:") or not inputs["image"].startswith("http"):
                    inputs["image"] = f"data:image/png;base64,{b64}"
                    found += 1
        if found == 0:
            logger.warning("ComfyUI: could not find image input node — image may not be injected")
        return workflow

    # ── Queue & poll ────────────────────────────────────────────────────

    async def _run_workflow(self, workflow: dict[str, Any]) -> bytes:
        """Queue a workflow on ComfyUI and wait for it to complete.

        Returns the raw bytes of the first output image/video.
        """
        client_id = str(uuid.uuid4())

        # Queue
        resp = await self._client.post(
            f"{self._base_url}/prompt",
            json={"prompt": workflow, "client_id": client_id},
        )
        resp.raise_for_status()
        prompt_data = resp.json()
        prompt_id = prompt_data.get("prompt_id")
        if not prompt_id:
            raise ProviderError(f"ComfyUI queue failed: {resp.text[:300]}", "comfyui")

        logger.info("ComfyUI workflow queued – prompt_id=%s", prompt_id)

        # Poll
        start = asyncio.get_event_loop().time()
        history_url = f"{self._base_url}/history/{prompt_id}"
        while True:
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed > _POLL_TIMEOUT:
                raise ProviderError(f"ComfyUI workflow {prompt_id} timed out", "comfyui")

            await asyncio.sleep(_POLL_INTERVAL)
            hist_resp = await self._client.get(history_url)
            if hist_resp.status_code != 200:
                continue

            history = hist_resp.json()
            prompt_history = history.get(prompt_id)
            if not prompt_history:
                continue

            outputs = prompt_history.get("outputs", {})
            if not outputs:
                continue

            # Find the first output file
            for node_id, node_outputs in outputs.items():
                if isinstance(node_outputs, dict):
                    for media_list in node_outputs.values():
                        if isinstance(media_list, list):
                            for media_item in media_list:
                                if isinstance(media_item, dict):
                                    filename = media_item.get("filename")
                                    subfolder = media_item.get("subfolder", "")
                                    folder = media_item.get("type", "output")
                                    if filename:
                                        # Download
                                        dl = await self._client.get(
                                            f"{self._base_url}/view",
                                            params={
                                                "filename": filename,
                                                "subfolder": subfolder,
                                                "type": folder,
                                            },
                                        )
                                        if dl.status_code == 200:
                                            logger.info("ComfyUI: downloaded %s (%d bytes)", filename, len(dl.content))
                                            return dl.content

            raise ProviderError(
                f"ComfyUI completed but no output file found: {json.dumps(outputs)[:300]}",
                "comfyui",
            )

    async def close(self) -> None:
        await self._client.aclose()
        logger.debug("ComfyUI HTTP client closed")
