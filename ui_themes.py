"""Desktop-only appearance. No conversion settings or credentials are stored here."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import sys
import tempfile
from tkinter import ttk, font as tkfont

THEMES = {
    'light': dict(name='简约浅色', bg='#EEF2F7', surface='#E2EAF3', card='#FFFFFF',
                  hover='#E6EFF9', input='#F4F7FB', fg='#172C46', secondary='#4B6078',
                  muted='#62758A', accent='#275687', active='#19446F', glow='#278B98',
                  success='#246956', error='#AD3F50', warn='#876429', border='#D5DADE',
                  subtle='#BCC6CD', ghost='#E8ECEC', prompt='#FAFAF7', on_accent='#FFFFFF',
                  ornament='#7FD4DA', ornament_soft='#DDF0F2',
                  stage_start='#EAF2FA', stage_end='#E2EDEF', stage_glow='#62C9DE', stage_shadow='#CBDDE9',
                  banner='#183650', banner_end='#326577', banner_fg='#F5FAFF', banner_muted='#D0E4ED'),
    'warm': dict(name='柔和暖色', bg='#EDE9E2', surface='#E3DDD2', card='#FCFAF4',
                 hover='#E9E8DA', input='#F4F0E8', fg='#353D36', secondary='#586158',
                 muted='#6C7267', accent='#3D6355', active='#2E5043', glow='#957347',
                 success='#426747', error='#A34245', warn='#816025', border='#D7D4C7',
                 subtle='#C1C4B1', ghost='#E8E6DB', prompt='#FCFAF5', on_accent='#FFFFFF',
                 ornament='#B78C5C', ornament_soft='#EEDFC9',
                 stage_start='#F1E8D9', stage_end='#E4E9DC', stage_glow='#EFC89C', stage_shadow='#D9D5C3',
                 banner='#2E4A40', banner_end='#647B67', banner_fg='#FCF5E8', banner_muted='#E1E0CF'),
    'dark': dict(name='深色科技', bg='#161B27', surface='#1D2536', card='#232C3D',
                 hover='#354056', input='#1B2435', fg='#EBEEF5', secondary='#C2CBDC',
                 muted='#A0AEC4', accent='#BBAFF2', active='#D0C7FA', glow='#8BDDE0',
                 success='#94D2B6', error='#EF9DA6', warn='#DDC18F', border='#3B475F',
                 subtle='#536079', ghost='#2E394E', prompt='#20293A', on_accent='#202B40',
                 ornament='#89D5DC', ornament_soft='#2A3B50',
                 stage_start='#302C48', stage_end='#223C4A', stage_glow='#A093EF', stage_shadow='#182333',
                 banner='#292A48', banner_end='#3C4F65', banner_fg='#F0EEF8', banner_muted='#D0CCDF'),
}
DEFAULT_THEME = 'light'


def preferences_path() -> Path:
    base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    return base / 'ui_preferences.json'


def load_theme(path: Path | None = None) -> str:
    try:
        value = json.loads((path or preferences_path()).read_text(encoding='utf-8')).get('theme')
        return value if value in THEMES else DEFAULT_THEME
    except (OSError, ValueError, AttributeError, TypeError):
        return DEFAULT_THEME


def save_theme(theme: str, path: Path | None = None) -> bool:
    if theme not in THEMES:
        raise ValueError(f'Unknown UI theme: {theme}')
    path = path or preferences_path()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.ui_theme_', suffix='.json', delete=False) as file:
            temporary = Path(file.name)
            json.dump({'theme': theme}, file, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
        return True
    except OSError as exc:
        logging.getLogger(__name__).warning('界面主题已应用，但偏好未能保存: %s', exc)
        return False
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def legacy_colors(theme: str) -> dict[str, str]:
    """Keep existing GUI callbacks and review dialogs on the current palette."""
    p = THEMES[theme]
    roles = dict(BG='bg', SURFACE='surface', CARD='card', CARD_HOVER='hover', INPUT_BG='input',
                 FG='fg', FG_SECONDARY='secondary', FG_TERTIARY='muted', FG_MUTED='muted',
                 ACCENT='accent', ACCENT_HOVER='active', ACCENT_GLOW='glow', SUCCESS='success',
                 ERROR='error', WARN='warn', BORDER='border', BORDER_SUBTLE='subtle',
                 BORDER_GHOST='ghost', PROMPT_BG='prompt', PROMPT_BORDER='border',
                 CARD_HIGHLIGHT='hover', NEON_GLOW='active', GRID_LINE='ghost',
                 TEXT_SECONDARY='secondary', TEXT_MUTED='muted', DIVIDER='ghost',
                 SECTION_BG='surface', SURFACE_ALT='card', BADGE_BG='hover')
    return {'C_' + name: p[role] for name, role in roles.items()}


def configure_styles(master, theme: str) -> None:
    p = THEMES[theme]
    style = ttk.Style(master)
    if style.theme_use() != 'clam':
        style.theme_use('clam')
    master.configure(bg=p['bg'])
    for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont'):
        tkfont.nametofont(name, root=master).configure(family='Microsoft YaHei UI', size=10)
    for option, value in dict(background=p['card'], foreground=p['fg'],
                              selectBackground=p['accent'], selectForeground=p['on_accent'],
                              font=('Microsoft YaHei UI', 10), relief='flat', borderWidth=0).items():
        master.option_add('*TCombobox*Listbox.' + option, value)
    style.configure('.', font=('Microsoft YaHei UI', 10), background=p['card'], foreground=p['fg'],
                    bordercolor=p['border'], lightcolor=p['card'], darkcolor=p['card'],
                    focuscolor=p['accent'], troughcolor=p['surface'], selectbackground=p['accent'],
                    selectforeground=p['on_accent'])
    for name, role in {'TFrame':'bg', 'Card.TFrame':'card', 'Surface.TFrame':'surface',
                       'Highlight.TFrame':'ghost', 'BgDark.TFrame':'bg', 'Divider.TFrame':'ghost',
                       'PromptText.TFrame':'prompt', 'CardSep.TFrame':'ghost'}.items():
        style.configure(name, background=p[role], relief='flat', borderwidth=0)
    style.configure('RaisedCard.TFrame', background=p['card'], borderwidth=1,
                    relief='solid', bordercolor=p['border'], lightcolor=p['card'], darkcolor=p['border'])
    style.configure('Banner.TLabel', background=p['banner_end'], foreground=p['banner_muted'],
                    font=('Microsoft YaHei UI',9))
    for name, bg, fg, font in [
        ('TLabel','bg','fg',('Microsoft YaHei UI',10)),
        ('Card.TLabel','card','fg',('Microsoft YaHei UI',10)),
        ('Title.TLabel','bg','fg',('Segoe UI Semibold',23)),
        ('Section.TLabel','card','fg',('Microsoft YaHei UI',11,'bold')),
        ('Status.TLabel','bg','muted',('Microsoft YaHei UI',9)),
        ('Accent.TLabel','card','accent',('Microsoft YaHei UI',10,'bold')),
        ('PaneHeader.TLabel','card','fg',('Microsoft YaHei UI',12,'bold')),
        ('Muted.TLabel','card','muted',('Microsoft YaHei UI',9)),
        ('Divider.TLabel','bg','muted',('Microsoft YaHei UI',9)),
        ('Step.TLabel','surface','muted',('Microsoft YaHei UI',10)),
        ('EmptyTitle.TLabel','prompt','fg',('Microsoft YaHei UI',19,'bold')),
        ('Empty.TLabel','prompt','secondary',('Microsoft YaHei UI',11)),
        ('EmptyMuted.TLabel','prompt','muted',('Microsoft YaHei UI',10)),
    ]:
        style.configure(name, background=p[bg], foreground=p[fg], font=font)
    for name in ('TEntry', 'TCombobox', 'TSpinbox'):
        style.configure(name, fieldbackground=p['input'], background=p['input'], foreground=p['fg'],
                        insertcolor=p['accent'], arrowcolor=p['secondary'], bordercolor=p['border'],
                        lightcolor=p['input'], darkcolor=p['input'], borderwidth=1,
                        relief='flat', padding=(9,7), arrowsize=13)
        style.map(name, fieldbackground=[('disabled',p['surface']),('readonly',p['input']),('focus',p['card'])],
                  foreground=[('disabled',p['muted']),('readonly',p['fg'])],
                  bordercolor=[('focus',p['accent']),('active',p['subtle'])],
                  selectbackground=[('!disabled',p['accent'])],
                  selectforeground=[('!disabled',p['on_accent'])])
    for name in ('TButton','Small.TButton','Accent.TButton','Danger.TButton','Success.TButton'):
        primary = name == 'Accent.TButton'
        fg = p['on_accent'] if primary else p['error'] if name == 'Danger.TButton' else p['success'] if name == 'Success.TButton' else p['fg']
        style.configure(name, background=p['accent'] if primary else p['card'], foreground=fg,
                        font=('Microsoft YaHei UI',10,'bold') if primary else ('Microsoft YaHei UI',10),
                        padding=(14,9), width=-7, borderwidth=0 if primary else 1, relief='flat',
                        bordercolor=p['accent'] if primary else p['border'],
                        lightcolor=p['card'], darkcolor=p['card'])
        style.map(name, background=[('disabled',p['surface']),('pressed',p['active'] if primary else p['surface']),
                                    ('active',p['active'] if primary else p['hover'])],
                  foreground=[('disabled',p['muted'])], bordercolor=[('focus',p['accent']),('active',p['accent'])])
    style.configure('TCheckbutton', background=p['card'], foreground=p['fg'], padding=(0,5),
                    indicatorbackground=p['input'], indicatorforeground=p['on_accent'],
                    indicatorcolor=p['input'], indicatormargin=(0,0,7,0), indicatorsize=15,
                    bordercolor=p['border'])
    style.map('TCheckbutton', background=[('active',p['card'])],
              foreground=[('disabled',p['muted'])],
              indicatorbackground=[('selected',p['accent'])], indicatorcolor=[('selected',p['accent'])])
    style.configure('Horizontal.TProgressbar', background=p['accent'], troughcolor=p['surface'],
                    borderwidth=0, lightcolor=p['accent'], darkcolor=p['accent'], thickness=5)
    for name in ('Vertical.TScrollbar','Horizontal.TScrollbar'):
        style.configure(name, background=p['subtle'], troughcolor=p['bg'], borderwidth=0,
                        arrowcolor=p['muted'], arrowsize=11, width=11, relief='flat')
        style.map(name, background=[('active',p['muted']),('pressed',p['accent'])])
    style.configure('TPanedwindow', background=p['bg'], sashwidth=12, sashrelief='flat')
    style.configure('TPanedWindow', background=p['bg'], borderwidth=0)
    style.configure('Sash', sashthickness=12, background=p['bg'], borderwidth=0)
    style.configure('TNotebook', background=p['bg'], borderwidth=0, tabmargins=(0,0,0,10))
    style.configure('TNotebook.Tab', background=p['bg'], foreground=p['muted'],
                    font=('Microsoft YaHei UI',10), padding=(18,11), borderwidth=0,
                    lightcolor=p['bg'], darkcolor=p['bg'], bordercolor=p['bg'])
    style.map('TNotebook.Tab', background=[('selected',p['card']),('active',p['hover'])],
              lightcolor=[('selected',p['card']),('!selected',p['bg'])],
              darkcolor=[('selected',p['card']),('!selected',p['bg'])],
              padding=[('selected',(18,11)),('!selected',(18,11))],
              foreground=[('selected',p['accent']),('active',p['fg'])])
    style.configure('Horizontal.TScale', background=p['card'], troughcolor=p['surface'],
                    borderwidth=0, sliderlength=22, sliderthickness=13)
    for name in ('TLabelframe','TLabelFrame'):
        style.configure(name, background=p['card'], borderwidth=0)
    style.configure('TLabelframe.Label', background=p['card'], foreground=p['fg'])
    style.configure('TSeparator', background=p['ghost'])
