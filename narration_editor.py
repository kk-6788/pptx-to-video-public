"""Standalone page-by-page Tk narration review window."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import asdict, is_dataclass
import difflib
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import uuid


class NarrationEditor(tk.Toplevel):
    def __init__(self, parent, project, *, on_change=None, rewrite=None):
        super().__init__(parent)
        self.project, self.on_change, self.rewrite = project, on_change, rewrite
        self.title('讲稿审阅与编辑')
        self.geometry('1120x720')
        self.current_index = None
        self.history = {}
        self.events = queue.Queue()
        self._closed = False
        self._loading = False
        self._timer = None
        self.autosave_path = Path.cwd() / 'work' / 'narration-autosave' / f'{project.source_sha256[:16]}-{uuid.uuid4().hex[:8]}.json'
        toolbar = ttk.Frame(self)
        toolbar.pack(fill='x', padx=10, pady=8)
        for label, command in [('撤销', self.undo), ('恢复初稿', self.restore), ('保存项目', self.save_project), ('导出讲稿', self.export), ('单页试听', self.audition)]:
            ttk.Button(toolbar, text=label, command=lambda fn=command: self._guard(fn)).pack(side='left', padx=3)
        ttk.Button(toolbar, text='AI 重写预览', command=lambda: self._guard(self.request_rewrite), state='normal' if rewrite else 'disabled').pack(side='left', padx=3)
        ttk.Button(toolbar, text='按选择重建预览', command=lambda: self._guard(lambda: self.request_rewrite('按内容选择重建')), state='normal' if rewrite else 'disabled').pack(side='left', padx=3)
        self.locked, self.muted = tk.BooleanVar(), tk.BooleanVar()
        ttk.Checkbutton(toolbar, text='锁定', variable=self.locked, command=lambda: self._guard(self.toggle_lock)).pack(side='left')
        ttk.Checkbutton(toolbar, text='静音', variable=self.muted, command=lambda: self._guard(self.toggle_mute)).pack(side='left')
        body = ttk.Panedwindow(self, orient='horizontal')
        body.pack(fill='both', expand=True, padx=10)
        self.pages = tk.Listbox(body, width=18, exportselection=False)
        body.add(self.pages, weight=0)
        self.page_indices = list(project.segments)
        for index in self.page_indices:
            self.pages.insert('end', f'{index} · {project.segments[index].title}')
        self.pages.bind('<<ListboxSelect>>', self._select_page)
        source_panel, edit_panel = ttk.Frame(body), ttk.Frame(body)
        body.add(source_panel, weight=1)
        body.add(edit_panel, weight=1)
        ttk.Label(source_panel, text='原始内容（不随讲稿修改）').pack(anchor='w')
        self.source = tk.Text(source_panel, height=12, wrap='word', state='disabled')
        self.source.pack(fill='both', expand=True)
        ttk.Label(source_panel, text='内容选择：选中条目后更改朗读方式').pack(anchor='w')
        self.units = ttk.Treeview(source_panel, columns=('decision','text'), show='headings', height=9)
        self.units.heading('decision', text='朗读方式')
        self.units.heading('text', text='内容 / 理由')
        self.units.column('decision', width=80, stretch=False)
        self.units.column('text', width=290)
        self.units.pack(fill='both', expand=True)
        self.decision = ttk.Combobox(source_panel, state='readonly', values=['讲述','概括','不朗读','待确认'])
        self.decision.pack(fill='x')
        self.decision.bind('<<ComboboxSelected>>', lambda event: self._guard(self.change_decision))
        ttk.Label(edit_panel, text='最终讲稿（配音与字幕使用此文本）').pack(anchor='w')
        self.text = tk.Text(edit_panel, wrap='word', undo=True, font=('Microsoft YaHei UI', 12))
        self.text.pack(fill='both', expand=True)
        self.text.bind('<<Modified>>', self._text_modified)
        self.status = tk.StringVar()
        ttk.Label(self, textvariable=self.status, wraplength=1050).pack(fill='x', padx=10, pady=8)
        self.protocol('WM_DELETE_WINDOW', lambda: self._guard(self.close))
        if self.page_indices:
            self.show_page(self.page_indices[0])
        self._poll_id = self.after(100, self._poll)

    def _guard(self, fn):
        try:
            return fn()
        except Exception as exc:
            self.status.set(str(exc))
            messagebox.showerror('讲稿操作失败', str(exc), parent=self)

    def _select_page(self, event=None):
        selection = self.pages.curselection()
        if selection:
            self._guard(lambda: self.show_page(self.page_indices[selection[0]]))

    def _text_modified(self, event=None):
        if self.text.edit_modified():
            self.text.edit_modified(False)
            if not self._loading:
                if self._timer:
                    self.after_cancel(self._timer)
                self._timer = self.after(700, lambda: self._guard(self.commit_current))

    def _changed(self):
        self.project.save(self.autosave_path)
        if self.on_change:
            self.on_change(self.project)

    def commit_current(self):
        self._timer = None
        if self.current_index is None:
            return
        segment = self.project.segments[self.current_index]
        value = self.text.get('1.0', 'end-1c')
        if value != segment.text:
            previous = segment.text
            self.project.update_segment(self.current_index, text=value)
            self.history.setdefault(self.current_index, []).append(previous)
            self._changed()
        self._update_status()

    def show_page(self, index):
        self.commit_current()
        self.current_index = index
        self._render_page()

    def _render_page(self):
        self._loading = True
        segment = self.project.segments[self.current_index]
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        self.text.insert('1.0', segment.text)
        self.text.edit_reset()
        self.text.edit_modified(False)
        self.text.configure(state='disabled' if segment.locked else 'normal')
        self.source.configure(state='normal')
        self.source.delete('1.0', 'end')
        self.source.insert('1.0', segment.source_text)
        self.source.configure(state='disabled')
        self.units.delete(*self.units.get_children())
        labels = {'read':'讲述','speak':'讲述','summarize':'概括','skip':'不朗读','review':'待确认'}
        for number, unit in enumerate(segment.units):
            self.units.insert('', 'end', iid=str(number), values=(labels.get(unit.get('decision'),unit.get('decision','待确认')), f"{unit.get('text','')} · {unit.get('reason','')}"))
        self.locked.set(segment.locked)
        self.muted.set(segment.muted)
        self.pages.selection_clear(0, 'end')
        self.pages.selection_set(self.page_indices.index(self.current_index))
        self._loading = False
        self._update_status()

    def _update_status(self):
        segment = self.project.segments[self.current_index]
        seconds = 0 if segment.muted else max(1, round(len(segment.text) / 4.5))
        self.status.set(f'第 {segment.slide_index} 页 · 约 {seconds} 秒（实际以音频为准） · 修订 {segment.revision} · {segment.status}  ' + '；'.join(segment.warnings))

    def undo(self):
        self.commit_current()
        history = self.history.get(self.current_index, [])
        if history:
            self.project.update_segment(self.current_index, text=history[-1])
            history.pop()
            self._changed()
            self._render_page()

    def restore(self):
        self.commit_current()
        previous = self.project.segments[self.current_index].text
        self.project.restore_initial(self.current_index)
        self.history.setdefault(self.current_index, []).append(previous)
        self._changed()
        self._render_page()

    def toggle_lock(self):
        self.commit_current()
        self.project.update_segment(self.current_index, locked=self.locked.get())
        self._changed()
        self._render_page()

    def toggle_mute(self):
        self.commit_current()
        try:
            self.project.update_segment(self.current_index, muted=self.muted.get())
            self._changed()
        finally:
            self._render_page()

    def change_decision(self):
        self.commit_current()
        selection = self.units.selection()
        if not selection:
            return
        units = deepcopy(self.project.segments[self.current_index].units)
        unit = units[int(selection[0])]
        unit['decision'] = {'讲述':'read','概括':'summarize','不朗读':'skip','待确认':'review'}[self.decision.get()]
        unit['reason'] = '用户选择；请重写或编辑讲稿以应用此选择'
        unit['user_override'] = True
        self.project.update_segment(self.current_index, units=units)
        self._changed()
        self._render_page()

    def save_project(self):
        self.commit_current()
        path = filedialog.asksaveasfilename(parent=self, defaultextension='.json', filetypes=[('讲稿项目','*.json')])
        if path:
            self.project.save(path)
            self.status.set(f'项目已保存：{path}')

    def export(self):
        self.commit_current()
        path = filedialog.asksaveasfilename(parent=self, defaultextension='.md', filetypes=[('Markdown','*.md'),('文本','*.txt')])
        if path:
            self.project.export_script(path)

    def _background(self, work, callback):
        def run():
            try:
                self.events.put((callback, work(), None))
            except Exception as exc:
                self.events.put((callback, None, str(exc)))
        threading.Thread(target=run, daemon=True).start()

    def _poll(self):
        if self._closed:
            return
        try:
            while True:
                callback, value, error = self.events.get_nowait()
                if error:
                    self.status.set(error)
                else:
                    self._guard(lambda: callback(value))
        except queue.Empty:
            pass
        self._poll_id = self.after(100, self._poll)

    def request_rewrite(self, instruction=None):
        self.commit_current()
        segment = self.project.segments[self.current_index]
        if segment.locked:
            raise ValueError('请先解锁此页')
        if instruction is None:
            instruction = simpledialog.askstring('重写讲稿', '填写要求，例如：缩短至约 30 秒，保留关键数字与限制条件', parent=self)
        if not instruction or not self.rewrite:
            return
        index, revision = self.current_index, segment.revision
        selections = deepcopy(segment.units)
        self.status.set('正在生成重写预览…')
        self._background(lambda: self.rewrite(index, instruction, selections), lambda record: self._preview(index, revision, record))

    def _preview(self, index, revision, record):
        record = asdict(record) if is_dataclass(record) else record
        preview = tk.Toplevel(self)
        preview.title('重写差异预览：确认后才应用')
        preview.geometry('850x550')
        output = tk.Text(preview, wrap='word')
        output.pack(fill='both', expand=True)
        before = self.project.segments[index].text
        difference = '\n'.join(difflib.unified_diff(before.splitlines(), record['text'].splitlines(), fromfile='当前稿', tofile='建议稿', lineterm=''))
        output.insert('1.0', difference or '讲稿没有变化')
        output.configure(state='disabled')
        def accept():
            self.commit_current()
            self.apply_rewrite(index, revision, record)
            preview.destroy()
        ttk.Button(preview, text='应用修改', command=lambda: self._guard(accept)).pack(side='right', padx=10, pady=10)
        ttk.Button(preview, text='取消', command=preview.destroy).pack(side='right')

    def apply_rewrite(self, index, revision, record):
        record = asdict(record) if is_dataclass(record) else record
        if not isinstance(record, dict) or not isinstance(record.get('text'), str):
            raise ValueError('重写结果缺少讲稿文本')
        if self.project.segments[index].locked:
            raise ValueError('此页已锁定，请先解锁')
        if self.project.segments[index].locked:
            raise ValueError('此页已锁定，请先解锁')
        previous = self.project.segments[index].text
        segment = self.project.update_segment(index, text=record['text'], units=record.get('units'), expected_revision=revision)
        segment.warnings = list(record.get('warnings', []))
        segment.status = record.get('status', segment.status)
        self.history.setdefault(index, []).append(previous)
        self._changed()
        if self.current_index == index:
            self._render_page()

    def audition(self):
        self.commit_current()
        segment = self.project.segments[self.current_index]
        if segment.muted or not segment.text.strip():
            raise ValueError('此页静音或讲稿为空，无法试听')
        index, revision, text = segment.slide_index, segment.revision, segment.text
        voice = self.project.settings.get('voice', 'zh-CN-XiaoxiaoNeural')
        path = self.autosave_path.parent / f'audition-{index}-{revision}-{uuid.uuid4().hex[:8]}.mp3'
        path.parent.mkdir(parents=True, exist_ok=True)
        def work():
            from tts_audio import generate_narration
            result = asyncio.run(generate_narration(text, output_path=path, voice=voice,
                rate=self.project.settings.get('rate', '+0%'), preserve_text=True))
            if not result:
                raise RuntimeError('单页配音失败，请检查网络或配音配置后重试')
            return result
        def play(result):
            if self.project.segments[index].revision != revision:
                self.status.set('讲稿已变化，已忽略旧版本试听结果')
                return
            os.startfile(str(result))
            self.status.set(f'正在播放第 {index} 页试听')
        self.status.set('正在生成单页试听…')
        self._background(work, play)

    def close(self):
        self.commit_current()
        self._changed()
        self.destroy()

    def destroy(self):
        self._closed = True
        for timer in (self._timer, getattr(self, '_poll_id', None)):
            if timer:
                self.after_cancel(timer)
        super().destroy()
