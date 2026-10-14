"""Deterministic, source-preserving information animation for MoviePy v2.

All visible business text comes from the slide. Cards indicate reading focus,
never magnitude or causality. Layout pagination is also the timing authority:
call ``minimum_readable_duration`` before allocating a scene on the timeline.
"""
from __future__ import annotations

import math
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
from moviepy import VideoClip

import config

_BACKGROUND = (247, 247, 242)
_INK = (31, 47, 64)
_MUTED = (88, 103, 112)
_ACCENT = (137, 107, 55)
_GOLD = (185, 157, 103)
_NUMBERS = re.compile(r"[+-]?\d+(?:[.,:/-]\d+)*(?:[%％])?")


@lru_cache(maxsize=24)
def _font(size: int):
    # Deferred import avoids a composer -> renderer -> composer import cycle.
    from video_composer import _get_font_param
    return ImageFont.truetype(_get_font_param(), size)


@lru_cache(maxsize=12)
def _title_font(size):
    from video_composer import _get_font_param
    regular = Path(_get_font_param())
    bold = regular.with_name("msyhbd.ttc")
    return ImageFont.truetype(str(bold if bold.exists() else regular), size)


@lru_cache(maxsize=4)
def _paper(w, h):
    """Quiet warm-to-cool paper tones; the subtitle zone remains plain."""
    yy, xx = np.mgrid[0:h, 0:w]
    blend = np.clip((xx / w * .65 + yy / h * .35), 0, 1)[..., None]
    start, end = np.array((250, 249, 243)), np.array((237, 243, 245))
    canvas = (start * (1 - blend) + end * blend).astype(np.uint8)
    canvas[int(h * .82):] = _BACKGROUND
    return canvas


def _facts(slide, plan):
    if plan is not None and getattr(plan, "source_facts", None) is not None:
        return list(plan.source_facts)
    from faithful_plan import source_units
    return source_units(slide)


def _lines(text, font, width):
    """Wrap without dropping even whitespace; concatenation recovers the source."""
    result, current = [], ""
    # Keep dates, percentages and English words together when they fit.
    tokens = re.findall(r"[+-]?\d+(?:[.,:/-]\d+)*(?:[%％])?|[A-Za-z]+|[\s\S]", text)
    for token in tokens:
        units = [token] if font.getlength(token) <= width else list(token)
        for unit in units:
            if unit == "\n":
                result.append(current + unit)
                current = ""
            elif current and font.getlength(current.rstrip("\r\n") + unit) > width:
                result.append(current)
                current = unit
            else:
                current += unit
    if current:
        result.append(current)
    return result or [""]


def _reading_seconds(text):
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    words = len(re.findall(r"[A-Za-z0-9]+(?:[.,%/-][A-Za-z0-9]+)*", text))
    return cjk / 5.5 + words / 2.7


def _source_image(slide):
    for path in getattr(slide, "image_paths", []):
        try:
            with Image.open(path) as source:
                return str(path), ImageOps.exif_transpose(source).convert("RGBA")
        except (OSError, ValueError):
            continue
    return None, None


