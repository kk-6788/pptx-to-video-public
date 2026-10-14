"""Original Tk desktop controls inspired by the interaction patterns in UI libraries.

No React/CSS implementation is copied. Rendering uses the project's existing Pillow
dependency; controls retain Tk variables, keyboard focus and disabled-state behavior.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageTk
from ui_themes import THEMES


def blend(a, b, amount):
    colors = [tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in (a, b)]
    return '#%02x%02x%02x' % tuple(round(x + (y - x) * amount) for x, y in zip(*colors))


def rounded_image(size, background, fill, border, radius=12):
    w, h = size
    image = Image.new('RGB', (max(2, w * 2), max(2, h * 2)), background)
    draw = ImageDraw.Draw(image)
    if w >= 4 and h >= 4:
        draw.rounded_rectangle((2, 2, w * 2 - 3, h * 2 - 3), radius=radius * 2,
                               fill=fill, outline=border, width=2)
    return image.resize((max(1, w), max(1, h)), Image.Resampling.LANCZOS)


class PaintedControl(tk.Canvas):
    """One coalesced paint callback per control; nothing runs while idle."""
    def __init__(self, master, *, theme='light', background_role='card',
                 reduced_motion=lambda: False, state='normal', **kw):
        self.palette = THEMES[theme]
        self.background_role = background_role
        self.reduced_motion = reduced_motion
        self._control_state = state
        self._paint_job = None
        self._alive = True
        self._focused = self._hovered = self._pressed = False
        self._traces = []
        self._interactive = bool(kw.get('takefocus'))
        super().__init__(master, bg=self.palette[background_role], highlightthickness=0,
                         borderwidth=0, **kw)
        if state == 'disabled':
            super().configure(takefocus=0)
        self.bind('<Configure>', self.redraw)
        self.bind('<FocusIn>', lambda e: self._focus(True))
        self.bind('<FocusOut>', lambda e: self._focus(False))
        self.bind('<Enter>', lambda e: self._hover(True))
        self.bind('<Leave>', lambda e: self._hover(False))
        self.bind('<Destroy>', self._dispose, add='+')

    def _focus(self, focused):
        self._focused = focused
        self.redraw()

    def _hover(self, hovered):
        self._hovered = hovered and self._control_state != 'disabled'
        self.redraw()

    def watch(self, variable, callback=None):
        trace = variable.trace_add('write', callback or self.redraw)
        self._traces.append((variable, trace))

    def _dispose(self, event):
        if event.widget is not self:
            return
        self._alive = False
        if self._paint_job is not None:
            self.after_cancel(self._paint_job)
            self._paint_job = None
        for variable, trace in self._traces:
            variable.trace_remove('write', trace)
        self._traces.clear()

    def redraw(self, *_):
        if self._alive and self._paint_job is None:
            self._paint_job = self.after_idle(self._paint)

    def _paint(self):
        self._paint_job = None
        if self._alive:
            self.delete('all')
            if self.winfo_width() >= 20 and self.winfo_height() >= 20:
                self.draw(self.winfo_width(), self.winfo_height())

    def set_theme(self, theme):
        self.palette = THEMES[theme]
        super().configure(bg=self.palette[self.background_role])
        self.redraw()

    def configure(self, cnf=None, **kw):
        if cnf is None and not kw:
            return super().configure()
        if isinstance(cnf, str):
            return super().configure(cnf)
        kw = {**(cnf or {}), **kw}
        if 'state' in kw:
            self._control_state = kw.pop('state')
            self._pressed = False
            if self._interactive:
                kw['takefocus'] = 0 if self._control_state == 'disabled' else 1
        result = super().configure(**kw) if kw else None
        self.redraw()
        return result

    config = configure

    def cget(self, key):
        return self._control_state if key == 'state' else super().cget(key)

    def state(self, statespec=None):
        if statespec is not None:
            self.configure(state='disabled' if 'disabled' in statespec else 'normal')
        return ('disabled',) if self._control_state == 'disabled' else ()

    def put_image(self, image):
        self._image = ImageTk.PhotoImage(image, master=self)
        self.create_image(0, 0, anchor='nw', image=self._image)


class ActionButton(PaintedControl):
    def __init__(self, master, text='', command=None, variant='primary', **kw):
        self.text, self.command, self.variant = text, command, variant
        kw.setdefault('width', 160)
        kw.setdefault('height', 42)
        super().__init__(master, takefocus=1, cursor='hand2', **kw)
        self.bind('<ButtonPress-1>', self._press)
        self.bind('<ButtonRelease-1>', self._release)
        self.bind('<Key-space>', self._activate)
        self.bind('<Return>', self._activate)

    def _press(self, _event):
        if self._control_state != 'disabled':
            self.focus_set()
            self._pressed = True
            self.redraw()

    def _release(self, event):
        pressed, self._pressed = self._pressed, False
        self.redraw()
        if pressed and 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self.invoke()

    def _activate(self, _event):
        self.invoke()
        return 'break'

    def invoke(self):
        if self._control_state != 'disabled' and self.command:
            return self.command()

    def configure(self, cnf=None, **kw):
        if isinstance(cnf, dict):
            kw, cnf = {**cnf, **kw}, None
        for name in ('text', 'command'):
            if name in kw:
                setattr(self, name, kw.pop(name))
        result = super().configure(cnf, **kw)
        self.redraw()
        return result

    config = configure

    def cget(self, key):
        return getattr(self, key) if key in ('text', 'command') else super().cget(key)

    def draw(self, w, h):
        p = self.palette
        disabled = self._control_state == 'disabled'
        primary = self.variant == 'primary'
        fill = p['surface'] if disabled else p['accent'] if primary else p['card']
        if not disabled and (self._hovered or self._pressed):
            fill = p['active'] if primary else p['hover']
        border = p['accent'] if self._focused and not disabled else fill if primary else p['border']
        self.put_image(rounded_image((w, h), p[self.background_role], fill, border))
        fg = p['muted'] if disabled else p['on_accent'] if primary else p['fg']
        self.create_text(w / 2, h / 2 + (1 if self._pressed else 0), text=self.text,
                         fill=fg, font=('Microsoft YaHei UI', 10, 'bold' if primary else 'normal'))
        if self._focused and not disabled:
            self.create_line(w * .35, h - 6, w * .65, h - 6, fill=fg, width=1)


class ToggleSwitch(ActionButton):
    def __init__(self, master, text, variable, command=None, **kw):
        self.variable, self.on_change = variable, command
        self._position = float(variable.get())
        kw.setdefault('width', 180)
        kw.setdefault('height', 36)
        super().__init__(master, text=text, command=self._toggle, **kw)
        self.watch(variable)

    def _toggle(self):
        self.variable.set(not self.variable.get())
        if self.on_change:
            self.on_change()

    def draw(self, w, h):
        p, target = self.palette, float(self.variable.get())
        disabled = self._control_state == 'disabled'
        if self.reduced_motion() or disabled or abs(target - self._position) < .03:
            self._position = target
        else:
            self._position += (target - self._position) * .45
            self._paint_job = self.after(20, self._paint)
        fill = p['surface'] if disabled else blend(p['subtle'], p['accent'], self._position)
        image = Image.new('RGB', (w * 2, h * 2), p[self.background_role])
        draw = ImageDraw.Draw(image)
        y = h - 20
        draw.rounded_rectangle((2, y, 80, y + 40), radius=20, fill=fill)
        x = 7 + self._position * 36
        draw.ellipse((x, y + 5, x + 30, y + 35), fill=p['card'] if disabled else p['on_accent'])
        self.put_image(image.resize((w, h), Image.Resampling.LANCZOS))
        foreground = p['banner_fg'] if self.background_role == 'banner_end' else p['fg']
        self.create_text(51, h / 2, text=self.text, anchor='w', fill=p['muted'] if disabled else foreground,
                         font=('Microsoft YaHei UI', 10))
        if self._focused:
            self.create_line(51, h - 4, min(w - 3, 155), h - 4, fill=p['accent'])


class SegmentedControl(PaintedControl):
    def __init__(self, master, textvariable, **kw):
        self.variable = textvariable
        kw.pop('values', None)
        kw.setdefault('width', 245)
        kw.setdefault('height', 42)
        super().__init__(master, takefocus=1, cursor='hand2', **kw)
        self.watch(textvariable)
        self.bind('<Button-1>', self._select)
        for key in ('Left', 'Right', 'space'):
            self.bind('<Key-' + key + '>', self._key)

    def _select(self, event):
        if self._control_state != 'disabled':
            self.focus_set()
            self.variable.set('16:9' if event.x < self.winfo_width() / 2 else '9:16')

    def _key(self, event):
        if self._control_state != 'disabled':
            value = '16:9' if event.keysym == 'Left' else '9:16' if event.keysym == 'Right' else (
                '9:16' if self.variable.get() == '16:9' else '16:9')
            self.variable.set(value)
        return 'break'

    def get(self):
        return self.variable.get()

    def set(self, value):
        self.variable.set(value)

    def draw(self, w, h):
        p = self.palette
        image = rounded_image((w, h), p['card'], p['input'], p['border'])
        draw = ImageDraw.Draw(image)
        index = 0 if self.variable.get() == '16:9' else 1
        start, end = round(index * w / 2 + 4), round((index + 1) * w / 2 - 4)
        selected = p['surface'] if self._control_state == 'disabled' else p['accent']
        draw.rounded_rectangle((start, 4, end, h - 5), radius=8, fill=selected)
        self.put_image(image)
        for i, label in enumerate(('16:9  横屏', '9:16  竖屏')):
            fg = p['muted'] if self._control_state == 'disabled' else p['on_accent'] if i == index else p['secondary']
            self.create_text((i + .5) * w / 2, h / 2, text=label, fill=fg,
                             font=('Microsoft YaHei UI', 9, 'bold' if i == index else 'normal'))
        if self._focused:
            self.create_line(start + 18, h - 8, end - 18, h - 8, fill=p['on_accent'])


class RoundedSurface(tk.Frame):
    def __init__(self, master, *, theme='light', **kw):
        self.palette = THEMES[theme]
        super().__init__(master, bg=self.palette['bg'], **kw)
        self.canvas = tk.Canvas(self, highlightthickness=0, bg=self.palette['bg'])
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self._last_size = None
        self.bind('<Configure>', self._draw)

    def set_theme(self, theme):
        self.palette = THEMES[theme]
        self.configure(bg=self.palette['bg'])
        self.canvas.configure(bg=self.palette['bg'])
        self._last_size = None
        self._draw()

    def _draw(self, _event=None):
        size = (self.winfo_width(), self.winfo_height())
        if size == self._last_size or min(size) < 2:
            return
        self._last_size = size
        p = self.palette
        self._image = ImageTk.PhotoImage(rounded_image(size, p['bg'], p['card'], p['border'], 16), master=self)
        self.canvas.delete('all')
        self.canvas.create_image(0, 0, anchor='nw', image=self._image)


class WorkflowSteps(PaintedControl):
    def __init__(self, master, **kw):
        self.current, self.complete = 0, False
        super().__init__(master, height=52, background_role='bg', **kw)

    def set_step(self, current, complete=False):
        self.current, self.complete = current, complete
        self.redraw()

    def draw(self, w, h):
        p = self.palette
        labels = ('选择文件', '规划分镜', '确认生成', '导出视频')
        cell = w / 4
        for i, label in enumerate(labels):
            x = i * cell + 20
            done = i < self.current or self.complete
            active = i == self.current and not self.complete
            if i < 3:
                self.create_line(x + 130, h / 2, x + cell - 20, h / 2,
                                 fill=p['accent'] if done else p['border'], width=1)
            fill = p['accent'] if active or done else p['surface']
            self.create_oval(x - 15, h / 2 - 15, x + 15, h / 2 + 15, fill=fill, outline='')
            self.create_text(x, h / 2, text='✓' if done else str(i + 1),
                             fill=p['on_accent'] if active or done else p['muted'],
                             font=('Segoe UI', 10, 'bold'))
            self.create_text(x + 25, h / 2, text=label, anchor='w',
                             fill=p['fg'] if active or done else p['muted'],
                             font=('Microsoft YaHei UI', 10, 'bold' if active else 'normal'))


class FileStage(ActionButton):
    """Clickable source selector; source/video silhouettes are an illustration, not a preview."""
    def __init__(self, master, command, **kw):
        self.filename = ''
        self.pointer = None
        kw.setdefault('width', 540)
        kw.setdefault('height', 236)
        super().__init__(master, command=command, background_role='prompt', **kw)
        self.bind('<Motion>', self._move)

    def set_file(self, path):
        self.filename = Path(path).name if path else ''
        self.redraw()

    def _move(self, event):
        if not self.reduced_motion() and self._control_state != 'disabled':
            self.pointer = (event.x, event.y)
            if self._paint_job is None:
                self._paint_job = self.after(25, self._paint)

    def draw(self, w, h):
        p = self.palette
        output_height, h = h, 236
        image = Image.new('RGB', (w, h), p['prompt'])
        draw = ImageDraw.Draw(image)
        for y in range(h):
            draw.line((0, y, w, y), fill=blend(p['stage_start'], p['stage_end'], y / h))
        if self._hovered and self.pointer and not self.reduced_motion():
            glow = Image.new('RGBA', (w, h))
            g = ImageDraw.Draw(glow)
            x, y = self.pointer
            y = y * h / output_height
            g.ellipse((x - 80, y - 80, x + 80, y + 80), fill=p['stage_glow'] + '50')
            image = Image.alpha_composite(image.convert('RGBA'), glow.filter(ImageFilter.GaussianBlur(45))).convert('RGB')
        # Rounded clipping keeps the art integrated into the workbench.
        mask = Image.new('L', (w, h))
        ImageDraw.Draw(mask).rounded_rectangle((1, 1, w - 2, h - 2), radius=20, fill=255)
        image = Image.composite(image, Image.new('RGB', (w, h), p['prompt']), mask)
        draw = ImageDraw.Draw(image)
        center = w / 2
        left = max(18, center - 158)
        right = min(w - 18, center + 158)
        draw.rounded_rectangle((left + 12, 45, left + 170, 163), radius=12, fill=p['stage_shadow'])
        draw.rounded_rectangle((left, 31, left + 158, 152), radius=12, fill=p['card'], outline=p['border'])
        draw.rounded_rectangle((left + 18, 51, left + 55, 69), radius=4, fill=p['accent'])
        for y, end in ((88, 116), (103, 94), (118, 109)):
            draw.rounded_rectangle((left + 18, y, left + end, y + 4), radius=2, fill=p['subtle'])
        vx = right - 114
        draw.rounded_rectangle((vx + 5, 79, right + 5, 172), radius=14, fill=p['stage_shadow'])
        draw.rounded_rectangle((vx, 72, right, 165), radius=14, fill=p['accent'])
        px = vx + 56
        draw.polygon(((px - 10, 98), (px - 10, 138), (px + 20, 118)), fill=p['on_accent'])
        self.put_image(image.resize((w, output_height), Image.Resampling.LANCZOS))
        self.create_text(left + 37, 60 * output_height / h, text='PPT', fill=p['on_accent'], font=('Segoe UI', 8, 'bold'))
        self.create_text(center, 199 * output_height / h, text='PPTX   →   分镜 · 配音   →   MP4',
                         fill=p['secondary'], font=('Microsoft YaHei UI', 10))
        if self._focused:
            self.create_line(25, output_height - 9, w - 25, output_height - 9, fill=p['accent'], width=2)
