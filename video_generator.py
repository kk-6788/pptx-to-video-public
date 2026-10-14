#!/usr/bin/env python3
"""
Video generator — orchestrates multi-provider, director-style video generation.

Flow
----
1. Parse PPTX → list of Slide
2. Director generates scene plans (image + video prompts)
3. *(optional)* User reviews & confirms prompts
4. For each slide:
   - If slide has images → use them directly
   - Otherwise → generate image(s) via provider
   - Generate video (image→video) via provider
5. Return list of GeneratedClip for composition

Supports multiple providers out of the box:
- ``siliconflow`` — cloud API (default)
- ``comfyui`` — local, free (needs ComfyUI running)
- ``custom_api`` — any OpenAI-compatible endpoint
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import subprocess
import json
import logging
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

import config
from pptx_parser import Slide


# ── Helpers ─────────────────────────────────────────────────────────────

async def _await_with_stop(awaitable, stop_event: threading.Event | None, poll_s: float = 1.0):
    """Await a coroutine with periodic stop_event checks.

    Wraps the coroutine in a task and polls every *poll_s* seconds.
    If stop_event is set, cancels the task and raises asyncio.CancelledError.
    """
    if stop_event is None:
        return await awaitable
    task = asyncio.create_task(awaitable)
    while True:
        done, _ = await asyncio.wait([task], timeout=poll_s)
        if done:
            return task.result()
        if stop_event.is_set():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            raise asyncio.CancelledError("User stopped")

from prompt_engine import Director, EnhancedScenePlan, ScenePlan, generate_scene_plans, PromptSimplifier
from providers import GenerationProvider, GenerationResult, get_provider
from providers.base import AcceptedTaskError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class GeneratedClip:
    """Result of a successful video-generation task for one slide."""

    slide_index: int
    file_path: str
    duration: float = 5.0
    """Actual duration of the generated video clip (seconds)."""
    planned_duration: float = 5.0
    """Duration planned by ScriptWriter (used to speed-adjust in compose)."""
    keyframe_count: int = 1
    """Number of keyframe images generated for this slide (1 for legacy ScenePlan)."""
    keyframe_paths: list[str] = field(default_factory=list)
    """Paths to all saved keyframe images (empty for legacy ScenePlan)."""


def _media_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _is_decodable_video(path) -> bool:
    """PPT-02: verify the file is a real, decodable video before it can enter
    (or be served from) the visual cache. A hash match only proves bytes are
    unchanged — not that they form a playable MP4 (HTML error pages, truncated
    downloads and zero-stream files previously passed the non-empty check)."""
    ffprobe = shutil.which('ffprobe')
    if ffprobe is None:
        # No ffprobe available: fall back to the mp4 signature so we at least
        # reject HTML/JSON error bodies. Log once so operators know the check
        # is degraded.
        logger.debug("ffprobe not found; using container signature fallback")
        try:
            with Path(path).open('rb') as fh:
                return fh.read(12).startswith(b'\x00\x00\x00\x18ftypmp4') or b'ftyp' in fh.read(28)
        except OSError:
            return False
    try:
        result = subprocess.run(
            [ffprobe, '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'format=format_name,duration:stream=codec_type,width,height',
             '-of', 'json', str(path)],
            capture_output=True, timeout=30,
        )
        if result.returncode != 0:
            return False
        import json as _json
        info = _json.loads(result.stdout.decode('utf-8', 'replace'))
        fmt = info.get('format') or {}
        streams = info.get('streams') or []
        if not any(s.get('codec_type') == 'video' for s in streams):
            return False
        duration = float(fmt.get('duration') or 0.0)
        return duration > 0 and (fmt.get('format_name') or '') != ''
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def _visual_cache_key(plan, slides_by_index, image_provider, video_provider, use_slide_images):
    """Fingerprint visual inputs only; never serialize provider credentials."""
    def identity(provider):
        # PPT-03: prefer the public cache_identity() contract; fall back to the
        # legacy attribute probe only for third-party providers that predate it.
        contract = getattr(provider, 'cache_identity', None)
        if callable(contract):
            values = dict(contract())
        else:
            values = {'class': f'{type(provider).__module__}.{type(provider).__qualname__}',
                      'name': getattr(provider, 'name', '')}
            for field_name in ('image_model', 'video_model', 'model'):
                value = getattr(provider, '_' + field_name, getattr(provider, field_name, ''))
                if isinstance(value, (str, int, float, bool)):
                    values[field_name] = value
            endpoint = getattr(provider, '_base_url', getattr(provider, 'base_url', ''))
            if endpoint:
                endpoint = urlsplit(str(endpoint))
                # Userinfo, queries and fragments may contain credentials.
                values['endpoint'] = [endpoint.scheme, endpoint.hostname, endpoint.port, endpoint.path]
        if values.get('name', getattr(provider, 'name', '')) == 'comfyui':
            for kind, default in [('IMAGE', 'txt2img'), ('VIDEO', 'img2video')]:
                workflow = Path(os.getenv(f'COMFYUI_{kind}_WORKFLOW', f'comfy_workflows/{default}.json'))
                values[kind + '_workflow'] = _media_hash(workflow) if workflow.is_file() else None
        return values

    sources = []
    for index in (getattr(plan, 'slide_indices', None) or [plan.slide_index]):
        slide = slides_by_index.get(index)
        if slide is None:
            sources.append({'index': index, 'missing': True})
            continue
        sources.append({'index': index, 'title': slide.title, 'body': slide.body,
                        'text_content': slide.text_content, 'notes': slide.notes,
                        'images': [_media_hash(path) if Path(path).is_file() else None
                                   for path in slide.image_paths]})
    visual = {name: getattr(plan, name, None) for name in
              ('image_prompt', 'image_prompts', 'video_prompt')}
    duration = (plan.suggested_duration_sec if isinstance(plan, EnhancedScenePlan)
                and plan.suggested_duration_sec else int(config.VIDEO_DURATION))
    payload = {'version': 1, 'slide_index': plan.slide_index, 'sources': sources, 'visual': visual,
               'image_provider': identity(image_provider), 'video_provider': identity(video_provider),
               'size': config.VIDEO_SIZE, 'duration': duration, 'use_slide_images': use_slide_images}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def _read_visual_cache(directory, cache_key):
    try:
        saved = json.loads((directory / 'visual-cache.json').read_text(encoding='utf-8'))
        if saved['version'] != 1 or saved['key'] != cache_key:
            return None
        clip = GeneratedClip(**saved['clip'])
        paths = [clip.file_path, *clip.keyframe_paths]
        if len(saved['media']) != len(paths):
            return None
        for path in paths:
            item = Path(path).resolve()
            if item.parent != directory.resolve() or not item.is_file() or item.stat().st_size == 0:
                return None
            if _media_hash(item) != saved['media'][path]:
                return None
        # PPT-02: hash equality only proves bytes are unchanged. The main clip
        # must also be a decodable video; a poisoned cache entry is invalidated
        # here instead of being served into composition.
        if not _is_decodable_video(clip.file_path):
            logger.warning("Cached video %s failed decode validation; invalidating cache entry",
                           clip.file_path)
            return None
        return clip
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _save_visual_cache(directory, cache_key, clip):
    paths = [clip.file_path, *clip.keyframe_paths]
    if any(not Path(path).is_file() or Path(path).stat().st_size == 0 for path in paths):
        return
    # PPT-02: publish only decodable videos into the cache — an HTML error page
    # or truncated MP4 must never become a "valid" cache hit later.
    if not _is_decodable_video(clip.file_path):
        logger.warning("Refusing to cache %s: not a decodable video", clip.file_path)
        return
    payload = {'version': 1, 'key': cache_key, 'clip': asdict(clip),
               'media': {path: _media_hash(path) for path in paths}}
    temporary = directory / ('.visual-cache-' + uuid.uuid4().hex + '.json')
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(directory / 'visual-cache.json')
    finally:
        temporary.unlink(missing_ok=True)


@dataclass
class SlideGenerationState:
    """Internal state for tracking per-slide generation progress."""

    slide: Slide
    plan: ScenePlan | EnhancedScenePlan
    image_data: Optional[bytes] = None
    keyframe_images: list[bytes] = field(default_factory=list)
    clip: Optional[GeneratedClip] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Progress callback type
# ---------------------------------------------------------------------------

ProgressCallback = Callable[[int, int, str], None]
"""Signature: ``(current_step, total_steps, message)``

