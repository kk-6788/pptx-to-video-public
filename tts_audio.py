"""
Text-to-Speech audio generation for PPTX-to-Video.

Uses edge-tts (Microsoft Edge online TTS, free) by default.
Falls back to Windows built-in SAPI5 (offline, no install needed).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import hashlib
import json
import shutil
import math
import re
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _narration_parts(text: str) -> list[str]:
    """Normalize presentation bullets and deduplicate complete phrases."""
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\u00a0", " ").replace("\u200b", "")
    lines = []
    for line in normalized.splitlines():
        line = re.sub(r"^\s*#{1,6}\s*", "", line)
        line = re.sub(r"^\s*(?:(?:[•●◦▪·*]\s*|[+\-]\s+|\d+[.)、]\s+|[一二三四五六七八九十]+、\s*))+", "", line)
        line = line.replace("**", "").replace("__", "")
        lines.append(re.sub(r"\s+", " ", line).strip())
    # A decimal point is not a sentence boundary; keep quantities unchanged.
    chunks = re.split(r"[\n。！？!?；;]+|(?<!\d)\.(?:\s+|$)", "\n".join(lines))
    parts = []
    seen = set()
    for chunk in chunks:
        chunk = chunk.strip(" \t。.!?！？；;")
        key = re.sub(r"\s+", "", chunk).casefold()
        if key and key not in seen:
            parts.append(chunk)
            seen.add(key)
    return parts


def clean_narration_text(text: str) -> str:
    """Return speakable text without bullet markers or duplicate sentences."""
    parts = _narration_parts(text)
    return "。".join(parts) + ("。" if parts else "")


def build_slide_narration(slide, narration_style: str = "direct") -> str:
    """Build one page's narration without adding unsupported facts.

    ``direct`` preserves the slide's complete information. ``explain`` uses
    local wording rules and whole-sentence selection, targeting 40–80 Chinese
    characters while retaining all quantities and explicit conclusions.
    """
    if narration_style not in {"direct", "explain"}:
        raise ValueError("narration_style must be 'direct' or 'explain'")
    title = str(getattr(slide, "title", "") or "").strip()
    content = getattr(slide, "text_content", "") or getattr(slide, "body", "") or ""
    direct = clean_narration_text(title + "\n" + content)
    if narration_style == "direct" or not direct:
        return direct

    sentences = _narration_parts(direct)
    for i, sentence in enumerate(sentences):
        sentence = re.sub(r"^(?:首先|其次|最后)(?:[，,：:\s]+|$)", "", sentence)
        for formal, spoken in (("与此同时", "同时"), ("主要包括", "包括"),
                               ("能够", "能"), ("以此", "这样"), ("综上所述，", "")):
            sentence = sentence.replace(formal, spoken)
        sentences[i] = sentence
    title_parts = _narration_parts(title)
    if title_parts and sentences and sentences[0] == title_parts[0]:
        sentences[0] = "这页讲的是" + sentences[0]
    elif sentences:
        sentences[0] = "我们来看，" + sentences[0]

    def han_count(value: str) -> int:
        return len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", value))

    complete = clean_narration_text("。".join(sentences))
    if han_count(complete) < 40 and title_parts and len(sentences) > 1:
        details = sentences[1:]
        if all(len(part) <= 18 for part in details):
            joined = "、".join(details[:-1]) + ("，以及" if len(details) > 1 else "") + details[-1]
            complete = f"接下来，我们一起看一下{title}。这一页提到的内容包括{joined}。"
        if han_count(complete) < 40:
            complete += "我们把这些内容放在一起，接着往下看。"
    if han_count(complete) > 80:
        # Quantities, their original context, and conclusion/action sentences
        # are inseparable. Never shorten a number or cut a clause mid-sentence.
        essential = {0, len(sentences) - 1}
        conclusion = r"结论|因此|所以|可见|表明|意味着|建议|下一步|下一阶段|应当|需要|必须|继续|总结"
        quantities = r"\d|[一二三四五六七八九十百千万亿两半]+(?:年|月|日|个|项|次|元|万|亿|成|倍|%|％)|百分之"
        essential.update(i for i, s in enumerate(sentences)
                         if re.search(quantities, s) or re.search(conclusion, s))
        selected = set(essential)
        essential_text = clean_narration_text("。".join(sentences[i] for i in sorted(selected)))
        if han_count(essential_text) > 80:
            logger.warning("Slide %s narration contains dense facts (%d Chinese characters); retaining complete facts beyond the 80-character target",
                           getattr(slide, "index", "?"), han_count(complete))
            return complete
        for i in range(len(sentences)):
            candidate = sorted(selected | {i})
            candidate_text = "。".join(sentences[j] for j in candidate)
            if han_count(candidate_text) <= 80:
                selected.add(i)
        complete = clean_narration_text("。".join(sentences[i] for i in sorted(selected)))
    if han_count(complete) < 40:
        logger.warning("Slide %s has too little source text for 40 Chinese characters; keeping the factual short narration",
                       getattr(slide, "index", "?"))
    return complete


# ---------------------------------------------------------------------------
# Edge TTS (preferred — high-quality Chinese voice)
# ---------------------------------------------------------------------------


async def _edge_tts(
    text: str,
    voice: str = "zh-CN-XiaoxiaoNeural",
    output_path: str | Path | None = None,
    *, preserve_text: bool = False, rate: str = '+0%',
) -> Optional[Path]:
    """Generate TTS audio using edge-tts (Microsoft Edge online TTS).

    Args:
        text: Text to speak.
        voice: Edge TTS voice name (default: zh-CN-XiaoxiaoNeural, female).
        output_path: Where to save the audio file (auto-generates if None).

    Returns:
        Path to the generated audio file, or None if edge-tts is not available.
    """
    text = str(text).strip() if preserve_text else clean_narration_text(text)
    if not text:
        return None
    try:
        import edge_tts as _edge
    except ImportError:
        return None

    if output_path is None:
        output_path = Path(tempfile.mkdtemp(prefix="pptx2vid_tts_")) / "narration.mp3"

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Save atomically, so a failed retry cannot expose a partial audio file.
    partial_path = output_path.with_name(output_path.name + ".part")
    for attempt in range(3):
        try:
            communicate = _edge.Communicate(text, voice, rate=rate)
            await asyncio.wait_for(communicate.save(str(partial_path)), timeout=60.0)
            if not partial_path.exists() or partial_path.stat().st_size == 0:
                raise RuntimeError("Empty TTS response")
            partial_path.replace(output_path)
            logger.info("Edge TTS audio generated: %s (%.1f KB)",
                        output_path.name, output_path.stat().st_size / 1024)
            return output_path
        except Exception as exc:
            logger.warning("Edge TTS attempt %d/3 failed for %s (%s)",
                           attempt + 1, output_path.name, type(exc).__name__)
            if attempt < 2:
                await asyncio.sleep(attempt + 1)
        finally:
            partial_path.unlink(missing_ok=True)
    return None


# ---------------------------------------------------------------------------
# Windows SAPI fallback (offline, no deps)
# ---------------------------------------------------------------------------


def _sapi_tts(
    text: str,
    output_path: str | Path | None = None,
) -> Optional[Path]:
    """Generate TTS audio using Windows SAPI5 via PowerShell (no deps).

    Args:
        text: Text to speak.
        output_path: Where to save the WAV file.

    Returns:
        Path to the generated audio file, or None on failure.
    """
    if output_path is None:
        output_path = Path(tempfile.mkdtemp(prefix="pptx2vid_tts_")) / "narration.wav"
    # SAPI writes WAV data; never label that payload as MP3.
    output_path = Path(output_path).with_suffix(".wav")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Data is Base64-decoded inside PowerShell, never interpolated as code.
    text_b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    path_b64 = base64.b64encode(str(output_path.resolve()).encode("utf-8")).decode("ascii")
    ps_script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$narrationText = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{text_b64}'))
$narrationPath = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{path_b64}'))
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {{
    try {{ $synth.SelectVoice('Microsoft Huihui Desktop') }} catch {{}}
    $synth.SetOutputToWaveFile($narrationPath)
    $synth.Speak($narrationText)
}} finally {{
    $synth.Dispose()
}}
"""
    encoded_script = base64.b64encode(ps_script.encode("utf-16-le")).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_script],
            capture_output=True, text=True, errors='replace', timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            logger.info(
                "SAPI TTS audio generated: %s (%.1f KB)",
                output_path.name, output_path.stat().st_size / 1024,
            )
            return output_path
        else:
            logger.warning("SAPI TTS failed (exit code %s)", result.returncode)
            return None
    except Exception as exc:
        logger.warning("SAPI TTS exception: %s", type(exc).__name__)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def generate_narration(
    text: str,
    output_path: str | Path | None = None,
    voice: str = "zh-CN-XiaoxiaoNeural",
    *, preserve_text: bool = False, rate: str = '+0%',
) -> Optional[Path]:
    """Generate narration audio from text.

    Tries edge-tts first (high quality), falls back to Windows SAPI.

    Args:
        text: Text to narrate.
        output_path: Where to save the audio file.
        voice: Edge TTS voice name.

    Returns:
        Path to generated audio file, or None if all methods failed.
    """
    text = str(text).strip() if preserve_text else clean_narration_text(text)
    if not text:
        return None
    # Try edge-tts first
    options = {"preserve_text": True} if preserve_text else {}
    if rate != '+0%':
        options['rate'] = rate
    audio_path = await _edge_tts(text, voice=voice, output_path=output_path, **options)
    if audio_path:
        return audio_path

    # Fallback: Windows SAPI
    logger.info("edge-tts not available, trying Windows SAPI...")
    audio_path = await asyncio.to_thread(_sapi_tts, text, output_path=output_path)
    if audio_path:
        return audio_path

    logger.warning("All TTS methods failed — no narration audio generated")
    return None


