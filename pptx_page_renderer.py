"""Export original PPTX pages using PowerPoint, with a verified atomic cache.

PowerPoint exports static slides only. No renderer failure falls back to cards.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import posixpath
import shutil
import subprocess
import tempfile
import uuid
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from PIL import Image

_P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
_R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
_CACHE_VERSION = 1


class PageRenderError(RuntimeError):
    """The native renderer is missing or could not export the presentation."""


def _sha256(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _slide_metadata(path):
    """Resolve presentation order through relationships, not slide filenames."""
    with ZipFile(path) as archive:
        presentation = ET.fromstring(archive.read('ppt/presentation.xml'))
        rels = ET.fromstring(archive.read('ppt/_rels/presentation.xml.rels'))
        targets = {r.attrib['Id']: r.attrib['Target'] for r in rels}
        result = {}
        for index, item in enumerate(presentation.findall(f'{{{_P}}}sldIdLst/{{{_P}}}sldId'), 1):
            target = targets[item.attrib[f'{{{_R}}}id']]
            entry = target.lstrip('/') if target.startswith('/') else posixpath.normpath('ppt/' + target)
            root = ET.fromstring(archive.read(entry))
            tags = {element.tag.rsplit('}', 1)[-1] for element in root.iter()}
            warnings = []
            if tags.intersection({'timing', 'transition'}):
                warnings.append('原页含动画或转场；静态页面不回放动画、点击顺序或转场。')
            if tags.intersection({'videoFile', 'audioFile', 'wavAudioFile', 'media', 'snd'}):
                warnings.append('原页含音视频；静态页面仅保留其静态外观，不播放媒体。')
            result[index] = {'hidden': root.get('show', '1') in ('0', 'false'), 'warnings': warnings}
        return result


def _export_powerpoint(source, directory, slide_indices):
    """Open read-only without a window; only quit a newly owned COM process.

    Paths are JSON environment data, never interpolated PowerShell code.
    If COM reused a user's process we close only our presentation and do not Quit.
    """
    if os.name != 'nt':
        raise PageRenderError('原页渲染需要 Windows 上安装 Microsoft PowerPoint。请安装后重试；PDF/图片导入尚未提供。')
    script = r'''
$ErrorActionPreference = 'Stop'
$request = $env:PPTX_RENDER_REQUEST | ConvertFrom-Json
$existing = @(Get-Process POWERPNT -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
$application = $null
$presentation = $null
$owned = $false
try {
    Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class PptWindowProcess { [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId); }'
    $application = New-Object -ComObject PowerPoint.Application
    [uint32]$pptProcessId = 0
    [void][PptWindowProcess]::GetWindowThreadProcessId([IntPtr]$application.HWND, [ref]$pptProcessId)
    $owned = ($pptProcessId -ne 0 -and $existing -notcontains $pptProcessId)
    $presentation = $application.Presentations.Open([string]$request.source, -1, 0, 0)
    $pageWidth = [double]$presentation.PageSetup.SlideWidth
    $pageHeight = [double]$presentation.PageSetup.SlideHeight
    $factor = 1920.0 / [Math]::Max($pageWidth, $pageHeight)
    foreach ($index in $request.indices) {
        $slide = $presentation.Slides.Item([int]$index)
        try {
            $target = Join-Path ([string]$request.directory) ('slide-' + $index + '.png')
            $slide.Export($target, 'PNG', [int][Math]::Round($pageWidth*$factor), [int][Math]::Round($pageHeight*$factor))
        } finally { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($slide) }
    }
} finally {
    if ($null -ne $presentation) {
        $presentation.Close()
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($presentation)
    }
    if ($null -ne $application) {
        if ($owned) { $application.Quit() }
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($application)
    }
}
'''
    env = os.environ.copy()
    env['PPTX_RENDER_REQUEST'] = json.dumps({'source': str(source), 'directory': str(directory),
                                            'indices': slide_indices}, ensure_ascii=False)
    command = ['powershell.exe', '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden',
               '-EncodedCommand', base64.b64encode(script.encode('utf-16-le')).decode('ascii')]
    try:
        result = subprocess.run(command, env=env, capture_output=True, timeout=180,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PageRenderError('PowerPoint 原页导出无法启动或超时。请确认 PowerPoint 已安装且能打开此文件；不会改用重排卡片。') from exc
    if result.returncode:
        detail = result.stderr.decode('utf-8', errors='replace')[-1800:]
        raise PageRenderError('PowerPoint 原页导出失败。请确认本机 PowerPoint 可正常打开此文件；PDF/图片导入尚未提供。\n' + detail)


def _image_info(path):
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        image.load()
        return image.size


def render_pptx_pages(input_path, output_dir, *, include_hidden=False):
    """Return original 1-based slide numbers mapped to verified image records."""
    source = Path(input_path).resolve(strict=True)
    source_hash = _sha256(source)
    metadata = _slide_metadata(source)
    selected = [index for index, item in metadata.items() if include_hidden or not item['hidden']]
    if not selected:
        raise PageRenderError('PPT 没有可播放的页面；可选择包含隐藏页。')
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    key = f'{source_hash}-{"all" if include_hidden else "visible"}-v{_CACHE_VERSION}'
    cache = root / key
    manifest = cache / 'manifest.json'
    try:
        saved = json.loads(manifest.read_text(encoding='utf-8'))
        records = saved['pages']
        if (saved['source_sha256'] != source_hash or saved['version'] != _CACHE_VERSION
                or [r['slide_index'] for r in records] != selected):
            raise ValueError('Stale manifest')
        for record in records:
            path = Path(record['path'])
            if path.parent != cache or record['source_sha256'] != source_hash:
                raise ValueError('Invalid cache path or source')
            if _sha256(path) != record['sha256'] or _image_info(path) != (record['width'], record['height']):
                raise ValueError('Invalid cached image')
        return {record['slide_index']: record for record in records}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    staging = Path(tempfile.mkdtemp(prefix='.pptx-render-', dir=root))
    try:
        _export_powerpoint(source, staging, selected)
        if _sha256(source) != source_hash:
            raise PageRenderError('PPT 在导出期间发生变化，请重新分析后重试。')
        pages = {}
        for index in selected:
            filename = f'slide-{index}.png'
            path = staging / filename
            width, height = _image_info(path)
            pages[index] = {'slide_index': index, 'path': str(cache / filename),
                            'sha256': _sha256(path), 'source_sha256': source_hash,
                            'width': width, 'height': height, 'renderer': 'powerpoint-native',
                            'hidden': metadata[index]['hidden'],
                            'warnings': metadata[index]['warnings'] + ['页面字体由本机 PowerPoint 解析；未验证缺失字体替换，请对照原稿预览。']}
        payload = {'version': _CACHE_VERSION, 'source_sha256': source_hash, 'pages': list(pages.values())}
        (staging / 'manifest.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        # Publish a complete directory only. Preserve an invalid old cache until ready.
        backup = None
        if cache.exists():
            backup = root / ('.invalid-' + uuid.uuid4().hex)
            cache.rename(backup)
        try:
            staging.rename(cache)
        except OSError:
            if backup is not None:
                backup.rename(cache)
            raise
        if backup is not None:
            shutil.rmtree(backup)
        return pages
    finally:
        if staging.exists():
            shutil.rmtree(staging)