Useful for GUI progress bars and status updates."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def generate_images_for_slide(
    slide: Slide,
    plan: ScenePlan | EnhancedScenePlan,
    *,
    image_provider: GenerationProvider,
    output_dir: Path,
    use_slide_images: bool = True,
    step_num: int = 0,
    total: int = 0,
    progress_callback: Optional[ProgressCallback] = None,
) -> tuple[Optional[bytes], list[bytes]]:
    """Generate all keyframe images for one slide.

    For :class:`EnhancedScenePlan` with multiple ``image_prompts``, generates
    one image per prompt.  For legacy :class:`ScenePlan`, generates a single
    image from ``image_prompt``.

    Args:
        slide: The parsed slide.
        plan: The scene plan (legacy or enhanced).
        image_provider: An initialised :class:`GenerationProvider` for image generation.
        output_dir: Directory to save intermediate keyframe images.
        use_slide_images: If True, prefer images already in the slide.
        step_num: Current step index for progress reporting.
        total: Total steps for progress reporting.
        progress_callback: Optional progress callback.

    Returns:
        A tuple of ``(primary_image_data, list_of_all_keyframe_image_data)``.
        The primary image is the first keyframe (used for video generation).
    """
    # ── Prefer slide images ──────────────────────────────────────────────
    if use_slide_images and slide.image_paths:
        img_path = Path(slide.image_paths[0])
        if img_path.exists():
            logger.info(
                "Slide %d: using existing image %s", slide.index, img_path.name
            )
            data = img_path.read_bytes()
            if progress_callback:
                progress_callback(
                    step_num, total, f"Slide {slide.index}: using slide image..."
                )
            return data, [data]

    # ── Determine prompts ────────────────────────────────────────────────
    if isinstance(plan, EnhancedScenePlan) and plan.image_prompts:
        prompts = plan.image_prompts
        logger.info(
            "Slide %d: generating %d keyframe images...",
            slide.index,
            len(prompts),
        )
    else:
        # Legacy ScenePlan — single prompt
        prompts = [plan.image_prompt] if plan.image_prompt else []

    if not prompts:
        return None, []

    # ── Generate all keyframe images ─────────────────────────────────────
    keyframe_images: list[bytes] = []
    for idx, prompt in enumerate(prompts):
        if progress_callback:
            msg = (
                f"Slide {slide.index}: generating image {idx + 1}/{len(prompts)}..."
                if len(prompts) > 1
                else f"Slide {slide.index}: generating image..."
            )
            progress_callback(step_num, total, msg)

        logger.info(
            "Slide %d: generating keyframe %d/%d...",
            slide.index,
            idx + 1,
            len(prompts),
        )
        # ── Simplify prompt for non-LLM generation models (e.g. Agnes) ──
        simplified_prompt = PromptSimplifier.simplify_image_prompt(prompt, provider_name=getattr(image_provider, 'name', ''))
        logger.debug(
            "Slide %d: simplified prompt (%d chars): %s",
            slide.index, len(simplified_prompt), simplified_prompt[:100],
        )
        img_result: GenerationResult = await image_provider.generate_image(
            prompt=simplified_prompt,
            size=config.VIDEO_SIZE,
        )
        keyframe_images.append(img_result.data)

        # Save keyframe image to disk (for later reference / multi-angle context)
        if len(prompts) > 1:
            kf_path = output_dir / f"slide{slide.index:02d}_kf{idx:02d}.png"
        else:
            kf_path = output_dir / f"slide{slide.index:02d}_kf00.png"
        kf_path.write_bytes(img_result.data)

        logger.info(
            "Slide %d: keyframe %d generated (%d bytes)",
            slide.index,
            idx + 1,
            len(img_result.data),
        )

    primary = keyframe_images[0] if keyframe_images else None
    return primary, keyframe_images


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------