def _layout(slide, plan=None):
    w, h = map(int, config.VIDEO_SIZE.split("x"))
    if min(w, h) < 120:
        raise ValueError("Content video dimensions must be at least 120 pixels")
    portrait = h > w
    scale = min(w, h) / 720
    margin = round((44 if portrait else 70) * scale)
    title_size = max(12, round((42 if portrait else 48) * scale))
    body_size = max(10, round((30 if portrait else 32) * scale))
    title_font, body_font = _title_font(title_size), _font(body_size)
    title_line_height = round(title_size * 1.42)
    line_height = round(body_size * 1.52)
    pad, gap = round(18 * scale), round(12 * scale)
    title = str(getattr(slide, "title", "") or "")
    facts = _facts(slide, plan)
    title_lines = _lines(title, title_font, w - 2 * margin)
    title_y = round(83 * scale)
    content_bottom = int(h * .80)
    max_title_lines = 3 if portrait else 2
    long_title = len(title_lines) > max_title_lines
    displayed_title_lines = [] if long_title else title_lines
    body_y = title_y + max(1, len(displayed_title_lines)) * title_line_height + round(32 * scale)
    path, source = _source_image(slide)
    image_bounds = None
    body_width = w - margin * 2
    if source is not None:
        if portrait:
            image_height = min(round(h * .25), max(round(80 * scale), (content_bottom - body_y) // 2))
            image_bounds = (margin, body_y, w - margin, body_y + image_height)
            body_y += image_height + round(22 * scale)
        else:
            body_width = round(w * .53)
            image_bounds = (round(w * .64), body_y, w - margin, content_bottom)
    available = content_bottom - body_y
    max_lines = max(1, (available - 2 * pad) // line_height)
    # Individual facts may span several cards/pages, with every character kept.
    fragments = []
    for fact_index, fact in enumerate(facts):
        lines = _lines(fact, body_font, body_width - pad * 2)
        chunk_size = min(3, max_lines)
        for offset in range(0, len(lines), chunk_size):
            chunk = lines[offset:offset + chunk_size]
            fragments.append({"fact_index": fact_index, "text": "".join(chunk),
                              "lines": chunk, "height": len(chunk) * line_height + pad * 2})
    pages = []
    if long_title:
        title_capacity = max(1, (content_bottom - title_y - pad) // title_line_height)
        for offset in range(0, len(title_lines), title_capacity):
            chunk = title_lines[offset:offset + title_capacity]
            pages.append({"title_fragment": "".join(chunk), "title_lines": chunk,
                          "fragments": [], "title_only": True})
    page, used = [], 0
    for fragment in fragments:
        if page and used + gap + fragment["height"] > available:
            pages.append({"title_fragment": "" if long_title else title,
                          "title_lines": displayed_title_lines, "fragments": page,
                          "title_only": False})
            page, used = [], 0
        fragment["bounds"] = [margin, body_y + used, margin + body_width,
                              body_y + used + fragment["height"]]
        page.append(fragment)
        used += fragment["height"] + gap
    if page or not pages:
        pages.append({"title_fragment": "" if long_title else title,
                      "title_lines": displayed_title_lines, "fragments": page,
                      "title_only": False})
    for i, page in enumerate(pages):
        text = "".join(item["text"] for item in page["fragments"])
        if i == 0 or page["title_only"]:
            text += page["title_fragment"]
        page["minimum_duration"] = max(3.0, _reading_seconds(text) + .65 * len(page["fragments"]) + .5)
    return dict(width=w, height=h, scale=scale, margin=margin, title_size=title_size,
                body_size=body_size, title_line_height=title_line_height,
                line_height=line_height, pad=pad, title_y=title_y, source=source,
                image_source=path, image_bounds=image_bounds, pages=pages,
                source_title=title, source_facts=facts,
                layout_kind=getattr(plan, "layout_kind", "image" if source else "points"))


def minimum_readable_duration(slide, plan=None):
    """Minimum display time in seconds for the current output dimensions."""
    return sum(page["minimum_duration"] for page in _layout(slide, plan)["pages"])


def _draw_line(draw, xy, text, font, *, emphasize=False):
    text = text.rstrip("\r\n")
    x, y = xy
    if not emphasize:
        draw.text((x, y), text, font=font, fill=_INK, anchor="lt")
        return
    start = 0
    for match in _NUMBERS.finditer(text):
        prefix = text[start:match.start()]
        draw.text((x, y), prefix, font=font, fill=_INK, anchor="lt")
        x += font.getlength(prefix)
        draw.text((x, y), match.group(), font=font, fill=_ACCENT, anchor="lt")
        x += font.getlength(match.group())
        start = match.end()
    draw.text((x, y), text[start:], font=font, fill=_INK, anchor="lt")


def make_content_clip(slide, duration, *, plan=None, scene_number=1, total_scenes=1,
                      deck_title="", content_duration=None, speech_duration=None):
    """Render exact source text and the original main image on a stable canvas.

    ``duration`` remains the caller's timeline authority; a too-short duration is
    reported in the manifest, never silently extended. ``content_duration`` is
    the usable display window before an outgoing overlap, if the composer has
    reserved one. Text is visible throughout its page; animated focus follows
    source order without implying that an unordered list is a process.
    """
    duration = float(duration)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Content duration must be finite and positive")
    layout = _layout(slide, plan)
    w, h, scale = layout["width"], layout["height"], layout["scale"]
    pages = layout["pages"]
    required = sum(page["minimum_duration"] for page in pages)
    window = min(duration, float(content_duration)) if content_duration is not None else duration
    if not math.isfinite(window) or window <= 0:
        raise ValueError("content_duration must be finite and positive")
    cursor = 0.0
    for page in pages:
        page["start"] = cursor
        cursor += window * page["minimum_duration"] / required
        page["end"] = cursor
        weights = [max(1.0, _reading_seconds(f["text"])) for f in page["fragments"]]
        total_weight = sum(weights) or 1
        focus_cursor = page["start"]
        for fragment, weight in zip(page["fragments"], weights):
            fragment["visible_start"] = page["start"]
            fragment["visible_end"] = page["end"]
            fragment["focus_start"] = focus_cursor
            focus_cursor += (page["end"] - page["start"]) * weight / total_weight
            fragment["focus_end"] = focus_cursor
    alignment = "reading_duration"
    narration = getattr(plan, "narration_text", "") if plan is not None else ""
    if speech_duration and narration and window >= required:
        # Measured page speech plus source offsets gives approximate local
        # focus timing. Reading minima remain hard bounds, even with fast TTS.
        # This is deliberately not represented as word-level forced alignment.
        total_speech_weight = max(.001, _reading_seconds(narration))
        offset = 0
        for page in pages:
            for fragment in page["fragments"]:
                position = narration.find(fragment["text"], offset)
                if position >= 0:
                    fragment["speech_start_estimate"] = min(window, speech_duration *
                        _reading_seconds(narration[:position]) / total_speech_weight)
                    offset = position + len(fragment["text"])
        for i, page in enumerate(pages[1:], 1):
            if page["fragments"] and "speech_start_estimate" in page["fragments"][0]:
                earliest = pages[i-1]["start"] + pages[i-1]["minimum_duration"]
                latest = window - sum(p["minimum_duration"] for p in pages[i:])
                boundary = max(earliest, min(latest, page["fragments"][0]["speech_start_estimate"]))
                page["start"] = boundary
                pages[i-1]["end"] = boundary
        for page in pages:
            for i, fragment in enumerate(page["fragments"]):
                fragment["visible_start"], fragment["visible_end"] = page["start"], page["end"]
                previous = page["fragments"][i-1]["focus_start"] if i else page["start"]
                fragment["focus_start"] = max(previous, min(page["end"],
                    fragment.get("speech_start_estimate", page["start"])))
                if i:
                    page["fragments"][i-1]["focus_end"] = fragment["focus_start"]
            if page["fragments"]:
                page["fragments"][-1]["focus_end"] = page["end"]
        alignment = "source_offsets_in_measured_speech_approximate"
    pages[-1]["end"] = duration
    for fragment in pages[-1]["fragments"]:
        fragment["visible_end"] = duration

    @lru_cache(maxsize=16)
    def render(page_index, active):
        canvas = Image.fromarray(_paper(w, h).copy())
        draw = ImageDraw.Draw(canvas)
        margin, pad = layout["margin"], layout["pad"]
        small = _font(max(10, round(18 * scale)))
        navigation = f"PPT   {scene_number:02d} / {max(1, total_scenes):02d}"
        nav_y = round(27 * scale)
        draw.rounded_rectangle((margin, nav_y, margin + small.getlength(navigation) + 24 * scale,
                                nav_y + 31 * scale), radius=6 * scale, fill=_INK)
        draw.text((margin + 12 * scale, nav_y + 5 * scale), navigation,
                  font=small, fill=(248, 243, 229), anchor="lt")
        if len(pages) > 1:
            label = f"{page_index + 1} / {len(pages)}"
            draw.text((w - margin - small.getlength(label), round(35 * scale)), label,
                      font=small, fill=_MUTED, anchor="lt")
        page = pages[page_index]
        for j, line in enumerate(page["title_lines"]):
            _draw_line(draw, (margin, layout["title_y"] + j * layout["title_line_height"]),
                       line, _title_font(layout["title_size"]))
        if not page["title_only"] and layout["source"] is not None:
            left, top, right, bottom = layout["image_bounds"]
            draw.rounded_rectangle((left, top, right, bottom), radius=round(16 * scale), fill="white")
            inset = max(4, round(14 * scale))
            image = ImageOps.contain(layout["source"], (right - left - inset * 2, bottom - top - inset * 2))
            canvas.paste(image, (left + (right - left - image.width) // 2,
                                 top + (bottom - top - image.height) // 2), image)
        for index, fragment in enumerate(page["fragments"]):
            left, top, right, bottom = fragment["bounds"]
            focused = index == active
            draw.rounded_rectangle((left + 2 * scale, top + 4 * scale, right + 2 * scale, bottom + 4 * scale),
                                   radius=round(12 * scale), fill=(225, 230, 229))
            draw.rounded_rectangle((left, top, right, bottom), radius=round(12 * scale),
                                   fill=(248, 242, 228) if focused else (253, 254, 251),
                                   outline=_GOLD if focused else (217, 225, 225),
                                   width=max(1, round((2 if focused else 1) * scale)))
            if focused:
                draw.rounded_rectangle((left, top + pad, left + max(3, round(4 * scale)), bottom - pad),
                                       radius=2, fill=_INK)
            for j, line in enumerate(fragment["lines"]):
                _draw_line(draw, (left + pad, top + pad + j * layout["line_height"]),
                           line, _font(layout["body_size"]),
                           emphasize=layout["layout_kind"] == "metrics")
        return np.array(canvas)

    def frame(t):
        t = min(duration, max(0.0, float(t)))
        page_index = next((i for i, p in enumerate(pages) if t < p["end"]), len(pages) - 1)
        fragments = pages[page_index]["fragments"]
        active = next((i for i, f in enumerate(fragments) if t < f["focus_end"]), len(fragments) - 1)
        if fragments and t < fragments[0]["focus_start"]:
            active = -1
        result = render(page_index, active).copy()
        if active >= 0:
            elapsed = t - fragments[active]["focus_start"]
            if 0 <= elapsed < .28:
                old = render(page_index, active - 1)
                alpha = elapsed / .28
                result = np.rint(old * (1-alpha) + result * alpha).astype(np.uint8)
        if page_index and t - pages[page_index]["start"] < .25:
            alpha = max(0., (t - pages[page_index]["start"]) / .25)
            old = render(page_index - 1, len(pages[page_index-1]["fragments"]) - 1)
            result = np.rint(old * (1-alpha) + result * alpha).astype(np.uint8)
        # A small top progress track denotes playback time, never source data.
        track_y = round(64 * scale)
        margin = layout["margin"]
        result[track_y:track_y + max(2, round(3 * scale)), margin:w - margin] = (222, 229, 238)
        progress = int((w - 2 * margin) * min(1, (scene_number - 1 + t / duration) / max(1, total_scenes)))
        result[track_y:track_y + max(2, round(3 * scale)), margin:margin + progress] = _ACCENT
        return result

    clip = VideoClip(frame, duration=duration)
    clip.content_manifest = {
        "renderer": "source-cards-v1", "slide_index": getattr(slide, "index", scene_number),
        "source_title": layout["source_title"], "source_facts": layout["source_facts"],
        "layout_kind": layout["layout_kind"], "image_source": layout["image_source"],
        "size": [w, h], "duration": duration, "minimum_readable_duration": required,
        "readable_duration_satisfied": window >= required - .001,
        "speech_duration": speech_duration, "subtitle_safe_top": int(h * .82),
        "focus_timing": alignment,
        "pages": pages,
    }
    return clip
