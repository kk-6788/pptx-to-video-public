#!/usr/bin/env python3
"""
PPT转视频工具 v2.0 — GUI 桌面应用

优化功能：
1. 导演引擎生成专业级提示词（风格/运镜/光影都考虑）
2. 提示词预览 → 用户确认后再生视频
3. 多Provider支持（SiliconFlow / ComfyUI / 自定义API）
4. 视觉风格选择（豪华/科技/自然/时尚/商务/生活）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import webbrowser
from pathlib import Path
from tkinter import (
    Tk,
    Toplevel,
    ttk,
    BooleanVar,
    DoubleVar,
    IntVar,
    StringVar,
    Canvas,
    filedialog,
    messagebox,
    scrolledtext,
)
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── Version ──────────────────────────────────────────────────────────────
VERSION = "2.4.0"

# Shared palette for the main window and review dialogs.
from ui_themes import THEMES, configure_styles, legacy_colors, load_theme, save_theme
from ui_components import ActionButton, ToggleSwitch, SegmentedControl, RoundedSurface, WorkflowSteps, FileStage
globals().update(legacy_colors("light"))


def _use_themed_scrollbar(text_widget):
    """Tk's native Windows scrollbar ignores dark colors; use ttk instead."""
    text_widget.vbar.destroy()
    text_widget.vbar = ttk.Scrollbar(text_widget.frame, orient="vertical",
                                     command=text_widget.yview, style="Vertical.TScrollbar")
    text_widget.vbar.pack(side="right", fill="y")
    text_widget.configure(yscrollcommand=text_widget.vbar.set)

# Available providers & styles for GUI dropdowns
_PROVIDER_NAMES = {
    "siliconflow": "SiliconFlow (云端全功能)",
    "agnes": "🌟 Agnes AI (免费)",
    "kling": "可灵AI (Kling)",
    "volcengine": "火山引擎 (豆包/Seed)",
    "openai": "OpenAI (DALL-E/GPT)",
    "gemini": "Google Gemini",
    "comfyui": "ComfyUI (本地免费)",
    "custom_api": "自定义API",
}

_STYLE_NAMES = {
    "auto": "自动检测",
    "modern luxury": "现代奢华",
    "tech innovation": "科技创新",
    "nature organic": "自然有机",
    "fashion editorial": "时尚编辑",
    "corporate clean": "商务简洁",
    "warm lifestyle": "温暖生活",
}

# Available use cases (客户需求类型)
_USE_CASES = {
    "auto": "🎯 通用/自动",
    "education": "📚 上课/教学",
    "ecommerce": "🛒 带货/电商",
    "product-launch": "🚀 产品发布",
    "brand-story": "💎 品牌故事",
    "corporate": "🏢 企业宣传",
    "academic": "📖 学术报告",
}

_USE_CASE_DEFAULTS = None  # lazy-loaded when needed
def _get_use_case_data(key: str) -> dict:
    global _USE_CASE_DEFAULTS
    if _USE_CASE_DEFAULTS is None:
        from prompt_engine import _USE_CASE_STRUCTURES
        _USE_CASE_DEFAULTS = _USE_CASE_STRUCTURES
    return _USE_CASE_DEFAULTS.get(key, {})

# Model defaults per provider
_PROVIDER_MODELS: dict[str, tuple[list[str], list[str]]] = {
    "siliconflow": (
        [
            "pro/black-forest-labs/FLUX.1-pro",
            "black-forest-labs/FLUX.1-dev",
            "black-forest-labs/FLUX.1-schnell",
            "stabilityai/stable-diffusion-3-5-large",
            "stabilityai/stable-diffusion-3-5-medium",
            "Kwai-Kolors/Kolors-IMAGEN",
            "seedream-250",
            "ByteDance/SDXL-Lightning",
        ],
        [
            "wan-2.1",
            "CogVideoX",
            "SVD",
            "Mochi-1",
            "seedance-2.0",
        ],
    ),
    "kling": (
        [
            "kling-image-v1-6",
            "kling-image-v1-5",
            "kling-image-v1",
        ],
        [
            "kling-video-v1-6",
            "kling-v1-6",
            "kling-video-v1-5",
            "kling-v1-5",
            "kling-video-v1",
            "kling-v1",
        ],
    ),
    "volcengine": (
        [
            "seedream-5.0",
            "seedream-3.0",
            "seedream-2.5",
            "seedream-2.0",
        ],
        [
            "seedance-2.0",
            "seedance-1.5",
            "seedance-1.0",
        ],
    ),
    "comfyui": (
        ["sd3.5", "sdxl", "flux", "sd1.5"],
        ["wan2.1", "animatediff", "svd"],
    ),
    "custom_api": (
        ["", "dall-e-3", "dall-e-2"],
        [""],
    ),
    "agnes": (
        ["agnes-image-2.1-flash"],
        ["agnes-video-v2.0"],
    ),
    "openai": (
        ["dall-e-3", "dall-e-2"],
        [""],
    ),
    "gemini": (
        ["imagen-3.0", "imagen-2.0"],
        [""],
    ),
}


# ── Log Handler ──────────────────────────────────────────────────────────


class GuiLogHandler(logging.Handler):
    """Forward log records to a tkinter ScrolledText widget."""

    def __init__(self, text_widget: scrolledtext.ScrolledText) -> None:
        super().__init__()
        self.text_widget = text_widget
        self.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S"
        ))
        self.setLevel(logging.INFO)

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record) + "\n"
        self.text_widget.after(0, self._append, msg)

    def _append(self, msg: str) -> None:
        w = self.text_widget
        w.configure(state="normal")
        w.insert("end", msg)
        w.see("end")
        w.configure(state="disabled")


# ── Main Application ─────────────────────────────────────────────────────


def _refresh_plan_narration(slides: list[Any], plans: list[Any], narration_style: str) -> None:
    """Apply the current narration choice while preserving edited visual prompts."""
    from tts_audio import build_slide_narration

    slide_by_index = {slide.index: slide for slide in slides}
    for plan in plans:
        if getattr(plan, "narration_state", "legacy") in {"edited", "generated"}:
            continue
        indices = getattr(plan, "slide_indices", None) or [plan.slide_index]
        plan.narration_style = narration_style
        plan.narration_by_slide = {
            index: build_slide_narration(slide_by_index[index], narration_style=narration_style)
            for index in indices if index in slide_by_index
        }
        plan.narration_text = "\n".join(plan.narration_by_slide.values())


