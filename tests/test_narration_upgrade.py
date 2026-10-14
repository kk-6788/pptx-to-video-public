"""Regression checks for per-scene narration and slide-aware prompt plans."""

import asyncio
import base64
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import config
import prompt_engine
import tts_audio
from pptx_parser import Slide


class NarrationTextTests(unittest.TestCase):
    def test_legacy_builder_deduplicates_title_and_keeps_decimal(self):
        slide = Slide(1, "销售结果", text_content="销售结果\n营收1.2亿元。\n营收1.2亿元。")
        text = tts_audio.build_narration_text([slide])
        self.assertEqual(text.count("销售结果"), 1)
        self.assertEqual(text.count("营收1.2亿元"), 1)

    def test_cleaning_removes_bullets_without_losing_signs_or_ratio(self):
        self.assertTrue(hasattr(tts_audio, "clean_narration_text"))
        text = tts_audio.clean_narration_text("  # 概览\n• 增长-3.5%，画幅16:9\n- 增长-3.5%，画幅16:9\n")
        self.assertEqual(text.count("增长-3.5%，画幅16:9"), 1)
        self.assertNotIn("•", text)
        self.assertNotIn("#", text)

    def test_direct_keeps_body_only_content(self):
        self.assertTrue(hasattr(tts_audio, "build_slide_narration"))
        slide = Slide(4, "结论", body="- 第二阶段投入20万元\n- 保留现有服务")
        result = tts_audio.build_slide_narration(slide)
        self.assertIn("投入20万元", result)
        self.assertIn("保留现有服务", result)

    def test_explain_preserves_numbers_and_conclusion_in_target_length(self):
        self.assertTrue(hasattr(tts_audio, "build_slide_narration"))
        source = ("季度经营结果\n首先，2025年第二季度，营收达到1.2亿元，同比增长30%。\n"
                  "客户留存率提升至92%，毛利率达到45%。\n"
                  "结论：增长来自老客户复购，下一阶段继续优化服务。")
        text = tts_audio.build_slide_narration(Slide(1, "季度经营结果", text_content=source), "explain")
        self.assertFalse(text.startswith(("首先", "其次", "最后")))
        for value in ("2025", "1.2", "30%", "92%", "45%", "老客户复购", "继续优化服务"):
            self.assertIn(value, text)
        han_count = len(re.findall(r"[\u4e00-\u9fff]", text))
        self.assertGreaterEqual(han_count, 40)
        self.assertLessEqual(han_count, 80)

    def test_dense_facts_are_never_truncated_to_meet_character_budget(self):
        self.assertTrue(hasattr(tts_audio, "build_slide_narration"))
        facts = [f"区域{i}的服务收入达到{i + 10}万元，并继续保持现有客户服务团队" for i in range(1, 9)]
        with self.assertLogs("tts_audio", level="WARNING"):
            text = tts_audio.build_slide_narration(Slide(3, "区域结果", text_content="。".join(facts)), "explain")
        for fact in facts:
            self.assertIn(fact, text)

    def test_explain_preserves_timing_words_that_are_not_list_markers(self):
        slide = Slide(1, "交易安排", text_content="最后交易日为2025年6月30日。结论：此日期之后不再受理申请。")
        text = tts_audio.build_slide_narration(slide, "explain")
        self.assertIn("最后交易日", text)

    def test_short_bullet_page_becomes_connected_speech_without_new_claims(self):
        slide = Slide(2, "核心功能", text_content="核心功能\n智能识别与理解\n毫秒级响应速度\n多语言自然交互\n安全可靠的架构")
        text = tts_audio.build_slide_narration(slide, "explain")
        self.assertGreaterEqual(len(re.findall(r"[\u4e00-\u9fff]", text)), 40)
        self.assertLessEqual(len(re.findall(r"[\u4e00-\u9fff]", text)), 80)
        self.assertIn("以及", text)
        for fact in ("智能识别与理解", "毫秒级响应速度", "多语言自然交互", "安全可靠的架构"):
            self.assertIn(fact, text)