async def generate_scene_plans_only(
    slides: list[Slide],
    style: str | dict[str, str] = "auto",
    overall_theme: str = "",
    validate_prompts: bool = True,
) -> list[ScenePlan]:
    """Generate scene plans **without** running any generation.

    This is the "preview" step — call this first, show the plans to the
    user, let them edit, then pass to :func:`generate_clips_from_plans`.

    Args:
        slides: Parsed slides.
        style: Visual style name or custom dict.
        overall_theme: Optional high-level theme.
        validate_prompts: Run PromptValidator on generated prompts.

    Returns:
        List of :class:`ScenePlan` objects (some may be :class:`EnhancedScenePlan`).
    """
    from prompt_engine import PromptValidator
    director = Director(slides, style=style, overall_theme=overall_theme)
    plans = director.plan()
    logger.info("Scene plans generated for %d slides", len(plans))

    if validate_prompts:
        validation = PromptValidator.validate_all(plans)
        logger.info(
            "Prompt validation: image %s passed, video %s passed (%d slides)",
            validation["image_pass_rate"], validation["video_pass_rate"],
            validation["total_slides"],
        )
        # Log issues/warnings at debug
        for report in validation["reports"]:
            for key in ("image", "video"):
                r = report[key]
                if r["issues"]:
                    logger.debug(
                        "Slide %d %s issues: %s",
                        report["slide"], key, "; ".join(r["issues"]),
                    )
                if r["warnings"]:
                    logger.debug(
                        "Slide %d %s warnings: %s",
                        report["slide"], key, "; ".join(r["warnings"]),
                    )

    return plans


