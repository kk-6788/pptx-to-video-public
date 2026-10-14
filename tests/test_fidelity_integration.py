"""Source fidelity boundaries, failure isolation and actual frame composition."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import numpy as np
from moviepy import AudioClip
import config
import main
import tts_audio
import video_composer as vc
from faithful_plan import build_faithful_plans
from pptx_parser import Slide
from video_generator import generate_clips_from_plans


class FidelityIntegrationTests(unittest.TestCase):
    def setUp(self):
        import hashlib
        from PIL import Image
        self.pages_folder = tempfile.TemporaryDirectory()
        image_path = Path(self.pages_folder.name) / 'page.png'
        Image.new('RGB', (1280, 720), 'white').save(image_path)
        record = dict(path=str(image_path), sha256=hashlib.sha256(image_path.read_bytes()).hexdigest(),
                      width=1280, height=720, renderer='fixture-native-export')
        def attach(slides):
            for slide in slides:
                slide.original_page = dict(record, slide_index=slide.index)
        self.page_patch = patch('narration_workflow.attach_original_pages', side_effect=attach)
        self.page_patch.start()
        self.addCleanup(self.page_patch.stop)
        self.addCleanup(self.pages_folder.cleanup)
    def test_default_cli_never_initializes_a_generation_provider(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch('providers.get_providers', side_effect=AssertionError('provider called')), \
                patch('video_generator.generate_clips_from_plans', side_effect=AssertionError('AI called')), \
                patch.object(vc, 'compose_video', return_value=Path(folder) / 'out.mp4') as compose:
            self.assertEqual(main.main(['-i', 'demo.pptx', '-o', str(Path(folder)/'out.mp4')]), 0)
            self.assertEqual(compose.call_args.kwargs['visual_mode'], 'faithful')
            self.assertEqual(compose.call_args.args[1], [])
            self.assertEqual([p.slide_indices for p in compose.call_args.kwargs['plans']], [[1], [2]])

    def test_explicit_creative_mode_remains_available(self):
        provider = SimpleNamespace(close=AsyncMock())
        with tempfile.TemporaryDirectory() as folder, \
                patch('providers.get_providers', return_value=(provider, provider)) as factory, \
                patch('video_generator.generate_clips_from_plans', new=AsyncMock(return_value=[])), \
                patch('video_generator.cleanup_temp_files', new=AsyncMock()), \
                patch.object(vc, 'compose_video') as compose:
            self.assertEqual(main.main(['-i','demo.pptx','-o',str(Path(folder)/'out.mp4'),
                                        '--visual-mode','creative','--provider','comfyui']), 0)
            factory.assert_called_once()
            self.assertEqual(compose.call_args.kwargs['visual_mode'], 'creative')

    def test_generator_cannot_submit_faithful_plans(self):
        slides = [Slide(1, '真实标题', body='准确率为 93.2%')]
        provider = SimpleNamespace(generate_image=AsyncMock(side_effect=AssertionError('image API')),
                                   generate_video=AsyncMock(side_effect=AssertionError('video API')))
        with tempfile.TemporaryDirectory() as folder:
            result = asyncio.run(generate_clips_from_plans(slides, build_faithful_plans(slides),
                image_provider=provider, video_provider=provider, output_dir=Path(folder)))
            self.assertEqual(result, [])
            provider.generate_image.assert_not_called()
            provider.generate_video.assert_not_called()

    def test_mode_mismatch_and_changed_facts_fail_before_encoding(self):
        slides = [Slide(1, '结果', body='增长35%')]
        plans = build_faithful_plans(slides)
        with patch.object(vc, '_write_video', side_effect=AssertionError('encoded')):
            with self.assertRaises(ValueError):
                vc.compose_video(slides, [], 'unused.mp4', plans=plans, visual_mode='creative')
            plans[0].source_facts[0] = '增长99%'
            with self.assertRaises(ValueError):
                vc.compose_video(slides, [], 'unused.mp4', plans=plans)

    def test_composition_ignores_generated_video_and_exports_source_timeline(self):
        slides = [Slide(1, '原文一', body='收入 128.75 万元'), Slide(2, '原文二', body='后续投入20万元')]
        plans = build_faithful_plans(slides)
        decoded = []
        def encode(final, path, fps, codec):
            for stamp in (.01, plans[0].suggested_duration_sec - .02,
                          plans[0].suggested_duration_sec + .2, final.duration - .05):
                frame = final.get_frame(stamp)
                self.assertGreater(frame.mean(), 140)
                decoded.append(stamp)
            path.write_bytes(b'encoded-test')
        with tempfile.TemporaryDirectory() as folder, patch.object(config, 'VIDEO_SIZE', '1280x720'), \
                patch.object(vc, '_write_video', side_effect=encode), \
                patch.object(vc, '_quality_check_video'), \
                patch.object(vc, 'VideoFileClip', side_effect=AssertionError('external video loaded')):
            path = Path(folder)/'out.mp4'
            external = SimpleNamespace(slide_index=1, file_path='unrelated.mp4')
            vc.compose_video(slides, [external], path, plans=plans, add_subtitles=True, add_bgm=False)
            manifest = json.loads(path.with_suffix('.content.json').read_text(encoding='utf-8'))
            scenes = manifest['scenes']
            self.assertEqual([s['slide_index'] for s in scenes], [1, 2])
            self.assertEqual(scenes[0]['end'], scenes[1]['start'])
            self.assertTrue(all(s['visuals']['renderer'] == 'original-slide-v1' for s in scenes))
            self.assertEqual(path.read_bytes(), b'encoded-test')
            self.assertTrue(path.with_suffix('.srt').read_bytes().startswith(b'\xef\xbb\xbf'))
            self.assertEqual(list(Path(folder).glob('.pptx2vid_*')), [])
        self.assertEqual(len(decoded), 4)

    def test_failed_tts_is_isolated_and_cannot_shorten_a_page(self):
        scenes = [dict(index=i+1, text=f'页面{i}', duration=d) for i, d in enumerate([6,200,6])]
        sounds = []
        def audio(_):
            clip = AudioClip(lambda t: np.array([0.0]), duration=2, fps=8000)
            sounds.append(clip)
            return clip
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(tts_audio, 'generate_scene_narrations', new=AsyncMock(return_value=[None, {'path':'ok.mp3'}, None])), \
                patch.object(tts_audio, 'generate_narration', new=AsyncMock(side_effect=[None,'recovered.wav'])) as retry, \
                patch.object(vc, 'AudioFileClip', side_effect=audio):
            fitted, global_audio = vc._prepare_narrations(scenes, Path(folder), [], allow_global_fallback=False)
            self.assertIsNone(global_audio)
            self.assertIsNone(fitted[0])
            self.assertEqual([s['duration'] for s in scenes], [6,200,6])
            self.assertEqual([s['narration_status'] for s in scenes], ['unavailable','generated','recovered'])
            self.assertEqual([c.args[0] for c in retry.call_args_list], ['页面0','页面2'])
        for sound in sounds:
            sound.close()

    def test_tts_preserves_repeated_source_facts_in_faithful_mode(self):
        text = '试验一。数值35%。试验二。数值35%。'
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(tts_audio, '_edge_tts', new=AsyncMock(return_value=Path(folder)/'scene.mp3')) as synth, \
                patch.object(tts_audio, '_audio_duration', return_value=5):
            asyncio.run(tts_audio.generate_scene_narrations(
                [dict(index=1, text=text, preserve_text=True)], folder))
            self.assertEqual(synth.call_args.args[0], text)
            self.assertTrue(synth.call_args.kwargs['preserve_text'])

    def test_fractional_scene_durations_do_not_lose_the_last_video_frame(self):
        slides = [Slide(1, '开始', body='内容一'), Slide(2, '继续', body='内容二')]
        plans = build_faithful_plans(slides)
        plans[0].suggested_duration_sec = 18.25
        plans[1].suggested_duration_sec = 22.083333333333332
        def encode(final, path, fps, codec):
            self.assertEqual(int(final.duration * fps), 484)
            path.write_bytes(b'frames-test')
        with tempfile.TemporaryDirectory() as folder, patch.object(config, 'VIDEO_SIZE', '1280x720'), \
                patch.object(vc, '_write_video', side_effect=encode), patch.object(vc, '_quality_check_video'):
            vc.compose_video(slides, [], Path(folder)/'fractional.mp4', plans=plans,
                             fps=12, add_bgm=False)


if __name__ == '__main__':
    unittest.main()
