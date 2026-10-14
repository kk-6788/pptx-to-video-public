"""Real Windows desktop checks: python tools/check_ui_themes.py."""
from pathlib import Path
import ctypes
import json
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import gui
import ui_themes
from tkinter import Tk, ttk
from PIL import ImageGrab

OUT = ROOT / 'artifacts/ui-library'
OUT.mkdir(parents=True, exist_ok=True)


def capture(root, name):
    root.update_idletasks()
    hwnd = ctypes.windll.user32.GetAncestor(root.winfo_id(), 2)
    ImageGrab.grab(window=hwnd).save(OUT / (name + '.png'))


def main():
    errors, results = [], []
    with tempfile.TemporaryDirectory(dir=OUT) as temp, \
         patch.object(ui_themes, 'preferences_path', return_value=Path(temp) / 'ui.json'):
        root = Tk()
        root.report_callback_exception = lambda *args: errors.append(str(args))
        app = gui.PptxToVideoApp(root)

        def check_theme(position=0):
            try:
                if position < len(ui_themes.THEMES):
                    key = list(ui_themes.THEMES)[position]
                    root.tk.call('ttk::combobox::Post', str(app._theme_combo))
                    root.update_idletasks()
                    root.tk.call('ttk::combobox::Unpost', str(app._theme_combo))
                    app.ui_theme_var.set(ui_themes.THEMES[key]['name'])
                    app._theme_combo.event_generate('<<ComboboxSelected>>')
                    root.after(300, lambda: snapshot(position, key))
                else:
                    check_preservation()
            except Exception as exc:
                errors.append(repr(exc))
                root.destroy()

        def snapshot(position, key):
            try:
                palette = ui_themes.THEMES[key]
                assert app._theme_id == key and ui_themes.load_theme() == key
                assert root.cget('bg') == palette['bg']
                assert app._prompt_text.cget('bg') == palette['prompt']
                assert ttk.Style(root).lookup('TCombobox', 'fieldbackground', ['readonly']) == palette['input']
                assert app._gen_prompts_btn.winfo_ismapped()
                assert app._image_provider_combo.get()
                assert app._video_provider_combo.get()
                assert app._style_combo.get()
                assert app._prompt_text.vbar.winfo_class() == 'TScrollbar'
                assert root.tk.call(str(app._theme_combo)+'.popdown.f.l','cget','-background') == palette['card']
                for widget in (app._image_provider_combo, app._video_provider_combo, app._style_combo,
                               app._theme_combo, app._gen_prompts_btn):
                    if widget.winfo_ismapped():
                        assert widget.winfo_width() > 100, str(widget)
                capture(root, key)
                results.append({'theme':key, 'persisted':True, 'text_background':app._prompt_text.cget('bg')})
                check_theme(position+1)
            except Exception as exc:
                errors.append(repr(exc))
                root.destroy()

        def check_preservation():
            try:
                app.input_var.set(str(ROOT / 'demo.pptx'))
                app._style_combo.set('科技创新')
                app._style_combo.event_generate('<<ComboboxSelected>>')
                assert app.style_var.get() == 'tech innovation'
                for provider, entry in app._api_key_widgets.items():
                    app._toggle_key_visible_provider(provider)
                    assert entry.cget('show') == ''
                    app._toggle_key_visible_provider(provider)
                    assert entry.cget('show') == '*'
                app.output_var.set(str(OUT / 'example.mp4'))
                app.ratio_var.set('9:16')
                app.audio_var.set(True)
                app.narration_explain_var.set(True)
                app.bgm_volume_var.set(23)
                assert app._bgm_volume_label.cget('text') == '23%'
                app._prompt_text.configure(state='normal')
                app._prompt_text.insert('end','保留分镜文本 35%')
                app._prompt_text.configure(state='disabled')
                app._scene_plans = [object()]
                app._refresh_empty_state()
                app._set_busy(True)
                before = (app.input_var.get(), app.output_var.get(), app.ratio_var.get(),
                          app.audio_var.get(), app.narration_explain_var.get(), app.bgm_volume_var.get(),
                          app._prompt_text.get('1.0','end'), id(app._scene_plans[0]))
                for key in ('warm','dark','light'):
                    app._change_theme(theme_id=key)
                    assert before == (app.input_var.get(), app.output_var.get(), app.ratio_var.get(),
                          app.audio_var.get(), app.narration_explain_var.get(), app.bgm_volume_var.get(),
                          app._prompt_text.get('1.0','end'), id(app._scene_plans[0]))
                    assert 'disabled' in app._confirm_btn.state()
                app._set_busy(False)
                app._scene_plans = []
                app._set_busy(False)
                app._prompt_text.configure(state='normal')
                app._prompt_text.delete('1.0','end')
                app._prompt_text.configure(state='disabled')
                app.input_var.set('')
                root.geometry('1000x720')
                root.after(400, check_small)
            except Exception as exc:
                errors.append(repr(exc))
                root.destroy()

        def check_small():
            try:
                app._scroll_canvas.yview_moveto(0)
                root.update_idletasks()
                app._entry_input.event_generate('<MouseWheel>', delta=-120)
                assert app._scroll_canvas.yview()[0] > 0
                app._scroll_canvas.yview_moveto(0)
                right = app._scroll_canvas.winfo_rootx() + app._scroll_canvas.winfo_width()
                for widget in (app._entry_input, app._image_provider_combo, app._video_provider_combo,
                               app._ratio_combo, app._bgm_volume_slider):
                    assert widget.winfo_rootx() + widget.winfo_width() <= right + 2, str(widget)
                capture(root, 'small_1000x720')
                # Center the sound card in the scroll viewport for visual review.
                height = app._content_area.winfo_height()
                app._scroll_canvas.yview_moveto(app._card_sound.master.winfo_y() / height)
                root.after(350, finish)
            except Exception as exc:
                errors.append(repr(exc))
                root.destroy()

        def finish():
            try:
                capture(root, 'sound_settings')
                assert app._confirm_btn.winfo_ismapped()
                app._change_theme(theme_id='dark')
            except Exception as exc:
                errors.append(repr(exc))
            finally:
                root.update_idletasks()
                root.destroy()

        root.after(500, check_theme)
        root.mainloop()
        assert not errors, errors
        second = Tk()
        second.withdraw()
        restarted = gui.PptxToVideoApp(second)
        assert restarted._theme_id == 'dark'
        second.update_idletasks()
        second.destroy()
    result = {'python':sys.version, 'themes':results, 'restart_restores_theme':True,
              'conversion_state_preserved':True, 'minimum_window':'1000x720', 'errors':errors}
    (OUT / 'checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
