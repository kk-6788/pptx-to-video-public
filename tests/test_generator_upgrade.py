"""A provider double verifies real slide selection without consuming an API."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pptx_parser import Slide
from prompt_engine import ScenePlan
import video_generator


class GeneratorSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_based_and_subset_indices_use_correct_source_image(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, last = root / 'first.png', root / 'last.png'
            first.write_bytes(b'first-image')
            last.write_bytes(b'last-image')
            slides = [Slide(1, 'First', image_paths=[str(first)]),
                      Slide(5, 'Last', image_paths=[str(last)])]
            provider = SimpleNamespace(name='test', generate_video=AsyncMock(
                return_value=SimpleNamespace(data=b'video' * 1024, metadata={'duration': 5})))
            clips = await video_generator.generate_clips_from_plans(
                slides, [ScenePlan(1), ScenePlan(5)], image_provider=provider,
                video_provider=provider, output_dir=root, max_concurrent=1)
            self.assertEqual([clip.slide_index for clip in clips], [1, 5])
            self.assertEqual([call.kwargs['image_data'] for call in provider.generate_video.await_args_list],
                             [b'first-image', b'last-image'])


if __name__ == '__main__':
    unittest.main()
