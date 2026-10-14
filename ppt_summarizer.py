"""
PPT Summarizer — AI-powered content analysis and summary for PPTX files.

Provides a human-readable summary of the presentation content before
proceeding to video generation, so the user can review and provide feedback.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from pptx_parser import Slide, parse_pptx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SlideSummary:
    """Summary of a single slide."""

    index: int
    title: str
    content_summary: str  # 1-2 sentence summary of what's on the slide
    has_images: bool
    key_points: list[str] = field(default_factory=list)
    suggested_visual_style: str = ""  # e.g. "product shot", "infographic", "scene"


@dataclass
class PresentationSummary:
    """Full summary of a presentation."""

    filename: str
    total_slides: int
    overall_theme: str  # AI-inferred overall theme
    target_audience: str  # inferred audience
    content_type: str  # "product_pitch", "report", "education", "portfolio", etc.
    slides: list[SlideSummary] = field(default_factory=list)
    style_recommendation: str = ""
    estimated_video_duration_sec: int = 0


# ---------------------------------------------------------------------------
# AI-powered summarizer (uses chat model)
# ---------------------------------------------------------------------------


def _build_analysis_prompt(slides: list[Slide]) -> str:
    """Build a prompt for the AI to analyze the presentation."""
    slides_text = []
    for s in slides:
        img_info = f"  [Images: {len(s.image_paths)} attached]" if s.image_paths else "  [No images]"
        slides_text.append(
            f"--- Slide {s.index} ---\n"
            f"Title: {s.title or '(no title)'}\n"
            f"Content: {s.text_content[:500]}\n"
            f"{img_info}"
        )

    return f"""You are a professional presentation analyst and video director.
Analyze the following PowerPoint slides and produce a structured analysis.

For each slide, provide:
1. A 1-2 sentence summary of the content
2. 2-4 key talking points
3. Suggested visual style for video generation (e.g. "product close-up", "infographic", "scene", "diagram animation")

Then provide overall analysis:
- Overall theme / topic
- Target audience
- Content type (product_pitch / report / education / portfolio / event / other)
- Recommended video style
- Estimated total video duration in seconds (5 sec per slide baseline)

Return ONLY valid JSON with this structure:
{{
  "overall_theme": "...",
  "target_audience": "...",
  "content_type": "...",
  "style_recommendation": "...",
  "estimated_duration": 30,
  "slides": [
    {{
      "index": 1,
      "summary": "...",
      "key_points": ["...", "..."],
      "suggested_visual": "..."
    }}
  ]
}}