async def generate_clips_from_plans(
    slides: list[Slide],
    plans: list[ScenePlan] | None,
    *,
    image_provider: GenerationProvider,
    video_provider: GenerationProvider,
    output_dir: Path,
    max_concurrent: int = 3,
    progress_callback: Optional[ProgressCallback] = None,
    use_slide_images: bool = True,
    stop_event: Optional[threading.Event] = None,
) -> list[GeneratedClip]:
    """Generate video clips from pre-existing scene plans.

    This is the "confirm" step — run this after the user has approved the
    prompts (or after :func:`generate_scene_plans_only`).

    Args:
        slides: Parsed slides (in order).
        plans: Scene plans from the Director. If ``None``, generates on the fly.
        image_provider: An initialised :class:`GenerationProvider` for image generation.
        video_provider: An initialised :class:`GenerationProvider` for video generation.
        output_dir: Directory to save generated clips.
        max_concurrent: Max concurrent API/image generation calls.
        progress_callback: Optional progress callback.
        use_slide_images: If True, prefer images already in the slide.

    Returns:
        List of successfully generated clips.
    """
    clips_dir = output_dir / "visual-cache"
    clips_dir.mkdir(parents=True, exist_ok=True)

    # Build scene plans if not provided
    if plans is None:
        plans = await generate_scene_plans_only(slides)

    modes = {getattr(plan, "visual_mode", "creative") for plan in plans}
    if "faithful" in modes:
        if modes != {"faithful"}:
            raise ValueError("Cannot mix faithful and creative scene plans")
        from faithful_plan import audit_faithful_plans
        audit_faithful_plans(slides, plans)
        logger.info("忠实计划由内容渲染器制作，跳过所有图像和视频生成接口")
        return []

    # Sort plans by slide_index to maintain order
    sorted_plans = sorted(plans, key=lambda p: p.slide_index)

    slides_by_index = {slide.index: slide for slide in slides}

    non_retryable: set[int] = set()
    sem = asyncio.Semaphore(max_concurrent)
    total = len(plans)  # Use plan count, not slide count (ScriptWriter may merge slides)

    async def _process_plan(plan: ScenePlan, idx: int) -> Optional[GeneratedClip]:
        """Process a single scene plan into a clip."""
        # ── Check stop before starting ──
        if stop_event and stop_event.is_set():
            raise asyncio.CancelledError("User stopped")

        async with sem:
            slide_idx = plan.slide_index
            slide = slides_by_index.get(slide_idx)
            if slide is None:
                logger.warning("Scene references missing slide %s; skipping", slide_idx)
                return None

            step_num = idx + 1

            # Detect if this is an enhanced plan with multiple prompts
            is_enhanced = isinstance(plan, EnhancedScenePlan) and bool(plan.image_prompts)
            num_keyframes = len(plan.image_prompts) if is_enhanced else 1

            # Notify
            if progress_callback:
                progress_callback(
                    step_num, total, f"Scene {step_num}: generating..."
                )

            try:
                cache_key = _visual_cache_key(plan, slides_by_index, image_provider,
                                              video_provider, use_slide_images)
                scene_dir = clips_dir / cache_key
                cached = _read_visual_cache(scene_dir, cache_key)
                if cached is not None:
                    if progress_callback:
                        progress_callback(step_num, total, f'✓ Slide {slide.index}: 复用已有画面')
                    return cached
                scene_dir.mkdir(parents=True, exist_ok=True)
                # ── Check stop before image generation ──
                if stop_event and stop_event.is_set():
                    raise asyncio.CancelledError("User stopped")

                # ── Step A: Get image(s) ──
                primary_image_data: Optional[bytes] = None
                all_keyframe_data: list[bytes] = []

                if is_enhanced:
                    # Multi-keyframe enhanced flow
                    primary_image_data, all_keyframe_data = await _await_with_stop(
                        generate_images_for_slide(
                            slide,
                            plan,
                            image_provider=image_provider,
                            output_dir=scene_dir,
                            use_slide_images=use_slide_images,
                            step_num=step_num,
                            total=total,
                            progress_callback=progress_callback,
                        ), stop_event, poll_s=1.0,
                    )
                else:
                    # Legacy single-image flow
                    if use_slide_images and slide.image_paths:
                        img_path = Path(slide.image_paths[0])
                        if img_path.exists():
                            logger.info(
                                "Slide %d: using existing image %s",
                                slide.index,
                                img_path.name,
                            )
                            primary_image_data = img_path.read_bytes()
                            all_keyframe_data = [primary_image_data]
                            if progress_callback:
                                progress_callback(
                                    step_num,
                                    total,
                                    f"Slide {slide.index}: using slide image...",
                                )
                    else:
                        if progress_callback:
                            progress_callback(
                                step_num,
                                total,
                                f"Slide {slide.index}: generating image...",
                            )
                        # Simplify for non-LLM models
                        _simple_img = PromptSimplifier.simplify_image_prompt(plan.image_prompt, provider_name=getattr(image_provider, 'name', ''))
                        logger.info("Slide %d: simplified image prompt (%d chars)",
                                    slide.index, len(_simple_img))
                        img_result: GenerationResult = await _await_with_stop(
                            image_provider.generate_image(
                                prompt=_simple_img,
                                size=config.VIDEO_SIZE,
                            ), stop_event, poll_s=1.0,
                        )
                        primary_image_data = img_result.data
                        all_keyframe_data = [primary_image_data]
                        logger.info(
                            "Slide %d: image generated (%d bytes)",
                            slide.index,
                            len(primary_image_data),
                        )

                # ── Check stop before video generation ──
                if stop_event and stop_event.is_set():
                    raise asyncio.CancelledError("User stopped")

                # ── Step B: Generate video from primary image ──
                if progress_callback:
                    progress_callback(
                        step_num, total, f"Slide {slide.index}: generating video..."
                    )
                logger.info("Slide %d: generating video...", slide.index)

                # Determine video prompt and duration from plan
                video_prompt = plan.video_prompt
                # Simplify for non-LLM generation models (e.g. Agnes)
                video_prompt = PromptSimplifier.simplify_video_prompt(video_prompt, provider_name=getattr(video_provider, 'name', ''))
                logger.info(
                    "Slide %d: simplified video prompt (%d chars)",
                    slide.index, len(video_prompt),
                )
                duration = (
                    plan.suggested_duration_sec
                    if isinstance(plan, EnhancedScenePlan) and plan.suggested_duration_sec
                    else int(config.VIDEO_DURATION)
                )

                if is_enhanced and len(all_keyframe_data) > 1:
                    # Pass all angle images as context (metadata)
                    # The first image is used as the primary frame; additional
                    # keyframes are provided as reference via kwargs
                    video_result: GenerationResult = await _await_with_stop(
                        video_provider.generate_video(
                            prompt=video_prompt,
                            image_data=primary_image_data,
                            size=config.VIDEO_SIZE,
                            duration=duration,
                            reference_images=all_keyframe_data[1:],
                        ), stop_event, poll_s=1.0,
                    )
                elif primary_image_data is not None:
                    video_result = await _await_with_stop(
                        video_provider.generate_video(
                            prompt=video_prompt,
                            image_data=primary_image_data,
                            size=config.VIDEO_SIZE,
                            duration=duration,
                        ), stop_event, poll_s=1.0,
                    )
                else:
                    # Text→video directly (no image)
                    video_result = await _await_with_stop(
                        video_provider.generate_video(
                            prompt=video_prompt,
                            image_data=None,
                            size=config.VIDEO_SIZE,
                            duration=duration,
                        ), stop_event, poll_s=1.0,
                    )

                # A completed generation must not be charged again if local saving fails.
                non_retryable.add(idx)

                # ── Step C: Save video ──
                clip_path = scene_dir / f"slide{slide.index:02d}.mp4"
                clip_path.write_bytes(video_result.data)

                # ── Validate video data ──
                if len(video_result.data) < 1024:  # <1KB = almost certainly corrupt/empty
                    logger.warning(
                        "Slide %d: generated video is suspiciously small (%d bytes), may be blank",
                        slide.index, len(video_result.data),
                    )
                    if progress_callback:
                        progress_callback(
                            step_num, total,
                            f"⚠ Slide {slide.index}: video too small ({len(video_result.data)} bytes)",
                        )
                    # Still keep the file — compose will handle it as-is

                actual_duration = video_result.metadata.get(
                    "duration", float(duration)
                )
                logger.info(
                    "✓ Slide %d complete (%.1fs, %d bytes)",
                    slide.index, actual_duration, len(video_result.data),
                )

                if progress_callback:
                    progress_callback(
                        step_num, total, f"✓ Slide {slide.index} done"
                    )

                # Build keyframe path list
                keyframe_paths: list[str] = []
                if is_enhanced:
                    for kf_idx in range(num_keyframes):
                        kf_path = scene_dir / f"slide{slide.index:02d}_kf{kf_idx:02d}.png"
                        if kf_path.exists():
                            keyframe_paths.append(str(kf_path.resolve()))

                clip = GeneratedClip(
                    slide_index=slide.index,
                    file_path=str(clip_path.resolve()),
                    duration=actual_duration,
                    planned_duration=duration,
                    keyframe_count=num_keyframes,
                    keyframe_paths=keyframe_paths,
                )
                try:
                    _save_visual_cache(scene_dir, cache_key, clip)
                except OSError as exc:
                    logger.warning('Slide %d: cache could not be saved: %s', slide.index, exc)
                return clip

            except Exception as exc:
                failure_message = f"✗ Slide {slide.index} failed: {exc}"
                if isinstance(exc, AcceptedTaskError):
                    non_retryable.add(idx)
                    # Retain recovery identifiers beside the scene; never retain
                    # bearer credentials or signed download URLs on disk.
                    recovery_path = scene_dir / 'accepted-task.json'
                    recovery_notice = f"恢复记录：{recovery_path}。"
                    try:
                        recovery_path.write_text(json.dumps({
                            'provider': exc.provider, 'request_id': exc.request_id,
                            'model': exc.model, 'state': 'accepted_result_unavailable',
                        }, ensure_ascii=False), encoding='utf-8')
                    except OSError as save_exc:
                        logger.warning('Could not save task recovery ID: %s', save_exc)
                        recovery_notice = "恢复记录未能保存，请保留此任务号。"
                    failure_message = (
                        f"✗ Slide {slide.index}：服务商 {exc.provider} 已受理任务，"
                        f"结果暂未取回；已停止自动重提。任务号：{exc.request_id}。"
                        f"{recovery_notice}请先在服务商确认任务状态及结果；"
                        "重新生成可能重复计费。"
                    )
                logger.error("%s", failure_message)
                if progress_callback:
                    progress_callback(
                        step_num, total, failure_message
                    )
                return None

    # Process all plans (with ScriptWriter, plans may merge multiple slides)
    sorted_plans = sorted(plans, key=lambda p: p.slide_index)
    tasks = [_process_plan(plan, i) for i, plan in enumerate(sorted_plans)]
    results: list[Optional[GeneratedClip]] = [None] * len(tasks)  # ← pre-allocate so CancelledError doesn't cause NameError
    try:
        results = await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.warning("Generation cancelled by user")
        return [r for r in results if r is not None]

    clips = [r for r in results if r is not None]

    # ── Retry failed plans with exponential backoff ──
    MAX_RETRIES = 2
    for retry_num in range(MAX_RETRIES):
        if stop_event and stop_event.is_set():
            logger.warning("Generation cancelled during retry")
            break
        failed_indices = [i for i, r in enumerate(results) if r is None and i not in non_retryable]
        if not failed_indices:
            break

        # Exponential backoff: 2s, 4s, ...
        backoff = 2.0 * (retry_num + 1)
        logger.info(
            "Retrying %d failed plan(s) in %.0fs (attempt %d/%d)...",
            len(failed_indices), backoff, retry_num + 1, MAX_RETRIES,
        )
        if progress_callback:
            progress_callback(
                0, len(failed_indices),
                f"🔄 Retrying {len(failed_indices)} failed scenes ({retry_num + 1}/{MAX_RETRIES})...",
            )

        await asyncio.sleep(backoff)  # ← exponential backoff

        retry_tasks = [_process_plan(sorted_plans[i], i) for i in failed_indices]
        retry_results = await asyncio.gather(*retry_tasks)

        for i, r in zip(failed_indices, retry_results):
            if r is not None:
                clips.append(r)
                results[i] = r  # mark as recovered

    if None in results:
        n_failed = sum(1 for r in results if r is None)
        logger.warning(
            "%d scene(s) still failed after all retries", n_failed,
        )

    logger.info(
        "Generation complete: %d/%d scenes succeeded",
        len(clips), len(plans),
    )
    return clips


