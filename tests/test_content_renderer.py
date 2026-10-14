"""Offline acceptance checks for sourced information animation."""
from types import SimpleNamespace

import numpy as np
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image

import config
from pptx_parser import Slide
from content_renderer import make_content_clip, minimum_readable_duration


def check_long_source(size):
    config.VIDEO_SIZE = size
    facts = ["2026 年收入为 128.75 万元，同比增长 23.6%。" * 24,
             "保留重复事实", "保留重复事实", "最终验收时间：2027-12-31。"]
    title = "不应丢失任何来源字符的长标题" * 18
    slide = Slide(index=2, title=title)
    plan = SimpleNamespace(source_facts=facts, layout_kind="metrics")
    duration = minimum_readable_duration(slide, plan)
    clip = make_content_clip(slide, duration, plan=plan)
    manifest = clip.content_manifest
    assert len(manifest["pages"]) > 2
    rendered = {i: "" for i in range(len(facts))}
    title_parts = []
    for page in manifest["pages"]:
        assert page["end"] - page["start"] >= page["minimum_duration"] - .001
        title_parts.append(page["title_fragment"])
        frame = clip.get_frame((page["start"] + page["end"]) / 2)
        assert frame.mean() > 200
        assert frame[int(frame.shape[0] * .82):].min() >= 230
        for fragment in page["fragments"]:
            rendered[fragment["fact_index"]] += fragment["text"]
            x, y, right, bottom = fragment["bounds"]
            assert bottom <= frame.shape[0] * .82
            assert np.count_nonzero(frame[y:bottom, x:right].min(axis=2) < 100) > 10
    assert list(rendered.values()) == facts
    assert title in "".join(title_parts)
    clip.close()


def check_animation():
    config.VIDEO_SIZE = "1280x720"
    slide = Slide(index=1, title="核心能力", body="多模态理解\n实时推理\n低代码集成")
    clip = make_content_clip(slide, 8)
    a, b = clip.get_frame(.1), clip.get_frame(5)
    assert not np.array_equal(a, b)
    assert np.array_equal(a[70:145], b[70:145])
    assert clip.content_manifest["source_facts"] == ["多模态理解", "实时推理", "低代码集成"]
    assert clip.content_manifest["layout_kind"] == "points"
    clip.close()


def check_image(tmp_path, size):
    config.VIDEO_SIZE = size
    path = tmp_path / "source.png"
    source = Image.new("RGB", (400, 100), (210, 20, 60))
    source.save(path)
    slide = Slide(index=1, title="原始产品图", body="版本 2.0", image_paths=[str(path)])
    clip = make_content_clip(slide, 6)
    frame = clip.get_frame(2)
    red = (frame[:, :, 0] > 180) & (frame[:, :, 1] < 50)
    ys, xs = np.where(red)
    assert xs.size > 1000
    assert abs((xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1) - 4) < .1
    assert clip.content_manifest["image_source"] == str(path)
    clip.close()


def check_empty():
    clip = make_content_clip(Slide(index=1), 1.25)
    assert clip.duration == 1.25
    assert clip.get_frame(.5).shape[2] == 3
    assert clip.content_manifest["source_facts"] == []
    clip.close()


class ContentRendererTests(unittest.TestCase):
    def test_measured_speech_focus_keeps_title_and_every_page_readable(self):
        from faithful_plan import build_faithful_plans
        slide = Slide(1, '季度经营结果', body='\n'.join(
            f'区域{i}收入为{i+10}.25万元，保留现有团队并继续改善服务。' for i in range(12)))
        plan = build_faithful_plans([slide], 'explain')[0]
        with patch.object(config, 'VIDEO_SIZE', '720x1280'):
            minimum = minimum_readable_duration(slide, plan)
            for speed in (.5, 1.2):
                clip = make_content_clip(slide, minimum * 1.5, plan=plan,
                                         speech_duration=minimum * speed)
                pages = clip.content_manifest['pages']
                self.assertIn('approximate', clip.content_manifest['focus_timing'])
                for page in pages:
                    self.assertGreaterEqual(page['end'] - page['start'] + .001, page['minimum_duration'])
                    for fact in page['fragments']:
                        self.assertGreaterEqual(fact['focus_start'], page['start'])
                        self.assertLessEqual(fact['focus_end'], page['end'])
                        self.assertGreaterEqual(fact['focus_end'], fact['focus_start'])
                for before, after in zip(pages, pages[1:]):
                    self.assertEqual(before['end'], after['start'])
                clip.close()

    def test_long_source(self):
        with patch.object(config, "VIDEO_SIZE", config.VIDEO_SIZE):
            for size in ["1280x720", "720x1280"]:
                with self.subTest(size=size):
                    check_long_source(size)

    def test_animation(self):
        with patch.object(config, "VIDEO_SIZE", config.VIDEO_SIZE):
            check_animation()

    def test_original_image(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(config, "VIDEO_SIZE", config.VIDEO_SIZE):
            for size in ["1280x720", "720x1280"]:
                with self.subTest(size=size):
                    check_image(Path(directory), size)

    def test_empty_slide(self):
        check_empty()