Presentation content:
{"".join(slides_text)}"""


def analyze_slides(slides: list[Slide], api_key: str = "") -> PresentationSummary:
    """Analyze slides using AI to produce a structured summary.

    Falls back to basic analysis if no API key is available.
    """
    filename = "presentation"
    total = len(slides)

    if api_key:
        try:
            return _ai_analyze(slides, api_key)
        except Exception as e:
            logger.warning("AI analysis failed, using basic: %s", e)

    # Fallback: basic analysis
    return _basic_analyze(slides)


def _basic_analyze(slides: list[Slide]) -> PresentationSummary:
    """Basic analysis without AI."""
    slide_summaries = []
    for s in slides:
        key_points = []
        text = s.text_content[:200]
        # Extract bullet points
        for line in text.split("\n"):
            line = line.strip().strip("•-*")
            if line and len(line) > 10:
                key_points.append(line)
                if len(key_points) >= 3:
                    break

        slide_summaries.append(SlideSummary(
            index=s.index,
            title=s.title or f"Slide {s.index}",
            content_summary=text[:150] + ("..." if len(text) > 150 else ""),
            has_images=len(s.image_paths) > 0,
            key_points=key_points[:3],
            suggested_visual_style="auto",
        ))

    return PresentationSummary(
        filename="presentation.pptx",
        total_slides=len(slides),
        overall_theme="",
        target_audience="",
        content_type="presentation",
        slides=slide_summaries,
        style_recommendation="auto",
        estimated_video_duration_sec=len(slides) * 5,
    )


def _ai_analyze(slides: list[Slide], api_key: str) -> PresentationSummary:
    """Use Agnes AI or DeepSeek to analyze the slides."""
    prompt = _build_analysis_prompt(slides)

    # Try using existing chat provider
    try:
        import os
        import httpx

        # Use DeepSeek as the analyzer (better at structured analysis)
        deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
        if deepseek_key:
            headers = {
                "Authorization": f"Bearer {deepseek_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "You are a JSON-only response bot. Return only valid JSON, no markdown."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 4096,
            }
            resp = httpx.post(
                "https://api.deepseek.com/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                # Strip markdown code fences if present
                content = content.strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[-1]
                    content = content.rsplit("```", 1)[0]
                content = content.strip()
                result = json.loads(content)
                return _parse_ai_result(result, slides)
    except Exception as e:
        logger.warning("DeepSeek analysis failed: %s", e)

    # Fallback to Agnes
    try:
        agnes_key = api_key or os.getenv("AGNES_API_KEY", "")
        if agnes_key:
            from providers.agnes import AgnesProvider
            import asyncio

            agnes = AgnesProvider(api_key=agnes_key)
            loop = asyncio.new_event_loop()
            try:
                resp = loop.run_until_complete(agnes.chat([
                    {"role": "system", "content": "Return only valid JSON, no markdown."},
                    {"role": "user", "content": prompt},
                ], max_tokens=4096, temperature=0.3))
                content = resp["choices"][0]["message"]["content"]
                content = content.strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[-1]
                    content = content.rsplit("```", 1)[0]
                content = content.strip()
                result = json.loads(content)
                return _parse_ai_result(result, slides)
            finally:
                loop.close()
    except Exception as e:
        logger.warning("Agnes analysis also failed: %s", e)

    return _basic_analyze(slides)


def _parse_ai_result(result: dict, slides: list[Slide]) -> PresentationSummary:
    """Parse AI JSON response into PresentationSummary."""
    slide_summaries = []
    for s in slides:
        ss_data = None
        for sd in result.get("slides", []):
            if sd.get("index") == s.index:
                ss_data = sd
                break

        if ss_data:
            slide_summaries.append(SlideSummary(
                index=s.index,
                title=s.title or ss_data.get("summary", f"Slide {s.index}")[:60],
                content_summary=ss_data.get("summary", ""),
                has_images=len(s.image_paths) > 0,
                key_points=ss_data.get("key_points", []),
                suggested_visual_style=ss_data.get("suggested_visual", "auto"),
            ))
        else:
            slide_summaries.append(SlideSummary(
                index=s.index,
                title=s.title or f"Slide {s.index}",
                content_summary=s.text_content[:150],
                has_images=len(s.image_paths) > 0,
                suggested_visual_style="auto",
            ))

    return PresentationSummary(
        filename="presentation.pptx",
        total_slides=len(slides),
        overall_theme=result.get("overall_theme", ""),
        target_audience=result.get("target_audience", ""),
        content_type=result.get("content_type", "presentation"),
        slides=slide_summaries,
        style_recommendation=result.get("style_recommendation", "auto"),
        estimated_video_duration_sec=result.get("estimated_duration", len(slides) * 5),
    )


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


def format_summary(summary: PresentationSummary) -> str:
    """Format a presentation summary as a human-readable string."""
    lines = []
    lines.append("=" * 60)
    lines.append(f"  📊 PPT 分析报告")
    lines.append("=" * 60)
    lines.append(f"  文件: {summary.filename}")
    lines.append(f"  页数: {summary.total_slides} 页")
    if summary.overall_theme:
        lines.append(f"  主题: {summary.overall_theme}")
    if summary.target_audience:
        lines.append(f"  受众: {summary.target_audience}")
    if summary.content_type:
        lines.append(f"  类型: {summary.content_type}")
    if summary.style_recommendation:
        lines.append(f"  推荐风格: {summary.style_recommendation}")
    lines.append(f"  预计视频时长: ~{summary.estimated_video_duration_sec} 秒")
    lines.append("-" * 60)

    for s in summary.slides:
        lines.append(f"\n  📄 第 {s.index} 页: {s.title}")
        if s.content_summary:
            lines.append(f"    内容: {s.content_summary[:200]}")
        if s.key_points:
            for kp in s.key_points[:3]:
                lines.append(f"    • {kp[:100]}")
        if s.has_images:
            lines.append(f"    🖼️ 含图片")
        if s.suggested_visual_style and s.suggested_visual_style != "auto":
            lines.append(f"    建议视觉: {s.suggested_visual_style}")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)
