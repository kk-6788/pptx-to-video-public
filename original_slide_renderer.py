"""Static original PowerPoint pages, fitted without cropping or restyling."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np
from PIL import Image
from moviepy import ImageClip


def make_original_slide_clip(page_record, duration, *, size=None, subtitle_band=False):
    """Return a static clip; ``None`` size preserves the original page dimensions.

    The optional subtitle band reserves the bottom 18% outside the page.
    The caller may place captions there. Original pixels are never covered.
    """
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Page duration must be finite and positive')
    path = Path(page_record['path'])
    if hashlib.sha256(path.read_bytes()).hexdigest() != page_record['sha256']:
        raise ValueError('Original page image hash does not match its manifest')
    with Image.open(path) as source:
        source.load()
        if source.size != (page_record['width'], page_record['height']):
            raise ValueError('Original page image dimensions do not match its manifest')
        original = source.convert('RGB')
    if isinstance(size, str):
        size = tuple(map(int, size.lower().split('x')))
    width, height = map(int, size or original.size)
    if min(width, height) <= 0:
        raise ValueError('Output size must be positive')
    available_height = max(1, int(height * .82)) if subtitle_band else height
    scale = min(width / original.width, available_height / original.height)
    fitted = (max(1, round(original.width * scale)),
              max(1, round(original.height * scale)))
    x, y = (width - fitted[0]) // 2, (available_height - fitted[1]) // 2
    canvas = Image.new('RGB', (width, height), 'black')
    canvas.paste(original.resize(fitted, Image.Resampling.LANCZOS), (x, y))
    clip = ImageClip(np.asarray(canvas), duration=float(duration))
    clip.content_manifest = {
        **page_record, 'renderer': 'original-slide-v1',
        'page_renderer': page_record['renderer'], 'duration': float(duration),
        'page_bounds': [x, y, x + fitted[0], y + fitted[1]],
        'subtitle_band': bool(subtitle_band),
        'subtitle_bounds': [0, available_height, width, height] if subtitle_band else None,
        'output_size': [width, height],
    }
    return clip
