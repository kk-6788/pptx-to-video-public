from types import SimpleNamespace

from narration_policy import classify_slides


def slide(index=1, **kw):
    return SimpleNamespace(index=index, title='', body='', notes='', text_content='', **kw)


def test_noise_and_qualifiers_are_separate_decisions():
    s = SimpleNamespace(index=1, title='结果', body='- 12\n- 收入增长20%\n- 仅限2025年试点客户', notes='[此处停顿]\n请注意适用范围')
    units = classify_slides([s])[1]
    by_text = {u['text']: u for u in units}
    assert by_text['12']['decision'] == 'review'
    assert by_text['[此处停顿]']['decision'] == 'skip'
    assert by_text['仅限2025年试点客户']['decision'] == 'read'
    assert all(u['id'] and u['source'] and u['reason'] for u in units)


def test_repeated_body_is_not_assumed_to_be_footer():
    slides = [SimpleNamespace(index=i, title='进展', body='增长20%', notes='') for i in (1, 2)]
    assert all(u['decision'] == 'read' for units in classify_slides(slides).values() for u in units)


def test_notes_ignore_and_uncertain_footnotes():
    s = SimpleNamespace(index=1, title='', body='* 数据来源：年度报告', notes='讲稿')
    units = classify_slides([s], notes_policy='ignore')[1]
    assert units[0]['decision'] == 'review'
    assert units[1]['decision'] == 'skip'


def test_structured_units_keep_ids_and_repeated_footer():
    slides = [SimpleNamespace(index=i, title='', body='', notes='', content_units=[
        {'id': f'{i}-f', 'text': '公司内部资料', 'source': 'shape:3', 'role': 'footer'}]) for i in (1, 2)]
    result = classify_slides(slides)
    assert result[2][0]['id'] == '2-f'
    assert result[2][0]['decision'] == 'skip'


def test_numeric_title_is_not_mistaken_for_page_number():
    s = SimpleNamespace(index=1, title='2026', body='第 1 页', notes='')
    units = classify_slides([s])[1]
    assert units[0]['decision'] == 'read'
    assert units[1]['decision'] == 'skip'


def load_tests(loader, tests, pattern):
    import unittest
    return unittest.TestSuite(unittest.FunctionTestCase(value) for name, value in globals().items() if name.startswith('test_'))
