import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

from pptx_parser import Slide
from faithful_plan import (
    audit_faithful_plans, build_faithful_plans, min_scene_duration, source_units,
)


class FaithfulPlanTests(unittest.TestCase):
    def test_body_facts_preserve_decimals_order_and_duplicates(self):
        slide = Slide(1, title="概览", body="  - • 收入 3.14 亿元\n    - - 增长 -2.5%\n- 1. 研发\n- 研发\n- 研发")
        self.assertEqual(source_units(slide), ["收入 3.14 亿元", "增长 -2.5%", "1. 研发", "研发", "研发"])

    def test_plans_follow_supplied_original_pages_without_merging(self):
        slides = [Slide(3, "甲", "- 内容甲"), Slide(8, "乙", "- 内容乙")]
        plans = build_faithful_plans(slides)
        self.assertEqual([p.slide_indices for p in plans], [[3], [8]])
        self.assertEqual([p.slide_index for p in plans], [3, 8])
        self.assertTrue(all(p.visual_mode == "faithful" for p in plans))
        report = audit_faithful_plans(slides, plans)
        self.assertTrue(report["passed"])
        self.assertEqual(report["pages"][0]["source_facts"], ["内容甲"])
        json.dumps(report, ensure_ascii=False)

    def test_missing_reordered_duplicate_and_merged_pages_rejected(self):
        slides = [Slide(1, "甲", "- a"), Slide(2, "乙", "- b")]
        plans = build_faithful_plans(slides)
        variants = [plans[:1], list(reversed(plans)), [plans[0], plans[0]]]
        merged = copy.deepcopy(plans)
        merged[0].slide_indices = [1, 2]
        variants.append(merged)
        for variant in variants:
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                audit_faithful_plans(slides, variant)
        with self.assertRaises(ValueError):
            build_faithful_plans([slides[0], slides[0]])

    def test_numeric_and_text_fact_tampering_rejected(self):
        slides = [Slide(1, "经营", "- 收入 3.14 亿元\n- 面向企业客户")]
        for replacement in ["收入 3.15 亿元", "面向个人客户"]:
            plans = build_faithful_plans(slides)
            plans[0].source_facts[0] = replacement
            with self.assertRaises(ValueError):
                audit_faithful_plans(slides, plans)

    def test_source_changes_in_title_notes_and_text_detected(self):
        source = Slide(1, "标题", "- 原始正文", text_content="原始全文", notes="备注")
        plans = build_faithful_plans([source])
        for field in ["title", "body", "notes", "text_content"]:
            changed = copy.deepcopy(source)
            setattr(changed, field, getattr(changed, field) + "变更")
            with self.subTest(field=field), self.assertRaises(ValueError):
                audit_faithful_plans([changed], plans)

    def test_image_content_tampering_detected_even_with_same_size(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.png"
            path.write_bytes(b"not-image-one")
            slides = [Slide(1, "原图", image_paths=[str(path)])]
            plans = build_faithful_plans(slides)
            path.write_bytes(b"not-image-two")
            with self.assertRaises(ValueError):
                audit_faithful_plans(slides, plans)

    def test_dense_nonnumeric_body_preserved_in_explain_narration(self):
        facts = ["这是一条必须完整保留的独立来源说明，不能因为正文较长就把中间句子删去" + marker
                 for marker in ["甲", "乙", "丙", "丁", "戊", "己"]]
        slide = Slide(1, "完整内容", "\n".join("- " + fact for fact in facts), notes="讲者提供的补充说明")
        plan = build_faithful_plans([slide], narration_style="explain")[0]
        self.assertEqual(plan.source_facts, facts)
        for fact in facts + [slide.notes]:
            self.assertIn(fact, plan.narration_text)
        self.assertEqual([beat["text"] for beat in plan.visual_beats], facts)
        self.assertTrue(all(beat["weight"] > 0 for beat in plan.visual_beats))

    def test_stale_or_invented_narrative_and_visual_beats_rejected(self):
        slides = [Slide(1, "能力", "- 智能分析\n- 自动处理")]
        for field, value in [("narration_text", "机器人因此拯救城市。"),
                             ("narrative_bridge", "因此销量翻倍"),
                             ("subtitle_text", "销量翻倍"),
                             ("layout_kind", "flow"),
                             ("visual_beats", [{"text": "销量翻倍", "weight": 4, "role": "point"}])]:
            plans = build_faithful_plans(slides)
            setattr(plans[0], field, value)
            with self.subTest(field=field), self.assertRaises(ValueError):
                audit_faithful_plans(slides, plans)

    def test_creative_director_fields_cannot_leak_into_faithful_plan(self):
        slides = [Slide(1, "能力", "- 分析")]
        for field in ["director_vision", "transition_description", "camera_angle"]:
            plans = build_faithful_plans(slides)
            setattr(plans[0], field, "机器人飞过未来城市")
            with self.subTest(field=field), self.assertRaises(ValueError):
                audit_faithful_plans(slides, plans)

    def test_layout_does_not_invent_order_or_metrics_from_year_title(self):
        slides = [Slide(1, "2026 新品", "- 智能分析\n- 自动处理"),
                  Slide(2, "能力", "- 方案 A\n- 方案 B"),
                  Slide(3, "流程", "- 需求 → 开发 → 验证"),
                  Slide(4, "数据", "- 收入 3.14 亿元\n- 增长 12%"),
                  Slide(5, "清单", "- 版本 3.14\n- 型号 2026")]
        self.assertEqual([p.layout_kind for p in build_faithful_plans(slides)],
                         ["points", "points", "flow", "metrics", "points"])

    def test_image_layout_requires_decodable_source_image(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.png"
            Image.new("RGB", (16, 16), "red").save(path)
            image_plan = build_faithful_plans([Slide(1, "图", image_paths=[str(path)])])[0]
            self.assertEqual(image_plan.layout_kind, "image")
            path.write_bytes(b"invalid")
            invalid_plan = build_faithful_plans([Slide(1, "图", image_paths=[str(path)])])[0]
            self.assertEqual(invalid_plan.layout_kind, "points")

    def test_readability_minimum_survives_impossibly_short_total(self):
        slides = [Slide(1, "密集信息", "- " + "必须让每一个来源文字都能读清楚。" * 30),
                  Slide(2, "短页", "- 内容")]
        plans = build_faithful_plans(slides, total_duration=1.0)
        self.assertGreater(plans[0].suggested_duration_sec, 60)
        for slide, plan in zip(slides, plans):
            self.assertGreaterEqual(plan.suggested_duration_sec, min_scene_duration(slide))
        longer = sum(p.suggested_duration_sec for p in plans) + 100
        extended = build_faithful_plans(slides, total_duration=longer)
        self.assertAlmostEqual(sum(p.suggested_duration_sec for p in extended), longer)
        plans[0].suggested_duration_sec = 0.5
        with self.assertRaises(ValueError):
            audit_faithful_plans(slides, plans)

    def test_empty_title_only_and_invalid_options(self):
        self.assertEqual(build_faithful_plans([]), [])
        plan = build_faithful_plans([Slide(1, "标题")])[0]
        self.assertEqual(plan.source_facts, [])
        self.assertEqual(plan.visual_beats[0]["role"], "title")
        self.assertEqual(plan.visual_beats[0]["text"], "标题")
        for duration in [-1, math.nan, math.inf]:
            with self.assertRaises(ValueError):
                build_faithful_plans([], total_duration=duration)
        with self.assertRaises(ValueError):
            build_faithful_plans([], narration_style="invent")


if __name__ == "__main__":
    unittest.main()
