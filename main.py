#!/usr/bin/env python3
"""
pptx-to-video — Convert PowerPoint presentations to product videos.

CLI entry point.  Parses a PPTX file, uses the AI "Director" to craft
cinematic prompts, generates video clips via a pluggable provider, and
composes them into a single MP4.

Usage::

    # Default: SiliconFlow cloud API
    python main.py --input demo.pptx --output out.mp4

    # Use local ComfyUI (free, GPU required)
    python main.py --input demo.pptx --output out.mp4 --provider comfyui

    # Preview prompts without generating video
    python main.py --input demo.pptx --output out.mp4 --preview

    # Full flow with custom style
    python main.py --input demo.pptx --output out.mp4 \\
        --provider custom_api --style "tech innovation" --subtitle
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


class _StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        level = record.levelname
        msg = record.getMessage()
        return f"{ts} {level:8s} {msg}"


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_StructuredFormatter())
    logging.basicConfig(level=level, handlers=[handler])
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("moviepy").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


async def _run_pipeline(
    input_path: Path,
    output_path: Path,
    *,
    fps: int,
    add_subtitles: bool,
    max_concurrent: int,
    provider_name: str,
    image_provider_name: str = "",
    video_provider_name: str = "",
    image_model: str,
    video_model: str,
    style: str,
    overall_theme: str,
    dry_run: bool,
    preview_only: bool,
    auto_compare: bool = False,
    images_per_slide: int = 2,
    duration_mode: str = "auto",
    ratio: str = "16:9",
    srt_only: bool = False,
    narration_style: str = "direct",
    add_audio: bool = False,
    add_bgm: bool = True,
    bgm_path: Path | None = None,
    bgm_volume: float | None = None,
    visual_mode: str = "faithful",
    presentation_style: str = "auto",
    script_length: str = "standard",
    notes_policy: str = "reference",
    project_path: Path | None = None,
    save_project: Path | None = None,
    include_hidden: bool = False,
    voice: str = "zh-CN-XiaoxiaoNeural",
    rate: str = "+0%",
) -> int:
    """Execute the full extract → direct → generate → compose pipeline."""
    import config as _cfg
    from pptx_parser import parse_pptx

    if project_path:
        from narration_project import NarrationProject
        saved = NarrationProject.load(project_path)
        saved.validate_source(input_path)
        visual_mode = saved.settings.get('visual_mode', visual_mode)
        include_hidden = saved.settings.get('include_hidden', include_hidden)

    if ratio != "original":
        _cfg.set_ratio(ratio)

    logger = logging.getLogger(__name__)

    # ── 1. Parse ────────────────────────────────────────────────────────
    logger.info("=== Phase 1: Parse PPTX ===")
    try:
        slides = parse_pptx(input_path, include_hidden=include_hidden)
    except Exception as exc:
        logger.error("Failed to parse PPTX: %s", exc)
        return 1

    if not slides:
        logger.error("No slides found in %s", input_path)
        return 1

    from narration_workflow import source_ratio
    source_ratio(slides, ratio)
    logger.info("Parsed %d slides", len(slides))
    for s in slides:
        logger.info(
            "  Slide %d: %s | images=%d | text=%d chars",
            s.index,
            s.title[:50] if s.title else "(no title)",
            len(s.image_paths),
            len(s.text_content),
        )

    if dry_run:
        logger.info("=== Dry run – stopping after parse ===")
        return 0

    # ── 2. Director — generate scene plans ──────────────────────────────
    from prompt_engine import Director

    logger.info("=== Phase 2: Director — craft prompts ===")
    director = Director(
        slides, style=style, overall_theme=overall_theme,
        images_per_slide=images_per_slide, narration_style=narration_style,
        visual_mode=visual_mode,
    )
    logger.info("Visual style:\n%s", director.style_description)
    plans = director.plan()
    from narration_workflow import prepare_scripts
    project = prepare_scripts(input_path, slides, plans, settings=dict(
        visual_mode=visual_mode, presentation_style=presentation_style, length=script_length,
        notes_policy=notes_policy, include_hidden=include_hidden, voice=voice, rate=rate), project_path=project_path, offline=srt_only)
    if save_project:
        project.save(save_project)
    if add_audio:
        from video_composer import build_scene_timeline
        missing = [s['index'] for s in build_scene_timeline(slides, plans)
                   if not s['text'].strip() and not s['muted']]
        if missing:
            logger.error('第 %s 页讲稿为空；请编辑讲稿或明确选择静音。', missing)
            return 1
    for segment in project.segments.values():
        for warning in segment.warnings:
            logger.warning('第 %s 页：%s', segment.slide_index, warning)


    for plan in plans:
        if visual_mode == "faithful":
            logger.info("Slide %d: 原文要点=%d, 计划 %.2fs, 逐页忠实讲解",
                        plan.slide_index, len(plan.source_facts), plan.suggested_duration_sec)
            logger.info("  讲解: %s", plan.narration_text)
            continue
        logger.info("── Slide %d ──", plan.slide_index)
        logger.info("  Vision:  %s", plan.director_vision)
        logger.info("  Image:   %s", plan.image_prompt[:120])
        logger.info("  Video:   %s", plan.video_prompt[:120])

    if srt_only:
        from video_composer import build_scene_timeline, build_subtitle_items, export_srt

        try:
            scenes = build_scene_timeline(slides, plans)
            subtitle_items = build_subtitle_items(scenes)
            srt_path = export_srt(subtitle_items, output_path.with_suffix(".srt"))
        except Exception as exc:
            logger.error("Subtitle export failed: %s", exc)
            return 1
        logger.info("Subtitles exported: %s", srt_path)
        logger.info("Timing follows the scene plan; no API calls or TTS measurement were used.")
        return 0

    if preview_only:
        logger.info("=== Preview only – stopping after prompts ===")
        return 0

    if visual_mode == "faithful":
        from video_composer import compose_video
        logger.info("=== 忠实讲解：按 PPT 原文与原图制作，无需生成 API ===")
        try:
            await asyncio.to_thread(
                compose_video, slides, [], output_path, plans=plans,
                add_subtitles=add_subtitles, fps=fps, add_audio=add_audio,
                add_bgm=add_bgm, bgm_path=bgm_path, bgm_volume=bgm_volume,
                narration_style=narration_style, visual_mode=visual_mode,
            )
        except Exception as exc:
            logger.error("Video composition failed: %s", exc, exc_info=True)
            return 1
        logger.info("Output: %s", output_path)
        return 0

    # ── 3. Generate clips ───────────────────────────────────────────────
    from video_generator import generate_clips_from_plans, cleanup_temp_files
    from video_composer import compose_video

    logger.info("=== Phase 3: Generate video clips ===")

    # The CLI resolves explicit flags and environment defaults before dispatch.
    image_provider_name = image_provider_name or provider_name
    video_provider_name = video_provider_name or provider_name

    # Resolve API keys
    from providers import get_providers

    key_env_map = {
        "siliconflow": "SILICONFLOW_API_KEY",
        "agnes": "AGNES_API_KEY",
        "kling": "KLING_API_KEY",
        "volcengine": "VOLC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }

    # Build api_keys dict from environment
    api_keys: dict[str, str] = {}
    for prov_name in [image_provider_name, video_provider_name]:
        env_var = key_env_map.get(prov_name, "")
        if env_var:
            key = os.getenv(env_var, "")
            if key:
                api_keys[prov_name] = key

    # For siliconflow, try the config-based resolution (interactive if needed)
    if image_provider_name == "siliconflow" or video_provider_name == "siliconflow":
        try:
            sf_key = _cfg.resolve_api_key(interactive=True)
            if sf_key:
                api_keys["siliconflow"] = sf_key
        except RuntimeError as exc:
            logger.error("SiliconFlow API key not found: %s", exc)
            return 1

    # Check required API keys for specific providers
    for prov_name in [image_provider_name, video_provider_name]:
        if prov_name in key_env_map and prov_name not in api_keys:
            env_var = key_env_map[prov_name]
            logger.warning("No API key found for %s. Set %s env var or pass --api-key.",
                           prov_name, env_var)
            # Only fail for non-free providers
            if prov_name != "agnes":
                logger.error("Cannot proceed without API key for %s", prov_name)
                return 1

    provider_kwargs = {}
    if image_model:
        provider_kwargs["image_model"] = image_model
    if video_model:
        provider_kwargs["video_model"] = video_model

    image_prov, video_prov = get_providers(
        image_provider=image_provider_name,
        video_provider=video_provider_name,
        api_keys=api_keys,
        image_kwargs=provider_kwargs,
        video_kwargs=provider_kwargs,
    )
    temp_dir = input_path.parent  # Save clips near the input file

    # ── Auto-compare: if enabled and not already Agnes, try both ──────
    agnes_provider = None
    if auto_compare and provider_name != "agnes":
        agnes_key = os.getenv("AGNES_API_KEY", "") or api_keys.get("agnes", "")
        if agnes_key:
            from providers.agnes import AgnesProvider
            agnes_provider = AgnesProvider(api_key=agnes_key)
            logger.info("🔬 Auto-compare enabled — will compare with Agnes AI (free)")

    try:
        from config import ensure_temp_dir
        temp_dir = ensure_temp_dir()  # but use temp dir for intermediate files

        clips = await generate_clips_from_plans(
            slides,
            plans,
            image_provider=image_prov,
            video_provider=video_prov,
            output_dir=temp_dir,
            max_concurrent=max_concurrent,
            progress_callback=lambda cur, total, msg: logger.info(
                "  [%d/%d] %s", cur, total, msg
            ),
        )

        generated_idx = {c.slide_index for c in clips}
        missing = [s.index for s in slides if s.index not in generated_idx]
        if missing:
            logger.warning(
                "Missing clips for slides %s – will use fallback text clips",
                missing,
            )
    finally:
        await image_prov.close()
        if video_prov is not image_prov:
            await video_prov.close()
        if agnes_provider is not None:
            await agnes_provider.close()

    # ── 4. Compose ──────────────────────────────────────────────────────
    logger.info("=== Phase 4: Compose final video ===")
    try:
        await asyncio.to_thread(
            compose_video,
            slides,
            clips,
            output_path,
            plans=plans,
            add_subtitles=add_subtitles,
            fps=fps,
            add_audio=add_audio,
            add_bgm=add_bgm,
            bgm_path=bgm_path,
            bgm_volume=bgm_volume,
            narration_style=narration_style,
            visual_mode=visual_mode,
        )
    except Exception as exc:
        logger.error("Video composition failed: %s", exc)
        return 1

    # ── 5. Cleanup ──────────────────────────────────────────────────────
    logger.info("=== Cleanup ===")
    await cleanup_temp_files()

    logger.info("=== Done ===")
    logger.info("Output: %s", output_path)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pptx-to-video",
        description="Animate original PPTX content locally, with optional AI creative generation.",
    )
    parser.add_argument("--input", "-i", required=True, type=Path,
                        help="Path to the input .pptx file")
    parser.add_argument("--output", "-o", required=True, type=Path,
                        help="Output .mp4 path; --srt-only writes the same stem as .srt")
    parser.add_argument("--ratio", choices=["original", "16:9", "9:16", "1:1"], default="original",
                        help="Video aspect ratio (default: original PPT page ratio)")
    parser.add_argument("--visual-mode", choices=["faithful", "creative"], default="faithful",
                        help="faithful: animate PPT facts locally (default); creative: AI-generated interpretation")
    parser.add_argument("--fps", type=int, default=24,
                        help="Frames per second (default: 24)")
    parser.add_argument("--subtitle", action="store_true", default=False,
                        help="Burn slide text as subtitles into the video")
    parser.add_argument("--srt-only", action="store_true", default=False,
                        help="Export planned subtitles locally, without API calls, TTS or video composition")
    parser.add_argument("--narration-style", choices=["direct", "explain"], default="direct",
                        help="Narration: direct slide reading or conversational explanation (default: direct)")
    parser.add_argument("--audio", "--tts", dest="add_audio", action="store_true", default=False,
                        help="Enable TTS narration (off by default)")
    parser.add_argument("--bgm", type=Path, default=None,
                        help="Background music path (default: assets/bgm/bgm.mp3)")
    parser.add_argument("--no-bgm", action="store_true", default=False,
                        help="Disable background music, including when --bgm is supplied")
    parser.add_argument("--max-concurrent", type=int, default=3,
                        help="Maximum concurrent API calls (default: 3)")
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="Only parse the PPTX, do not generate or compose")
    parser.add_argument("--preview", action="store_true", default=False,
                        help="Generate and show prompts only (no video generation)")
    parser.add_argument("--api-key", type=str, default=None,
                        help="SiliconFlow API key (overrides env var and config file)")

    # New: Provider & style
    parser.add_argument("--provider", type=str, default=None,
                        choices=["siliconflow", "agnes", "kling", "volcengine", "comfyui", "custom_api", "openai", "gemini"],
                        help="Generation provider (default: siliconflow). "
                             "Agnes AI is free.")
    parser.add_argument("--image-provider", type=str, default=None,
                        help="Image generation provider (overrides --provider for images only)")
    parser.add_argument("--video-provider", type=str, default=None,
                        help="Video generation provider (overrides --provider for videos only)")
    parser.add_argument("--auto-compare", action="store_true", default=False,
                        help="Compare Agnes (free) with selected provider and pick the better result")
    parser.add_argument("--image-model", type=str, default="",
                        help="Image generation model name")
    parser.add_argument("--video-model", type=str, default="",
                        help="Video generation model name")
    parser.add_argument("--style", type=str, default="auto",
                        help="Visual style: auto | modern luxury | tech innovation | "
                             "nature organic | fashion editorial | corporate clean | "
                             "warm lifestyle")
    parser.add_argument("--theme", type=str, default="",
                        help="Overall theme description for the Director")
    parser.add_argument("--images-per-slide", type=int, default=2,
                        help="Number of keyframe images per slide (1-6, default: 2)")
    parser.add_argument("--duration-mode", type=str, default="auto",
                        choices=["auto", "fixed"],
                        help="Duration mode: 'auto' (per-slide recommendation) or 'fixed' (use --fps based)")

    parser.add_argument("--verbose", "-v", action="store_true", default=False,
                        help="Enable debug-level logging")
    parser.add_argument("--analyze", action="store_true", default=False,
                        help="Analyze and summarize the PPTX content first, then proceed")
    parser.add_argument('--presentation-style', choices=['auto','internal-training','external-meeting','public-presentation','work-report','education','product-intro'], default='auto')
    parser.add_argument('--script-length', choices=['concise','standard','detailed'], default='standard')
    parser.add_argument('--notes-policy', choices=['ignore','reference','prefer'], default='reference')
    parser.add_argument('--project', type=Path, help='Load a saved final narration project')
    parser.add_argument('--save-project', type=Path, help='Save the narration project for editing')
    parser.add_argument('--voice', default='zh-CN-XiaoxiaoNeural')
    parser.add_argument('--speech-rate', default='+0%', choices=['-20%','-10%','+0%','+10%','+20%'])
    parser.add_argument('--include-hidden', action='store_true', help='Include hidden PPT pages')
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    _setup_logging(verbose=args.verbose)
    logger = logging.getLogger(__name__)

    # Inject API key
    if args.api_key:
        import config
        config.set_api_key(args.api_key.strip())

    # Validate input
    input_path: Path = args.input.resolve()
    if not input_path.exists():
        logger.error("Input file not found: %s", input_path)
        return 1
    if input_path.suffix.lower() != ".pptx":
        logger.error("Input must be a .pptx file, got: %s", input_path.suffix)
        return 1

    output_path: Path = args.output.resolve()

    # Load .env before resolving providers; explicit flags take precedence.
    import config
    provider_name = args.provider or os.getenv("PROVIDER") or config.PROVIDER

    # Resolve separate image/video providers
    image_provider_name = (
        args.image_provider or args.provider
        or os.getenv("IMAGE_PROVIDER") or provider_name
    )
    video_provider_name = (
        args.video_provider or args.provider
        or os.getenv("VIDEO_PROVIDER") or provider_name
    )

    # ── 0. Analyze / Summarize ──────────────────────────────────────────
    if args.analyze and not (args.dry_run or args.srt_only):
        from pptx_parser import parse_pptx
        from ppt_summarizer import analyze_slides, format_summary
        logger.info("=== Phase 0: Analyze PPTX content ===")
        try:
            slides_for_analysis = parse_pptx(input_path)
            if slides_for_analysis:
                summary = analyze_slides(slides_for_analysis)
                print("\n" + format_summary(summary) + "\n")
                try:
                    input("Press Enter to continue with video generation, or Ctrl+C to abort...")
                except (EOFError, KeyboardInterrupt):
                    logger.info("Aborted by user")
                    return 0
        except Exception as e:
            logger.warning("Analysis failed, proceeding anyway: %s", e)

    try:
        return asyncio.run(
            _run_pipeline(
                input_path=input_path,
                output_path=output_path,
                fps=args.fps,
                add_subtitles=args.subtitle,
                max_concurrent=args.max_concurrent,
                provider_name=provider_name,
                image_provider_name=image_provider_name,
                video_provider_name=video_provider_name,
                image_model=args.image_model or "",
                video_model=args.video_model or "",
                auto_compare=args.auto_compare,
                style=args.style,
                overall_theme=args.theme,
                images_per_slide=args.images_per_slide,
                duration_mode=args.duration_mode,
                dry_run=args.dry_run,
                preview_only=args.preview,
                ratio=args.ratio,
                srt_only=args.srt_only,
                narration_style=args.narration_style,
                visual_mode=args.visual_mode,
                presentation_style=args.presentation_style, script_length=args.script_length,
                notes_policy=args.notes_policy, project_path=args.project,
                save_project=args.save_project, include_hidden=args.include_hidden,
                voice=args.voice, rate=args.speech_rate,
                add_audio=args.add_audio,
                add_bgm=not args.no_bgm,
                bgm_path=args.bgm.resolve() if args.bgm else None,
            )
        )
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        return 130
    except Exception as exc:
        logger.error("Unexpected error: %s", exc, exc_info=args.verbose)
        return 1


if __name__ == "__main__":
    sys.exit(main())
