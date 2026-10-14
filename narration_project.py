"""Portable final scripts, explicitly associated with their source presentation."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
import hashlib
import json
from pathlib import Path
import re

VISUAL_FIELDS = ('slide_index', 'slide_indices', 'image_prompt', 'image_prompts',
                 'video_prompt', 'director_vision', 'suggested_duration_sec',
                 'visual_mode', 'transition_type', 'transition_description',
                 'camera_angle', 'narrative_bridge', 'narration_style')


def _safe_settings(value):
    if isinstance(value, dict):
        return {str(k): _safe_settings(v) for k, v in value.items()
                if not re.search(r'key|token|secret|password|credential|authorization|cookie', str(k), re.I)}
    if isinstance(value, (list, tuple)):
        return [_safe_settings(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError('项目设置必须为 JSON 数据')


def _digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


@dataclass
class ScriptSegment:
    slide_index: int
    text: str = ''
    initial_text: str = ''
    locked: bool = False
    muted: bool = False
    modified: bool = False
    revision: int = 0

    units: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: str = 'generated'
    source_text: str = ''
    title: str = ''

    @property
    def segment_id(self):
        return f'slide-{self.slide_index}'


@dataclass
class NarrationProject:
    source_path: str
    source_sha256: str
    segments: dict[int, ScriptSegment] = field(default_factory=dict)
    settings: dict = field(default_factory=dict)
    schema_version: int = 1
    revision: int = 0
    visual_plans: list[dict] = field(default_factory=list)

    @classmethod
    def from_plans(cls, input_path, slides, plans, settings=None):
        text_by_page, muted_by_page, states = {}, {}, {}
        for plan in plans:
            indices = getattr(plan, 'slide_indices', None) or [plan.slide_index]
            mapping = getattr(plan, 'narration_by_slide', {}) or {}
            for position, index in enumerate(indices):
                # A legacy merged scene is assigned once, never repeated for each page.
                text_by_page[index] = mapping.get(index, mapping.get(str(index), getattr(plan, 'narration_text', '') if position == 0 else ''))
                muted_by_page[index] = (getattr(plan, 'narration_muted_by_slide', {}) or {}).get(index, False)
                states[index] = getattr(plan, 'narration_state', 'generated')
        project = cls(str(Path(input_path).resolve()), _digest(input_path), settings=_safe_settings(settings or {}))
        project.visual_plans = [{key: deepcopy(getattr(plan, key)) for key in VISUAL_FIELDS if hasattr(plan, key)} for plan in plans]
        for slide in slides:
            if slide.index not in text_by_page:
                continue
            units = []
            for unit in getattr(slide, 'content_units', []) or []:
                units.append(asdict(unit) if is_dataclass(unit) else deepcopy(unit))
            text = text_by_page[slide.index]
            project.segments[slide.index] = ScriptSegment(slide.index, text, text,
                muted=bool(muted_by_page[slide.index]), modified=states[slide.index] == 'edited',
                source_text='\n'.join(filter(None, [getattr(slide, 'text_content', '') or getattr(slide, 'body', ''), getattr(slide, 'notes', '')])),
                title=slide.title, units=units)
        return project

    def get_segment(self, slide_index):
        return self.segments[int(slide_index)]

    def update_segment(self, slide_index, *, text=None, locked=None, muted=None, units=None, expected_revision=None):
        segment = self.get_segment(slide_index)
        if expected_revision is not None and segment.revision != expected_revision:
            raise ValueError('此页讲稿已更新，请重新预览后应用')
        edits = {k: deepcopy(v) for k, v in {'text':text, 'locked':locked, 'muted':muted, 'units':units}.items()
                 if v is not None and v != getattr(segment, k)}
        if segment.locked and any(k != 'locked' for k in edits):
            raise ValueError('此页已锁定，请先解锁')
        if edits:
            for key, value in edits.items():
                setattr(segment, key, value)
            segment.revision += 1
            self.revision += 1
            if any(k != 'locked' for k in edits):
                segment.modified = True
                segment.status = '用户修改、未验证'
        return segment

    def restore_initial(self, slide_index):
        return self.update_segment(slide_index, text=self.get_segment(slide_index).initial_text)

    def validate_source(self, input_path):
        if _digest(input_path) != self.source_sha256:
            raise ValueError('来源 PPT 已变化，旧讲稿不能自动绑定；请重新分析并核对页面')
        return True

    def apply_to_plans(self, plans):
        indices_by_plan = [getattr(plan, 'slide_indices', None) or [plan.slide_index] for plan in plans]
        if any(index not in self.segments for indices in indices_by_plan for index in indices):
            raise ValueError('计划包含项目中不存在的来源页面')
        for plan, indices in zip(plans, indices_by_plan):
            plan.narration_by_slide = {i: '' if self.segments[i].muted else self.segments[i].text for i in indices}
            plan.narration_muted_by_slide = {i: self.segments[i].muted for i in indices}
            plan.narration_text = ''.join(plan.narration_by_slide.values())
            plan.subtitle_text = plan.narration_text
            plan.narration_state = 'edited' if any(self.segments[i].modified for i in indices) else 'generated'
            plan.narration_voice = self.settings.get('voice', 'zh-CN-XiaoxiaoNeural')
            plan.narration_rate = self.settings.get('rate', '+0%')
        return plans

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data['settings'] = _safe_settings(self.settings)
        data['segments'] = [asdict(segment) for segment in self.segments.values()]
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        temporary.replace(path)
        return path

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if not isinstance(data, dict) or data.get('schema_version') != 1:
            raise ValueError('不支持的讲稿项目版本')
        if not isinstance(data.get('source_path'), str) or not re.fullmatch(r'[0-9a-f]{64}', data.get('source_sha256', '')):
            raise ValueError('项目缺少有效来源摘要')
        raw_segments = data.get('segments')
        if not isinstance(raw_segments, list):
            raise ValueError('项目页面格式错误')
        segments = {}
        try:
            for raw in raw_segments:
                segment = ScriptSegment(**raw)
                if type(segment.slide_index) is not int or segment.slide_index < 1 or segment.slide_index in segments:
                    raise ValueError('项目页面编号无效或重复')
                if not isinstance(segment.text, str) or not isinstance(segment.initial_text, str):
                    raise ValueError('讲稿必须是文本')
                if type(segment.revision) is not int or segment.revision < 0 or any(type(getattr(segment, k)) is not bool for k in ('locked', 'muted', 'modified')):
                    raise ValueError('页面状态格式错误')
                if not isinstance(segment.units, list) or any(not isinstance(u, dict) for u in segment.units):
                    raise ValueError('内容单元格式错误')
                segments[segment.slide_index] = segment
        except TypeError as exc:
            raise ValueError('项目页面字段错误') from exc
        visual_plans = data.get('visual_plans', [])
        if not isinstance(visual_plans, list) or any(not isinstance(plan, dict) for plan in visual_plans):
            raise ValueError('画面计划格式错误')
        visual_plans = [{k: v for k, v in plan.items() if k in VISUAL_FIELDS} for plan in visual_plans]
        return cls(data['source_path'], data['source_sha256'], segments, _safe_settings(data.get('settings', {})), revision=data.get('revision', 0), visual_plans=visual_plans)

    def build_plans(self, slides):
        """Rebuild trusted source facts; restore only the saved visual parameters."""
        from prompt_engine import EnhancedScenePlan
        slides = list(slides)
        slide_by_index = {slide.index: slide for slide in slides}
        if set(slide_by_index) != set(self.segments):
            raise ValueError('来源页面与讲稿项目不匹配，请重新核对')
        if not self.visual_plans:
            mode = self.settings.get('visual_mode', 'faithful')
            records = [{'slide_index': i, 'slide_indices': [i], 'visual_mode': mode} for i in self.segments]
        else:
            records = deepcopy(self.visual_plans)
        plans = []
        covered = []
        for record in records:
            indices = record.get('slide_indices') or [record.get('slide_index')]
            if any(type(index) is not int or index not in slide_by_index for index in indices):
                raise ValueError('保存的画面计划引用无效页面')
            covered.extend(indices)
            if record.get('visual_mode') == 'faithful':
                from faithful_plan import build_faithful_plans
                if len(indices) != 1:
                    raise ValueError('原页播放计划必须逐页对应')
                plan = build_faithful_plans([slide_by_index[indices[0]]], narration_style=record.get('narration_style', 'direct'))[0]
                for key, value in record.items():
                    setattr(plan, key, value)
            else:
                plan = EnhancedScenePlan(**record)
            plans.append(plan)
        if covered != list(self.segments):
            raise ValueError('保存的画面计划页序、覆盖范围或分组无效')
        return self.apply_to_plans(plans)

    def export_script(self, path):
        markdown = Path(path).suffix.lower() in {'.md', '.markdown'}
        sections = []
        for segment in self.segments.values():
            heading = f'第 {segment.slide_index} 页 — {segment.title}'
            sections.append(('## ' if markdown else '') + heading + '\n\n' + ('[静音]' if segment.muted else segment.text))
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text('\n\n'.join(sections) + '\n', encoding='utf-8')
        return Path(path)