class PromptNarrationTests(unittest.TestCase):
    def setUp(self):
        self.slides = [Slide(i, f"页面{i}主题", text_content=f"页面{i}主题\n本页独立结果数值为{i * 10}万元。") for i in range(1, 6)]

    def test_script_grouping_keeps_one_based_pages_and_per_page_narration(self):
        script = prompt_engine.ScriptWriter(self.slides, narration_style="explain").write()
        self.assertEqual([s.slide_indices for s in script.scenes], [[1], [2, 3, 4], [5]])
        for scene in script.scenes:
            self.assertEqual(scene.narration_style, "explain")
            self.assertEqual(list(scene.narration_by_slide), scene.slide_indices)
            self.assertEqual(scene.narration_text, "".join(scene.narration_by_slide.values()))
        plans = prompt_engine.Director(self.slides, script=script).plan()
        self.assertEqual([p.slide_index for p in plans], [1, 2, 5])
        self.assertEqual([p.slide_indices for p in plans], [[1], [2, 3, 4], [5]])
        self.assertIn("[TASK] Generate a high-quality image of: 页面1主题.", plans[0].image_prompt)
        self.assertIn("[TASK] Generate a high-quality image of: 页面5主题.", plans[-1].image_prompt)
        self.assertEqual(plans[1].narration_by_slide, script.scenes[1].narration_by_slide)
        self.assertIn("[页 1]", script.describe())
        self.assertIn("[页 2,3,4]", script.describe())

    def test_director_uses_slide_numbers_for_noncontiguous_subset(self):
        selected = [self.slides[1], self.slides[-1]]
        script = prompt_engine.ScriptWriter(selected).write()
        plans = prompt_engine.Director(selected, script=script).plan()
        self.assertIn("[TASK] Generate a high-quality image of: 页面2主题.", plans[0].image_prompt)
        self.assertIn("[TASK] Generate a high-quality image of: 页面5主题.", plans[-1].image_prompt)

    def test_per_slide_api_propagates_narration_style(self):
        plans = prompt_engine.generate_scene_plans(self.slides[:1], use_script_writer=False,
                                                 validate_prompts=False, narration_style="explain")
        self.assertEqual(plans[0].narration_style, "explain")
        self.assertEqual(plans[0].slide_indices, [1])
        self.assertEqual(plans[0].narration_by_slide, {1: plans[0].narration_text})

    def test_dynamic_ratio_survives_prompt_simplification(self):
        for ratio, description in (("16:9", "横屏 16:9 宽画幅"), ("9:16", "竖屏 9:16 手机竖版")):
            with self.subTest(ratio=ratio), patch.object(config, "RATIO", ratio, create=True):
                plan = prompt_engine.Director(self.slides).plan()[0]
                for prompt, simplify in ((plan.image_prompt, prompt_engine.PromptSimplifier.simplify_image_prompt),
                                         (plan.video_prompt, prompt_engine.PromptSimplifier.simplify_video_prompt)):
                    self.assertIn(description, prompt)
                    self.assertIn(description, simplify(prompt, "agnes"))
                self.assertNotRegex(plan.transition_type.lower(), r"fade.*black")


class SceneAudioTests(unittest.IsolatedAsyncioTestCase):
    async def test_scene_failure_preserves_results_alignment_and_measured_duration(self):
        self.assertTrue(hasattr(tts_audio, "generate_scene_narrations"))
        scenes = [{"index": i, "text": "原文字段", "narration_text": f"口播{i}", "start_time": i * 5, "duration": 5}
                  for i in range(3)]

        async def save_audio(text, voice="zh-CN-XiaoxiaoNeural", output_path=None):
            if text.startswith("口播1"):
                raise TimeoutError("synthetic network failure")
            path = Path(output_path)
            path.write_bytes(b"ID3-test")
            return path

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(tts_audio, "_edge_tts", side_effect=save_audio), \
             patch.object(tts_audio, "_audio_duration", return_value=2.75):
            result = await tts_audio.generate_scene_narrations(scenes, directory)
            self.assertEqual(len(result), 3)
            self.assertIsNone(result[1])
            self.assertEqual(result[0]["index"], 0)
            self.assertEqual(result[2]["duration"], 2.75)
            self.assertEqual(Path(result[2]["path"]).name, "scene_002.mp3")

    async def test_edge_timeout_is_retried_then_reported_without_raising(self):
        attempts = []

        class Communicate:
            def __init__(self, *args, **kwargs):
                pass

            async def save(self, path):
                attempts.append(path)
                raise TimeoutError("synthetic timeout")

        with tempfile.TemporaryDirectory() as directory, \
             patch.dict("sys.modules", {"edge_tts": SimpleNamespace(Communicate=Communicate)}), \
             patch("tts_audio.asyncio.sleep", new=AsyncMock()):
            result = await tts_audio._edge_tts("网络失败测试", output_path=Path(directory) / "speech.mp3")
        self.assertIsNone(result)
        self.assertGreaterEqual(len(attempts), 2)

    async def test_sapi_wav_has_correct_extension_and_literal_safe_powershell(self):
        recorded = []

        def fake_run(args, **kwargs):
            recorded.append((args, kwargs))
            Path(directory, "narration'$(literal).wav").write_bytes(b"RIFF-test-wave")
            return SimpleNamespace(returncode=0, stderr="")

        with tempfile.TemporaryDirectory() as directory, patch("tts_audio.subprocess.run", side_effect=fake_run):
            path = tts_audio._sapi_tts("售价$5，O'Brien", Path(directory) / "narration'$(literal).mp3")
        self.assertIsNotNone(path)
        self.assertEqual(path.suffix, ".wav")
        args, kwargs = recorded[0]
        self.assertIn("-EncodedCommand", args)
        script = base64.b64decode(args[args.index("-EncodedCommand") + 1]).decode("utf-16-le")
        self.assertIn("$synth.Speak($narrationText)", script)
        self.assertNotIn("售价$5", script)
        self.assertEqual(kwargs["timeout"], 60)


if __name__ == "__main__":
    unittest.main()
