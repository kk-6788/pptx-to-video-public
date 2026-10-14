"""Deterministic, source-bound slide plans for faithful local video rendering.

Facts are body paragraphs, in source order, without unordered bullet decoration.
Titles remain separate; notes are narrated but are not presented as slide facts.
This module verifies exact source/plan correspondence, not AI semantic quality.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from prompt_engine import EnhancedScenePlan
    from pptx_parser import Slide


_BULLET = re.compile(r"^(?:[-+*]\s+|[•●◦▪·‣⁃]\s*)")
_METRIC = re.compile(
    r"[+-]?\d+(?:[.,]\d+)*\s*(?:[%％]|亿元|万元|元|美元|人民币|倍|毫秒|秒|分钟|小时|"
    r"公里|千米|米|公斤|千克|吨|人|户|家|台|件|项|次|个|GB|MB|TB|ms|kg|km)(?:\b|(?=[\u3400-\u9fff\W])|$)",
    re.IGNORECASE,
)


def _body_lines(text: str) -> list[str]:
    result = []
    for line in str(text or "").splitlines():
        line = line.strip()
        # The parser wraps existing bullets in its own '- ' prefix. Remove both,
        # but preserve signs, decimal points, ordered labels and factual words.
        while _BULLET.match(line):
            line = _BULLET.sub("", line, count=1).strip()
        if line:
            result.append(line)
    return result


def source_units(slide: Slide) -> list[str]:
    """Return every body paragraph without summarizing or deduplicating it."""
    return _body_lines(getattr(slide, "body", ""))


def _image_sources(slide: Slide) -> list[dict]:
    records = []
    for raw_path in getattr(slide, "image_paths", []) or []:
        path = Path(raw_path)
        record = {"path": str(path), "status": "missing", "usable": False}
        try:
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
            record.update(status="present", size_bytes=size, sha256=digest.hexdigest())
            try:
                from PIL import Image
                with Image.open(path) as image:
                    image.verify()
                with Image.open(path) as image:
                    record.update(usable=True, width=image.width, height=image.height)
            except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
                pass
        except OSError:
            record["status"] = "missing" if not path.exists() else "unreadable"
        records.append(record)
    return records


def _source_record(slide: Slide) -> dict:
    return {
        "slide_index": slide.index,
        "title": str(getattr(slide, "title", "") or ""),
        "body": str(getattr(slide, "body", "") or ""),
        "notes": str(getattr(slide, "notes", "") or ""),
        "text_content": str(getattr(slide, "text_content", "") or ""),
        "images": _image_sources(slide),
    }


def _digest(record: dict) -> str:
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _layout(facts: list[str], source: dict) -> str:
    if any(image["usable"] for image in source["images"]):
        return "image"
    if any(re.search(r"→|⇒|⟶|->", fact) for fact in facts):
        return "flow"
    # Enumeration is evidence of displayed order only when a complete sequence
    # is explicitly printed. Unordered lists never acquire causal arrows here.
    ordered = [re.match(r"^(?:步骤\s*)?(\d+)[.)、：:]\s*", fact) for fact in facts]
    if len(facts) >= 2 and all(ordered):
        numbers = [int(match.group(1)) for match in ordered]
        if numbers == list(range(1, len(facts) + 1)):
            return "flow"
    if facts and all(_METRIC.search(fact) for fact in facts):
        return "metrics"
    return "points"


def _narration(slide: Slide, style: str, position: int) -> str:
    parts = [str(getattr(slide, "title", "") or "").strip()]
    parts.extend(source_units(slide))
    parts.extend(_body_lines(getattr(slide, "notes", "")))
    text = "".join(part + ("" if part[-1:] in "。！？.!?；;" else "。")
                   for part in parts if part)
    if style == "explain" and text:
        return ("接下来，" if position else "我们来看，") + text
    return text


def _reading_seconds(text: str) -> float:
    # Conservative Chinese rate and a word-based Latin rate avoid absurdly long
    # English slides while accounting for every displayed number and character.
    han = len(re.findall(r"[\u3400-\u9fff]", text))
    remainder = re.sub(r"[\u3400-\u9fff]", " ", text)
    words = len(re.findall(r"[A-Za-z0-9]+(?:[.'’+-][A-Za-z0-9]+)*", remainder))
    other = len(re.findall(r"[^\W\d_a-zA-Z\u3400-\u9fff]", text))
    return han / 4.0 + words / 2.3 + other / 4.0


def min_scene_duration(slide: Slide) -> float:
    """Readable minimum in seconds; dense pages have no arbitrary upper cap."""
    title = str(getattr(slide, "title", "") or "").strip()
    facts = source_units(slide)
    visual = max(2.0, _reading_seconds(title) + 0.7) if title else 1.0
    visual += sum(max(2.2, _reading_seconds(fact) + 0.7) for fact in facts)
    spoken = _reading_seconds(_narration(slide, "direct", 0)) + 2.0 + len(facts) * 0.35
    # Reserve a neutral connective and a settling interval before the next page.
    return round(max(6.0, visual + 1.0, spoken + 1.5), 3)


def _beats(slide: Slide, facts: list[str]) -> list[dict]:
    if facts:
        return [{"text": text, "weight": max(1, len(re.sub(r"\s", "", text))), "role": "point"}
                for text in facts]
    title = str(getattr(slide, "title", "") or "").strip()
    return ([{"text": title, "weight": max(1, len(re.sub(r"\s", "", title))), "role": "title"}]
            if title else [])


def _validate_slides(slides: list[Slide]) -> None:
    indices = [slide.index for slide in slides]
    if any(type(index) is not int or index < 1 for index in indices):
        raise ValueError("Source slide indices must be positive integers")
    if len(set(indices)) != len(indices):
        raise ValueError("Duplicate source pages are not allowed")


def _bridge(slides: list[Slide], position: int) -> str:
    if position + 1 >= len(slides):
        return ""
    title = str(getattr(slides[position + 1], "title", "") or "").strip()
    return "接下来，" + title + "。" if title else "接下来，下一页。"


def build_faithful_plans(
    slides: list[Slide], narration_style: str = "direct", total_duration: float = 0.0,
) -> list[EnhancedScenePlan]:
    """Build one local content scene for each supplied source page, in order."""
    from prompt_engine import EnhancedScenePlan

    slides = list(slides)
    _validate_slides(slides)
    if narration_style not in {"direct", "explain"}:
        raise ValueError("narration_style must be 'direct' or 'explain'")
    if not isinstance(total_duration, (int, float)) or not math.isfinite(total_duration) or total_duration < 0:
        raise ValueError("total_duration must be finite and nonnegative")
    minima = [min_scene_duration(slide) for slide in slides]
    scale = max(1.0, total_duration / sum(minima)) if minima else 1.0
    plans = []
    for position, (slide, minimum) in enumerate(zip(slides, minima)):
        source = _source_record(slide)
        facts = source_units(slide)
        narration = _narration(slide, narration_style, position)
        plans.append(EnhancedScenePlan(
            slide_index=slide.index, slide_indices=[slide.index], visual_mode="faithful",
            source_facts=facts, source_digest=_digest(source), layout_kind=_layout(facts, source),
            visual_beats=_beats(slide, facts), narration_style=narration_style,
            narration_text=narration, narration_by_slide={slide.index: narration},
            subtitle_text=narration, narrative_bridge=_bridge(slides, position),
            transition_type="cut" if position == 0 else "dissolve",
            suggested_duration_sec=minimum * scale,
        ))
    return plans


def audit_faithful_plans(slides: list[Slide], plans: list[EnhancedScenePlan]) -> dict:
    """Raise on stale or altered plans and return a JSON-safe provenance audit.

    Exact body/beat/narration matching deliberately fails closed. The audit does
    not claim that original PPT statements are true or that pixels were checked.
    Image hashes are computed at build/audit time, never for individual frames.
    """
    slides, plans = list(slides), list(plans)
    _validate_slides(slides)
    if len(plans) != len(slides):
        raise ValueError("Faithful plans must cover every source page exactly once")
    pages = []
    for position, (slide, plan) in enumerate(zip(slides, plans)):
        label = f"Page {slide.index}"
        if plan.slide_index != slide.index or plan.slide_indices != [slide.index]:
            raise ValueError(f"{label}: missing, reordered, duplicate or merged page")
        if plan.visual_mode != "faithful":
            raise ValueError(f"{label}: expected faithful visual mode")
        source = _source_record(slide)
        facts = source_units(slide)
        digest = _digest(source)
        if plan.source_digest != digest or plan.source_facts != facts:
            raise ValueError(f"{label}: source facts or digest changed; rebuild the plan")
        if plan.narration_style not in {"direct", "explain"}:
            raise ValueError(f"{label}: invalid narration style")
        expected = _narration(slide, plan.narration_style, position)
        state = getattr(plan, "narration_state", "legacy")
        final_script = state in {"edited", "generated"}
        if final_script:
            expected = plan.narration_text
            if not isinstance(expected, str):
                raise ValueError(f"{label}: invalid final script")
        if (plan.narration_text != expected or plan.narration_by_slide != {slide.index: expected}
                or plan.subtitle_text != expected or plan.narrative_bridge != _bridge(slides, position)):
            raise ValueError(f"{label}: stale or unsupported narration, subtitle or bridge")
        if plan.layout_kind != _layout(facts, source) or plan.visual_beats != _beats(slide, facts):
            raise ValueError(f"{label}: unsupported layout or changed visual facts")
        creative_fields = ("image_prompt", "image_prompts", "video_prompt", "characters_in_scene",
                           "setting_name", "director_vision", "transition_description", "camera_angle", "image_angles")
        if any(getattr(plan, field, None) for field in creative_fields):
            raise ValueError(f"{label}: generated scenes are not permitted in faithful plans")
        duration = plan.suggested_duration_sec
        minimum = 0.5 if final_script else min_scene_duration(slide)
        if not isinstance(duration, (float, int)) or not math.isfinite(duration) or duration + 1e-6 < minimum:
            raise ValueError(f"{label}: duration is below the readable minimum")
        pages.append({
            "slide_index": slide.index, "source": source, "source_digest": digest,
            "source_facts": facts, "fact_count": len(facts), "covered_fact_count": len(facts),
            "facts_coverage": 1.0, "title_preserved": True, "layout_kind": plan.layout_kind,
            "narration_text": expected, "minimum_duration_sec": minimum,
            "narration_verification": ("user_edited_unverified" if state == "edited" else
                                       "source_linked_not_semantically_verified" if final_script else "canonical"),
            "suggested_duration_sec": duration,
        })
    return {
        "passed": True, "visual_mode": "faithful", "page_count": len(slides), "pages": pages,
        "method": "exact_source_and_plan_correspondence",
        "notes": ["Source text, page order and image hashes were checked. Final edited/model scripts are source-linked, not a semantic proof.",
                  "Layout and reading duration are conservative heuristics, not an AI semantic score.",
                  "This audit does not verify source truth or final rendered pixels."],
    }
