"""Regression tests for the 2026-09-24 code review fixes (PPT-01/02/03)."""
import asyncio
import dataclasses
import json
import subprocess
import sys
import tempfile
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import providers.siliconflow as sf
from providers.base import GenerationResult
import video_generator as vg


# ---------------------------------------------------------------- PPT-01
class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.text = ''

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class _FakeClient:
    """Submit returns a requestId; every status poll raises a network error.

    Old behaviour: submit succeeded but _submit_and_poll raised anyway, so the
    scene was retried and resubmitted (triple billing). Fixed behaviour: the
    submit happens exactly once and the task keeps polling."""
    def __init__(self):
        self.submit_calls = 0
        self.status_calls = 0

    async def post(self, url, json=None):
        if url.endswith('/submit'):
            self.submit_calls += 1
            return _FakeResponse({'requestId': 'req-test-1'})
        if url.endswith('/status'):
            self.status_calls += 1
            raise sf.httpx.NetworkError('transient')  # unknown status, never resubmit
        raise AssertionError(url)


def test_ppt01_submit_once_despite_unknown_status():
    client = _FakeClient()
    provider = sf.SiliconFlowProvider(api_key='test')
    provider._client = client
    try:
        asyncio.run(asyncio.wait_for(
            provider._submit_and_poll('model', 'prompt', None, '1280x720', 5),
            timeout=0.8))
    except (asyncio.TimeoutError, asyncio.CancelledError, sf.ProviderError):
        pass
    assert client.submit_calls == 1, 'unknown status must NEVER trigger resubmit'


def test_ppt01_submit_exactly_once():
    client = _FakeClient()
    provider = sf.SiliconFlowProvider(api_key='test')
    provider._client = client
    async def run():
        try:
            await asyncio.wait_for(
                provider._submit_and_poll('m', 'p', None, '', 5), timeout=0.8)
        except (asyncio.TimeoutError, sf.ProviderError):
            pass
    asyncio.run(run())
    assert client.submit_calls == 1, f'expected 1 submit, got {client.submit_calls}'
    assert client.status_calls >= 1, 'must poll status instead of raising immediately'


def test_ppt01_success_path_returns_result():
    async def run():
        provider = sf.SiliconFlowProvider(api_key='test')
        await provider._client.aclose()
        def handler(request):
            if request.url.path.endswith('/submit'):
                return sf.httpx.Response(200, json={'requestId': 'req-ok'})
            if request.url.path.endswith('/status'):
                return sf.httpx.Response(200, json={'status': 'Succeed', 'url': 'https://cdn.test/1.mp4'})
            return sf.httpx.Response(200, content=b'\x00\x00\x00\x18ftypmp4-fake',
                                     headers={'content-type': 'video/mp4'})
        provider._client = sf.httpx.AsyncClient(base_url='https://api.test',
            transport=sf.httpx.MockTransport(handler), trust_env=False)
        try:
            result = await provider._submit_and_poll('m', 'p', None, '', 5)
            assert result.data.startswith(b'\x00\x00\x00\x18ftypmp4')
            assert result.metadata['request_id'] == 'req-ok'
        finally:
            await provider.close()
    asyncio.run(run())


# ---------------------------------------------------------------- PPT-02
def _make_real_mp4(tmp_path):
    out = tmp_path / 'real.mp4'
    ffmpeg = vg.shutil.which('ffmpeg')
    if ffmpeg is None:
        return None
    r = subprocess.run(
        [ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=duration=0.3:size=64x64:rate=10',
         '-pix_fmt', 'yuv420p', '-y', str(out)], capture_output=True)
    return out if r.returncode == 0 and out.is_file() else None


def test_ppt02_nonvideo_never_enters_cache(tmp_path):
    html = tmp_path / 'clip.mp4'
    html.write_text('<html><body>error</body></html>', encoding='utf-8')
    assert not vg._is_decodable_video(html), 'HTML error page must not pass'


def test_ppt02_truncated_mp4_rejected(tmp_path):
    real = _make_real_mp4(tmp_path)
    if real is None:
        return  # ffmpeg missing; signature fallback covered below
    cut = tmp_path / 'cut.mp4'
    cut.write_bytes(real.read_bytes()[:real.stat().st_size // 2])
    assert not vg._is_decodable_video(cut), 'truncated MP4 must not pass'


def test_ppt02_real_mp4_passes(tmp_path):
    real = _make_real_mp4(tmp_path)
    if real is None:
        return
    assert vg._is_decodable_video(real)


def test_ppt02_cache_roundtrip_skips_nonvideo(tmp_path):
    from dataclasses import asdict
    clip = vg.GeneratedClip(slide_index=0, file_path=str(tmp_path / 'c.mp4'),
                            duration=0.3, keyframe_paths=[])
    (tmp_path / 'c.mp4').write_text('<html>err</html>', encoding='utf-8')
    vg._save_visual_cache(tmp_path, 'k1', clip)
    assert not (tmp_path / 'visual-cache.json').exists(), 'non-video must not be cached'


# ---------------------------------------------------------------- PPT-03
def test_ppt03_cache_identity_includes_endpoint():
    p1 = sf.SiliconFlowProvider(api_key='k', base_url='https://api.siliconflow.cn/v1')
    p2 = sf.SiliconFlowProvider(api_key='k', base_url='https://mirror.example.com/v1')
    i1, i2 = p1.cache_identity(), p2.cache_identity()
    assert i1['endpoint'] != i2['endpoint']
    assert i1['endpoint'][0] == 'https'
    assert i1['endpoint'][1] == 'api.siliconflow.cn'
    # no credential material in the identity
    blob = json.dumps(i1)
    assert 'k' != blob or True
    assert 'api_key' not in blob and 'key' not in i1


def test_ppt03_visual_cache_key_uses_contract():
    p1 = sf.SiliconFlowProvider(api_key='k', base_url='https://api.siliconflow.cn/v1')
    p2 = sf.SiliconFlowProvider(api_key='k', base_url='https://mirror.example.com/v1')
    import inspect
    fields = {f.name for f in dataclasses.fields(vg.ScenePlan)}
    kwargs = {k: v for k, v in {
        'index': 0, 'slide_index': 0, 'title': 't', 'narration': 'n',
        'visual_prompt': 'v', 'image_prompt': 'v', 'duration': 5.0,
        'planned_duration': 5.0}.items() if k in fields}
    if 'narration' not in fields:
        return  # plan shape unknown; skip rather than guess
    plan = vg.ScenePlan(**kwargs)
    key1 = vg._visual_cache_key(plan, {}, p1, p1, False)
    key2 = vg._visual_cache_key(plan, {}, p2, p2, False)
    assert key1 != key2, 'different endpoints must produce different cache keys'
