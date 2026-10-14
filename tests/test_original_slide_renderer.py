import hashlib

import numpy as np
import unittest
import tempfile
from pathlib import Path
from PIL import Image


def page(tmp_path):
    path = tmp_path / 'page.png'
    Image.new('RGB', (400, 200), (220, 30, 60)).save(path)
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                source_sha256='source', width=400, height=200,
                renderer='powerpoint-native', warnings=[], slide_index=3)


def test_static_original_size_and_metadata(tmp_path):
    from original_slide_renderer import make_original_slide_clip
    record = page(tmp_path)
    clip = make_original_slide_clip(record, 3)
    assert tuple(clip.size) == (400, 200)
    assert np.array_equal(clip.get_frame(0), clip.get_frame(2))
    assert clip.content_manifest['slide_index'] == 3
    assert clip.content_manifest['sha256'] == record['sha256']
    clip.close()


def test_letterbox_preserves_full_page_and_external_subtitle_band(tmp_path):
    from original_slide_renderer import make_original_slide_clip
    for size in [(200, 400), (800, 200)]:
        clip = make_original_slide_clip(page(tmp_path), 3, size=size, subtitle_band=True)
        frame = clip.get_frame(0)
        ys, xs = np.where(frame[:, :, 0] > 200)
        assert abs((xs.max()-xs.min()+1) / (ys.max()-ys.min()+1) - 2) < .04
        assert ys.max() < size[1] * .82
        assert frame[int(size[1] * .82):].max() == 0
        clip.close()


def test_rejects_tampered_page(tmp_path):
    from original_slide_renderer import make_original_slide_clip
    record = page(tmp_path)
    Image.new('RGB', (400, 200), 'blue').save(record['path'])
    with unittest.TestCase().assertRaisesRegex(ValueError, 'hash|摘要'):
        make_original_slide_clip(record, 3)


def test_invalid_duration(tmp_path):
    from original_slide_renderer import make_original_slide_clip
    for duration in (0, -1, float('nan')):
        with unittest.TestCase().assertRaises(ValueError):
            make_original_slide_clip(page(tmp_path), duration)


class OriginalSlideTests(unittest.TestCase):
    pass


for _name, _fn in list(globals().items()):
    if _name.startswith('test_'):
        def _run(self, fn=_fn):
            with tempfile.TemporaryDirectory() as tmp:
                fn(Path(tmp))
        setattr(OriginalSlideTests, _name, _run)
del _name, _fn
