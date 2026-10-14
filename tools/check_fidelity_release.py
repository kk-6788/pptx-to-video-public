"""Launch only our built EXE, capture its window and verify desktop video access."""
import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import subprocess
import time

import psutil
from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'artifacts/ui-library'
EXE = ROOT/'dist/PPT转视频工具.exe'
process = subprocess.Popen([str(EXE)], cwd=EXE.parent)
user32 = ctypes.windll.user32
window = None
title = ''
try:
    for attempt in range(60):
        if process.poll() is not None:
            raise RuntimeError(f'EXE exited: {process.returncode}')
        ids = {process.pid}
        try:
            ids.update(p.pid for p in psutil.Process(process.pid).children(recursive=True))
        except psutil.Error:
            pass
        windows = []
        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum(hwnd, _):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in ids and user32.IsWindowVisible(hwnd):
                text = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, text, 512)
                if 'PPT' in text.value:
                    windows.append((hwnd,text.value))
            return True
        user32.EnumWindows(enum, 0)
        if windows:
            window, title = windows[0]
            break
        time.sleep(.5)
    assert window and '2.3.0' in title, (window,title)
    time.sleep(1)
    screenshot = OUT/'exe-v2.3.0.png'
    ImageGrab.grab(window=window).save(screenshot)
    video = ROOT/'out.mp4'
    with video.open('rb') as stream:
        assert len(stream.read(1024)) == 1024
    subprocess.run(['ffmpeg','-v','error','-i',str(video),'-f','null','-'],check=True,capture_output=True)
    result = {'exe':str(EXE),'size_bytes':EXE.stat().st_size,
              'sha256':hashlib.file_digest(EXE.open('rb'),'sha256').hexdigest(),
              'window_title':title,'startup':'passed','screenshot':str(screenshot),
              'desktop_user_video_read':'passed','desktop_user_full_decode':'passed'}
    (OUT/'exe-checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
finally:
    if window:
        user32.PostMessageW(window, 0x0010, 0, 0)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        for child in psutil.Process(process.pid).children(recursive=True):
            child.terminate()
        process.terminate()
