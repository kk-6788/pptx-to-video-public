"""MoviePy v2 composition with a shared slide, narration and subtitle timeline."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageStat
from moviepy import (
    AudioFileClip, ColorClip, CompositeAudioClip, CompositeVideoClip,
    ImageClip, TextClip, VideoClip, VideoFileClip, afx,
)
from moviepy.video.fx import CrossFadeIn, MultiplySpeed

import config
from pptx_parser import Slide

if TYPE_CHECKING:
    from video_generator import GeneratedClip

logger = logging.getLogger(__name__)
_FONT_CANDIDATES = [
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc",
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/simhei.ttf",
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
]
_DEFAULT_FONT_PATH = next((str(p) for p in _FONT_CANDIDATES if p.exists()), None)
_DEFAULT_FONT = _DEFAULT_FONT_PATH or "Arial"


def _get_font_param() -> str:
    """Use an explicit CJK font path, as required by Pillow/MoviePy v2."""
    return _DEFAULT_FONT


@lru_cache(maxsize=4)
def _gradient(w: int, h: int) -> np.ndarray:
    mix = (np.linspace(0, 1, h, dtype=np.float32)[:, None]
           + np.linspace(0, 1, w, dtype=np.float32)[None, :]) / 2
    return (np.array([245, 247, 250]) + mix[:, :, None]
            * np.array([-13, -11, -9])).astype(np.int16)


def _make_animated_bg_frame(t, w: int, h: int, duration: float) -> np.ndarray:
    """A moving #F5F7FA to #E8ECF1 gradient; every pixel stays light."""
    shift = round(2 * math.sin(t / max(duration, 0.1) * math.pi))
    return (_gradient(w, h) + shift).astype(np.uint8)


def _make_panel_frame(t, pw: int, ph: int, dur: float) -> np.ndarray:
    """RGBA white panel. Keep its alpha instead of discarding it to black RGB."""
    panel = Image.new("RGBA", (pw, ph))
    ImageDraw.Draw(panel).rounded_rectangle(
        (int(pw * .04), int(ph * .035), int(pw * .96), int(ph * .82)),
        radius=24, fill=(255, 255, 255, 160),
    )
    return np.asarray(panel)


def _wrap_text(text: str, max_chars: int = 22, *, max_lines: int | None = None,
               font_size: int = 40, max_width: int | None = None) -> str:
    """Wrap CJK character by character, also checking actual mixed-text width."""
    font = ImageFont.truetype(_get_font_param(), font_size)
    lines = []
    for paragraph in text.splitlines() or [text]:
        current = ""
        current_units = []
        tokens = re.findall(r"[+-]?\d+(?:[.,:/-]\d+)*(?:[%％])?|[A-Za-z]+|.", paragraph)
        units = []
        for token in tokens:
            if len(token) > max_chars or (max_width and font.getlength(token) > max_width):
                units.extend(token)
            else:
                units.append(token)
        for char in units:
            candidate = current + char
            if current and (len(candidate) > max_chars or
                            (max_width and font.getlength(candidate) > max_width)):
                if char in "，。、；：！？,.;:!?）】》" and len(current_units) > 1:
                    # Do not strand closing punctuation at the start of a line.
                    tail = current_units.pop()
                    lines.append("".join(current_units))
                    current_units = [tail, char]
                    current = tail + char
                else:
                    lines.append(current)
                    current_units = [char]
                    current = char
            else:
                current = candidate
                current_units.append(char)
        if current:
            lines.append(current)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and (len(last + "…") > max_chars or
                        (max_width and font.getlength(last + "…") > max_width)):
            last = last[:-1]
        lines[-1] = last + "…"
    return "\n".join(lines)


def _body_points(slide: Slide) -> list[str]:
    source = slide.body or slide.text_content
    points = []
    for line in source.splitlines():
        line = re.sub(r"^\s*(?:(?:[-*•●]+\s*)|\d+[.)、]\s*)+", "", line).strip()
        if not line or re.fullmatch(r"[|:\-\s]+", line) or line == slide.title:
            continue
        points.append(line.replace(" | ", " · ").strip("| "))
    return points


