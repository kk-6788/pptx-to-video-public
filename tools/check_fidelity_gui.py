"""Real desktop faithful workflow with all generation provider calls forbidden."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tkinter import Tk
from PIL import ImageGrab
import gui
import config

OUT = ROOT / 'artifacts/ui-library'
OUT.mkdir(parents=True, exist_ok=True)
errors = []
root = Tk()
root.report_callback_exception = lambda *exc: errors.append(str(exc))
app = gui.PptxToVideoApp(root)
app.input_var.set(str(ROOT/'demo.pptx'))
app.output_var.set(str(OUT/'gui-faithful.mp4'))
app.total_duration_var.set(10)
app.fps_var.set(12)
app.narration_explain_var.set(True)
started = time.monotonic()

def finish():
    try:
        summary = app._preview_content.get('1.0','end')
        assert '2/2' in summary and '失败' not in summary, summary
        assert app._right_notebook.index(app._right_notebook.select()) == 2
        assert app._visual_mode() == 'faithful'
        assert str(app._visual_mode_combo.cget('state')) == 'readonly'
        root.update_idletasks()
        user32 = ctypes.windll.user32
        # Use pointer-sized HWND values rather than ctypes' default 32-bit return.
        user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        user32.GetAncestor.restype = wintypes.HWND
        hwnd = user32.GetAncestor(root.winfo_id(), 2)
        screenshot_error = None
        try:
            ImageGrab.grab(window=hwnd).save(OUT/'gui-faithful-complete.png')
        except OSError as exc:
            # Keep capture availability separate from the verified conversion assertions.
            screenshot_error = str(exc)
        result = {'completed':True, 'elapsed':time.monotonic()-started,
                  'preview':summary, 'provider_calls':0, 'errors':errors,
                  'screenshot_captured':screenshot_error is None, 'screenshot_error':screenshot_error}
        (OUT/'gui-workflow.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False))
    except Exception as exc:
        errors.append(repr(exc))
    root.destroy()

def await_complete():
    if time.monotonic() - started > 180 or errors:
        errors.append('workflow timeout/error')
        root.destroy()
    elif app._preview_video_path:
        root.after(300, finish)
    elif not app._running and '错误' in app._status_bar.cget('text'):
        errors.append(app.log_text.get('1.0','end'))
        root.destroy()
    else:
        root.after(200, await_complete)

def await_plan():
    if errors or time.monotonic() - started > 60:
        root.destroy()
    elif app._scene_plans and str(app._confirm_btn.cget('state')) != 'disabled':
        app._start_pipeline()
        root.after(200, await_complete)
    else:
        root.after(100, await_plan)

def begin():
    try:
        app.visual_mode_var.set('AI 创意演绎')
        app._on_visual_mode_change()
        assert app._card_api.master.winfo_manager() == 'grid'
        app.visual_mode_var.set('忠实讲解')
        app._on_visual_mode_change()
        assert not app._card_api.master.winfo_manager()
        app._generate_prompts()
        root.after(100, await_plan)
    except Exception as exc:
        errors.append(repr(exc))
        root.destroy()

with patch('providers.get_providers', side_effect=AssertionError('Provider API initialized')), \
        patch.object(config,'VIDEO_CODEC','libx264'):
    root.after(400, begin)
    root.mainloop()
assert not errors, errors
