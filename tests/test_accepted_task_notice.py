"""Offline regression: accepted-task failures must provide actionable recovery notice."""
import asyncio
import json
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from providers.base import AcceptedTaskError, GenerationResult
from pptx_parser import Slide
from prompt_engine import ScenePlan
import video_generator as vg


class RecoveryNoticeTests(unittest.IsolatedAsyncioTestCase):
    async def run_failure(self, write_fails=False):
        messages = []
        log = []
        class Recorder(logging.Handler):
            def emit(self, record):
                log.append(record.getMessage())
        class Provider:
            submissions = 0
            async def generate_image(self, **kwargs):
                return GenerationResult(b'synthetic-image')
            async def generate_video(self, **kwargs):
                self.submissions += 1
                raise AcceptedTaskError('Result download failed: https://cdn.test/result?secret=SYNTHETIC_SIGNED_TOKEN', 'siliconflow',
                    request_id='accepted-notice-test', model='synthetic-model',
                    result_url='https://cdn.test/result?secret=SYNTHETIC_SIGNED_TOKEN')
        provider = Provider()
        original = Path.write_text
        def write(path, *args, **kwargs):
            if write_fails and path.name == 'accepted-task.json':
                raise OSError('synthetic read-only directory')
            return original(path, *args, **kwargs)
        handler = Recorder()
        vg.logger.addHandler(handler)
        try:
            with tempfile.TemporaryDirectory() as directory, patch.object(Path, 'write_text', write), patch.object(vg.asyncio, 'sleep', AsyncMock()):
                clips = await vg.generate_clips_from_plans([Slide(1)], [ScenePlan(1)],
                    image_provider=provider, video_provider=provider, output_dir=Path(directory),
                    use_slide_images=False, progress_callback=lambda current, total, text: messages.append(text))
                self.assertEqual(clips, [])
                self.assertEqual(provider.submissions, 1)
                text = '\n'.join(messages)
                self.assertIn('已受理', text)
                self.assertIn('accepted-notice-test', text)
                self.assertIn('重复计费', text)
                self.assertIn('服务商', text)
                self.assertNotIn('SYNTHETIC_SIGNED_TOKEN', text)
                self.assertNotIn('SYNTHETIC_SIGNED_TOKEN', '\n'.join(log))
                self.assertTrue(any('已受理' in item and '重复计费' in item for item in log))
                recovery = list(Path(directory).rglob('accepted-task.json'))
                if write_fails:
                    self.assertFalse(recovery)
                    self.assertIn('恢复记录未能保存', text)
                else:
                    self.assertEqual(len(recovery), 1)
                    self.assertIn(str(recovery[0]), text)
                    self.assertEqual(json.loads(recovery[0].read_text(encoding='utf-8'))['request_id'], 'accepted-notice-test')
                return text
        finally:
            vg.logger.removeHandler(handler)

    async def test_notice_reaches_gui_callback_and_log(self):
        await self.run_failure()

    async def test_failed_recovery_write_keeps_task_id_and_does_not_claim_saved(self):
        await self.run_failure(write_fails=True)

    async def test_pre_accept_failure_remains_retryable_without_accepted_warning(self):
        messages = []
        class Provider:
            submissions = 0
            async def generate_image(self, **kwargs):
                return GenerationResult(b'image')
            async def generate_video(self, **kwargs):
                self.submissions += 1
                if self.submissions == 1:
                    raise RuntimeError('not submitted')
                return GenerationResult(b'video')
        provider = Provider()
        with tempfile.TemporaryDirectory() as directory, patch.object(vg.asyncio, 'sleep', AsyncMock()):
            clips = await vg.generate_clips_from_plans([Slide(1)], [ScenePlan(1)],
                image_provider=provider, video_provider=provider, output_dir=Path(directory),
                use_slide_images=False, progress_callback=lambda current, total, text: messages.append(text))
        self.assertEqual(len(clips), 1)
        self.assertEqual(provider.submissions, 2)
        self.assertNotIn('已受理', '\n'.join(messages))
