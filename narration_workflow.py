"""Shared final-script boundary for the desktop and command-line workflows."""
from __future__ import annotations

from pathlib import Path


def apply_records(plans, records):
    """Assign explicit per-page scripts; empty text represents intentional silence."""
    from faithful_plan import _reading_seconds
    for plan in plans:
        indices = getattr(plan, 'slide_indices', None) or [plan.slide_index]
        missing = set(indices) - set(records)
        if missing:
            raise ValueError(f'讲稿缺少来源页：{sorted(missing)}')
        plan.narration_by_slide = {i: records[i]['text'] for i in indices}
        plan.narration_text = ''.join(plan.narration_by_slide.values())
        plan.subtitle_text = plan.narration_text
        plan.narration_state = 'generated'
        plan.narration_units_by_slide = {i: records[i].get('units', []) for i in indices}
        plan.narration_warnings_by_slide = {i: records[i].get('warnings', []) for i in indices}
        plan.narration_status_by_slide = {i: records[i].get('status', 'rules') for i in indices}
        # Original pages are static, so duration no longer depends on card pagination.
        if getattr(plan, 'visual_mode', '') == 'faithful':
            plan.suggested_duration_sec = max(5., _reading_seconds(plan.narration_text) + 1.5)


def prepare_scripts(input_path, slides, plans, *, settings=None, project_path=None, offline=False, records=None):
    from narration_project import NarrationProject
    from narration_engine import generate_narrations
    settings = dict(settings or {})
    if project_path:
        project = NarrationProject.load(project_path)
        project.validate_source(input_path)
        plans[:] = project.build_plans(slides)
        return project
    records = records if records is not None else generate_narrations(slides,
        presentation_style=settings.get('presentation_style', 'auto'),
        length=settings.get('length', 'standard'), notes_policy=settings.get('notes_policy', 'reference'),
        creative=settings.get('visual_mode') == 'creative',
        model_config={} if offline else None)
    apply_records(plans, records)
    project = NarrationProject.from_plans(input_path, slides, plans, settings=settings)
    for i, record in records.items():
        segment = project.segments[i]
        segment.units = record.get('units', [])
        segment.warnings = record.get('warnings', [])
        segment.status = record.get('status', 'rules')
    project.apply_to_plans(plans)
    return project


def source_ratio(slides, ratio):
    if ratio != 'original':
        return ratio
    first = slides[0]
    width, height = getattr(first, 'page_width', 0), getattr(first, 'page_height', 0)
    if width <= 0 or height <= 0:
        import config
        config.set_ratio('16:9')
        return '16:9'
    import config
    target_width = 1920 if width >= height else 1080
    target_height = round(target_width * height / width / 2) * 2
    config.VIDEO_SIZE = f'{target_width}x{max(2, target_height)}'
    return 'original'


def attach_original_pages(slides):
    from pptx_page_renderer import render_pptx_pages
    sources = {getattr(slide, 'source_path', '') for slide in slides}
    if len(sources) != 1 or not next(iter(sources)):
        raise ValueError('原页播放需要原始 PPTX 文件，请重新选择文件并规划。')
    source = next(iter(sources))
    import config
    import hashlib
    key = hashlib.sha256(str(Path(source).resolve()).encode('utf-8')).hexdigest()[:16]
    pages = render_pptx_pages(source, config.ensure_temp_dir() / 'original-pages' / key,
                              include_hidden=any(getattr(s, 'hidden', False) for s in slides))
    for slide in slides:
        if slide.index not in pages:
            raise ValueError(f'原始页面渲染缺少第 {slide.index} 页')
        slide.original_page = pages[slide.index]
    return pages
