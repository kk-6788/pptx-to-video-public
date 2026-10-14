import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

import numpy as np
from moviepy import AudioClip, VideoClip

import config
import video_composer as vc
from pptx_parser import Slide


class ComposerRegressionTests(unittest.TestCase):
    def test_group_video_distributes_all_segments_to_original_pages(self):
        colors = [(240, 30, 30), (30, 240, 30), (30, 30, 240)]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'group.mp4'
            clip = VideoClip(lambda t: np.full((90, 160, 3), colors[min(2, int(t))], dtype=np.uint8), duration=3)
            clip.write_videofile(str(source), fps=12, codec='libx264', audio=False, logger=None)
            clip.close()
            slides = [Slide(i, f'Page {i}') for i in (1, 2, 3)]
            plan = SimpleNamespace(slide_index=1, slide_indices=[1, 2, 3], suggested_duration_sec=3)
            generated = SimpleNamespace(slide_index=1, file_path=str(source), planned_duration=3)

            def check_frames(final, path, fps, codec):
                for second, channel in ((.65, 0), (1.65, 1), (2.65, 2)):
                    pixel = final.get_frame(second)[90, 160]
                    self.assertGreater(pixel[channel], 200, (second, pixel))
                    self.assertLess(pixel[(channel + 1) % 3], 60, (second, pixel))
                path.write_bytes(b'composition frames verified')

            with patch.object(config, 'VIDEO_SIZE', '320x180'), patch.object(config, 'VIDEO_CODEC', 'libx264'), \
                 patch.object(vc, '_write_video', side_effect=check_frames), \
                 patch.object(vc, '_quality_check_video'):
                vc.compose_video(slides, [generated], Path(directory) / 'out.mp4',
                                  plans=[plan], add_bgm=False, fps=12)

    def test_fallback_is_light_and_works_with_moviepy_v2(self):
        with patch.object(config, 'VIDEO_SIZE', '1280x720'):
            clip = vc._make_fallback_clip(Slide(1, '转化率提升 35%', '- 优化路径\n- 降低操作成本'), 5)
            try:
                self.assertEqual(clip.size, (1280, 720))
                self.assertGreater(clip.get_frame(0).mean(), 180)
                self.assertGreater(clip.get_frame(2.5).mean(), 180)
            finally:
                clip.close()

    def test_black_runs_do_not_join_across_bright_frames(self):
        self.assertTrue(vc._has_black_segment([(0, 0), (1, 0), (2, 0)]))
        self.assertFalse(vc._has_black_segment([(0, 0), (1, 245), (2, 0)]))
        self.assertFalse(vc._has_black_segment([]))

    def test_srt_bom_rounding_and_chinese(self):
        with tempfile.TemporaryDirectory() as temp:
            path = vc.export_srt([{'start': 59.9996, 'end': 62.1, 'text': '增长 35%'}], Path(temp) / '字幕.srt')
            self.assertTrue(path.read_bytes().startswith(b'\xef\xbb\xbf'))
            self.assertIn('00:01:00,000 --> 00:01:02,100', path.read_text(encoding='utf-8-sig'))

    def test_grouped_plans_narrate_each_page_once(self):
        slides = [Slide(1, '甲', '- 数据 35%'), Slide(2, '乙', '- 成本 20%')]
        plan = SimpleNamespace(slide_index=1, slide_indices=[1, 2], suggested_duration_sec=12,
                               narration_by_slide={1: '看甲的数据 35%。', 2: '再看乙的成本 20%。'},
                               narration_text='不应重复这一组的讲解', narration_style='direct')
        scenes = vc.build_scene_timeline(slides, [plan])
        self.assertEqual(len(scenes), 2)
        self.assertEqual(scenes[1]['text'], '再看乙的成本 20%。')
        self.assertAlmostEqual(scenes[1]['start_time'], scenes[0]['duration'])
        self.assertAlmostEqual(sum(s['duration'] for s in scenes), 12)

    def test_long_audio_extends_scene_without_truncation_or_loop(self):
        clip = AudioClip(lambda t: np.sin(2 * np.pi * 440 * t), duration=10, fps=24000)
        fitted, duration = vc._fit_narration(clip, 3)
        self.assertGreaterEqual(fitted.duration, 8)
        self.assertGreaterEqual(duration, fitted.duration)
        fitted.close()
        clip.close()

    def test_subtitles_keep_all_text_and_stay_within_scene(self):
        text = '这一页的转化率提升了35%，成本减少了20%。接下来我们看具体流程。'
        scenes = [{'index': 1, 'text': text, 'start_time': 3., 'duration': 8.}]
        with patch.object(config, 'VIDEO_SIZE', '720x1280'):
            items = vc.build_subtitle_items(scenes)
        self.assertEqual(''.join(i['text'].replace('\n', '') for i in items), text)
        self.assertEqual(items[0]['start'], 3.)
        self.assertEqual(items[-1]['end'], 11.)
        self.assertTrue(all(len(line) <= 18 for i in items for line in i['text'].splitlines()))

    def test_numbers_and_closing_punctuation_are_not_stranded(self):
        wrapped = vc._wrap_text('这一页的服务成本降低了20%。后续继续改进。', 18)
        self.assertIn('20%', wrapped)
        self.assertFalse(any(line.startswith(('。', '，', '%')) for line in wrapped.splitlines()))

    def test_missing_ffmpeg_skips_both_detection_paths(self):
        with patch.object(vc.subprocess, 'run', side_effect=FileNotFoundError):
            self.assertEqual(vc._detect_black_frames('missing.mp4'), [])
            self.assertFalse(vc._is_black_clip('missing.mp4', 3))

    def test_failed_scene_uses_one_global_narration_without_reusing_partial_audio(self):
        scenes = [{'index': 1, 'text': '第一句。', 'duration': 2},
                  {'index': 2, 'text': '第二句。', 'duration': 2}]
        audio = AudioClip(lambda t: np.sin(2 * np.pi * 220 * t), duration=9, fps=24000)
        with tempfile.TemporaryDirectory() as directory, \
             patch('tts_audio.generate_scene_narrations', new=AsyncMock(return_value=[None, None])), \
             patch('tts_audio.generate_narration', new=AsyncMock(return_value=Path(directory) / 'global.mp3')) as global_tts, \
             patch.object(vc, 'AudioFileClip', return_value=audio):
            per_scene, global_audio = vc._prepare_narrations(scenes, Path(directory), [])
            self.assertEqual(per_scene, [])
            global_tts.assert_awaited_once()
            self.assertEqual(global_tts.await_args.args[0], '第一句。第二句')
            self.assertGreaterEqual(global_audio.duration, 9 * .8)
            self.assertGreaterEqual(sum(scene['duration'] for scene in scenes), global_audio.duration)
            global_audio.close()
        audio.close()


if __name__ == '__main__':
    unittest.main()