class PptxToVideoApp:
    """GUI for pptx-to-video with director-style prompt preview."""

    def __init__(self, master: Tk) -> None:
        self.master = master
        master.title(f"PPT转视频工具 v{VERSION}")
        master.geometry("1280x860")
        master.minsize(1000, 720)

        # Center on screen
        master.update_idletasks()
        sw = master.winfo_screenwidth()
        sh = master.winfo_screenheight()
        width, height = min(1280, sw - 40), min(860, sh - 80)
        x, y = max(0, (sw - width) // 2), max(0, (sh - height) // 2)
        master.geometry(f"{width}x{height}+{x}+{y}")

        # Icon
        ico = PROJECT_ROOT / "app_icon.ico"
        if ico.exists():
            try:
                master.iconbitmap(str(ico))
            except Exception:
                pass

        # ── State ──
        self._running = False
        self._scene_plans: list[Any] = []       # generated by Director
        self._parsed_slides: list[Any] = []      # parsed slides
        self._narration_project = None
        self._narration_editor = None
        self._stop_flag = False
        self._stop_event: threading.Event | None = None
        self._regeneration_feedback: dict[int, str] | None = None

        # ── New feature state ──
        self.total_duration_var = IntVar(value=30)
        self.images_per_slide_var = IntVar(value=4)
        self.lang_var = StringVar(value="zh-CN")

        self._theme_id = load_theme()
        self.ui_theme_var = StringVar(value=THEMES[self._theme_id]["name"])
        self.reduce_motion_var = BooleanVar(value=False)
        globals().update(legacy_colors(self._theme_id))
        self._setup_styles()
        self._build_widgets()
        self._apply_visual_mode()
        self._change_theme(theme_id=self._theme_id, persist=False)
        self._progress_frame.grid_remove()
        self.master.after(100, lambda: self._main_paned.sashpos(0, 460))

        # Force scrollregion update in left panel after all widgets built
        self.master.after(100, self._refresh_scrollregion)

    def _refresh_scrollregion(self) -> None:
        """Recalculate the scrollable area in the left settings panel."""
        try:
            self._content_area.update_idletasks()
            bbox = self._scroll_canvas.bbox("all")
            if bbox:
                self._scroll_canvas.configure(scrollregion=bbox)
        except Exception:
            pass

    def _constrain_sash(self, _event=None) -> None:
        width = self._main_paned.winfo_width()
        if width > 800:
            position = self._main_paned.sashpos(0)
            bounded = max(440, min(width - 420, position))
            if bounded != position:
                self._main_paned.sashpos(0, bounded)

    # ── Theme ───────────────────────────────────────────────────────────

    def _setup_styles(self) -> None:
        configure_styles(self.master, self._theme_id)

    def _change_theme(self, event=None, *, theme_id=None, persist=True) -> None:
        selected = theme_id or next((key for key, p in THEMES.items()
                                    if p["name"] == self.ui_theme_var.get()), "light")
        if selected not in THEMES:
            selected = "light"
        old, new = legacy_colors(self._theme_id), legacy_colors(selected)
        replacements = {value.lower(): new[key] for key, value in old.items()}
        replacements["#15142b"] = new["C_INPUT_BG"]
        replacements["#ffcc80"] = new["C_WARN"]
        self._theme_id = selected
        self.ui_theme_var.set(THEMES[selected]["name"])
        globals().update(new)
        self._setup_styles()
        # Apply classic Tk colors and explicit overrides without recreating controls.
        pending = [self.master]
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            keys = widget.keys()
            for option in ("background", "foreground", "insertbackground", "selectbackground",
                           "selectforeground", "highlightbackground", "highlightcolor",
                           "activebackground", "activeforeground", "troughcolor"):
                if option in keys:
                    value = str(widget.cget(option)).lower()
                    if value in replacements:
                        widget.configure(**{option: replacements[value]})
            if widget.winfo_class() == "Text":
                for tag in widget.tag_names():
                    for option in ("foreground", "background"):
                        value = str(widget.tag_cget(tag, option)).lower()
                        if value in replacements:
                            widget.tag_configure(tag, **{option: replacements[value]})
            if widget.winfo_class() == "Scrollbar":
                widget.configure(background=C_SURFACE, activebackground=C_BORDER_SUBTLE,
                                 troughcolor=C_PROMPT_BG, highlightthickness=0,
                                 borderwidth=0, relief="flat", width=11)
            if isinstance(widget, ttk.Combobox):
                # Already-opened Tcl popdowns do not inherit new option defaults.
                listbox = widget._w + ".popdown.f.l"
                if widget.tk.call("winfo", "exists", listbox):
                    widget.tk.call(listbox, "configure", "-background", C_CARD,
                                   "-foreground", C_FG, "-selectbackground", C_ACCENT,
                                   "-selectforeground", THEMES[selected]['on_accent'])
            if hasattr(widget, 'set_theme'):
                widget.set_theme(selected)
        self._update_steps()
        self._draw_empty_art()
        self._draw_banner()
        if persist and not save_theme(selected):
            self._log("界面主题已切换，本次无法保存，下次启动将使用原主题。", "warn")

    def _draw_empty_art(self) -> None:
        self._empty_art.set_theme(self._theme_id)
        self._empty_art.set_file(self.input_var.get())

    def _draw_banner(self, _event=None) -> None:
        from PIL import Image, ImageDraw, ImageTk
        canvas = self._banner
        canvas.delete("all")
        p = THEMES[self._theme_id]
        width = max(900, canvas.winfo_width())
        canvas.configure(bg=p['bg'])
        start, end = [tuple(int(p[k][i:i+2], 16) for i in (1, 3, 5)) for k in ('banner', 'banner_end')]
        banner_image = Image.new('RGB', (width, 94))
        draw = ImageDraw.Draw(banner_image)
        for x in range(0, width, 4):
            alpha = min(1., x / max(1, width * .75))
            rgb = tuple(round(a * (1-alpha) + b * alpha) for a, b in zip(start, end))
            draw.rectangle((x, 0, x + 4, 94), fill=rgb)
        mask = Image.new('L', (width * 2, 188))
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, width * 2 - 1, 187), radius=30, fill=255)
        banner_image = Image.composite(banner_image, Image.new('RGB', (width, 94), p['bg']),
                                      mask.resize((width, 94), Image.Resampling.LANCZOS))
        self._banner_image = ImageTk.PhotoImage(banner_image, master=canvas)
        canvas.create_image(0, 0, anchor='nw', image=self._banner_image)
        # The stacked slide mark is also the video timeline motif.
        canvas.create_rectangle(25, 24, 61, 54, outline=p['banner_muted'], width=1)
        canvas.create_rectangle(31, 30, 67, 60, fill=p['banner'], outline=p['ornament'], width=2)
        canvas.create_polygon(43, 37, 43, 53, 55, 45, fill=p['ornament'], outline='')
        canvas.create_text(84, 29, text='PPT → Video', anchor='w',
                           font=('Segoe UI Semibold', 22), fill=p['banner_fg'])
        canvas.create_text(85, 60, text='内容 · 讲解 · 影像', anchor='w',
                           font=('Microsoft YaHei UI', 10), fill=p['banner_muted'])
        canvas.create_line(85, 78, 145, 78, fill=p['ornament'], width=2)

    def _refresh_empty_state(self, *_args) -> None:
        source = self.input_var.get()
        if source != getattr(self, '_last_input', source):
            # A reviewed storyboard belongs to one source, including when a path is typed.
            self._scene_plans = []
            self._narration_project = None
            self._parsed_slides = []
            self._confirm_btn.configure(state='disabled')
            self._prompt_text.configure(state='normal')
            self._prompt_text.delete('1.0', 'end')
            self._prompt_text.configure(state='disabled')
            if hasattr(self, '_status_bar'):
                self._status_bar.configure(text='就绪 · 文件已变更，请重新规划分镜')
        self._last_input = source
        self._update_steps()
        if self._scene_plans:
            self._empty_panel.place_forget()
            return
        self._empty_panel.place(relx=.5, rely=.48, anchor="center", relwidth=.87)
        name = Path(self.input_var.get()).name if self.input_var.get() else ""
        self._empty_art.set_file(self.input_var.get())
        self._empty_title.configure(text="文件已就绪" if name else "从一份 PPT 开始")
        self._empty_description.configure(text=(f"{name}\n点击「规划分镜」，查看每页画面和讲解。" if name else
            "保留你的内容，让每一页都有清晰的讲解。\n选择文件，预览分镜，再生成视频。"))

    # ── Widgets ─────────────────────────────────────────────────────────

    def _build_widgets(self) -> None:
        # Desktop layout: settings and workspace share a resizable divider.
        self.master.grid_rowconfigure(0, weight=0)  # header
        self.master.grid_rowconfigure(1, weight=0)  # desc
        self.master.grid_rowconfigure(2, weight=1)  # PanedWindow (main content)
        self.master.grid_rowconfigure(3, weight=0)  # progress bar (hidden)
        self.master.grid_rowconfigure(4, weight=0)  # status bar
        self.master.grid_columnconfigure(0, weight=1)

        header = ttk.Frame(self.master, height=94)
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(18, 12))
        header.pack_propagate(False)
        self._banner = Canvas(header, highlightthickness=0, height=94)
        self._banner.pack(fill='both', expand=True)
        self._banner.bind('<Configure>', self._draw_banner)
        self._theme_combo = ttk.Combobox(header, textvariable=self.ui_theme_var,
                                        values=[p["name"] for p in THEMES.values()], state="readonly", width=12)
        self._theme_combo.place(relx=1, x=-22, y=32, anchor='ne')
        self._theme_combo.bind("<<ComboboxSelected>>", self._change_theme)
        ttk.Label(header, text="界面主题", style="Banner.TLabel").place(relx=1, x=-170, y=44, anchor='ne')
        self._workflow_steps = WorkflowSteps(self.master, theme=self._theme_id)
        self._workflow_steps.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 10))
        self._motion_check = ToggleSwitch(header, text="减弱动效", variable=self.reduce_motion_var,
            theme=self._theme_id, width=150, background_role='banner_end', reduced_motion=lambda: True,
            command=self._on_reduce_motion)
        self._motion_check.place(relx=1, x=-270, y=32, anchor='ne')

        # ═══════════════════════════════════════════════════════════════
        # Main content: PanedWindow [Scrollable Settings | Notebook]
        # ═══════════════════════════════════════════════════════════════
        self._main_paned = ttk.PanedWindow(self.master, orient="horizontal",
                                           style="TPanedwindow")
        self._main_paned.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 0))

        # ── Left: Scrollable Settings ─────────────────────────────────────
        settings_wrapper = ttk.Frame(self._main_paned, style="TFrame")
        self._main_paned.add(settings_wrapper, weight=0)
        settings_wrapper.configure(width=480)
        settings_wrapper.rowconfigure(0, weight=1)

        settings_scroll = ttk.Frame(settings_wrapper)
        settings_scroll.pack(fill="both", expand=True)
        self._scroll_canvas = Canvas(settings_scroll, bg=C_BG,
                                     highlightthickness=0)
        self._scrollbar = ttk.Scrollbar(settings_scroll, orient="vertical",
                                    style="Vertical.TScrollbar",
                                    command=self._scroll_canvas.yview)
        self._scroll_canvas.configure(yscrollcommand=self._scrollbar.set)

        self._content_area = ttk.Frame(self._scroll_canvas, style="TFrame")
        self._content_area.bind(
            "<Configure>",
            lambda e: self._scroll_canvas.configure(
                scrollregion=self._scroll_canvas.bbox("all"))
        )
        self._canvas_window = self._scroll_canvas.create_window(
            (0, 0), window=self._content_area, anchor="nw")

        self._scroll_canvas.pack(side="left", fill="both", expand=True,
                                 padx=0, pady=0)
        self._scrollbar.pack(side="right", fill="y")

        def _on_canvas_configure(event):
            self._scroll_canvas.itemconfig(self._canvas_window,
                                           width=event.width)
        self._scroll_canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            widget = event.widget
            while widget is not None and widget is not self.master:
                if widget in (self._content_area, self._scroll_canvas, self._scrollbar):
                    self._scroll_canvas.yview_scroll(int(-event.delta / 120), "units")
                    return "break"
                widget = getattr(widget, "master", None)
        self.master.bind("<MouseWheel>", _on_mousewheel, add="+")

        # ── _content_area grid weights ──
        self._content_area.grid_columnconfigure(0, weight=1)
        self._content_area.grid_rowconfigure(0, weight=0)  # file card
        self._content_area.grid_rowconfigure(1, weight=0)  # api key card
        self._content_area.grid_rowconfigure(2, weight=0)  # engine card
        self._content_area.grid_rowconfigure(3, weight=0)  # duration card
        self._content_area.grid_rowconfigure(4, weight=0)  # buttons

        # ── Card: File Selection ──
        self._card_file = self._make_card("项目文件",
                                          row=0, column=0, padx=0, pady=(0, 0))
        self._card_file.columnconfigure(1, weight=1)

        ttk.Label(self._card_file, text="输入 PPTX:",
                  style="Card.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 6))
        self.input_var = StringVar()
        self._entry_input = ttk.Entry(self._card_file,
                                      textvariable=self.input_var, width=1)
        self._entry_input.grid(row=0, column=1, sticky="ew", padx=(0, 4))
        self._browse_input_btn = ttk.Button(self._card_file, text="浏览…", style="Small.TButton",
                                             command=self._browse_input)
        self._browse_input_btn.grid(row=0, column=2)

        ttk.Label(self._card_file, text="输出 MP4:",
                  style="Card.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 6), pady=(6, 0))
        self.output_var = StringVar()
        self._entry_output = ttk.Entry(self._card_file,
                                       textvariable=self.output_var, width=1)
        self._entry_output.grid(row=1, column=1, sticky="ew",
                                pady=(6, 0), padx=(0, 4))
        self._browse_output_btn = ttk.Button(self._card_file, text="浏览…", style="Small.TButton",
                                              command=self._browse_output)
        self._browse_output_btn.grid(
            row=1, column=2, padx=(0, 0), pady=(6, 0))

        ttk.Label(self._card_file, text="内容呈现:", style="Card.TLabel").grid(
            row=2, column=0, sticky="w", pady=(12, 0), padx=(0, 6))
        self.visual_mode_var = StringVar(value="忠实讲解")
        self._visual_mode_combo = ttk.Combobox(
            self._card_file, textvariable=self.visual_mode_var, state="readonly",
            values=["忠实讲解", "AI 创意演绎"], width=15)
        self._visual_mode_combo.grid(row=2, column=1, columnspan=2, sticky="ew", pady=(12, 0))
        self._visual_mode_combo.bind("<<ComboboxSelected>>", self._on_visual_mode_change)
        self._visual_mode_hint = ttk.Label(self._card_file, style="Muted.TLabel", wraplength=355)
        self._visual_mode_hint.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(8, 0))

        # ── Card: API Key ──
        self._card_api = self._make_card("引擎连接",
                                         row=1, column=0, padx=0, pady=(12, 0))
        self._card_api.columnconfigure(1, weight=1)
        self._api_key_frame = ttk.Frame(self._card_api, style="Card.TFrame")
        self._api_key_frame.grid(row=0, column=0, columnspan=3, sticky="ew")
        self._api_key_frame.columnconfigure(1, weight=1)
        self._api_key_vars: dict[str, StringVar] = {}
        self._api_key_widgets: dict[str, ttk.Entry] = {}
        self._build_api_key_fields()

        self._api_status = StringVar(value=self._get_key_source_text())
        ttk.Label(self._card_api, textvariable=self._api_status,
                  style="Muted.TLabel", wraplength=360).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        # Full-width fields remain readable in the settings pane.
        self._card_set = self._make_card("生成设置", row=2, column=0, padx=0, pady=(12, 0))
        self._card_set.columnconfigure(1, weight=1)
        default_prov = os.getenv("PROVIDER", "siliconflow")
        self.image_provider_var = StringVar(value=os.getenv("IMAGE_PROVIDER", default_prov))
        self.video_provider_var = StringVar(value=os.getenv("VIDEO_PROVIDER", default_prov))
        self.style_var = StringVar(value=os.getenv("VISUAL_STYLE", "auto"))
        self.use_case_var = StringVar(value=os.getenv("USE_CASE", "auto"))
        self.image_model_var, self.video_model_var = StringVar(), StringVar()
        self._field_vars = []

        def field(row, label, values, variable, callback=None, readonly=True):
            self._field_vars.append(variable)
            ttk.Label(self._card_set, text=label, style="Card.TLabel").grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=5)
            combo = ttk.Combobox(self._card_set, values=values, textvariable=variable,
                                 state="readonly" if readonly else "normal", width=15)
            combo.grid(row=row, column=1, sticky="ew", pady=5)
            if callback:
                combo.bind("<<ComboboxSelected>>", callback)
                if not readonly:
                    combo.bind("<FocusOut>", callback)
            return combo

        self._image_provider_combo = field(0, "图片引擎", list(_PROVIDER_NAMES.values()),
            StringVar(value=_PROVIDER_NAMES.get(self.image_provider_var.get(), self.image_provider_var.get())),
            self._on_image_provider_change, False)
        self._image_model_combo = field(1, "图片模型", [], self.image_model_var)
        self._video_provider_combo = field(2, "视频引擎", list(_PROVIDER_NAMES.values()),
            StringVar(value=_PROVIDER_NAMES.get(self.video_provider_var.get(), self.video_provider_var.get())),
            self._on_video_provider_change, False)
        self._video_model_combo = field(3, "视频模型", [], self.video_model_var)
        self._style_combo = field(4, "画面风格", list(_STYLE_NAMES.values()),
            StringVar(value=_STYLE_NAMES.get(self.style_var.get(), _STYLE_NAMES["auto"])), self._on_style_change)
        self._use_case_combo = field(5, "视频用途", list(_USE_CASES.values()),
            StringVar(value=_USE_CASES.get(self.use_case_var.get(), _USE_CASES["auto"])), self._on_use_case_change)
        self._lang_combo = field(6, "语言", ["zh-CN", "en"], self.lang_var)
        self._use_case_hint = ttk.Label(self._card_set, text="", style="Muted.TLabel", wraplength=355)
        self._use_case_hint.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self._update_models_for_provider()

        from narration_engine import PRESENTATION_STYLES
        self.presentation_style_var = StringVar(value='通用 / 自动')
        self._presentation_labels = {k: (v if isinstance(v, str) else v['label']) for k, v in PRESENTATION_STYLES.items()}
        self.presentation_style_var.set(self._presentation_labels.get('auto', next(iter(self._presentation_labels.values()))))
        self.script_length_var = StringVar(value='标准')
        self.notes_policy_var = StringVar(value='参考备注')
        self.include_hidden_var = BooleanVar(value=False)
        self._script_style_combo = field(8, '讲述场景', list(self._presentation_labels.values()), self.presentation_style_var)
        self._script_length_combo = field(9, '讲稿篇幅', ['精简', '标准', '详细'], self.script_length_var)
        self._notes_policy_combo = field(10, '备注使用', ['不用备注', '参考备注', '优先讲稿备注'], self.notes_policy_var)
        ttk.Checkbutton(self._card_set, text='包含隐藏页', variable=self.include_hidden_var).grid(row=11, column=0, columnspan=2, sticky='w')
        self.voice_var = StringVar(value='zh-CN-XiaoxiaoNeural')
        self.rate_var = StringVar(value='+0%')
        self._voice_combo = field(12, '配音声音', ['zh-CN-XiaoxiaoNeural', 'zh-CN-YunxiNeural', 'en-US-JennyNeural'], self.voice_var)
        self._rate_combo = field(13, '语速', ['-20%', '-10%', '+0%', '+10%', '+20%'], self.rate_var)

        self._card_sound = self._make_card("画幅与声音", row=3, column=0, padx=0, pady=(12, 0))
        self._card_sound.columnconfigure(1, weight=1)
        ttk.Label(self._card_sound, text="画面比例", style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=(0,12))
        self.ratio_var = StringVar(value="original")
        self._ratio_combo = ttk.Combobox(self._card_sound, textvariable=self.ratio_var,
                                        values=['original', '16:9', '9:16', '1:1'], state='readonly')
        self._ratio_combo.grid(row=0, column=1, sticky="ew", pady=(0,8))
        self.subtitle_var, self.audio_var = BooleanVar(value=False), BooleanVar(value=True)
        self.narration_explain_var, self.bgm_var = BooleanVar(value=False), BooleanVar(value=True)
        checks = ttk.Frame(self._card_sound, style="Card.TFrame")
        checks.grid(row=1, column=0, columnspan=2, sticky="ew")
        checks.columnconfigure((0, 1), weight=1)
        for i, (attribute, label, variable) in enumerate((
                ('_subtitle_check', '添加字幕', self.subtitle_var),
                ('_audio_check', '配音 (TTS)', self.audio_var),
                ('_narration_check', '口播转述', self.narration_explain_var),
                ('_bgm_check', '背景音乐', self.bgm_var))):
            control = ToggleSwitch(checks, text=label, variable=variable, theme=self._theme_id,
                                   reduced_motion=self.reduce_motion_var.get, width=175)
            control.grid(row=i // 2, column=i % 2, sticky='ew')
            setattr(self, attribute, control)
        music = ttk.Frame(self._card_sound, style="Card.TFrame")
        music.grid(row=2,column=0,columnspan=2,sticky="ew",pady=(8,0))
        ttk.Label(music,text="音乐音量",style="Muted.TLabel").pack(side="left",padx=(0,12))
        self.bgm_volume_var = DoubleVar(value=15.)
        self._bgm_volume_slider = ttk.Scale(music, from_=0, to=50, variable=self.bgm_volume_var,
            orient="horizontal")
        self._bgm_volume_slider.pack(side="left",fill="x",expand=True)
        self._bgm_volume_label = ttk.Label(music,text="15%",style="Muted.TLabel",width=4)
        self._bgm_volume_label.pack(side="right",padx=(12,0))
        self.bgm_volume_var.trace_add("write", lambda *_: self._bgm_volume_label.configure(
            text=f"{self.bgm_volume_var.get():.0f}%"))

        # ── Card: Duration & Keyframes ──
        self._card_duration = self._make_card("时长与输出",
                                              row=4, column=0, padx=0,
                                              pady=(12, 12))
        self._card_duration.columnconfigure(1, weight=1)
        self._card_duration.columnconfigure(3, weight=1)

        self._duration_value_label = ttk.Label(
            self._card_duration, text="总时长: 30 秒",
            style="Card.TLabel")
        self._duration_value_label.grid(row=0, column=0, sticky="w",
                                        padx=(0, 4))
        self._duration_slider = ttk.Scale(
            self._card_duration, from_=10, to=120,
            variable=self.total_duration_var, orient="horizontal",
            command=self._on_duration_slide,
        )
        self._duration_slider.grid(row=0, column=1, columnspan=2,
                                   sticky="ew", padx=(0, 8))

        self._duration_readout = ttk.Label(
            self._card_duration, text="30s",
            style="Card.TLabel", width=6)
        self._duration_readout.grid(row=0, column=3, sticky="w")

        ttk.Label(self._card_duration, text="每页关键帧数:",
                  style="Card.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 4), pady=(6, 0))
        self._images_per_slide_spin = ttk.Spinbox(
            self._card_duration, from_=1, to=6,
            textvariable=self.images_per_slide_var, width=6,
        )
        self._images_per_slide_spin.grid(row=1, column=1, sticky="w",
                                         pady=(6, 0))

        detail = ttk.Frame(self._card_duration, style="Card.TFrame")
        detail.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(12,0))
        self.fps_var = IntVar(value=int(os.getenv("FPS", "24")))
        self.concurrent_var = IntVar(value=int(os.getenv("MAX_CONCURRENT", "1")))
        ttk.Label(detail, text="帧率", style="Card.TLabel").pack(side="left",padx=(0,8))
        ttk.Spinbox(detail,from_=1,to=60,textvariable=self.fps_var,width=4).pack(side="left")
        ttk.Label(detail,text="并发数",style="Card.TLabel").pack(side="left",padx=(20,8))
        ttk.Spinbox(detail,from_=1,to=10,textvariable=self.concurrent_var,width=4).pack(side="left")
        self.auto_compare_var = BooleanVar(value=False)
        ttk.Checkbutton(self._card_duration,text="自动对比生成效果",variable=self.auto_compare_var).grid(
            row=3,column=0,columnspan=4,sticky="w",pady=(8,0))

        # Actions stay accessible while the settings panel scrolls.
        btn_card_frame = ttk.Frame(settings_wrapper, style="Card.TFrame", padding=12)
        btn_card_frame.pack(fill="x", pady=(12,0))

        # Primary actions row
        btn_row = ttk.Frame(btn_card_frame, style="Card.TFrame")
        btn_row.pack(fill="x", pady=(0, 4))

        self._analyze_btn = ttk.Button(
            btn_row, text="分析 PPT",
            style="Small.TButton",
            command=self._analyze_pptx)
        self._analyze_btn.pack(side="left", padx=2)

        self._gen_prompts_btn = ActionButton(
            btn_row, text="规划分镜  →", theme=self._theme_id,
            command=self._generate_prompts)
        self._gen_prompts_btn.pack(side="left", padx=2, expand=True, fill="x")

        # Secondary actions row
        btn_row2 = ttk.Frame(btn_card_frame, style="Card.TFrame")
        btn_row2.pack(fill="x")

        self._confirm_btn = ActionButton(
            btn_row2, text="确认并生成视频", theme=self._theme_id,
            command=self._start_pipeline, state="disabled")
        self._confirm_btn.pack(side="left", padx=2, expand=True, fill="x")

        self._stop_btn = ttk.Button(
            btn_row2, text="停止",
            style="Danger.TButton",
            command=self._stop_pipeline, state="disabled")
        self._stop_btn.pack(side="left", padx=2)

        ttk.Button(btn_row2, text="清空日志",
                   style="Small.TButton",
                   command=self._clear_log).pack(side="left", padx=2)


        # ── Right: Notebook (Logs + Prompts tabs) ────────────────────────
        self._right_notebook = ttk.Notebook(self._main_paned, style="TNotebook")
        self._main_paned.add(self._right_notebook, weight=5)
        self._main_paned.bind("<ButtonRelease-1>", self._constrain_sash, add="+")
        self._main_paned.bind("<Configure>", self._constrain_sash, add="+")
        self._right_notebook.rowconfigure(0, weight=1)
        self._right_notebook.columnconfigure(0, weight=1)

        # ── Tab 1: Run Log ──
        log_tab = ttk.Frame(self._right_notebook, style="Card.TFrame", padding=6)
        log_tab.rowconfigure(0, weight=1)
        log_tab.columnconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(
            log_tab, state="disabled", wrap="word",
            font=("Microsoft YaHei UI", 10), bg=C_PROMPT_BG, fg=C_FG,
            insertbackground=C_ACCENT_HOVER, relief="flat", borderwidth=0,
            highlightthickness=0, highlightbackground=C_BORDER,
            highlightcolor=C_ACCENT_HOVER, padx=8, pady=8,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.tag_configure("ok", foreground=C_SUCCESS)
        self.log_text.tag_configure("err", foreground=C_ERROR)
        self.log_text.tag_configure("info", foreground=C_ACCENT_HOVER)
        self.log_text.tag_configure("warn", foreground=C_WARN)

        # ── Tab 2: Prompt Preview ──
        prompt_tab = ttk.Frame(self._right_notebook, style="Card.TFrame", padding=6)
        prompt_tab.rowconfigure(0, weight=1)
        prompt_tab.columnconfigure(0, weight=1)
        self._right_notebook.add(prompt_tab, text="分镜计划")
        script_tools = ttk.Frame(prompt_tab)
        script_tools.grid(row=1, column=0, sticky='ew')
        self._edit_script_btn = ttk.Button(script_tools, text='编辑讲稿 / 试听', command=self._open_script_editor)
        self._edit_script_btn.pack(side='left', padx=4, pady=6)
        ttk.Button(script_tools, text='打开讲稿项目', command=self._load_script_project).pack(side='left', padx=4)
        ttk.Button(script_tools, text='文字模型设置', command=self._configure_narration_model).pack(side='left', padx=4)

        self._prompt_text = scrolledtext.ScrolledText(
            prompt_tab, state="disabled", wrap="word",
            font=("Microsoft YaHei UI", 10), bg=C_PROMPT_BG, fg=C_FG,
            insertbackground=C_ACCENT_HOVER, relief="flat", borderwidth=0,
            highlightthickness=0, highlightbackground=C_BORDER,
            highlightcolor=C_ACCENT_HOVER, padx=10, pady=10,
        )
        self._prompt_text.grid(row=0, column=0, sticky="nsew")
        self._prompt_text.tag_configure("slide_header",
                                        foreground=C_ACCENT,
                                        font=("Microsoft YaHei UI", 14, "bold"), spacing1=18, spacing3=10)
        self._prompt_text.tag_configure("vision", foreground=C_WARN)
        self._prompt_text.tag_configure("image_prompt",
                                        foreground=C_SUCCESS)
        self._prompt_text.tag_configure("video_prompt",
                                        foreground=C_ACCENT_HOVER)
        self._prompt_text.tag_configure("label", foreground=C_FG_TERTIARY)
        self._prompt_text.tag_configure('facts', spacing1=6, spacing3=6, lmargin1=4, lmargin2=18)
        self._prompt_text.tag_configure('narration', spacing1=6, spacing3=16, lmargin1=4, lmargin2=4)
        self._empty_panel = ttk.Frame(prompt_tab, style="PromptText.TFrame")
        self._empty_art = FileStage(self._empty_panel, command=self._browse_input,
                                    theme=self._theme_id, reduced_motion=self.reduce_motion_var.get)
        self._empty_art.pack(fill='x', pady=(0,24))
        self._empty_title = ttk.Label(self._empty_panel, text="", style="EmptyTitle.TLabel")
        self._empty_title.pack()
        self._empty_description = ttk.Label(self._empty_panel, text="", style="Empty.TLabel",
                                            justify="center", wraplength=410)
        self._empty_description.pack(pady=(12,20))
        self._choose_file_btn = ActionButton(self._empty_panel, text="＋  选择 PPTX 文件", theme=self._theme_id,
                   command=self._browse_input, width=220, height=46, background_role='prompt')
        self._choose_file_btn.pack()
        ttk.Label(self._empty_panel, text="横竖屏适配  ·  中文配音  ·  字幕导出",
                  style="EmptyMuted.TLabel").pack(pady=(20,0))
        self._draw_empty_art()
        self._refresh_empty_state()
        self.input_var.trace_add("write", self._refresh_empty_state)
        prompt_tab.bind('<Configure>', self._resize_workspace)

        # ── Tab 3: PPT Analysis ──
        analysis_tab = ttk.Frame(self._right_notebook, style="Card.TFrame", padding=6)
        analysis_tab.rowconfigure(0, weight=1)
        analysis_tab.columnconfigure(0, weight=1)
        self._right_notebook.add(analysis_tab, text="内容分析")

        self._analysis_text = scrolledtext.ScrolledText(
            analysis_tab, state="disabled", wrap="word",
            font=("Microsoft YaHei UI", 10), bg=C_PROMPT_BG, fg=C_FG,
            insertbackground=C_ACCENT_HOVER, relief="flat", borderwidth=0,
            highlightthickness=0, highlightbackground=C_BORDER,
            highlightcolor=C_ACCENT_HOVER, padx=10, pady=10,
        )
        self._analysis_text.grid(row=0, column=0, sticky="nsew")

        # ── Tab 4: Preview ──
        preview_tab = ttk.Frame(self._right_notebook, style="Card.TFrame", padding=6)
        preview_tab.rowconfigure(1, weight=1)
        preview_tab.columnconfigure(0, weight=1)
        self._right_notebook.add(preview_tab, text="视频预览")

        # Preview header with play button
        preview_header = ttk.Frame(preview_tab, style="Card.TFrame")
        preview_header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self._preview_play_btn = ttk.Button(
            preview_header, text="▶ 播放视频", style="Accent.TButton",
            command=self._play_preview_video, state="disabled")
        self._preview_play_btn.pack(side="left", padx=4)
        self._preview_path_label = ttk.Label(
            preview_header, text="(尚无视频)", style="Muted.TLabel")
        self._preview_path_label.pack(side="left", padx=8)
        self._preview_status_label = ttk.Label(
            preview_header, text="", style="Status.TLabel")
        self._preview_status_label.pack(side="right", padx=4)

        # Preview content area (keyframe images + info)
        self._preview_content = scrolledtext.ScrolledText(
            preview_tab, state="disabled", wrap="word",
            font=("Microsoft YaHei UI", 10), bg=C_PROMPT_BG, fg=C_FG,
            insertbackground=C_ACCENT_HOVER, relief="flat", borderwidth=0,
            highlightthickness=0, highlightbackground=C_BORDER,
            highlightcolor=C_ACCENT_HOVER, padx=10, pady=10,
        )
        self._preview_content.grid(row=1, column=0, sticky="nsew")
        for text_widget in (self.log_text, self._prompt_text, self._analysis_text, self._preview_content):
            _use_themed_scrollbar(text_widget)
        self._preview_video_path: str = ""
        # ── Log tab added last ──
        self._right_notebook.add(log_tab, text="运行日志")
        # ── Progress bar (inline — replaces ProgressPopup) ──
        self._progress_frame = ttk.Frame(self.master, style="Card.TFrame")
        self._progress_frame.grid(row=3, column=0, sticky="ew", padx=20, pady=(3, 0))
        self._progress_frame.columnconfigure(0, weight=1)  # bar expands
        # Shown only while work is in progress.

        self._progress = ttk.Progressbar(
            self._progress_frame, mode="determinate",
            style="Horizontal.TProgressbar")
        self._progress.grid(row=0, column=0, sticky="ew", padx=(8, 8), pady=(8, 0))

        # Bottom row: percentage + status + stop button
        self._progress_bottom = ttk.Frame(self._progress_frame, style="Card.TFrame")
        self._progress_bottom.grid(row=1, column=0, sticky="ew", padx=(8, 8), pady=(4, 8))
        self._progress_bottom.columnconfigure(0, weight=0)
        self._progress_bottom.columnconfigure(1, weight=1)

        self._pct_label = ttk.Label(
            self._progress_bottom, text="0%",
            style="Section.TLabel", foreground=C_ACCENT_HOVER)
        self._pct_label.grid(row=0, column=0, sticky="w", padx=(0, 8))

        self._progress_status = ttk.Label(
            self._progress_bottom, text="",
            style="Muted.TLabel", anchor="w")
        self._progress_status.grid(row=0, column=1, sticky="ew", padx=(0, 8))

        self._stop_inline_btn = ttk.Button(
            self._progress_bottom, text="停止",
            style="Danger.TButton",
            command=self._stop_pipeline, state="disabled")
        self._stop_inline_btn.grid(row=0, column=2, sticky="e")

        # Progress bar tag colors (standalone, not part of progress_frame)
        self._progress_grid = ttk.Progressbar(self.master, mode="determinate")
        self._progress_grid.grid_remove()  # legacy hidden, kept for compat

        # ── Status bar ──
        self._status_bar = ttk.Label(
            self.master, text="就绪 · 选择 PPTX 文件，开始创作",
            style="Status.TLabel", anchor="w")
        self._status_bar.grid(row=4, column=0, sticky="ew",
                              padx=20, pady=(4, 12))

    # ── Helpers ─────────────────────────────────────────────────────────

    def _on_reduce_motion(self) -> None:
        pending = [self.master]
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            if hasattr(widget, 'redraw'):
                widget.redraw()

    def _resize_workspace(self, event) -> None:
        self._empty_art.configure(height=max(120, min(236, event.height - 270)))
        self._empty_description.configure(wraplength=max(260, int(event.width * .87) - 24))

    def _visual_mode(self) -> str:
        return "faithful" if self.visual_mode_var.get() == "忠实讲解" else "creative"

    def _apply_visual_mode(self) -> None:
        faithful = self._visual_mode() == "faithful"
        self._visual_mode_hint.configure(text=(
            "直接播放原 PPT 页面，保持原排版；讲稿可编辑。需本机页面渲染器，不调用图像/视频生成服务。"
            if faithful else "通过 AI 生成创意画面；人物、物体和场景可能超出 PPT 原文。"))
        api_card = self._card_api.master
        if faithful:
            api_card.grid_remove()
            self._card_set.master.grid()
        else:
            api_card.grid()
            self._card_set.master.grid()
        for widget in (self._image_provider_combo, self._image_model_combo,
                       self._video_provider_combo, self._video_model_combo,
                       self._style_combo, self._use_case_combo):
            widget.configure(state="disabled" if faithful else "readonly")
        self._images_per_slide_spin.configure(state="disabled" if faithful else "normal")
        self._refresh_scrollregion()

    def _on_visual_mode_change(self, _event=None) -> None:
        self._scene_plans = []
        self._narration_project = None
        self._parsed_slides = []
        self._confirm_btn.configure(state="disabled")
        self._display_plans()
        self._apply_visual_mode()

    def _script_settings(self):
        return dict(presentation_style=next((k for k, v in self._presentation_labels.items()
            if v == self.presentation_style_var.get()), 'auto'),
            length={'精简': 'concise', '标准': 'standard', '详细': 'detailed'}[self.script_length_var.get()],
            notes_policy={'不用备注': 'ignore', '参考备注': 'reference', '优先讲稿备注': 'prefer'}[self.notes_policy_var.get()],
            visual_mode=self._visual_mode(), include_hidden=self.include_hidden_var.get(),
            voice=self.voice_var.get(), rate=self.rate_var.get(), language=self.lang_var.get())

    def _script_changed(self, project=None):
        if project is not None and project is not self._narration_project:
            return
        if self._narration_project and self._scene_plans:
            self._narration_project.apply_to_plans(self._scene_plans)
            self._display_plans()

    def _open_script_editor(self):
        if self._running:
            return
        if not self._narration_project:
            messagebox.showinfo('讲稿编辑', '请先规划分镜，或打开已保存的讲稿项目。')
            return
        if self._narration_editor is not None and self._narration_editor.winfo_exists():
            if self._narration_editor.project is self._narration_project:
                self._narration_editor.lift()
                return
            self._narration_editor.close()
        from narration_editor import NarrationEditor
        from narration_engine import rewrite_narration
        settings = self._script_settings()
        project = self._narration_project
        project.settings.update(settings)
        slides = {s.index: s for s in self._parsed_slides}
        def rewrite(index, instruction, selections):
            if instruction == '按内容选择重建':
                from narration_engine import generate_narrations
                return generate_narrations([slides[index]], presentation_style=settings['presentation_style'],
                    length=settings['length'], notes_policy=settings['notes_policy'],
                    creative=settings['visual_mode'] == 'creative', selections=selections)[index]
            return rewrite_narration(slides[index], instruction=instruction,
                current_text=project.segments[index].text,
                presentation_style=settings['presentation_style'], length=settings['length'],
                notes_policy=settings['notes_policy'], creative=settings['visual_mode'] == 'creative',
                selections=selections)
        self._narration_editor = NarrationEditor(self.master, project,
            on_change=self._script_changed, rewrite=rewrite)

    def _load_script_project(self):
        if self._running:
            return
        path = filedialog.askopenfilename(filetypes=[('讲稿项目', '*.json')])
        if not path:
            return
        try:
            from narration_project import NarrationProject
            from pptx_parser import parse_pptx
            from faithful_plan import build_faithful_plans
            from prompt_engine import EnhancedScenePlan
            project = NarrationProject.load(path)
            project.validate_source(project.source_path)
            slides = parse_pptx(project.source_path, include_hidden=project.settings.get('include_hidden', False))
            mode = project.settings.get('visual_mode', 'faithful')
            plans = project.build_plans(slides)
            self.input_var.set(project.source_path)
            self.visual_mode_var.set('忠实讲解' if mode == 'faithful' else 'AI 创意演绎')
            self.presentation_style_var.set(self._presentation_labels.get(project.settings.get('presentation_style', 'auto'), self._presentation_labels['auto']))
            self.script_length_var.set({'concise':'精简','standard':'标准','detailed':'详细'}.get(project.settings.get('length'), '标准'))
            self.notes_policy_var.set({'ignore':'不用备注','reference':'参考备注','prefer':'优先讲稿备注'}.get(project.settings.get('notes_policy'), '参考备注'))
            self.include_hidden_var.set(project.settings.get('include_hidden', False))
            self.voice_var.set(project.settings.get('voice', 'zh-CN-XiaoxiaoNeural'))
            self.rate_var.set(project.settings.get('rate', '+0%'))
            self._narration_project, self._parsed_slides, self._scene_plans = project, slides, plans
            self._apply_visual_mode()
            self._display_plans()
            self._confirm_btn.configure(state='normal')
            self._open_script_editor()
        except Exception as exc:
            messagebox.showerror('无法打开项目', str(exc))

    def _configure_narration_model(self):
        if self._running:
            return
        win = Toplevel(self.master)
        win.title('讲稿文字模型（兼容 OpenAI 接口）')
        fields = {}
        for row, (key, label) in enumerate([('NARRATION_API_BASE', '接口地址'), ('NARRATION_MODEL', '模型名称'), ('NARRATION_API_KEY', 'API Key')]):
            ttk.Label(win, text=label).grid(row=row, column=0, padx=12, pady=8)
            value = StringVar(value=os.getenv(key, ''))
            ttk.Entry(win, textvariable=value, width=52, show='*' if key.endswith('KEY') else '').grid(row=row, column=1, padx=12)
            fields[key] = value
        ttk.Label(win, text='留空使用基础规则筛选。设置只用于本次运行，不写入讲稿项目。').grid(row=3, column=0, columnspan=2, padx=12, pady=8)
        def apply():
            for key, value in fields.items():
                os.environ[key] = value.get().strip()
            win.destroy()
        ttk.Button(win, text='应用', command=apply).grid(row=4, column=1, pady=12)

    def _make_card(self, label: str, **grid_kw) -> ttk.Frame:
        """Create a card with header, grid into _content_area. Returns content frame."""
        f = RoundedSurface(self._content_area, theme=self._theme_id)
        f.grid(sticky="nsew", **grid_kw)
        # Section title and consistent card padding
        header = ttk.Frame(f, style="Card.TFrame")
        header.pack(fill="x", anchor="w", padx=18, pady=(18, 12))
        lbl = ttk.Label(header, text=label, style="Section.TLabel", font=("Microsoft YaHei UI", 11, "bold"))
        lbl.pack(side="left")
        content = ttk.Frame(f, style="Card.TFrame")
        content.pack(fill="x", padx=18, pady=(0,18))
        return content

    # ── API Key ──

    def _get_key_source_text(self) -> str:
        sources = []
        # Check all provider keys
        key_checks = [
            ("AGNES_API_KEY", "Agnes AI (免费)"),
            ("SILICONFLOW_API_KEY", "SiliconFlow"),
            ("KLING_API_KEY", "可灵AI"),
            ("VOLC_API_KEY", "火山引擎"),
            ("OPENAI_API_KEY", "OpenAI"),
            ("GEMINI_API_KEY", "Gemini"),
        ]
        for env_var, display in key_checks:
            if os.getenv(env_var, "").strip():
                sources.append(f"✓ {display} 已配置")
        if sources:
            return " | ".join(sources)
        return "⚠ 未检测到 API Key — 请填写或设置环境变量"

    def _load_api_key(self) -> None:
        """Legacy no-op — keys loaded dynamically by _build_api_key_fields()."""
        pass

    def _toggle_key_visible(self) -> None:
        """Legacy no-op — use per-provider toggle instead."""
        pass

    def _toggle_key_visible_provider(self, provider_name: str) -> None:
        """Toggle show/hide for a specific provider's API key entry."""
        entry = self._api_key_widgets.get(provider_name)
        if not entry:
            return
        btn = None
        for child in self._api_key_frame.winfo_children():
            if isinstance(child, ttk.Button) and child.grid_info().get("row") == 2 * list(
                self._api_key_widgets.keys()
            ).index(provider_name) + 1:
                btn = child
                break
        if entry.cget("show") == "*":
            entry.configure(show="")
            if btn:
                btn.configure(text="隐藏")
        else:
            entry.configure(show="*")
            if btn:
                btn.configure(text="显示")

    def _build_api_key_fields(self) -> None:
        """Build dynamic API key entry fields for each unique provider."""
        for w in self._api_key_frame.winfo_children():
            w.destroy()
        self._api_key_widgets.clear()

        providers = set()
        default_prov = os.getenv("PROVIDER", "siliconflow")
        img = getattr(self, 'image_provider_var', None)
        vid = getattr(self, 'video_provider_var', None)
        img_val = img.get() if img is not None else os.getenv("IMAGE_PROVIDER", default_prov)
        vid_val = vid.get() if vid is not None else os.getenv("VIDEO_PROVIDER", default_prov)
        providers.add(img_val)
        providers.add(vid_val)

        env_map = {
            "siliconflow": "SILICONFLOW_API_KEY",
            "agnes": "AGNES_API_KEY",
            "kling": "KLING_API_KEY",
            "volcengine": "VOLC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "gemini": "GEMINI_API_KEY",
        }

        for i, prov in enumerate(sorted(providers)):
            display_name = _PROVIDER_NAMES.get(prov, prov)

            ttk.Label(self._api_key_frame, text=f"{display_name} · API Key",
                      style="Card.TLabel").grid(
                row=2*i, column=0, columnspan=3, sticky="w", pady=(4, 7))

            if prov not in self._api_key_vars:
                self._api_key_vars[prov] = StringVar()
            var = self._api_key_vars[prov]

            # Load from env if available
            env_var = env_map.get(prov)
            env_key = os.getenv(env_var, "").strip() if env_var else ""
            if env_key:
                var.set(env_key)

            entry = ttk.Entry(self._api_key_frame, textvariable=var, show="*", width=1)
            entry.grid(row=2*i+1, column=0, columnspan=2, sticky="ew", padx=(0, 8), pady=(0, 8))
            self._api_key_widgets[prov] = entry

            btn = ttk.Button(
                self._api_key_frame, text="显示", style="Small.TButton",
                command=lambda p=prov: self._toggle_key_visible_provider(p),
            )
            btn.grid(row=2*i+1, column=2, pady=(0, 8))

    def _get_api_key(self, provider_name: str) -> str:
        """Get the API key for a given provider, checking GUI first then env."""
        if provider_name in self._api_key_vars:
            key = self._api_key_vars[provider_name].get().strip()
            if key:
                return key
        # Fall back to env
        env_map = {
            "siliconflow": "SILICONFLOW_API_KEY",
            "agnes": "AGNES_API_KEY",
            "kling": "KLING_API_KEY",
            "volcengine": "VOLC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "gemini": "GEMINI_API_KEY",
        }
        env_var = env_map.get(provider_name)
        if env_var:
            return os.getenv(env_var, "").strip()
        return ""

    def _save_api_key_to_config(self, key: str, provider: str = "siliconflow") -> None:
        cfg_path = Path.home() / ".ppt2video_config.json"
        try:
            data = {}
            if cfg_path.exists():
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
            data[f"{provider}_api_key"] = key
            cfg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            self._api_status.set("✓ API Key 已保存")
        except Exception as exc:
            self._log(f"⚠ 保存 API Key 失败: {exc}", "warn")

    # ── File Browsing ──

    def _browse_input(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 PPTX 文件",
            filetypes=[("PowerPoint 演示文稿", "*.pptx"), ("所有文件", "*.*")],
        )
        if path:
            self.input_var.set(path)
            inp = Path(path)
            if not self.output_var.get():
                self.output_var.set(str(inp.parent / (inp.stem + "_视频.mp4")))

    def _browse_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="保存视频为",
            defaultextension=".mp4",
            filetypes=[("MP4 视频", "*.mp4")],
        )
        if path:
            self.output_var.set(path)

    # ── Provider/Style handling ──

    def _on_image_provider_change(self, event=None) -> None:
        display = self._image_provider_combo.get()
        new_key = display  # default: use raw text (for custom input)
        for key, val in _PROVIDER_NAMES.items():
            if val == display:
                new_key = key
                break
        if self.image_provider_var.get() == new_key:
            return  # no change, skip expensive rebuild
        self.image_provider_var.set(new_key)
        self._update_models_for_provider()

        # Rebuild API key fields for the new provider set
        self._build_api_key_fields()

        # Show/hide API key relevance
        prov = self.image_provider_var.get()
        self._update_api_status()

    def _on_video_provider_change(self, event=None) -> None:
        display = self._video_provider_combo.get()
        new_key = display  # default: use raw text (for custom input)
        for key, val in _PROVIDER_NAMES.items():
            if val == display:
                new_key = key
                break
        if self.video_provider_var.get() == new_key:
            return  # no change, skip expensive rebuild
        self.video_provider_var.set(new_key)
        self._update_models_for_provider()

        # Rebuild API key fields for the new provider set
        self._build_api_key_fields()

        self._update_api_status()

    def _update_api_status(self) -> None:
        """Show relevant API key info based on selected providers."""
        img = self.image_provider_var.get()
        vid = self.video_provider_var.get()
        providers = set([img, vid])
        statuses = []
        for p in providers:
            if p == "comfyui":
                statuses.append(f"ComfyUI 无需 API Key（本地运行）")
            elif p == "custom_api":
                statuses.append(f"自定义API — 密钥在 CUSTOM_API_KEY")
            elif p == "kling":
                statuses.append(f"可灵AI — 输入 Key 或设 KLING_API_KEY")
            elif p == "volcengine":
                statuses.append(f"火山引擎 — 输入 Key 或设 VOLC_API_KEY")
            elif p == "openai":
                statuses.append(f"OpenAI — 输入 Key 或设 OPENAI_API_KEY")
            elif p == "gemini":
                statuses.append(f"Gemini — 输入 Key 或设 GEMINI_API_KEY")
            elif p == "agnes":
                statuses.append(f"Agnes AI — 免费Key或设 AGNES_API_KEY")
            else:
                statuses.append(self._get_key_source_text())
        self._api_status.set(" | ".join(statuses))

    def _on_style_change(self, event=None) -> None:
        display = self._style_combo.get()
        for key, val in _STYLE_NAMES.items():
            label = f"{key} ({val})"
            if label == display or val == display:
                self.style_var.set(key)
                break

    def _on_use_case_change(self, event=None) -> None:
        """Handle use case selection — update hints and style suggestions."""
        display = self._use_case_combo.get()
        for key, val in _USE_CASES.items():
            if val == display:
                self.use_case_var.set(key)
                break
        use_case_key = self.use_case_var.get()
        defaults = _get_use_case_data(use_case_key)
        structure = defaults.get("structure", [])
        style_hint = defaults.get("style_hint", "")
        if structure:
            hint = f"剧本结构: {' → '.join(structure)}"
            if style_hint:
                hint += f" | 推荐风格: {_STYLE_NAMES.get(style_hint, style_hint)}"
            self._use_case_hint.configure(text=hint)
        else:
            self._use_case_hint.configure(text="")

    def _on_duration_slide(self, event=None) -> None:
        """Update the duration label when slider moves."""
        val = int(self.total_duration_var.get())
        self._duration_value_label.configure(text=f"总时长: {val} 秒")
        self._duration_readout.configure(text=f"{val}s")

    def _update_models_for_provider(self) -> None:
        """Update image and video model dropdowns based on selected providers."""
        img_prov = self.image_provider_var.get()
        vid_prov = self.video_provider_var.get()

        # Image models
        img_models, _ = _PROVIDER_MODELS.get(img_prov, ([], []))
        self._image_model_combo.configure(values=img_models)
        if img_models:
            default_img = os.getenv(f"{img_prov.upper()}_IMAGE_MODEL", img_models[0])
            self.image_model_var.set(default_img if default_img in img_models else img_models[0])

        # Video models
        _, vid_models = _PROVIDER_MODELS.get(vid_prov, ([], []))
        self._video_model_combo.configure(values=vid_models)
        if vid_models:
            default_vid = os.getenv(f"{vid_prov.upper()}_VIDEO_MODEL", vid_models[0])
            self.video_model_var.set(default_vid if default_vid in vid_models else vid_models[0])

    # ── UI state ──

    def _update_steps(self) -> None:
        """Derive progress from the same file/plan/output state used by the workflow."""
        if not hasattr(self, '_workflow_steps'):
            return
        status = self._status_bar.cget('text') if hasattr(self, '_status_bar') else ''
        complete = bool(self._scene_plans and getattr(self, '_preview_video_path', '')) and not self._running and '完成' in status
        current = 0
        if getattr(self, 'input_var', None) and self.input_var.get():
            current = 1
        if self._scene_plans:
            current = 3 if self._running else 2
        self._workflow_steps.set_step(current, complete)

    def _set_busy(self, busy: bool, generating: bool = False) -> None:
        state = "disabled" if busy else "normal"
        self._entry_input.configure(state=state)
        self._entry_output.configure(state=state)
        self._browse_input_btn.configure(state=state)
        self._browse_output_btn.configure(state=state)
        for entry in self._api_key_widgets.values():
            entry.configure(state=state)
        self._image_provider_combo.configure(state="disabled" if busy else "readonly")
        self._video_provider_combo.configure(state="disabled" if busy else "readonly")
        self._style_combo.configure(state="disabled" if busy else "readonly")
        self._lang_combo.configure(state="disabled" if busy else "readonly")
        self._use_case_combo.configure(state="disabled" if busy else "readonly")
        self._image_model_combo.configure(state="disabled" if busy else "readonly")
        self._video_model_combo.configure(state="disabled" if busy else "readonly")
        self._ratio_combo.configure(state="disabled" if busy else "readonly")
        self._visual_mode_combo.configure(state="disabled" if busy else "readonly")
        self._narration_check.configure(state=state)
        self._subtitle_check.configure(state=state)
        self._audio_check.configure(state=state)
        self._empty_art.configure(state=state)
        self._choose_file_btn.configure(state=state)
        self._bgm_check.configure(state=state)
        self._bgm_volume_slider.configure(state=state)

        # New widgets
        self._duration_slider.configure(state=state)
        self._images_per_slide_spin.configure(state=state)

        if busy:
            self._analyze_btn.configure(state="disabled")
            self._gen_prompts_btn.configure(state="disabled")
            self._confirm_btn.configure(state="disabled")
            self._stop_btn.configure(state="normal")
            self._stop_inline_btn.configure(state="normal")
        else:
            self._analyze_btn.configure(state="normal")
            self._gen_prompts_btn.configure(state="normal")
            self._confirm_btn.configure(state="normal" if self._scene_plans else "disabled")
            self._stop_btn.configure(state="disabled")
            self._stop_inline_btn.configure(state="disabled")
            self._apply_visual_mode()
        self._update_steps()

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _log(self, msg: str, tag: str | None = None) -> None:
        def _do():
            self.log_text.configure(state="normal")
            if tag:
                self.log_text.insert("end", msg + "\n", tag)
            else:
                self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.log_text.after(0, _do)

    def _set_status(self, text: str) -> None:
        def update():
            self._status_bar.configure(text=text)
            self._update_steps()
        self.master.after(0, update)

    def _show_progress(self, show: bool, maximum: int = 100) -> None:
        if show:
            self._progress.configure(maximum=maximum, value=0)
            self._pct_label.configure(text="0%")
            self._progress_frame.grid()
        else:
            # Progress bar always visible — just hide the frame
            self._progress_frame.grid_remove()

    def _update_progress(self, value: int, message: str = "") -> None:
        """Update determinate progress bar, percentage label, and status."""
        self._progress.configure(value=value)
        self._pct_label.configure(text=f"{value}%")
        if message:
            self._progress_status.configure(text=message)

    def _display_plans(self) -> None:
        """Render scene plans into the prompt preview text widget."""
        self._refresh_empty_state()
        self._prompt_text.configure(state="normal")
        self._prompt_text.delete("1.0", "end")

        if not self._scene_plans:
            self._prompt_text.insert("end", "暂无提示词 — 请先点击「规划分镜」\n")
            self._prompt_text.configure(state="disabled")
            return

        for i, plan in enumerate(self._scene_plans):
            if getattr(plan, "visual_mode", "creative") == "faithful":
                slide = next(s for s in self._parsed_slides if s.index == plan.slide_index)
                self._prompt_text.insert("end", f"\n第 {plan.slide_index} 页 · {slide.title}\n", "slide_header")
                self._prompt_text.insert("end", f"忠实讲解 · 计划 {plan.suggested_duration_sec:.1f} 秒\n", "label")
                self._prompt_text.insert("end", "\n".join(f"• {fact}" for fact in plan.source_facts) + "\n", 'facts')
                self._prompt_text.insert("end", "讲解词\n", "label")
                self._prompt_text.insert("end", plan.narration_text + "\n", 'narration')
                continue
            self._prompt_text.insert("end", f"\n台词 / 旁白\n{getattr(plan, 'narration_text', '') or '（本场景无旁白）'}\n", "narration")
            # Determine slide coverage
            slide_indices = getattr(plan, 'slide_indices', None) or getattr(plan, 'slide_range', None)
            if slide_indices is not None:
                # Use explicit coverage
                if isinstance(slide_indices, (list, tuple)):
                    if len(slide_indices) == 1:
                        coverage = f"涵盖页 {slide_indices[0]}"
                    else:
                        coverage = f"涵盖页 {slide_indices[0]}-{slide_indices[-1]}"
                else:
                    coverage = f"涵盖页 {slide_indices}"
            else:
                slide_idx = getattr(plan, 'slide_index', i + 1)
                # Try to determine range by looking at next plan's index
                next_idx = None
                if i + 1 < len(self._scene_plans):
                    next_idx = getattr(self._scene_plans[i + 1], 'slide_index', None)
                if next_idx is not None and next_idx > slide_idx + 1:
                    coverage = f"涵盖页 {slide_idx}-{next_idx - 1}"
                else:
                    coverage = f"涵盖页 {slide_idx}"

            # Arrow connector between scenes
            if i > 0:
                self._prompt_text.insert(
                    "end",
                    f"\n   ⬇ 下一场景\n",
                    "label",
                )

            # Slide header with coverage
            self._prompt_text.insert(
                "end",
                f"\n{'─' * 50}\n"
                f"  📍 场景 {i+1} — {coverage}\n"
                f"  Slide {plan.slide_index}\n"
                f"{'─' * 50}\n",
                "slide_header",
            )

            # Director's vision
            self._prompt_text.insert("end", "🎬 导演构想:\n", "label")
            self._prompt_text.insert("end", f"{plan.director_vision}\n\n", "vision")

            # Image prompt
            self._prompt_text.insert("end", "📷 图片提示词:\n", "label")
            self._prompt_text.insert("end", f"{plan.image_prompt}\n\n", "image_prompt")

            # Video prompt
            self._prompt_text.insert("end", "🎥 视频提示词:\n", "label")
            self._prompt_text.insert("end", f"{plan.video_prompt}\n", "video_prompt")

        self._prompt_text.insert("end", f"\n{'═' * 50}\n")
        self._prompt_text.insert("end", "✅ 提示词已就绪，点击「确认 & 生成视频」开始生成\n")

        self._prompt_text.configure(state="disabled")

    # ── Step 0: Analyze PPTX ──

    def _analyze_pptx(self) -> None:
        """Parse and analyze the PPTX, showing a summary."""
        input_path = self.input_var.get().strip()
        if not input_path or not Path(input_path).exists():
            messagebox.showerror("错误", "请先选择有效的 PPTX 文件")
            return

        self._set_busy(True)
        self._clear_log()
        self._log("📊 正在分析 PPT 内容...", "info")

        def _do():
            try:
                from pptx_parser import parse_pptx
                from ppt_summarizer import analyze_slides, format_summary

                slides = parse_pptx(Path(input_path))
                if not slides:
                    self._log("❌ 无法解析 PPT 内容", "err")
                    return

                self._log(f"✅ 共解析 {len(slides)} 页幻灯片", "info")
                summary = analyze_slides(slides)
                formatted = format_summary(summary)

                # Display in analysis tab instead of popup
                self._analysis_text.configure(state="normal")
                self._analysis_text.delete("1.0", "end")
                self._analysis_text.insert("1.0", formatted)
                self._analysis_text.configure(state="disabled")

                # Switch to analysis tab
                self._right_notebook.select(2)

                self._log("📊 分析完成，请在「分析」标签页中查看", "info")
            except Exception as e:
                self._log(f"❌ 分析失败: {e}", "err")
                import traceback
                self._log(traceback.format_exc(), "err")
            finally:
                self._set_busy(False)

        import threading
        thread = threading.Thread(target=_do, daemon=True)
        thread.start()

    # ── Step 1: Generate Prompts ──

    def _generate_prompts(self) -> None:
        """Parse PPTX and run Director to generate scene plans."""
        input_path = self.input_var.get().strip()
        if not input_path or not Path(input_path).exists():
            messagebox.showerror("错误", "请选择有效的 PPTX 文件")
            return

        # Save API keys if provided
        image_prov = self.image_provider_var.get()
        video_prov = self.video_provider_var.get()
        for prov in (set([image_prov, video_prov]) if self._visual_mode() == "creative" else []):
            key = self._get_api_key(prov)
            if key:
                import config as cfg
                cfg.set_api_key(key)
                self._save_api_key_to_config(key, provider=prov)

        self._clear_log()
        self._log("═" * 60, "info")
        self._log(f"  🎬 导演模式 — 规划分镜", "info")
        self._log(f"  文件: {Path(input_path).name}", "info")
        self._log("═" * 60, "info")

        previous_project = self._narration_project
        self._scene_plans = []
        self._narration_project = None
        self._parsed_slides = []

        self._set_busy(True, generating=False)
        self._show_progress(True)
        self._set_status("正在解析PPTX并规划分镜…")

        style_key = self.style_var.get()
        # Snapshot Tk variables on the main thread before starting the worker.
        prompt_options = dict(
            script_settings=self._script_settings(),
            previous_project=previous_project,
            visual_mode=self._visual_mode(),
            ratio=self.ratio_var.get(),
            narration_style="explain" if self.narration_explain_var.get() else "direct",
            images_per_slide=self.images_per_slide_var.get(),
            language=self.lang_var.get(),
            use_case=self.use_case_var.get(),
            total_duration=float(self.total_duration_var.get()),
        )

        thread = threading.Thread(
            target=self._run_prompt_gen,
            args=(input_path, style_key),
            kwargs=prompt_options,
            daemon=True,
        )
        thread.start()

    def _run_prompt_gen(
        self, input_path: str, style_key: str, *, ratio: str = "16:9",
        narration_style: str = "direct", images_per_slide: int = 4,
        language: str = "zh-CN", use_case: str = "auto", total_duration: float = 30.0,
        visual_mode: str = "faithful",
        script_settings: dict | None = None,
        previous_project=None,
    ) -> None:
        """Parse PPTX + generate prompts (runs in background thread)."""
        try:
            import config as cfg
            if ratio != "original":
                cfg.set_ratio(ratio)
            from pptx_parser import parse_pptx

            # Parse
            self._log("📄 解析 PPTX...", "info")
            slides = parse_pptx(input_path, include_hidden=(script_settings or {}).get("include_hidden", False))
            from narration_workflow import source_ratio
            source_ratio(slides, ratio)
            self._parsed_slides = slides
            self._log(f"✅ 解析完成: {len(slides)} 张幻灯片", "ok")

            # If user provided an overall theme
            overall_theme = os.getenv("OVERALL_THEME", "")

            # Generate prompts via generate_scene_plans (with ScriptWriter)
            self._log("🎬 导演正在构思场景...", "info")
            from narration_engine import generate_narrations
            settings = script_settings or {}
            records = generate_narrations(slides, presentation_style=settings.get('presentation_style', 'auto'),
                length=settings.get('length', 'standard'), notes_policy=settings.get('notes_policy', 'reference'),
                creative=visual_mode == 'creative')
            if previous_project is not None:
                try:
                    previous_project.validate_source(input_path)
                except (ValueError, OSError):
                    pass
                else:
                    for index, segment in previous_project.segments.items():
                        if index in records and (segment.modified or segment.locked):
                            records[index]['text'] = '' if segment.muted else segment.text
                            records[index]['units'] = segment.units
            from prompt_engine import generate_scene_plans
            plans = generate_scene_plans(
                slides, style=style_key, overall_theme=overall_theme,
                images_per_slide=images_per_slide,
                language=language, use_script_writer=True,
                use_case=use_case, total_duration=total_duration,
                narration_style=narration_style,
                visual_mode=visual_mode,
                narration_records=records,
            )
            self._scene_plans = plans
            from narration_workflow import prepare_scripts
            self._narration_project = prepare_scripts(input_path, slides, plans, settings=script_settings, records=records)
            if previous_project is not None:
                try:
                    previous_project.validate_source(input_path)
                except (ValueError, OSError):
                    self._log('PPT 已变化，新计划未复用旧稿；已保存项目仍可打开核对。', 'info')
                else:
                    from copy import deepcopy
                    for index, segment in previous_project.segments.items():
                        if index in self._narration_project.segments and (segment.modified or segment.locked):
                            self._narration_project.segments[index] = deepcopy(segment)
                    self._narration_project.apply_to_plans(plans)
            self._narration_project.save(cfg.ensure_temp_dir() / 'latest-narration-project.json')
            for segment in self._narration_project.segments.values():
                for warning in segment.warnings:
                    self._log(f'第 {segment.slide_index} 页：{warning}', 'info')

            # Display in GUI
            self.master.after(0, self._display_plans)
            self._log(f"✅ 提示词生成完成: {len(plans)} 个场景", "ok")
            self._set_status(f"✅ 提示词就绪 — 点击「确认 & 生成视频」继续")

        except Exception as exc:
            self._log(f"❌ 生成失败: {exc}", "err")
            self._set_status(f"❌ 错误: {exc}")
            import traceback
            self._log(traceback.format_exc(), "err")
        finally:
            self._show_progress(False)
            self.master.after(0, lambda: self._set_busy(False))

    # ── Step 2: Confirm & Generate ──

    def _start_pipeline(self) -> None:
        """Begin video generation using confirmed prompts."""
        import threading as _threading
        if self._running:
            return
        if not self._scene_plans:
            messagebox.showwarning("提示", "请先点击「规划分镜」生成导演提示词")
            return
        if self._narration_editor is not None and self._narration_editor.winfo_exists():
            self._narration_editor.close()

        input_path = self.input_var.get().strip()
        output_path = self.output_var.get().strip()

        if not input_path:
            messagebox.showerror("错误", "请选择要转换的 PPTX 文件")
            return
        if not output_path:
            messagebox.showerror("错误", "请指定输出视频的保存路径")
            return

        if self._narration_project:
            try:
                self._narration_project.settings.update(self._script_settings())
                self._narration_project.validate_source(input_path)
                self._narration_project.apply_to_plans(self._scene_plans)
            except Exception as exc:
                messagebox.showerror('PPT 来源已变化', f'{exc}\n请重新规划，原讲稿仍保留在保存的项目中。')
                return

        # Get selected providers
        if self.audio_var.get():
            from video_composer import build_scene_timeline
            missing = [s['index'] for s in build_scene_timeline(self._parsed_slides, self._scene_plans)
                       if not s['text'].strip() and not s['muted']]
            if missing:
                messagebox.showerror('讲稿未完成', f'第 {missing} 页讲稿为空，请补充或在编辑器中明确选择静音。')
                return
        image_provider_name = self.image_provider_var.get()
        video_provider_name = self.video_provider_var.get()
        visual_mode = self._visual_mode()
        active_providers = set([image_provider_name, video_provider_name]) if visual_mode == "creative" else set()

        # Check required API keys for both providers
        provider_requires_key = {
            "siliconflow": ("SILICONFLOW_API_KEY", "SiliconFlow"),
            "agnes": ("AGNES_API_KEY", "Agnes AI"),
            "kling": ("KLING_API_KEY", "可灵AI Kling"),
            "volcengine": ("VOLC_API_KEY", "火山引擎"),
            "openai": ("OPENAI_API_KEY", "OpenAI"),
            "gemini": ("GEMINI_API_KEY", "Gemini"),
        }
        for pname in active_providers:
            if pname in provider_requires_key:
                env_var, display_name = provider_requires_key[pname]
                key_for_this = self._get_api_key(pname)
                if not key_for_this:
                    key_for_this = os.getenv(env_var, "").strip()
                if pname == "agnes":
                    continue  # Agnes has free tier, skip key check
                if not key_for_this:
                    ret = messagebox.askyesno(
                        f"{display_name} API Key 未设置",
                        f"{display_name} 需要 API Key。\\n是否现在输入？",
                    )
                    if ret:
                        return

        # Save API keys
        if self.audio_var.get() and self._narration_project:
            from faithful_plan import _reading_seconds
            estimated = sum(max(5., _reading_seconds(s.text) + 1.5) if not s.muted else 5.
                            for s in self._narration_project.segments.values())
            if estimated > float(self.total_duration_var.get()) + 1:
                if not messagebox.askokcancel('讲稿时长超出目标',
                    f'当前讲稿预计至少 {estimated:.0f} 秒，超过目标 {self.total_duration_var.get()} 秒。\n'
                    '继续将按完整配音延长视频；取消后可在讲稿编辑中缩短内容。'):
                    return
        for pname in active_providers:
            key = self._get_api_key(pname)
            if key:
                import config as cfg
                cfg.set_api_key(key)

        self._stop_flag = False
        self._stop_event = threading.Event()
        self._running = True
        self._set_busy(True, generating=True)
        self._show_progress(True)  # show inline progress bar instead of popup

        self._clear_log()

        self._log("═" * 60, "info")
        self._log(f"  ▶ 确认生成 — 开始制作视频", "info")
        img_name = _PROVIDER_NAMES.get(image_provider_name, image_provider_name)
        vid_name = _PROVIDER_NAMES.get(video_provider_name, video_provider_name)
        self._log(f"  图片引擎: {img_name}", "info")
        self._log(f"  视频引擎: {vid_name}", "info")
        style_key = self.style_var.get()
        self._log(f"  风格: {_STYLE_NAMES.get(style_key, style_key)}", "info")
        self._log(f"  文件: {Path(input_path).name}", "info")
        self._log("═" * 60, "info")
        self._set_status("正在生成视频…")

        pipe_kwargs = dict(
            visual_mode=visual_mode,
            input_path=Path(input_path),
            output_path=Path(output_path),
            fps=self.fps_var.get(),
            add_subtitles=self.subtitle_var.get(),
            add_audio=self.audio_var.get(),
            ratio=self.ratio_var.get(),
            narration_style="explain" if self.narration_explain_var.get() else "direct",
            add_bgm=self.bgm_var.get(),
            bgm_volume=max(0.0, min(50.0, self.bgm_volume_var.get())) / 100.0,
            max_concurrent=self.concurrent_var.get(),
            dry_run=False,
            image_provider_name=image_provider_name,
            video_provider_name=video_provider_name,
            auto_compare=self.auto_compare_var.get(),
            image_model=self.image_model_var.get(),
            video_model=self.video_model_var.get(),
            total_duration=self.total_duration_var.get(),
            images_per_slide=self.images_per_slide_var.get(),
            language=self.lang_var.get(),
            stop_event=self._stop_event,
            api_keys={
                name: self._get_api_key(name)
                for name in {image_provider_name, video_provider_name, "agnes"}
            },
        )

        thread = threading.Thread(
            target=self._run_pipeline_with_plans,
            kwargs=pipe_kwargs,
            daemon=True,
        )
        thread.start()

    def _stop_pipeline(self) -> None:
        self._stop_flag = True
        if self._stop_event:
            self._stop_event.set()  # signal async operations to stop
        self._running = False
        self._log("⏹ 用户手动停止", "warn")
        self._set_status("正在停止...")
        self.master.after(0, lambda: self._update_progress(
            self._progress["value"], "正在停止..."))

    def _run_regeneration_with_feedback(self) -> None:
        """Re-run prompt generation incorporating user feedback."""
        feedback = self._regeneration_feedback
        self._regeneration_feedback = None
        if not feedback:
            self._log("⚠ 没有收集到反馈", "warn")
            return
        fb_count = sum(1 for v in feedback.values() if v.strip())
        self._log(f"🔄 使用 {fb_count} 条反馈重新规划分镜...", "info")
        # Store feedback on scene plans for reference during regeneration
        if self._scene_plans:
            for plan in self._scene_plans:
                idx = getattr(plan, 'slide_index', 0) - 1
                fb = feedback.get(idx, "")
                if fb.strip():
                    plan.user_feedback = fb
        # Re-trigger prompt generation
        self._generate_prompts()

    # ── Run pipeline (background thread) ──

    def _run_pipeline_with_plans(self, **kwargs) -> None:
        """Run the generation pipeline with pre-generated prompts."""
        import logging as py_logging

        gui_handler = GuiLogHandler(self.log_text)
        root_logger = py_logging.getLogger()
        root_logger.setLevel(py_logging.INFO)
        root_logger.addHandler(gui_handler)

        try:
            input_path = kwargs["input_path"]
            output_path = kwargs["output_path"]
            image_provider_name = kwargs.get("image_provider_name", "siliconflow")
            video_provider_name = kwargs.get("video_provider_name", "siliconflow")
            image_model = kwargs.get("image_model", "")
            video_model = kwargs.get("video_model", "")
            fps = kwargs.get("fps", 24)
            add_subtitles = kwargs.get("add_subtitles", True)
            add_audio = kwargs.get("add_audio", False)
            narration_style = kwargs.get("narration_style", "direct")
            add_bgm = kwargs.get("add_bgm", True)
            bgm_volume = kwargs.get("bgm_volume", 0.15)
            total_duration = kwargs.get("total_duration", 30)
            language = kwargs.get("language", "zh-CN")

            import config as cfg
            ratio = kwargs.get("ratio", "original")
            if ratio != 'original':
                cfg.set_ratio(ratio)
            from narration_workflow import source_ratio
            source_ratio(self._parsed_slides, ratio)
            if self._narration_project:
                self._narration_project.validate_source(input_path)
                self._narration_project.apply_to_plans(self._scene_plans)
            if kwargs.get("visual_mode", "faithful") == "faithful":
                from pptx_parser import parse_pptx
                from faithful_plan import build_faithful_plans
                from video_composer import compose_video
                # Reparse so an edited/reselected file cannot use stale facts.
                # Validate the immutable source while keeping the reviewed script.
                if not self._narration_project:
                    self._parsed_slides = parse_pptx(input_path)
                    self._scene_plans = build_faithful_plans(self._parsed_slides, narration_style, total_duration)
                self.master.after(0, self._display_plans)
                self._log("忠实讲解：播放原 PPT 页面，使用已审阅讲稿，跳过图像和视频生成接口", "info")
                self.master.after(0, lambda: self._update_progress(35, "制作内容动画与讲解…"))
                compose_video(
                    self._parsed_slides, [], output_path, plans=self._scene_plans,
                    fps=fps, add_subtitles=add_subtitles, add_audio=add_audio,
                    add_bgm=add_bgm, bgm_path=kwargs.get("bgm_path"), bgm_volume=bgm_volume,
                    narration_style=narration_style, visual_mode="faithful",
                )
                self._log(f"✅ 转换完成！视频已保存到: {output_path}", "ok")
                self.master.after(0, lambda: self._update_progress(100, "✅ 完成"))
                self._set_status(f"✅ 完成: {output_path}")
                self.master.after(500, lambda s=self._parsed_slides, p=self._scene_plans,
                                  v=str(output_path): self._show_preview(s, p, [], v))
                return
            _refresh_plan_narration(self._parsed_slides, self._scene_plans, narration_style)

            # Build provider kwargs
            image_kwargs: dict[str, Any] = {}
            video_kwargs: dict[str, Any] = {}
            if image_model:
                image_kwargs["image_model"] = image_model
            if video_model:
                video_kwargs["video_model"] = video_model

            # Provider-specific setup for image provider
            if image_provider_name == "custom_api":
                base_url = os.getenv("CUSTOM_API_BASE_URL", "")
                if not base_url:
                    self._log("❌ 自定义API需要设置 CUSTOM_API_BASE_URL 环境变量", "err")
                    self._set_status("❌ 配置错误")
                    return
                image_kwargs["base_url"] = base_url

            elif image_provider_name == "comfyui":
                image_kwargs["base_url"] = os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")

            # Provider-specific setup for video provider
            if video_provider_name == "custom_api":
                base_url = os.getenv("CUSTOM_API_BASE_URL", "")
                if not base_url:
                    self._log("❌ 自定义API需要设置 CUSTOM_API_BASE_URL 环境变量", "err")
                    self._set_status("❌ 配置错误")
                    return
                video_kwargs["base_url"] = base_url

            elif video_provider_name == "comfyui":
                video_kwargs["base_url"] = os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")

            # Get API keys
            env_key_map = {
                "siliconflow": "SILICONFLOW_API_KEY",
                "agnes": "AGNES_API_KEY",
                "kling": "KLING_API_KEY",
                "volcengine": "VOLC_API_KEY",
                "openai": "OPENAI_API_KEY",
                "gemini": "GEMINI_API_KEY",
            }
            gui_api_keys = kwargs.get("api_keys", {})
            api_keys: dict[str, str] = {}

            # Assign per-provider keys from GUI or env
            for pname in set([image_provider_name, video_provider_name]):
                gui_key = gui_api_keys.get(pname, "")
                if gui_key:
                    api_keys[pname] = gui_key
                # Also pull from env
                env_var = env_key_map.get(pname, "")
                if env_var and os.getenv(env_var, ""):
                    api_keys.setdefault(pname, os.getenv(env_var, ""))

            from providers import get_providers

            img_prov_name = image_provider_name
            vid_prov_name = video_provider_name

            image_prov, video_prov = get_providers(
                image_provider=img_prov_name,
                video_provider=vid_prov_name,
                api_keys=api_keys,
                image_kwargs=image_kwargs,
                video_kwargs=video_kwargs,
            )

            # Log which providers are being used
            self._log(f"🖼️ 图片生成引擎: {img_prov_name}", "info")
            self._log(f"🎬 视频生成引擎: {vid_prov_name}", "info")

            # ── Auto-compare: try Agnes alongside selected provider ──
            auto_compare = kwargs.get("auto_compare", False)
            agnes_provider = None
            if auto_compare and image_provider_name != "agnes" and video_provider_name != "agnes":
                agnes_key = gui_api_keys.get("agnes", "") or os.getenv("AGNES_API_KEY", "")
                if agnes_key:
                    from providers.agnes import AgnesProvider
                    agnes_provider = AgnesProvider(api_key=agnes_key)
                    self._log("🔬 自动对比择优启用 — 同时使用 Agnes AI 免费模型对比", "info")

            try:
                from config import ensure_temp_dir, VIDEO_SIZE, VIDEO_DURATION, MAX_CONCURRENT
                from video_generator import generate_clips_from_plans
                from video_composer import compose_video

                temp_dir = ensure_temp_dir()

                self._log(f"🎬 开始生成 {len(self._parsed_slides)} 个视频片段...", "info")

                # Custom progress callback
                def on_progress(current: int, total: int, msg: str) -> None:
                    self._log(f"  [{current}/{total}] {msg}", "info")
                    pct = int(min(current / max(total, 1) * 100, 100))
                    self.master.after(0, lambda v=pct, m=f"{msg} ({current}/{total} 场景)": self._update_progress(v, m))
                    if self._stop_flag or (self._stop_event and self._stop_event.is_set()):
                        raise InterruptedError("User stopped")

                clips = asyncio.run(
                    generate_clips_from_plans(
                        self._parsed_slides,
                        self._scene_plans,
                        image_provider=image_prov,
                        video_provider=video_prov,
                        output_dir=temp_dir,
                        max_concurrent=kwargs.get("max_concurrent", MAX_CONCURRENT),
                        progress_callback=on_progress,
                        stop_event=self._stop_event,
                    )
                )

                if self._stop_flag:
                    self._log("⏹ 生成已中断", "warn")
                    return

                if not clips:
                    self._log("⚠ 所有场景生成失败，将使用幻灯片文字画面继续合成", "warn")
                else:
                    self._log(f"✅ 成功生成 {len(clips)}/{len(self._scene_plans)} 个场景", "ok")

                # Compose final video with progress
                self._log("🎞️ 合成最终视频...", "info")
                self.master.after(0, lambda: self._update_progress(95, "🎞️ 合成最终视频..."))
                compose_video(
                    self._parsed_slides,
                    clips,
                    output_path,
                    plans=self._scene_plans,
                    add_subtitles=add_subtitles,
                    fps=fps,
                    add_audio=add_audio,
                    add_bgm=add_bgm,
                    bgm_path=kwargs.get("bgm_path"),
                    bgm_volume=bgm_volume,
                    narration_style=narration_style,
                    visual_mode="creative",
                )

                self._log("")
                self._log(f"✅ 转换完成！视频已保存到: {output_path}", "ok")
                self.master.after(0, lambda: self._update_progress(100, "✅ 完成"))
                self._set_status(f"✅ 完成: {output_path}")

                # Always show Preview & Feedback window after successful generation
                if self._parsed_slides and self._scene_plans:
                    final_path_str = str(output_path)
                    self.master.after(
                        500,
                        lambda s=self._parsed_slides,
                               p=self._scene_plans,
                               c=clips,
                               v=final_path_str: self._show_preview(s, p, c, v),
                    )

            finally:
                try:
                    asyncio.run(image_prov.close())
                except RuntimeError as _e:
                    self._log(f"⚠ 关闭图片引擎连接时出错（事件循环已关闭）", "warn")
                try:
                    if video_prov is not image_prov:
                        asyncio.run(video_prov.close())
                    if agnes_provider is not None:
                        asyncio.run(agnes_provider.close())
                except RuntimeError as _e:
                    self._log(f"⚠ 关闭视频引擎连接时出错（事件循环已关闭）", "warn")
                try:
                    from video_generator import cleanup_temp_files
                    asyncio.run(cleanup_temp_files())
                except RuntimeError as _e:
                    pass

        except InterruptedError:
            self._log("⏹ 已停止", "warn")
            self._set_status("已停止")
        except asyncio.CancelledError:
            self._log("⏹ 用户取消生成", "warn")
            self._set_status("已取消")
        except Exception as exc:
            self._set_status(f"❌ 错误: {exc}")
            self._log(f"❌ 错误: {exc}", "err")
            import traceback
            self._log(traceback.format_exc(), "err")
        finally:
            self._running = False
            self._stop_flag = False
            root_logger.removeHandler(gui_handler)
            self.master.after(0, lambda: self._show_progress(False))
            self.master.after(0, lambda: self._set_busy(False))

    # ── Preview Window ──────────────────────────────────────────────────

    def _show_preview(
        self,
        slides: list[Any],
        plans: list[Any],
        clips: list[Any],
        final_video_path: str,
    ) -> None:
        """Populate the Preview tab and still open the feedback window."""
        # Store path for play button
        self._preview_video_path = final_video_path
        self._update_steps()
        self._preview_play_btn.configure(state="normal")
        self._preview_path_label.configure(text=Path(final_video_path).name)
        self._preview_status_label.configure(text="✅ 视频已生成")

        # Build preview summary text
        lines = [f"📁 {Path(final_video_path).name}"]
        lines.append(f"📏 大小: {Path(final_video_path).stat().st_size / 1e6:.1f} MB")
        faithful = bool(plans) and all(getattr(p, "visual_mode", "creative") == "faithful" for p in plans)
        rendered_scenes = {}
        if faithful:
            try:
                manifest = json.loads(Path(final_video_path).with_suffix('.content.json').read_text(encoding='utf-8'))
                rendered_scenes = {s['slide_index']: s for s in manifest['scenes']}
            except (OSError, ValueError, KeyError):
                pass
        successful = len(rendered_scenes) if faithful else len(clips)
        lines.append(f"🎬 共 {successful}/{len(plans)} 个场景成功生成")
        lines.append("")
        for i, plan in enumerate(plans):
            if faithful:
                scene = rendered_scenes.get(plan.slide_index)
                if scene:
                    duration = scene['end'] - scene['start']
                    voice = ' · 本页无配音' if scene.get('narration_status') == 'unavailable' else ''
                    lines.append(f"  ✅ 第{plan.slide_index}页: {duration:.1f}s · 原文与原图{voice}")
                else:
                    lines.append(f"  第{plan.slide_index}页: 内容清单不可用，请播放成片检查")
                continue
            clip = next((c for c in clips if c.slide_index == getattr(plan, 'slide_index', i)), None)
            if clip:
                dur = getattr(clip, "duration", "?")
                kf = len(getattr(clip, "keyframe_paths", []))
                lines.append(f"  ✅ 场景{i+1}: {dur:.1f}s, {kf}张关键帧")
            else:
                lines.append(f"  ❌ 场景{i+1}: 失败")
        lines.append("")
        lines.append("💡 点击「▶ 播放视频」按钮预览完整视频")
        if faithful:
            lines.append("💡 同名 .content.json 可核对原文、配音状态与各页时间轴")

        self._preview_content.configure(state="normal")
        self._preview_content.delete("1.0", "end")
        self._preview_content.insert("1.0", "\n".join(lines))
        self._preview_content.configure(state="disabled")

        # Switch to preview tab
        self._right_notebook.select(2)

        # (Popup PreviewWindow removed — inline Tab 3 is sufficient)

    def _play_preview_video(self) -> None:
        """Play the preview video using ffplay."""
        if self._preview_video_path and Path(self._preview_video_path).exists():
            import subprocess as _sp
            import sys as _sys
            try:
                _sp.Popen(
                    ["ffplay", "-window_title", "🎬 PPT转视频 - 预览",
                     "-autoexit", "-i", str(self._preview_video_path)],
                    stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                )
            except FileNotFoundError:
                if _sys.platform == "win32":
                    os.startfile(self._preview_video_path)
                else:
                    _sp.run(["xdg-open", self._preview_video_path], check=False)
        else:
            messagebox.showwarning("提示", "尚无视频，请先生成")


# ── Progress Popup ──────────────────────────────────────────────────────────


# ── Preview & Feedback Window ──────────────────────────────────────────────


class PreviewWindow:
    """Toplevel window for reviewing generated content per-slide and
    providing feedback before final export."""

    def __init__(
        self,
        parent: Tk,
        slides: list[Any],
        plans: list[Any],
        clips: list[Any],
        final_video_path: str,
        app: PptxToVideoApp,
    ) -> None:
        self.parent = parent
        self.slides = slides
        self.plans = plans
        self.clips = clips
        self.final_video_path = final_video_path
        self.app = app
        self._feedback: dict[int, str] = {}
        self._selected_index: int = 0

        self._build_window()

    def _build_window(self) -> None:
        import tkinter as tk
        from tkinter import scrolledtext

        self.win = tk.Toplevel(self.parent)
        self.win.title("🎬 预览 & 反馈")
        self.win.geometry("1100x680")
        self.win.minsize(900, 550)
        self.win.configure(bg=C_BG)

        # ── Main paned window ──
        paned = ttk.PanedWindow(self.win, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=8)

        # ── Left: Scene list ──
        left_frame = ttk.Frame(paned, style="Card.TFrame", padding=6)
        paned.add(left_frame, weight=1)

        ttk.Label(left_frame, text="🎬 场景列表",
                  style="Section.TLabel").pack(anchor="w", pady=(0, 4))

        self._scene_listbox = tk.Listbox(
            left_frame,
            bg=C_INPUT_BG, fg=C_FG,
            selectbackground=C_ACCENT,
            selectforeground="white",
            font=("Segoe UI", 10),
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
        )
        self._scene_listbox.pack(fill="both", expand=True)
        # Show scenes (plans) not raw slides — ScriptWriter merges slides into scenes
        for i, plan in enumerate(self.plans):
            act = getattr(plan, "act_name", "") or ""
            # Show which slides this scene covers
            slide_idx = getattr(plan, "slide_index", i)
            covered = f" [页 {slide_idx+1}]"
            label = f"  {i+1}. {act}{covered}" if act else f"  {i+1}. 场景{covered}"
            self._scene_listbox.insert("end", label)
        self._scene_listbox.bind("<<ListboxSelect>>", self._on_scene_select)
        self._scene_listbox.selection_set(0)

        # ── Right: Detail panel ──
        right_frame = ttk.Frame(paned, style="Card.TFrame", padding=6)
        paned.add(right_frame, weight=3)

        self._detail_frame = ttk.Frame(right_frame, style="Card.TFrame")
        self._detail_frame.pack(fill="both", expand=True)

        # Detail content will be rebuilt on selection
        self._render_detail(0)

        # ── Bottom buttons ──
        btn_frame = ttk.Frame(self.win, style="TFrame")
        btn_frame.pack(fill="x", padx=12, pady=(0, 10))

        ttk.Button(
            btn_frame, text="▶ 播放完整视频 (ffplay)",
            style="Accent.TButton",
            command=self._play_video,
        ).pack(side="left", padx=4)

        ttk.Button(
            btn_frame, text="💾 确认 — 视频已保存",
            style="Success.TButton",
            command=self._confirm_and_export,
        ).pack(side="left", padx=4)

        ttk.Button(
            btn_frame, text="根据反馈重新生成",
            style="Accent.TButton",
            command=self._regenerate_with_feedback,
        ).pack(side="left", padx=4)

    # ── Detail rendering ──

    def _render_detail(self, idx: int) -> None:
        """Rebuild the right-side detail panel for slide at *idx*."""
        import tkinter as tk
        from tkinter import scrolledtext

        for w in self._detail_frame.winfo_children():
            w.destroy()

        if idx < 0 or idx >= len(self.plans):
            ttk.Label(self._detail_frame, text="请选择一个幻灯片",
                      style="Card.TLabel").pack(pady=40)
            return

        plan = self.plans[idx]
        slide = self.slides[idx] if idx < len(self.slides) else None
        is_enhanced = hasattr(plan, "image_prompts") and plan.image_prompts

        # Slide info
        header = ttk.Frame(self._detail_frame, style="Card.TFrame")
        header.pack(fill="x", pady=(0, 6))

        slide_num = plan.slide_index if hasattr(plan, 'slide_index') else (idx + 1)
        title_text = slide.title if slide and hasattr(slide, 'title') and slide.title else f"幻灯片 {slide_num}"
        ttk.Label(header, text=f"📄 第 {slide_num} 页 — {title_text}",
                  style="Title.TLabel",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w")

        # Scrollable detail area
        text_frame = ttk.Frame(self._detail_frame, style="Card.TFrame")
        text_frame.pack(fill="both", expand=True)

        canvas = tk.Canvas(text_frame, bg=C_CARD, highlightthickness=0)
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas, style="Card.TFrame")

        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Mousewheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self.win.protocol("WM_DELETE_WINDOW", lambda: (
            canvas.unbind_all("<MouseWheel>"), self.win.destroy()
        ))

        # ── Director's Vision ──
        section = ttk.LabelFrame(scrollable, text="🎬 导演构想", style="TLabelFrame")
        section.pack(fill="x", padx=6, pady=(4, 2))
        vision = getattr(plan, "director_vision", "")
        ttk.Label(section, text=vision or "(无)", wraplength=600,
                  style="Card.TLabel").pack(anchor="w", padx=6, pady=4)

        # ── Keyframe Image Prompts ──
        section = ttk.LabelFrame(scrollable, text="📷 关键帧提示词", style="TLabelFrame")
        section.pack(fill="x", padx=6, pady=(2, 2))

        if is_enhanced:
            for pi, (prompt, angle) in enumerate(
                zip(plan.image_prompts, plan.image_angles or [""] * len(plan.image_prompts))
            ):
                angle_text = f" [角度: {angle}]" if angle else ""
                ttk.Label(section, text=f"帧 {pi+1}{angle_text}:",
                          style="Accent.TLabel").pack(anchor="w", padx=6, pady=(2, 0))
                ttk.Label(section, text=prompt or "(无)",
                          wraplength=580, style="Card.TLabel").pack(anchor="w", padx=16, pady=(0, 2))
        else:
            image_prompt = getattr(plan, "image_prompt", "")
            ttk.Label(section, text=image_prompt or "(无)",
                      wraplength=580, style="Card.TLabel").pack(anchor="w", padx=6, pady=4)

        # ── Enhanced info (if EnhancedScenePlan) ──
        if is_enhanced:
            dur = getattr(plan, "suggested_duration_sec", None)
            if dur is not None:
                section = ttk.LabelFrame(scrollable, text="⏱️ 建议时长",
                                         style="TLabelFrame")
                section.pack(fill="x", padx=6, pady=(2, 2))
                ttk.Label(section, text=f"{dur:.1f} 秒",
                          style="Card.TLabel").pack(anchor="w", padx=6, pady=4)

            chars = getattr(plan, "characters_in_scene", [])
            if chars:
                section = ttk.LabelFrame(scrollable, text="👤 场景角色",
                                         style="TLabelFrame")
                section.pack(fill="x", padx=6, pady=(2, 2))
                ttk.Label(section, text=", ".join(chars),
                          style="Card.TLabel").pack(anchor="w", padx=6, pady=4)

            setting = getattr(plan, "setting_name", "")
            if setting:
                section = ttk.LabelFrame(scrollable, text="🏠 场景设置",
                                         style="TLabelFrame")
                section.pack(fill="x", padx=6, pady=(2, 2))
                ttk.Label(section, text=setting,
                          style="Card.TLabel").pack(anchor="w", padx=6, pady=4)

            cam = getattr(plan, "camera_angle", "")
            if cam:
                section = ttk.LabelFrame(scrollable, text="📐 运镜",
                                         style="TLabelFrame")
                section.pack(fill="x", padx=6, pady=(2, 2))
                ttk.Label(section, text=cam,
                          style="Card.TLabel").pack(anchor="w", padx=6, pady=4)

            trans_type = getattr(plan, "transition_type", "")
            trans_desc = getattr(plan, "transition_description", "")
            if trans_type:
                section = ttk.LabelFrame(scrollable, text="🔄 转场",
                                         style="TLabelFrame")
                section.pack(fill="x", padx=6, pady=(2, 2))
                ttk.Label(section, text=f"{trans_type}: {trans_desc}" if trans_desc else trans_type,
                          style="Card.TLabel").pack(anchor="w", padx=6, pady=4)

            bridge = getattr(plan, "narrative_bridge", "")
            if bridge:
                section = ttk.LabelFrame(scrollable, text="📖 叙事桥接",
                                         style="TLabelFrame")
                section.pack(fill="x", padx=6, pady=(2, 2))
                ttk.Label(section, text=bridge,
                          style="Card.TLabel").pack(anchor="w", padx=6, pady=4)

        # ── Clip info: find clip by matching slide_index ──
        plan_slide_idx = getattr(plan, 'slide_index', idx)
        clip = next((c for c in self.clips if c.slide_index == plan_slide_idx), None)
        if clip:
            section = ttk.LabelFrame(scrollable, text="🎥 视频片段",
                                     style="TLabelFrame")
            section.pack(fill="x", padx=6, pady=(2, 2))
            clip_dur = getattr(clip, "duration", "?")
            clip_path = getattr(clip, "file_path", "")
            ttk.Label(section, text=f"时长: {clip_dur}s  |  文件: {Path(clip_path).name}",
                      style="Card.TLabel").pack(anchor="w", padx=6, pady=4)

        # ── Keyframe Image Thumbnails ──
        keyframe_paths: list[str] = getattr(clip, "keyframe_paths", []) if clip else []
        if keyframe_paths:
            section = ttk.LabelFrame(scrollable, text="🖼️ 关键帧图片",
                                     style="TLabelFrame")
            section.pack(fill="x", padx=6, pady=(2, 2))
            img_frame = ttk.Frame(section, style="Card.TFrame")
            img_frame.pack(fill="x", padx=6, pady=4)
            _max_thumb_w = min(200, int((self.win.winfo_width() - 80) // max(len(keyframe_paths), 1)))
            from PIL import Image as _PIL_Image, ImageTk as _PIL_ImageTk
            for kf_idx, kf_path in enumerate(keyframe_paths):
                try:
                    pil_img = _PIL_Image.open(kf_path)
                    pil_img.thumbnail((_max_thumb_w, 140))
                    tk_img = _PIL_ImageTk.PhotoImage(pil_img)
                    # Store reference to prevent garbage collection
                    if not hasattr(self, '_thumb_refs'):
                        self._thumb_refs = []
                    self._thumb_refs.append(tk_img)
                    lbl = ttk.Label(img_frame, image=tk_img,
                                    style="Card.TLabel")
                    lbl.pack(side="left", padx=4)
                    # Angle label
                    angle = plan.image_angles[kf_idx] if is_enhanced and kf_idx < len(plan.image_angles) else ""
                    ttk.Label(img_frame, text=f"帧 {kf_idx+1}" + (f" [{angle}]" if angle else ""),
                              style="Accent.TLabel", font=("Segoe UI", 8)).pack(side="left", padx=4)
                except Exception as _exc:
                    ttk.Label(img_frame, text=f"🖼️ 帧{kf_idx+1} (加载失败)",
                              style="Card.TLabel").pack(side="left", padx=4)

        # ── Feedback text box ──
        section = ttk.LabelFrame(scrollable, text="✏️ 反馈", style="TLabelFrame")
        section.pack(fill="x", padx=6, pady=(6, 4))

        fb_header = ttk.Frame(section, style="Card.TFrame")
        fb_header.pack(fill="x", padx=6, pady=(4, 0))
        ttk.Label(fb_header, text="📝 你的反馈：",
                  style="Accent.TLabel").pack(side="left")
        ttk.Button(
            fb_header, text="💾 保存反馈", style="Small.TButton",
            command=self._save_current_feedback,
        ).pack(side="right")

        self._feedback_text = scrolledtext.ScrolledText(
            section, wrap="word",
            font=("Microsoft YaHei UI", 10),
            bg=C_INPUT_BG, fg=C_FG,
            insertbackground=C_ACCENT_HOVER,
            relief="flat", borderwidth=0,
            height=4,
        )
        self._feedback_text.pack(fill="x", padx=6, pady=4)
        # Restore existing feedback if any
        existing = self._feedback.get(idx, "")
        if existing:
            self._feedback_text.insert("1.0", existing)

    # ── Event handlers ──

    def _on_scene_select(self, event=None) -> None:
        sel = self._scene_listbox.curselection()
        if sel:
            # Save current feedback before switching
            self._save_current_feedback()
            idx = sel[0]
            self._selected_index = idx
            self._render_detail(idx)

    def _save_current_feedback(self) -> None:
        """Save feedback from the current detail view into the dict."""
        if hasattr(self, "_feedback_text") and self._feedback_text.winfo_exists():
            text = self._feedback_text.get("1.0", "end-1c").strip()
            self._feedback[self._selected_index] = text

    def _play_video(self) -> None:
        """Play the final video using ffplay (bundled with moviepy's ffmpeg)."""
        if self.final_video_path and Path(self.final_video_path).exists():
            import subprocess as _sp
            import sys as _sys
            try:
                _sp.Popen(
                    ["ffplay", "-window_title", "🎬 PPT转视频 - 预览",
                     "-autoexit", "-i", str(self.final_video_path)],
                    stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                )
            except FileNotFoundError:
                # Fallback: system default player
                if _sys.platform == "win32":
                    os.startfile(self.final_video_path)
                elif _sys.platform == "darwin":
                    _sp.run(["open", self.final_video_path], check=False)
                else:
                    _sp.run(["xdg-open", self.final_video_path], check=False)
        else:
            messagebox.showwarning("提示", "视频文件未找到，请先完成生成")

    def _confirm_and_export(self) -> None:
        """Save all feedback and close the preview window."""
        self._save_current_feedback()
        # Log feedback summary
        if self.app:
            fb_count = sum(1 for v in self._feedback.values() if v.strip())
            self.app._log(f"✅ 预览确认完成，共收到 {fb_count} 条反馈", "ok")
        self.win.destroy()

    def _regenerate_with_feedback(self) -> None:
        """Save feedback and signal regeneration to parent app."""
        self._save_current_feedback()
        if self.app:
            fb_count = sum(1 for v in self._feedback.values() if v.strip())
            self.app._log(
                f"🔄 根据反馈重新生成 (共 {fb_count} 条反馈)", "info")
            for idx, fb in self._feedback.items():
                if fb.strip():
                    self.app._log(
                        f"  幻灯片 {idx+1}: {fb[:80]}...", "info")
            # Store feedback on the parent app for regeneration
            self.app._regeneration_feedback = dict(self._feedback)
            self.win.destroy()
            # Trigger regeneration via parent app
            self.app.master.after(100, self.app._run_regeneration_with_feedback)
        else:
            self.win.destroy()
            messagebox.showinfo(
                "反馈已保存",
                "已收集反馈信息，请手动修改提示词后重新生成。",
            )


def main() -> None:
    root = Tk()
    _ = PptxToVideoApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
