"""Offline end-to-end regressions for PPT-R1/R2/R3/R4 (2026-10-10)."""
import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from providers.base import AcceptedTaskError, GenerationResult
from providers.siliconflow import SiliconFlowProvider
from providers.kling import KlingProvider
from providers.volcengine import VolcengineProvider
from providers.custom_api import CustomApiProvider
from providers.agnes import AgnesProvider
from providers.gemini import GeminiProvider
from providers.media import download_media
import video_generator as vg
from pptx_parser import Slide
from prompt_engine import ScenePlan

CLASSES = [SiliconFlowProvider, KlingProvider, VolcengineProvider, CustomApiProvider, AgnesProvider]

async def attach(provider, handler):
    old = getattr(provider, '_client', None)
    if old:
        await old.aclose()
    provider._client = httpx.AsyncClient(base_url='https://api.example.test/v1',
        headers={'Authorization': 'Bearer FAKE_ONLY', 'Cookie': 'secret=FAKE_ONLY'},
        transport=httpx.MockTransport(handler), trust_env=False)
    return provider

@pytest.mark.parametrize('cls', CLASSES)
@pytest.mark.parametrize('kind', ['image', 'video'])
@pytest.mark.asyncio
async def test_every_provider_media_keeps_bearer_at_api_only(cls, kind, monkeypatch):
    seen = []
    url = 'https://cdn.example.test/media?signature=keep-me'
    def handler(req):
        seen.append(req)
        if req.url.host == 'cdn.example.test':
            return httpx.Response(200, content=b'media-bytes', headers={'content-type':'video/mp4'})
        path = req.url.path
        if 'images/generations' in path:
            return httpx.Response(200, json=({'code':0, 'data':{'images':[{'url':url}]}} if cls is KlingProvider else {'data':[{'url':url}], 'images':[{'url':url}]}))
        if cls is CustomApiProvider:
            payload = {'url':url}
        elif req.method == 'POST' and 'status' not in path:
            payload = {'requestId':'task', 'task_id':'task', 'id':'task', 'code':0, 'data':{'task_id':'task'}}
        elif cls is SiliconFlowProvider:
            payload = {'status':'Succeed', 'results':{'videos':[{'url':url}]}}
        elif cls is KlingProvider:
            payload = {'code':0, 'data':{'status':'completed','output':{'video_url':url}}}
        elif cls is VolcengineProvider:
            payload = {'status':'completed', 'result':{'video_url':url}}
        else:
            payload = {'status':'completed', 'signed_url':url}
        return httpx.Response(200, json=payload)
    monkeypatch.setattr('providers.agnes.asyncio.sleep', AsyncMock())
    p = await attach(cls(api_key='FAKE_ONLY', base_url='https://api.example.test/v1', video_model='video'), handler)
    try:
        result = await (p.generate_image('p') if kind=='image' else p.generate_video('p', image_data=b'image'))
        assert result.data == b'media-bytes'
        api = [r for r in seen if r.url.host=='api.example.test']
        cdn = [r for r in seen if r.url.host=='cdn.example.test']
        assert api and cdn
        assert all(r.headers['Authorization']=='Bearer FAKE_ONLY' for r in api)
        assert all('authorization' not in r.headers and 'cookie' not in r.headers for r in cdn)
        assert all(r.url.query == b'signature=keep-me' for r in cdn)
    finally:
        await p.close()

@pytest.mark.parametrize('url,auth', [
    ('https://API.example.test:443/media', True),
    ('/media', True), ('media', True),
    ('//cdn.example.test/media', False),
    ('https://api.example.test:8443/media', False),
    ('https://api.example.test.evil.test/media', False),
    ('http://cdn.example.test/media', False), ('http://api.example.test/media', False),
])
@pytest.mark.asyncio
async def test_normalized_origins_and_relative_urls(url, auth):
    seen=[]
    async with httpx.AsyncClient(base_url='https://api.example.test/v1', headers={'Authorization':'Bearer FAKE'},
            transport=httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200)), trust_env=False) as client:
        await download_media(client,url)
    assert ('authorization' in seen[0].headers) == auth
    if url in ('/media','media'):
        assert seen[0].url.path == '/v1/media'

@pytest.mark.parametrize('url',[    'https://user:pass@api.example.test/a','file:///tmp/a','data:abc','https:///bad',
    ' https://cdn.example.test/a','https://cdn.example.test/\\bad','https://cdn.example.test/\nfoo'])
