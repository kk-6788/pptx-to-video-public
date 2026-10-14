# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

datas = [('app_icon.ico', '.'), ('使用说明.txt', '.'), ('assets/bgm', 'assets/bgm')]
binaries = []
tts_hiddenimports = ['tts_audio', 'edge_tts', 'aiohttp', 'ui_themes', 'ui_components', 'faithful_plan', 'content_renderer']
hiddenimports = ['main', 'config', 'pptx_parser', 'prompt_engine', 'video_generator', 'video_composer', 'providers.agnes', 'providers.base', 'providers.siliconflow', 'providers.kling', 'providers.volcengine', 'providers.comfyui', 'providers.custom_api', 'providers.openai', 'providers.gemini', 'dotenv', 'httpx', 'httpcore', 'h11', 'aiofiles', 'moviepy', 'PIL', 'PIL._imaging', 'numpy', 'imageio_ffmpeg', 'pptx', 'lxml', 'lxml._elementpath']
tmp_ret = collect_all('moviepy')
hiddenimports += tts_hiddenimports
hiddenimports += ['narration_project', 'narration_editor', 'narration_policy',
                  'narration_engine', 'narration_workflow', 'pptx_page_renderer',
                  'original_slide_renderer']
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('PIL')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('httpx')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# imageio 2.37 uses importlib.metadata at import time (__init__.py -> version("imageio"));
# collect_all pulls the package modules AND its dist-info METADATA so the frozen EXE
# does not throw "No package metadata was found for imageio".
tmp_ret = collect_all('imageio')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Optional imageio/notebook backends are unrelated to this desktop pipeline.
    excludes=['torch', 'tensorflow', 'keras', 'pandas', 'matplotlib', 'cv2',
              'sklearn', 'numba', 'IPython', 'pytest'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PPT转视频工具',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=os.environ.get('PPTX_VIDEO_BUILD_DEBUG') == '1',
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app_icon.ico'],
)