# ── All-in-one convenience ──────────────────────────────────────────────


async def generate_clips(
    slides: list[Slide],
    *,
    provider_name: str = "siliconflow",
    image_provider_name: str = "",
    video_provider_name: str = "",
    provider_kwargs: dict[str, Any] | None = None,
    style: str | dict[str, str] = "auto",
    overall_theme: str = "",
    max_concurrent: Optional[int] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> list[GeneratedClip]:
    """Full pipeline: plan → generate → return clips.

    This is a convenience wrapper that does everything in one call
    (no user confirmation step).  For the interactive flow, use
    :func:`generate_scene_plans_only` + :func:`generate_clips_from_plans`.

    Args:
        slides: Parsed slides.
        provider_name: Legacy single provider name (used if both
            *image_provider_name* and *video_provider_name* are empty).
        image_provider_name: Provider name for image generation.
        video_provider_name: Provider name for video generation.
        provider_kwargs: Additional provider init kwargs (model, base_url, etc.).
        style: Visual style for the Director.
        overall_theme: Optional theme description.
        max_concurrent: Max concurrent API operations.
        progress_callback: Optional progress callback.

    Returns:
        List of generated clips.
    """
    if provider_kwargs is None:
        provider_kwargs = {}

    # Resolve provider names — backward compat: if only provider_name is set, use it for both
    if not image_provider_name and not video_provider_name:
        image_provider_name = provider_name
        video_provider_name = provider_name

    # Resolve API keys
    import os as _os
    from providers import get_providers

    # Build api_keys dict from environment variables
    api_keys: dict[str, str] = {}
    key_env_map = {
        "siliconflow": "SILICONFLOW_API_KEY",
        "agnes": "AGNES_API_KEY",
        "kling": "KLING_API_KEY",
        "volcengine": "VOLC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }
    for prov_name in [image_provider_name, video_provider_name]:
        env_var = key_env_map.get(prov_name, "")
        if env_var:
            key = _os.getenv(env_var, "")
            if key:
                api_keys[prov_name] = key

    # Also try config.resolve_api_key for siliconflow
    if image_provider_name == "siliconflow" or video_provider_name == "siliconflow":
        try:
            sf_key = config.resolve_api_key(interactive=False)
            if sf_key:
                api_keys["siliconflow"] = sf_key
        except RuntimeError:
            pass  # Will be caught by provider init

    # Split provider_kwargs if needed for different providers
    image_prov, video_prov = get_providers(
        image_provider=image_provider_name,
        video_provider=video_provider_name,
        api_keys=api_keys,
        image_kwargs=provider_kwargs,
        video_kwargs=provider_kwargs,
    )
    temp_dir = config.ensure_temp_dir()

    try:
        plans = await generate_scene_plans_only(slides, style=style, overall_theme=overall_theme)
        clips = await generate_clips_from_plans(
            slides,
            plans,
            image_provider=image_prov,
            video_provider=video_prov,
            output_dir=temp_dir,
            max_concurrent=max_concurrent or config.MAX_CONCURRENT,
            progress_callback=progress_callback,
        )
        return clips
    finally:
        await image_prov.close()
        if video_prov is not image_prov:
            await video_prov.close()


async def cleanup_temp_files() -> None:
    """Remove temporary files, retaining the persistent visual cache.

    Retries on PermissionError (Windows file locks from ffmpeg subprocesses).
    """
    temp_dir = config.TEMP_DIR.resolve()
    if not temp_dir.exists():
        return
    import shutil
    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            for child in temp_dir.iterdir():
                # work also contains saved scripts, source images and verification
                # artifacts. Only our disposable staging directories may be removed.
                if not child.name.startswith('.pptx2vid_'):
                    continue
                # Check resolved targets before any recursive operation.
                if child.is_symlink():
                    child.unlink()
                elif child.is_dir():
                    if not child.resolve().is_relative_to(temp_dir):
                        logger.warning('Skipping temporary directory outside work root: %s', child)
                        continue
                    shutil.rmtree(child)
                else:
                    child.unlink()
            logger.info("Temporary files cleaned up")
            return
        except PermissionError:
            if attempt < max_attempts - 1:
                wait = (attempt + 1) * 0.5
                logger.warning(
                    "Temp dir locked, retrying in %.1fs (attempt %d/%d)...",
                    wait, attempt + 1, max_attempts,
                )
                await asyncio.sleep(wait)
            else:
                logger.warning(
                    "Temp dir still locked after %d attempts — skipping cleanup",
                    max_attempts,
                )
