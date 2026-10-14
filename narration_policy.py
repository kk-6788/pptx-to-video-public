"""Conservative, inspectable narration choices; never deletes source content."""
from __future__ import annotations

from collections import Counter
import re

DECISIONS = {'read', 'summarize', 'skip', 'review'}
NOTES_POLICIES = {'ignore', 'reference', 'prefer'}
QUALIFIER_RE = re.compile(r'仅|只限|不含|不包括|除外|除非|如果|假设|预计|可能|至少|至多|不超过|截至|口径|条件|范围|免责|不得|禁止|不适用|未|不保证|试点|同比|环比|税前|税后|含税|不含税|approximately|only|unless|except|may|not\b', re.I)
NUMBER_RE = re.compile(r'(?<!\w)[+-]?\d+(?:[.,]\d+)*(?:\s*[%％])?|\d+(?:[.,]\d+)*(?:\s*[%％])?')
_PAGE = re.compile(r'^(?:第\s*)?\d+\s*(?:页)?(?:\s*[/／]\s*\d+)?$')
_STAGE = re.compile(r'^[\[【（(]?\s*(?:此处)?(?:停顿|点击播放|点击下一页|切换幻灯片|播放视频|等待掌声|pause|click to play)\s*[。.!！]?\s*[\]】）)]?$', re.I)


def _lines(text):
    return [re.sub(r'^\s*(?:[-•*]\s+|#+\s*)', '', line).strip() for line in str(text or '').splitlines() if line.strip()]


def _units(slide):
    structured = getattr(slide, 'content_units', None)
    units = []
    if structured:
        for n, item in enumerate(structured):
            item = dict(item) if isinstance(item, dict) else vars(item).copy()
            if str(item.get('text', '')).strip():
                item.update(id=str(item.get('id') or f'{slide.index}:unit:{n}'), text=str(item['text']).strip(), source=str(item.get('source') or 'body'))
                units.append(item)
    else:
        title = getattr(slide, 'title', '')
        body = getattr(slide, 'body', '')
        if not body:
            body = getattr(slide, 'text_content', '')
        for source, text in [('title', title), ('body', body), ('notes', getattr(slide, 'notes', ''))]:
            for n, line in enumerate(_lines(text)):
                units.append({'id': f'{slide.index}:{source}:{n}', 'text': line, 'source': source})
    # Structured parsers may omit speaker notes; always retain their source records.
    if structured and not any(u['source'] == 'notes' for u in units):
        for n, line in enumerate(_lines(getattr(slide, 'notes', ''))):
            units.append({'id': f'{slide.index}:notes:{n}', 'text': line, 'source': 'notes'})
    return units


def classify_slides(slides, notes_policy='reference') -> dict[int, list[dict]]:
    if notes_policy not in NOTES_POLICIES:
        raise ValueError('未知备注策略')
    source = {s.index: _units(s) for s in slides}
    repeated = Counter(u['text'] for units in source.values() for u in units if u.get('role') in {'footer', 'header'})
    for units in source.values():
        seen = set()
        for u in units:
            text = u['text']
            decision, reason = 'read', '保留来源事实'
            if u['source'] == 'notes' and notes_policy == 'ignore':
                decision, reason = 'skip', '用户选择不用备注'
            elif u['source'] == 'notes' and _STAGE.fullmatch(text):
                decision, reason = 'skip', '独立舞台指示，不是旁白'
            elif _PAGE.fullmatch(text) and u['source'] != 'title' and u.get('kind') not in {'table', 'chart'}:
                if '页' in text or u.get('role') == 'footer':
                    decision, reason = 'skip', '明确页码或页脚中的页码'
                else:
                    decision, reason = 'review', '独立数字可能是数据，无法确定为页码；保留朗读并请核对'
            elif QUALIFIER_RE.search(text):
                reason = '保留影响事实含义的范围、口径或限制条件'
            elif text in seen:
                decision, reason = 'skip', '本页完全重复的文字，前一来源已保留'
            elif u.get('role') in {'footer', 'header'} and repeated[text] > 1 and not NUMBER_RE.search(text):
                decision, reason = 'skip', '已识别为跨页重复页眉或页脚'
            elif u.get('role') in {'footnote', 'disclaimer'} or any(w in text for w in ('数据来源', '参考资料', '免责声明')):
                decision, reason = 'review', '引用或脚注含义需人工确认；基础讲稿暂保留'
            elif u.get('kind') in {'table', 'chart'} or text in {'目录', '议程'}:
                decision, reason = 'summarize', '宜概括；规则模式保留原文，不推断趋势'
            elif u['source'] == 'notes' and notes_policy == 'prefer':
                reason = '优先组织讲者备注；保留页面事实和限制条件'
            u.update(decision=decision, reason=reason)
            if decision != 'skip':
                seen.add(text)
    return source
