import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _real_mp4_bytes():
    """PPT-02: cache validation now requires a decodable video, so provider
    stubs must produce real MP4 bytes (tiny ffmpeg testsrc clip)."""
    global _MP4_CACHE
    if _MP4_CACHE is None:
        import shutil as _shutil
        ffmpeg = _shutil.which('ffmpeg')
        if ffmpeg is None:
            return b'video-pixels' * 200  # degraded fallback, same as before
        import tempfile as _tf
        with _tf.TemporaryDirectory() as td:
            out = Path(td) / 't.mp4'
            subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi',
                            '-i', 'testsrc=duration=0.2:size=64x64:rate=10',
                            '-pix_fmt', 'yuv420p', '-y', str(out)],
                           capture_output=True, check=True)
            _MP4_CACHE = out.read_bytes()
    return _MP4_CACHE


_MP4_CACHE = None

import config
from pptx_parser import Slide
from prompt_engine import EnhancedScenePlan
from providers import GenerationResult
from video_generator import generate_clips_from_plans, cleanup_temp_files


class RecordingProvider:
    name = 'offline-test'
    _image_model = 'image-v1'
    _video_model = 'video-v1'
    _base_url = 'https://example.invalid/api?token=secret-url'
    _api_key = 'secret-key'

    def __init__(self):
        self.images = 0
        self.videos = 0

    async def generate_image(self, **kwargs):
        self.images += 1
        return GenerationResult(data=b'image-pixels')

    async def generate_video(self, **kwargs):
        self.videos += 1
        return GenerationResult(data=_real_mp4_bytes(), metadata={'duration': 5})


class VisualCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)
        self.slides = [Slide(index=1, title='One'), Slide(index=2, title='Two')]
        self.plans = [EnhancedScenePlan(slide_index=i, image_prompts=['a mountain'],
                     video_prompt='slow camera', narration_text='first narration') for i in (1, 2)]
        self.provider = RecordingProvider()

    async def generate(self, provider=None):
        provider = provider or self.provider
        return await generate_clips_from_plans(self.slides, self.plans,
            image_provider=provider, video_provider=provider, output_dir=self.out,
            use_slide_images=False)

    async def test_narration_edit_and_new_provider_reuse_without_requests(self):
        first = await self.generate()
        self.plans[0].narration_text = 'user edited narration'
        self.plans[0].subtitle_text = 'new captions'
        self.plans[0].narration_state = 'edited'
        provider = RecordingProvider()
        second = await self.generate(provider)
        self.assertEqual(provider.images, 0)
        self.assertEqual(provider.videos, 0)
        self.assertEqual(first, second)
        manifests = list(self.out.rglob('visual-cache.json'))
        self.assertEqual(len(manifests), 2)
        for path in manifests:
            raw = path.read_text(encoding='utf-8')
            self.assertNotIn('secret-key', raw)
            self.assertNotIn('secret-url', raw)

    async def test_prompt_change_regenerates_only_changed_scene(self):
        await self.generate()
        self.plans[1].video_prompt = 'new camera'
        await self.generate()
        self.assertEqual((self.provider.images, self.provider.videos), (3, 3))

    async def test_normal_cleanup_preserves_persistent_visual_cache(self):
        await self.generate()
        with patch.object(config, 'TEMP_DIR', self.out):
            await cleanup_temp_files()
        provider = RecordingProvider()
        await self.generate(provider)
        self.assertEqual(provider.videos, 0)

    async def test_changed_source_in_merged_plan_invalidates(self):
        self.plans = self.plans[:1]
        self.plans[0].slide_indices = [1, 2]
        await self.generate()
        self.slides[1].body = 'changed source'
        await self.generate()
        self.assertEqual(self.provider.videos, 2)

    async def test_corrupt_clip_and_missing_keyframe_regenerate(self):
        first = await self.generate()
        Path(first[0].file_path).write_bytes(b'corrupt')
        Path(first[1].keyframe_paths[0]).unlink()
        await self.generate()
        self.assertEqual(self.provider.videos, 4)

    async def test_model_size_duration_and_image_changes_invalidate(self):
        self.plans = self.plans[:1]
        image = self.out / 'source-image.png'
        image.write_bytes(b'original')
        self.slides[0].image_paths = [str(image)]
        await self.generate()
        self.provider._video_model = 'video-v2'
        await self.generate()
        with patch.object(config, 'VIDEO_SIZE', '720x1280'):
            await self.generate()
        self.plans[0].suggested_duration_sec = 8
        await self.generate()
        image.write_bytes(b'new image')
        await self.generate()
        self.assertEqual(self.provider.videos, 5)