def build_narration_text(
    slides: list,
    clips: list | None = None,
) -> str:
    """Build a single narration string from slide content.

    Concatenates slide titles and text content into a flowing narration.

    Args:
        slides: Parsed slides (in order).
        clips: Optional generated clips (unused, for future per-scene TTS).

    Returns:
        Narration text ready for TTS.
    """
    return "".join(build_slide_narration(slide) for slide in slides)


def _audio_duration(path: str | Path) -> float:
    """Read the generated audio's actual duration and close the decoder."""
    from moviepy import AudioFileClip
    with AudioFileClip(str(path)) as audio:
        duration = float(audio.duration)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Generated audio has no measurable duration")
    return duration


async def generate_scene_narrations(scenes, output_dir) -> list[dict | None]:
    """Synthesize independent MP3s, keeping a None slot for any failed scene.

    Scene mappings/objects provide ``index``, ``text``, ``start_time`` and
    ``duration``. A supplied ``narration_text`` takes precedence over ``text``.
    Returned duration is measured from the file, not the planned scene length.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict | None] = []
    for position, scene in enumerate(scenes):
        index = position
        try:
            get = scene.get if isinstance(scene, Mapping) else lambda key, default=None: getattr(scene, key, default)
            index = int(get("index", position))
            raw = get("narration_text", None)
            if raw is None:
                raw = get("text", "") or ""
            preserve = bool(get("preserve_text", False))
            text = str(raw).strip() if preserve else clean_narration_text(raw)
            if not text:
                results.append(None)
                continue
            options = {"preserve_text": True} if preserve else {}
            voice = get('voice', 'zh-CN-XiaoxiaoNeural')
            rate = get('rate', '+0%')
            if voice != 'zh-CN-XiaoxiaoNeural':
                options['voice'] = voice
            if rate != '+0%':
                options['rate'] = rate
            cache_dir = get('cache_dir')
            cache_path = None
            if cache_dir:
                fingerprint = hashlib.sha256(json.dumps([text, voice, rate, 'edge-tts-v1'], ensure_ascii=False).encode('utf-8')).hexdigest()
                cache_path = Path(cache_dir) / (fingerprint + '.mp3')
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                if cache_path.is_file():
                    try:
                        duration = await asyncio.to_thread(_audio_duration, cache_path)
                        if duration > 0 and math.isfinite(duration):
                            results.append({'index': index, 'path': str(cache_path.resolve()), 'duration': duration})
                            continue
                    except Exception:
                        pass
            path = await _edge_tts(text, output_path=output_dir / f"scene_{index:03d}.mp3", **options)
            if path is None:
                results.append(None)
                logger.warning("Scene %s has no Edge TTS audio; continuing with later scenes", index)
                continue
            duration = await asyncio.to_thread(_audio_duration, path)
            if cache_path and duration > 0 and math.isfinite(duration):
                import uuid
                partial = cache_path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
                try:
                    shutil.copyfile(path, partial)
                    partial.replace(cache_path)
                finally:
                    partial.unlink(missing_ok=True)
            results.append({"index": index, "path": str(path.resolve()), "duration": duration})
            logger.info("Scene %s narration duration: %.3fs", index, duration)
        except Exception as exc:
            logger.warning("Scene %s narration failed (%s); continuing with later scenes", index, type(exc).__name__)
            results.append(None)
    return results