@pytest.mark.asyncio
async def test_invalid_urls_do_not_send(url):
    seen=[]
    async with httpx.AsyncClient(base_url='https://api.example.test',
        transport=httpx.MockTransport(lambda r:seen.append(r) or httpx.Response(200)),trust_env=False) as client:
        with pytest.raises(ValueError):
            await download_media(client,url)
    assert not seen

@pytest.mark.asyncio
async def test_redirect_never_forwards_auth():
    seen=[]
    async with httpx.AsyncClient(base_url='https://api.example.test', headers={'Authorization':'FAKE'},
        transport=httpx.MockTransport(lambda r:seen.append(r) or httpx.Response(302,headers={'location':'https://evil.test/x'})),
        follow_redirects=True,trust_env=False) as client:
        for url in ['https://api.example.test/a','https://cdn.example.test/a']:
            response=await download_media(client,url)
            assert response.status_code==302
    assert len(seen)==2

@pytest.mark.parametrize('same_origin', [False,True])
@pytest.mark.asyncio
async def test_agnes_401_fallback_only_at_api_origin(same_origin):
    seen=[]; target='api.example.test' if same_origin else 'cdn.example.test'
    def handler(req):
        seen.append(req)
        if req.method=='POST': return httpx.Response(200,json={'data':[{'url':f'https://{target}/media'}]})
        if 'authorization' in req.headers: return httpx.Response(200,content=b'protected')
        return httpx.Response(401)
    p=await attach(AgnesProvider(api_key='FAKE_ONLY',base_url='https://api.example.test'),handler)
    try:
        if same_origin:
            assert (await p.generate_image('p')).data==b'protected'
            assert ['authorization' in r.headers for r in seen if r.method=='GET']==[False,True]
        else:
            with pytest.raises(httpx.HTTPStatusError): await p.generate_image('p')
            assert all('authorization' not in r.headers for r in seen if r.url.host==target)
    finally: await p.close()

@pytest.mark.parametrize('outcome',['download_failure','failed','malformed','missing_url','timeout'])
@pytest.mark.asyncio
async def test_accepted_task_never_reenters_generation(tmp_path,monkeypatch,outcome):
    counts={'submit':0,'image':0}; original=SiliconFlowProvider._poll_status
    def handler(req):
        if req.url.path.endswith('/submit'):
            counts['submit']+=1; return httpx.Response(200,json={'requestId':'accepted-123'})
        if req.url.path.endswith('/status'):
            if outcome=='malformed': return httpx.Response(503,text='bad gateway')
            if outcome=='failed': return httpx.Response(200,json={'status':'Failed'})
            if outcome=='timeout': return httpx.Response(200,json={'status':'InProgress'})
            return httpx.Response(200,json={'status':'Succeed','results':{'videos':[] if outcome=='missing_url' else [{'url':'https://cdn.example.test/video'}]}})
        return httpx.Response(503)
    p=await attach(SiliconFlowProvider(api_key='FAKE_ONLY'),handler)
    async def poll(request_id,model): return await original(p,request_id,model,max_attempts=1,interval_seconds=0)
    monkeypatch.setattr(p,'_poll_status',poll)
    class Images:
        async def generate_image(self,**kw):
            counts['image']+=1; return GenerationResult(b'image')
    try:
        clips=await vg.generate_clips_from_plans([Slide(1)],[ScenePlan(1,image_prompt='p',video_prompt='p')],
            image_provider=Images(),video_provider=p,output_dir=tmp_path,use_slide_images=False)
        assert clips==[] and counts=={'submit':1,'image':1}
        recovery=json.loads(next(tmp_path.rglob('accepted-task.json')).read_text())
        assert recovery['request_id']=='accepted-123'
        assert 'FAKE' not in json.dumps(recovery)
    finally: await p.close()

@pytest.mark.parametrize('cls',[SiliconFlowProvider,KlingProvider,VolcengineProvider,GeminiProvider])
@pytest.mark.asyncio
async def test_actual_provider_models_and_endpoints_change_identity(cls):
    ps=[cls(api_key='FAKE_KEY',base_url=endpoint,image_model=model,video_model=model)
        for endpoint,model in [('https://api.test/v1?secret=FAKE','one'),('https://api.test/v1?secret=FAKE','two'),('https://other.test/v1','one')]]
    try:
        ids=[p.cache_identity() for p in ps]
        assert ids[0]!=ids[1] and ids[0]!=ids[2]
        assert 'FAKE' not in json.dumps(ids)
    finally:
        for p in ps: await p.close()