def _make_fallback_clip(slide: Slide, duration: float = config.FALLBACK_DURATION) -> VideoClip:
    """Light slide animation with numbered reveals, pagination and a main image."""
    w, h = map(int, config.VIDEO_SIZE.split("x"))
    duration = max(.1, float(duration))
    portrait = h > w
    bg = VideoClip(lambda t: _make_animated_bg_frame(t, w, h, duration), duration=duration)
    layers = [bg, ImageClip(_make_panel_frame(0, w, h, duration), duration=duration)]
    title = _wrap_text(slide.title or f"第 {slide.index} 页", 22,
                       max_lines=2, font_size=64, max_width=int(w * .84))
    heading = TextClip(text=title, font=_get_font_param(), font_size=64,
                       color="#1F2937", stroke_color="#1F2937", stroke_width=1,
                       text_align="center", interline=14, margin=(6, 12), duration=duration)
    heading_y = int(h * .055)
    layers.append(heading.with_position(("center", heading_y)))
    layers.append(ColorClip((64, 5), (85, 113, 214), duration=duration)
                  .with_position((int((w - 64) / 2), heading_y + heading.h + 18)))
    body_x = int(w * .085)
    body_y = max(int(h * .25), heading_y + heading.h + 52)
    body_width = int(w * .83)

    # image_paths is already area-sorted by the parser.
    for image_path in slide.image_paths:
        try:
            with Image.open(image_path) as source:
                source = ImageOps.exif_transpose(source).convert("RGBA")
                if portrait:
                    box = (int(w * .80), int(h * .32))
                    image_x, image_y = int(w * .10), body_y
                    body_y += box[1] + 34
                else:
                    box = (int(w * .30), int(h * .44))
                    image_x, image_y = int(w * .63), body_y
                    body_width = int(w * .51)
                card = Image.new("RGBA", box, (255, 255, 255, 240))
                thumb = ImageOps.contain(source, (box[0] - 20, box[1] - 20))
                card.alpha_composite(thumb, ((box[0] - thumb.width) // 2,
                                             (box[1] - thumb.height) // 2))
                layers.append(ImageClip(np.asarray(card), duration=duration)
                              .with_position((image_x, image_y)))
            break
        except Exception as exc:
            logger.debug("Slide %d: image preview skipped: %s", slide.index, exc)

    # Reserve the lower part for subtitles. Long bodies paginate; an individual
    # oversize point gets an ellipsis without shortening its narration or SRT.
    font_size, line_height = 40, 64
    available = max(64, int(h * .79) - body_y)
    max_lines = max(1, min(3, available // line_height))
    pages, page, used = [], [], 0
    for number, point in enumerate(_body_points(slide), 1):
        wrapped = _wrap_text(point, 22, max_lines=max_lines, font_size=font_size,
                             max_width=body_width - 66)
        text = TextClip(text=wrapped, font=_get_font_param(), font_size=font_size,
                        color="#1F2937", interline=24, text_align="left", margin=(4, 10), duration=duration)
        needed = max(line_height, text.h + 8, (wrapped.count("\n") + 1) * line_height)
        if page and used + needed > available:
            pages.append(page)
            page, used = [], 0
        badge = TextClip(text=f"{number:02d}", font=_get_font_param(), font_size=26,
                         color="#5571D6", margin=(2, 12), duration=duration)
        page.append((text, badge, used))
        used += needed
    if page:
        pages.append(page)
    page_duration = duration / max(1, len(pages))
    for page_index, page in enumerate(pages):
        start = page_index * page_duration
        interval = min(1.2, max(.05, (page_duration - .6) / max(1, len(page))))
        for item_index, (text, badge, offset) in enumerate(page):
            reveal = item_index * interval
            visible = max(.05, page_duration - reveal)
            for layer, x, y in ((text, body_x + 60, body_y + offset),
                                (badge, body_x, body_y + offset + 10)):
                layers.append(layer.with_duration(visible)
                              .with_effects([CrossFadeIn(min(.35, visible / 3))])
                              .with_start(start + reveal).with_position((x, y)))
    return CompositeVideoClip(layers, size=(w, h), bg_color=(245, 247, 250)).with_duration(duration)


def _measure_text_height_pil(text, font_param, font_size, max_width) -> int | None:
    """Retained for callers of the previous subtitle helper."""
    try:
        font = ImageFont.truetype(str(font_param or _get_font_param()), font_size)
        bounds = ImageDraw.Draw(Image.new("RGB", (1, 1))).multiline_textbbox(
            (0, 0), text, font=font, spacing=8)
        return bounds[3] - bounds[1]
    except Exception:
        return None


def _make_subtitle_clip(text: str, clip_duration: float, video_width: int,
                        video_height: int, *, faithful: bool = False) -> VideoClip:
    if not text.strip():
        return ColorClip((1, 1), (255, 255, 255), duration=clip_duration).with_opacity(0)
    size = min(30, config.SUBTITLE_FONT_SIZE) if faithful else config.SUBTITLE_FONT_SIZE
    limit = 18 if video_height > video_width else 22
    wrapped = _wrap_text(text, limit, font_size=size, max_width=int(video_width * .87))
    txt = TextClip(text=wrapped, font=_get_font_param(), font_size=size,
                   color="white" if faithful else config.SUBTITLE_COLOR,
                   stroke_color=None if faithful else "#1F2937", stroke_width=0 if faithful else 2,
                   text_align="center", interline=8, margin=(8, 10), duration=clip_duration)
    if faithful:
        band_height = int(video_height * .18)
        if txt.h > band_height - 8:
            txt = txt.resized(height=max(1, band_height - 8))
        return txt.with_position(('center', int(video_height * .82) + (band_height - txt.h) // 2))
    return txt.with_position(("center", video_height - txt.h - int(video_height * .08)))


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def build_scene_timeline(slides: list[Slide], plans: list | None = None) -> list[dict]:
    """Plan one scene per original slide, including grouped ScriptWriter plans."""
    from tts_audio import build_slide_narration
    mapping = {}
    for plan in plans or []:
        indices = _field(plan, "slide_indices") or [_field(plan, "slide_index")]
        for index in indices:
            mapping[index] = (plan, len(indices))
    scenes, cursor = [], 0.
    for slide in slides:
        plan, count = mapping.get(slide.index, (None, 1))
        by_slide = _field(plan, "narration_by_slide", {}) or {}
        final_script = _field(plan, "narration_state", "legacy") in {"edited", "generated"}
        text = by_slide.get(slide.index, by_slide.get(str(slide.index)))
        if text is None and count == 1:
            text = _field(plan, "narration_text", "")
        if text is None or (not text and not final_script):
            text = build_slide_narration(slide, _field(plan, "narration_style", "direct"))
        muted = _field(plan, "narration_muted_by_slide", {}) or {}
        if muted.get(slide.index, muted.get(str(slide.index), False)):
            text = ""
        planned = float(_field(plan, "suggested_duration_sec", config.FALLBACK_DURATION)) / count
        duration = max(.5, planned) if math.isfinite(planned) else config.FALLBACK_DURATION
        scenes.append(dict(index=slide.index, slide=slide, text=text,
                           start_time=cursor, duration=duration, plan=plan,
                           voice=_field(plan, 'narration_voice', 'zh-CN-XiaoxiaoNeural'),
                           rate=_field(plan, 'narration_rate', '+0%'),
                           muted=bool(muted.get(slide.index, muted.get(str(slide.index), False))),
                           preserve_text=final_script or _field(plan, "visual_mode") == "faithful"))
        cursor += duration
    return scenes


def build_subtitle_items(scenes: list[dict]) -> list[dict]:
    """Two-line cues use the exact spoken text and the same scene clock.

    Cue timing is proportional to text length, not forced word alignment.
    With narration, cues end with speech; the remaining scene is a pause.
    """
    w, h = map(int, config.VIDEO_SIZE.split("x"))
    limit = 18 if h > w else 22
    items = []
    for scene in scenes:
        text = scene.get("text", "").replace("\n", " ")
        if scene.get("preserve_text"):
            # Keep complete short sentences together. Only long sentences
            # need a character wrap, so cues do not begin with a leftover word.
            sentences = [s for s in re.split(r"(?<=[。！？；])\s*", text) if s]
            lines = [line for sentence in sentences for line in _wrap_text(
                sentence, limit, font_size=min(30, config.SUBTITLE_FONT_SIZE),
                max_width=int(w * .87)).splitlines()]
        else:
            lines = _wrap_text(text, limit, font_size=config.SUBTITLE_FONT_SIZE,
                               max_width=int(w * .87)).splitlines()
        cue_lines = 1 if scene.get("preserve_text") else 2
        chunks = ["\n".join(lines[i:i + cue_lines]) for i in range(0, len(lines), cue_lines)]
        weights = [len(chunk.replace("\n", "")) for chunk in chunks]
        total = sum(weights)
        if not total:
            continue
        cursor = scene["start_time"]
        duration = min(scene["duration"], scene.get("speech_duration", scene["duration"]))
        end = cursor + duration
        for i, (chunk, weight) in enumerate(zip(chunks, weights)):
            next_time = end if i == len(chunks) - 1 else cursor + duration * weight / total
            items.append(dict(start=cursor, end=next_time, text=chunk))
            cursor = next_time
    return items


def _srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(float(seconds) * 1000))
    seconds, milliseconds = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def export_srt(subtitle_items: list[dict], srt_path: str | Path) -> Path:
    """Write standard, editable SRT in UTF-8 with BOM (Notepad/Jianying)."""
    path = Path(srt_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks = []
    for item in sorted(subtitle_items, key=lambda i: float(i["start"])):
        start, end = max(0., float(item["start"])), float(item["end"])
        text = str(item["text"]).strip().replace("\r\n", "\n").replace("\r", "\n")
        if not text or not all(map(math.isfinite, (start, end))) or end <= start:
            continue
        end = max(end, round(start * 1000) / 1000 + .001)
        blocks.append(f"{len(blocks) + 1}\n{_srt_timestamp(start)} --> {_srt_timestamp(end)}\n{text}\n")
    path.write_text("\n".join(blocks), encoding="utf-8-sig")
    logger.info("SRT 字幕: %s (%d 条 / %d 文本行)", path, len(blocks),
                sum(len(b.splitlines()) - 2 for b in blocks))
    return path


class _BrightnessSamples(list):
    """A list-compatible result carrying metadata for custom sampling intervals."""
    def __init__(self, values=(), *, threshold=18, interval=1., duration=None):
        super().__init__(values)
        self.threshold, self.interval, self.duration = threshold, interval, duration


def _detect_black_frames(video_path, threshold=18, sample_interval=1.0):
    """Return (approximate time, grayscale mean) for dark AND bright frames.

    ffmpeg samples at 1fps by default; Pillow computes luminance.
    Failed/missing ffmpeg is deliberately non-blocking.
    """
    try:
        interval = float(sample_interval)
        if interval <= 0 or not math.isfinite(interval):
            return []
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(video_path), "-an", "-vf",
             f"fps={1 / interval:g},scale=64:64:flags=area", "-f", "rawvideo",
             "-pix_fmt", "rgb24", "pipe:1"], capture_output=True, timeout=120,
        )
        if result.returncode:
            return []
        frame_bytes = 64 * 64 * 3
        samples = []
        for offset in range(0, len(result.stdout) - frame_bytes + 1, frame_bytes):
            frame = Image.frombytes("RGB", (64, 64), result.stdout[offset:offset + frame_bytes])
            samples.append((len(samples) * interval, ImageStat.Stat(frame.convert("L")).mean[0]))
        duration = None
        try:
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                    "-of", "default=nw=1:nk=1", str(video_path)],
                                   capture_output=True, text=True, timeout=15)
            duration = float(probe.stdout.strip()) if probe.returncode == 0 else None
        except Exception:
            pass
        return _BrightnessSamples(samples, threshold=threshold, interval=interval, duration=duration)
    except Exception:
        return []


def _black_segments(brightness_samples, min_black_duration=2.0):
    try:
        threshold = getattr(brightness_samples, "threshold", 18)
        ordered = sorted(brightness_samples)
        differences = [b[0] - a[0] for a, b in zip(ordered, ordered[1:]) if b[0] > a[0]]
        interval = getattr(brightness_samples, "interval", min(differences, default=1.))
        clip_end = getattr(brightness_samples, "duration", None)
        ranges, start, previous = [], None, None

        def finish():
            if start is None:
                return
            end = previous + interval
            if clip_end is not None:
                end = min(end, clip_end)
            if end - start >= min_black_duration - 1e-6:
                ranges.append((start, end))

        for stamp, brightness in ordered:
            if start is not None and (brightness >= threshold or stamp - previous > interval * 1.5):
                finish()
                start = None
            if brightness < threshold:
                if start is None:
                    start = stamp
                previous = stamp
        finish()
        return ranges
    except Exception:
        return []


def _has_black_segment(brightness_samples, min_black_duration=2.0):
    return bool(_black_segments(brightness_samples, min_black_duration))


def _is_black_clip(video_path, duration, threshold=18) -> bool:
    """Check start/middle/end before admitting generated video to the timeline."""
    try:
        means = []
        for stamp in (0., duration / 2, max(0., duration - .1)):
            result = subprocess.run(
                ["ffmpeg", "-v", "error", "-ss", str(stamp), "-i", str(video_path),
                 "-frames:v", "1", "-vf", "scale=64:64:flags=area", "-f", "rawvideo",
                 "-pix_fmt", "rgb24", "pipe:1"], capture_output=True, timeout=30,
            )
            if result.returncode or len(result.stdout) < 64 * 64 * 3:
                return False
            frame = Image.frombytes("RGB", (64, 64), result.stdout[:64 * 64 * 3])
            means.append(ImageStat.Stat(frame.convert("L")).mean[0])
        return sum(means) / 3 < threshold
    except Exception:
        return False


def _fit_narration(audio, planned_duration):
    """Compress to 80–100% duration (speed 1–1.25x), then extend the picture."""
    if audio.duration > planned_duration:
        time_ratio = max(.8, min(1., planned_duration / audio.duration))
        audio = audio.with_effects([MultiplySpeed(factor=1 / time_ratio)])
    return audio, max(float(planned_duration), audio.duration + .15)


def _run_async(coroutine):
    # Older callers may invoke synchronous compose_video from an asyncio loop.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()


def _prepare_narrations(scenes, temp_dir, resources, *, allow_global_fallback=True):
    from tts_audio import generate_scene_narrations, generate_narration
    if not allow_global_fallback:
        try:
            results = _run_async(generate_scene_narrations(scenes, temp_dir / "narrations"))
        except Exception as exc:
            logger.warning("逐页配音失败，改为逐页重试: %s", exc)
            results = []
        fitted = []
        for i, scene in enumerate(scenes):
            if not scene['text'].strip():
                scene['narration_status'] = 'muted'
                fitted.append(None)
                continue
            result = results[i] if results and i < len(results) else None
            audio = None
            for attempt in range(2):
                try:
                    path = result.get("path") if attempt == 0 and result else None
                    if attempt == 1:
                        logger.warning("Slide %d: 重试本页配音，保留原页时间轴", scene["index"])
                        path = _run_async(generate_narration(
                            scene["text"], output_path=temp_dir / f"retry_{scene['index']}.mp3",
                            voice=scene.get('voice', 'zh-CN-XiaoxiaoNeural'), rate=scene.get('rate', '+0%'),
                            preserve_text=True))
                    if not path:
                        continue
                    loaded = AudioFileClip(str(path))
                    resources.append(loaded)
                    if not loaded.duration or not math.isfinite(loaded.duration):
                        raise ValueError("empty narration")
                    audio, duration = _fit_narration(loaded, scene["duration"])
                    scene.update(duration=duration, speech_duration=audio.duration,
                                 narration_status="generated" if attempt == 0 else "recovered")
                    break
                except Exception as exc:
                    logger.warning("Slide %d: 本页配音不可用: %s", scene["index"], exc)
            if audio is None:
                scene["narration_status"] = "unavailable"
                logger.warning("Slide %d: 本页保留静音与完整字幕，其他页配音不受影响", scene["index"])
            fitted.append(audio)
        return fitted, None
    try:
        results = _run_async(generate_scene_narrations(scenes, temp_dir / "narrations"))
        usable = bool(results) and len(results) == len(scenes) and all(results)
        fitted = []
        if usable:
            for scene, result in zip(scenes, results):
                audio = AudioFileClip(str(result["path"]))
                resources.append(audio)
                audio, duration = _fit_narration(audio, scene["duration"])
                fitted.append((audio, duration))
            for scene, (audio, duration) in zip(scenes, fitted):
                if duration > scene["duration"] + .2:
                    logger.info("Slide %d: 为完整配音延长画面 %.2fs → %.2fs",
                                scene["index"], scene["duration"], duration)
                scene.update(duration=duration, speech_duration=audio.duration)
            return [entry[0] for entry in fitted], None
        logger.warning("逐段配音有场景失败，回退到全局拼串模式（只朗读一次）")
    except Exception as exc:
        logger.warning("逐段配音失败，回退到全局拼串模式: %s", exc)
    # Global fallback keeps exact texts including explain. It cannot promise
    # precise page alignment; still never loop speech or truncate a sentence.
    try:
        text = "。".join(scene["text"].rstrip("。；; ") for scene in scenes if scene["text"])
        path = _run_async(generate_narration(text, output_path=temp_dir / "narration_global.mp3"))
        if path:
            audio = AudioFileClip(str(path))
            resources.append(audio)
            total = sum(scene["duration"] for scene in scenes)
            audio, needed = _fit_narration(audio, total)
            weights = [max(1, len(scene["text"])) for scene in scenes]
            weight_sum = sum(weights)
            total = max(total, needed)
            for scene, weight in zip(scenes, weights):
                scene["duration"] = total * weight / weight_sum
            return [], audio
    except Exception as exc:
        logger.warning("全局配音也失败，继续合成画面: %s", exc)
    return [], None


def _bgm_track(path, duration, volume, has_narration, resources):
    """Loop only music, with gentle edges and a lower bed underneath speech."""
    if not path or not Path(path).is_file() or volume <= 0:
        return None
    try:
        source = AudioFileClip(str(path))
        resources.append(source)
        if not source.duration or source.duration <= 0:
            return None
        # Slider base level: 15% means 8% under speech or 30% alone.
        gain = volume * (8 / 15 if has_narration else 2)
        return source.with_effects([
            afx.AudioLoop(duration=duration), afx.MultiplyVolume(min(.95, gain)),
            afx.AudioFadeIn(min(.8, duration / 3)), afx.AudioFadeOut(min(1.2, duration / 3)),
        ])
    except Exception as exc:
        logger.debug("BGM skipped: %s", exc)
        return None


def _write_video(final, path, fps, codec):
    params = ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if codec == "hevc_nvenc":
        preset = config.NVENC_PRESET
        params += ["-rc", "vbr", "-cq", str(config.NVENC_CQ)]
    else:
        preset = "medium"
    final.write_videofile(str(path), fps=fps, codec=codec, bitrate=config.VIDEO_BITRATE,
                         audio=final.audio is not None, audio_codec="aac", preset=preset,
                         temp_audiofile=str(path.with_name("audio.m4a")),
                         threads=4, ffmpeg_params=params, logger=None)


def _scene_video_source(scene, clip_map):
    """Locate a page's own video or its ordered slice of a grouped video."""
    indices = _field(scene["plan"], "slide_indices", []) or []
    own = clip_map.get(scene["index"])
    if len(indices) > 1 and scene["index"] in indices:
        group = clip_map.get(indices[0])
        if group is not None and (own is None or own is group):
            return group, indices.index(scene["index"]), len(indices)
    return own, 0, 1


def compose_video(slides: list[Slide], clips: list[GeneratedClip], output_path: str | Path,
                  *, plans: list | None = None, add_subtitles: bool = False,
                  fps: int = config.FPS, add_audio: bool = False, add_bgm: bool = True,
                  bgm_path: str | Path | None = None, bgm_volume: float | None = None,
                  narration_style: str = "direct", visual_mode: str | None = None) -> Path:
    """Compose on one clock; no speech loops, black gaps or stretched images."""
    if not slides:
        raise RuntimeError("No slides to compose")
    if fps <= 0:
        raise ValueError("fps must be positive")
    if narration_style not in ("direct", "explain"):
        raise ValueError("narration_style must be direct or explain")
    from tts_audio import build_slide_narration
    modes = {_field(p, "visual_mode", "creative") for p in (plans or [])}
    if len(modes) > 1:
        raise ValueError("A video must use one visual mode; regenerate its scene plan")
    visual_mode = visual_mode or (next(iter(modes)) if modes else "creative")
    if visual_mode not in {"faithful", "creative"}:
        raise ValueError("visual_mode must be faithful or creative")
    if modes and modes != {visual_mode}:
        raise ValueError("Visual mode differs from scene plans; regenerate the plans")
    content_audit = None
    if add_audio:
        missing = [s['index'] for s in build_scene_timeline(slides, plans)
                   if not s['text'].strip() and not s['muted']]
        if missing:
            raise ValueError(f'第 {missing} 页讲稿为空。请补充讲稿或明确选择静音。')
    if visual_mode == "faithful":
        from faithful_plan import build_faithful_plans, audit_faithful_plans
        from original_slide_renderer import make_original_slide_clip
        from narration_workflow import attach_original_pages
        if plans is None:
            plans = build_faithful_plans(slides, narration_style)
        content_audit = audit_faithful_plans(slides, plans)
        attach_original_pages(slides)
        if clips:
            logger.warning("忠实讲解忽略 %d 个外部生成片段，画面只使用 PPT 来源", len(clips))
        clips = []
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    scenes = build_scene_timeline(slides, plans)
    clip_map = {clip.slide_index: clip for clip in clips}
    for scene in scenes:
        scene['cache_dir'] = str(config.ensure_temp_dir() / 'audio-cache')
        if visual_mode != "faithful" and not scene['preserve_text'] and narration_style == "explain" and _field(scene["plan"], "narration_style") != "explain":
            scene["text"] = build_slide_narration(scene["slide"], "explain")
        gen = clip_map.get(scene["index"])
        if scene["plan"] is None and gen:
            scene["duration"] = max(.5, float(getattr(gen, "planned_duration", scene["duration"])))

    # Keep temporary outputs on the destination volume for atomic replacement.
    temp_dir = Path(tempfile.mkdtemp(prefix=".pptx2vid_", dir=output_path.parent)).resolve()
    resources, final = [], None
    publish_path = output_path.parent / f".{output_path.stem}.{uuid.uuid4().hex}.mp4"
    rendered_manifest = []
    try:
        narration_clips, global_audio = _prepare_narrations(
            scenes, temp_dir, resources, allow_global_fallback=visual_mode != "faithful" and not any(s['preserve_text'] for s in scenes)
        ) if add_audio else ([], None)
        failures = [s['index'] for s in scenes if s.get('narration_status') == 'unavailable' and s['text']]
        if failures:
            raise RuntimeError(f'第 {failures} 页配音失败。讲稿和画面缓存已保留，请重试；如需静音请在讲稿编辑中明确选择。')
        frame_cursor = 0
        for scene in scenes:
            # Quantize to output frames; never shorten narration.
            frame_count = math.ceil(scene["duration"] * fps)
            scene["duration"] = frame_count / fps
            scene["start_time"] = frame_cursor / fps
            frame_cursor += frame_count
        total_duration = frame_cursor / fps
        w, h = map(int, config.VIDEO_SIZE.split("x"))
        background = ColorClip((w, h), (245, 247, 250), duration=total_duration)
        visuals = [background]
        resources.append(background)
        loaded_sources = {}
        for i, scene in enumerate(scenes):
            slide = scene["slide"]
            gen, part_index, part_count = _scene_video_source(scene, clip_map)
            # Outgoing visuals remain behind the incoming fade; speech never
            # overlaps. All subtitle/audio starts use the same scene boundaries.
            overlap = min(.4, scenes[i + 1]["duration"] / 3) if visual_mode != 'faithful' and i + 1 < len(scenes) else 0.
            visual_duration = scene["duration"] + overlap
            video = None
            if visual_mode == "faithful":
                video = make_original_slide_clip(slide.original_page, visual_duration,
                                                 size=(w, h), subtitle_band=add_subtitles)
                rendered_manifest.append({
                    "slide_index": slide.index, "start": scene["start_time"],
                    "end": scene["start_time"] + scene["duration"],
                    "narration": scene["text"],
                    "narration_status": scene.get("narration_status", "disabled"),
                    "layout_kind": _field(scene["plan"], "layout_kind", "points"),
                    "source_facts": _field(scene["plan"], "source_facts", []),
                    "visuals": getattr(video, "content_manifest", {}),
                })
                resources.append(video)
            if gen and Path(gen.file_path).is_file():
                try:
                    source_path = str(Path(gen.file_path).resolve())
                    if source_path not in loaded_sources:
                        loaded = VideoFileClip(source_path, audio=False)
                        resources.append(loaded)
                        if not loaded.duration or loaded.duration <= 0:
                            raise ValueError("empty generated clip")
                        loaded_sources[source_path] = (loaded, _is_black_clip(source_path, loaded.duration))
                    loaded, is_black = loaded_sources[source_path]
                    if is_black:
                        logger.warning("Slide %d: 检测到黑片，已用 fallback 替换", slide.index)
                    else:
                        if part_count > 1:
                            part_duration = loaded.duration / part_count
                            loaded = loaded.subclipped(part_index * part_duration,
                                                       (part_index + 1) * part_duration)
                        scale = min(w / loaded.w, h / loaded.h)
                        video = loaded.without_audio().resized(scale)
                        speed = max(.5, min(2., loaded.duration / visual_duration))
                        video = video.with_effects([MultiplySpeed(factor=speed)])
                        end_frame = max(0., video.duration - 1 / max(1., loaded.fps))
                        # Hold the last frame after a moderate slowdown.
                        video = video.time_transform(lambda t, end=end_frame: min(t, end))
                        video = video.with_duration(visual_duration).with_position("center")
                        video = CompositeVideoClip([video], size=(w, h),
                                                   bg_color=(245, 247, 250)).with_duration(visual_duration)
                        resources.append(video)
                except Exception as exc:
                    video = None
                    logger.warning("Slide %d: clip 加载失败，使用 fallback: %s", slide.index, exc)
            if video is None:
                logger.info("Slide %d: fallback %.2fs", slide.index, scene["duration"])
                video = _make_fallback_clip(slide, visual_duration)
                resources.append(video)
            if i and visual_mode != 'faithful':
                video = video.with_effects([CrossFadeIn(min(.4, scene["duration"] / 3))])
            visuals.append(video.with_start(scene["start_time"]))

        subtitle_items = build_subtitle_items(scenes)
        for item in subtitle_items if add_subtitles else []:
            subtitle = _make_subtitle_clip(item["text"], item["end"] - item["start"], w, h,
                                            faithful=visual_mode == "faithful")
            resources.append(subtitle)
            visuals.append(subtitle.with_start(item["start"]))
        final = CompositeVideoClip(visuals, size=(w, h), bg_color=(245, 247, 250)).with_duration(total_duration)
        audio_layers = [a.with_start(s["start_time"]) for s, a in zip(scenes, narration_clips) if a is not None]
        if global_audio:
            audio_layers.append(global_audio)
        if add_bgm:
            music = _bgm_track(config.BGM_PATH if bgm_path is None else bgm_path, total_duration,
                               config.BGM_VOLUME if bgm_volume is None else max(0., min(.5, bgm_volume)),
                               bool(audio_layers), resources)
            if music:
                audio_layers.append(music)
        if audio_layers:
            track = CompositeAudioClip(audio_layers).with_duration(total_duration)
            resources.append(track)
            final = final.with_audio(track)
        temp_output = temp_dir / "output.mp4"
        logger.info("Encoding %dx%d, %.2fs, fps=%d, audio=%s",
                    w, h, total_duration, fps, bool(audio_layers))
        try:
            _write_video(final, temp_output, fps, config.VIDEO_CODEC)
        except Exception as exc:
            if config.VIDEO_CODEC == "libx264":
                raise
            logger.warning("编码器 %s 不可用，回退 libx264: %s",
                           config.VIDEO_CODEC, str(exc)[-300:])
            _write_video(final, temp_output, fps, "libx264")
        final.close()
        final = None
        # A file moved from a private temporary directory retains its Windows ACL.
        # Create the published file in the output folder so it inherits that
        # folder's access rules, then atomically replace the previous video.
        with temp_output.open("rb") as src, publish_path.open("xb") as dst:
            shutil.copyfileobj(src, dst)
        os.replace(publish_path, output_path)
        if content_audit is not None:
            audit_path = output_path.with_suffix(".content.json")
            audit_path.write_text(json.dumps({
                "visual_mode": visual_mode, "source_audit": content_audit,
                "duration": total_duration, "video_size": config.VIDEO_SIZE,
                "scenes": rendered_manifest,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("内容来源与时间轴已导出: %s", audit_path)
        export_srt(subtitle_items, output_path.with_suffix(".srt"))
        logger.info("Final video written: %s (%.2f MB)", output_path, output_path.stat().st_size / 1e6)
        _quality_check_video(output_path, fps)
        return output_path
    finally:
        publish_path.unlink(missing_ok=True)
        if final:
            final.close()
        for resource in reversed(resources):
            try:
                resource.close()
            except Exception:
                pass
        # Delete only this verified, newly created child directory.
        if temp_dir.parent == output_path.parent and temp_dir.name.startswith(".pptx2vid_"):
            shutil.rmtree(temp_dir, ignore_errors=True)


def _quality_check_video(video_path: Path, expected_fps: int = 24) -> None:
    """Best-effort stream checks plus the final sampled black-segment gate."""
    video_path = Path(video_path)
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams",
                                 "-of", "json", str(video_path)],
                                capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            fmt = data.get("format", {})
            for stream in data.get("streams", []):
                if stream.get("codec_type") != "video":
                    continue
                width, height = stream.get("width", 0), stream.get("height", 0)
                if min(width, height) < 640:
                    logger.warning("Quality gate: Low resolution %dx%d", width, height)
                num, den = map(float, stream.get("r_frame_rate", "0/1").split("/"))
                if den and abs(num / den - expected_fps) > 2:
                    logger.warning("Quality gate: fps %.2f (expected %d)", num / den, expected_fps)
            bitrate = float(fmt.get("bit_rate", 0)) / 1000
            if 0 < bitrate < 500:
                logger.warning("Quality gate: Low bitrate %.0f kbps (static slides may compress well)", bitrate)
            logger.info("Quality gate: %.2fs, %.2f MB, %.0f kbps", float(fmt.get("duration", 0)),
                        video_path.stat().st_size / 1e6, bitrate)
    except Exception:
        pass
    for start, end in _black_segments(_detect_black_frames(video_path)):
        logger.error("Quality gate: 检测到黑段 %.2fs–%.2fs（连续 ≥2s）", start, end)
