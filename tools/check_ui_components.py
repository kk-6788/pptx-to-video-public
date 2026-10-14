"""Real Tk interaction regression: keyboard, disabled controls, motion, timers, layout."""
from pathlib import Path
import ctypes
import json
import sys
import tempfile
import time
import traceback
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tkinter import Tk, BooleanVar
from PIL import ImageGrab
import gui
import ui_themes
from ui_components import ToggleSwitch

OUT = ROOT / 'artifacts/ui-library'
OUT.mkdir(exist_ok=True, parents=True)


def main():
    errors, checks = [], []
    with tempfile.TemporaryDirectory(dir=OUT) as temp, \
            patch.object(ui_themes, 'preferences_path', return_value=Path(temp) / 'theme.json'):
        root = Tk()
        root.report_callback_exception = lambda *args: errors.append(''.join(traceback.format_exception(*args)))
        app = gui.PptxToVideoApp(root)

        def settle(seconds=.12):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                root.update()
                time.sleep(.01)

        def screenshot(name):
            hwnd = ctypes.windll.user32.GetAncestor(root.winfo_id(), 2)
            ImageGrab.grab(window=hwnd).save(OUT / (name + '.png'))

        try:
            settle(.4)
            assert app._workflow_steps.current == 0
            with patch.object(gui.filedialog, 'askopenfilename', return_value=str(ROOT / 'demo.pptx')) as dialog:
                app._choose_file_btn.focus_force()
                settle()
                app._choose_file_btn.event_generate('<Return>')
                settle()
                dialog.assert_called_once()
            assert app.input_var.get().endswith('demo.pptx') and app._workflow_steps.current == 1
            checks.append('Keyboard Return opens file picker and updates source / workflow')

            app._ratio_combo.focus_force()
            settle()
            app._ratio_combo.event_generate('<Key-Right>')
            assert app.ratio_var.get() == '9:16'
            app._ratio_combo.event_generate('<Key-Left>')
            assert app.ratio_var.get() == '16:9'
            checks.append('Arrow keys select portrait / landscape')

            initial = app.audio_var.get()
            app._audio_check.focus_force()
            settle()
            app._audio_check.event_generate('<Key-space>')
            assert app.audio_var.get() != initial
            settle(.3)
            assert app._audio_check._position == float(app.audio_var.get())
            assert app._audio_check._paint_job is None
            checks.append('Space toggles TTS; animation settles without a perpetual timer')

            app._set_busy(True)
            assert app._browse_input_btn.instate(['disabled'])
            assert app._browse_output_btn.instate(['disabled'])
            with patch.object(gui.filedialog, 'askopenfilename') as dialog:
                app._choose_file_btn.invoke()
                app._empty_art.invoke()
                assert not dialog.called
            before = (app.audio_var.get(), app.ratio_var.get())
            app._audio_check.invoke()
            app._ratio_combo.event_generate('<Key-Right>')
            assert before == (app.audio_var.get(), app.ratio_var.get())
            assert str(app._confirm_btn.cget('takefocus')) == '0'
            app._set_busy(False)
            checks.append('Busy state blocks source picker, TTS and ratio mutation; disabled button leaves Tab order')

            app._scene_plans = [object()]
            app._preview_video_path = str(OUT / 'previous.mp4')
            app._status_bar.configure(text='完成: previous.mp4')
            app._update_steps()
            assert app._workflow_steps.complete
            app._on_visual_mode_change()
            assert not app._workflow_steps.complete
            app._scene_plans = [object()]
            app._parsed_slides = [object()]
            app._status_bar.configure(text='完成: previous.mp4')
            app.input_var.set(str(ROOT / 'different.pptx'))
            assert not app._scene_plans and not app._parsed_slides
            assert not app._workflow_steps.complete and app._workflow_steps.current == 1
            assert 'disabled' in app._confirm_btn.state()
            app.input_var.set(str(ROOT / 'demo.pptx'))
            app._preview_video_path = ''
            checks.append('Changing source or presentation mode invalidates stale storyboard and completed steps')

            for theme in ui_themes.THEMES:
                app._change_theme(theme_id=theme, persist=False)
                app._empty_art.event_generate('<Enter>')
                app._empty_art.event_generate('<Motion>', x=80, y=80)
                settle()
                assert app._empty_art.pointer == (80, 80)
                screenshot(theme + '-hover')
            app._motion_check.invoke()
            settle()
            assert app.reduce_motion_var.get()
            app.audio_var.set(not app.audio_var.get())
            settle(.04)
            assert app._audio_check._position == float(app.audio_var.get())
            assert app._audio_check._paint_job is None
            previous = app._empty_art.pointer
            app._empty_art.event_generate('<Motion>', x=180, y=50)
            assert app._empty_art.pointer == previous
            checks.append('All themes render hover; reduced motion stops spotlight tracking and toggle interpolation')

            app._change_theme(theme_id='light', persist=False)
            root.geometry('1000x720')
            app.input_var.set('长文件名' * 12 + '.pptx')
            settle(.3)
            panel = app._empty_panel
            area = panel.master
            assert panel.winfo_rooty() >= area.winfo_rooty()
            assert panel.winfo_rooty() + panel.winfo_height() <= area.winfo_rooty() + area.winfo_height()
            screenshot('long-filename-small')
            checks.append('Long Chinese filename and file button remain inside 1000x720 workspace')

            variable = BooleanVar(root, value=False)
            transient = ToggleSwitch(root, text='temporary', variable=variable)
            transient.place(x=20, y=20)
            settle()
            variable.set(True)
            root.update_idletasks()
            transient.destroy()
            variable.set(False)
            settle()
            assert not transient._alive and transient._paint_job is None and not transient._traces
            checks.append('Destroy during animation cancels callback and releases variable trace')
            assert not errors, errors
        finally:
            root.update_idletasks()
            root.destroy()
    result = {'python':sys.version, 'checks':checks, 'errors':errors}
    (OUT / 'component-checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