@pytest.mark.asyncio
async def test_self_hosted_http_media_is_downloaded_without_api_credentials():
    seen=[]
    def handler(req):
        seen.append(req)
        if req.method=='POST': return httpx.Response(200,json={'data':[{'url':'http://127.0.0.1:8001/image.png'}]})
        return httpx.Response(200,content=b'local-media')
    p=CustomApiProvider(api_key='FAKE',base_url='http://127.0.0.1:8000')
    await p._client.aclose()
    p._client=httpx.AsyncClient(base_url='http://127.0.0.1:8000',headers={'Authorization':'FAKE'},
        transport=httpx.MockTransport(handler),trust_env=False)
    try:
        assert (await p.generate_image('p')).data==b'local-media'
        assert 'authorization' not in seen[-1].headers
    finally: await p.close()

@pytest.mark.parametrize('media_url',['file:///untrusted/video','https://cdn.example.test/video'])
@pytest.mark.asyncio
async def test_agnes_fixed_api_fallback_survives_invalid_or_denied_media(media_url,monkeypatch):
    seen=[]
    def handler(req):
        seen.append(req)
        if req.url.host=='cdn.example.test': return httpx.Response(403)
        if req.url.path.endswith('/download'): return httpx.Response(200,content=b'fallback-video',headers={'content-type':'video/mp4'})
        if req.method=='POST': return httpx.Response(200,json={'id':'task'})
        return httpx.Response(200,json={'status':'completed','video_url':media_url})
    monkeypatch.setattr('providers.agnes.asyncio.sleep',AsyncMock())
    p=await attach(AgnesProvider(api_key='FAKE_ONLY',base_url='https://api.example.test/v1'),handler)
    try:
        result=await p.generate_video('p',image_data=b'image')
        assert result.data==b'fallback-video'
        assert any(r.url.path.endswith('/download') for r in seen)
        assert all('authorization' not in r.headers for r in seen if r.url.host=='cdn.example.test')
    finally: await p.close()

@pytest.mark.asyncio
async def test_clean_media_request_has_no_client_auth_params_or_cookies():
    seen=[]
    async with httpx.AsyncClient(base_url='https://api.test',auth=('FAKE_USER','FAKE_PASS'),
        params={'api_key':'FAKE'},cookies={'session':'FAKE'},headers={'Authorization':'FAKE'},
        transport=httpx.MockTransport(lambda r:seen.append(r) or httpx.Response(200)),trust_env=False) as client:
        await download_media(client,'https://cdn.test/a?sig=%2Fkeep%2B')
    req=seen[0]
    assert req.url.query==b'sig=%2Fkeep%2B'
    assert not {'authorization','cookie','proxy-authorization'} & set(req.headers)

@pytest.mark.asyncio
async def test_siliconflow_inline_image_avoids_download():
    seen=[]
    p=await attach(SiliconFlowProvider(api_key='FAKE'),lambda r:seen.append(r) or httpx.Response(200,json={'images':[{'b64_json':'aW1hZ2U='}]}))
    try:
        assert (await p.generate_image('p')).data==b'image'
        assert len(seen)==1 and seen[0].method=='POST'
    finally: await p.close()

@pytest.mark.asyncio
async def test_pre_accept_failure_remains_retryable(tmp_path,monkeypatch):
    monkeypatch.setattr('video_generator.asyncio.sleep',AsyncMock())
    class Provider:
        images=0; videos=0
        async def generate_image(self,**kw):
            self.images+=1; return GenerationResult(b'image')
        async def generate_video(self,**kw):
            self.videos+=1
            if self.videos==1: raise RuntimeError('not submitted')
            return GenerationResult(b'video-result',metadata={'duration':5})
    p=Provider()
    clips=await vg.generate_clips_from_plans([Slide(1)],[ScenePlan(1)],image_provider=p,video_provider=p,output_dir=tmp_path,use_slide_images=False)
    assert len(clips)==1 and p.images==2 and p.videos==2

@pytest.mark.asyncio
async def test_completed_generation_is_not_repeated_on_local_write_failure(tmp_path,monkeypatch):
    from pathlib import Path
    original=Path.write_bytes
    def write(path,data):
        if path.suffix=='.mp4': raise OSError('disk full')
        return original(path,data)
    monkeypatch.setattr(Path,'write_bytes',write)
    class Provider:
        videos=0
        async def generate_image(self,**kw): return GenerationResult(b'image')
        async def generate_video(self,**kw):
            self.videos+=1; return GenerationResult(b'video-result')
    p=Provider()
    assert await vg.generate_clips_from_plans([Slide(1)],[ScenePlan(1)],image_provider=p,video_provider=p,output_dir=tmp_path,use_slide_images=False)==[]
    assert p.videos==1
