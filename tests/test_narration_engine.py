import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import narration_engine as engine


def source():
    return SimpleNamespace(index=1, title='试点结果', body='背景：本轮试点结束\n结论：收入增长20%\n仅限2025年试点客户\n步骤：检查适用范围', notes='[点击播放]')


def test_fallback_preserves_facts_and_has_real_style_organization():
    a = engine.generate_narrations([source()], presentation_style='internal-training')[1]
    b = engine.generate_narrations([source()], presentation_style='external-meeting', creative=True)[1]
    assert a['status'] == 'rules-fallback' and a['warnings']
    for r in (a, b):
        assert '20%' in r['text'] and '仅限2025年试点客户' in r['text']
        assert '点击播放' not in r['text']
    assert a['text'].index('步骤') < a['text'].index('结论')
    assert b['text'].index('结论') < b['text'].index('步骤')


def test_user_selection_can_silence_page():
    units = engine.classify_slides([source()])[1]
    r = engine.generate_narrations([source()], selections={1: {u['id']: 'skip' for u in units}})[1]
    assert r['text'] == '' and r['status'] == 'silent'


def model_response(text, ids):
    return httpx.Response(200, request=httpx.Request('POST', 'https://example.test/v1/chat/completions'), json={'choices': [{'message': {'content': json.dumps({'text': text, 'source_ids': ids})}}]})


def test_model_accepts_valid_structured_narration():
    s = source()
    ids = [u['id'] for u in engine.classify_slides([s])[1] if u['decision'] != 'skip']
    with patch('narration_engine.httpx.post', return_value=model_response(s.title + '\n' + s.body, ids)) as post:
        r = engine.generate_narrations([s], model_config={'base_url': 'https://example.test/v1', 'api_key': 'secret', 'model': 'text'})[1]
    assert r['status'] == 'model-generated'
    assert post.call_args.kwargs['timeout'] <= 60


def test_model_invented_number_or_lost_qualifier_falls_back():
    ids = [u['id'] for u in engine.classify_slides([source()])[1] if u['decision'] != 'skip']
    for text in ('收入增长90%，仅限2025年试点客户', '2025年收入增长20%'):
        with patch('narration_engine.httpx.post', return_value=model_response(text, ids)):
            r = engine.generate_narrations([source()], model_config={'model': 'text', 'base_url': 'https://example.test/v1'})[1]
        assert r['status'] == 'rules-fallback'
        assert '仅限2025年试点客户' in r['text']


def test_timeout_never_exposes_credentials():
    with patch('narration_engine.httpx.post', side_effect=httpx.ReadTimeout('secret-value')):
        r = engine.generate_narrations([source()], model_config={'model': 'text', 'api_key': 'secret-value', 'base_url': 'https://example.test/v1'})[1]
    assert 'secret-value' not in str(r)
    assert any('超时' in w for w in r['warnings'])


def test_rewrite_is_record_and_rejects_invalid_options():
    import unittest
    r = engine.rewrite_narration(source(), instruction='缩短')
    assert r['text'] and r['units']
    with unittest.TestCase().assertRaises(ValueError):
        engine.generate_narrations([source()], length='bad')


def test_explicit_empty_config_disables_environment_model():
    with patch.dict('os.environ', {'NARRATION_MODEL': 'text', 'NARRATION_API_BASE': 'https://example.test/v1'}), patch('narration_engine.httpx.post') as post:
        engine.generate_narrations([source()], model_config={})
    post.assert_not_called()


def test_model_can_classify_but_cannot_skip_key_qualifier():
    units = engine.classify_slides([source()])[1]
    ids = [u['id'] for u in units if u['decision'] != 'skip']
    payload = {'text': source().title + '\n' + source().body, 'source_ids': ids,
               'decisions': [{'id': units[1]['id'], 'decision': 'summarize', 'reason': '背景可简述'}]}
    engine._validate(payload, units)
    assert units[1]['decision'] == 'summarize'
    import unittest
    payload['decisions'] = [{'id': units[3]['id'], 'decision': 'skip', 'reason': '省略'}]
    with unittest.TestCase().assertRaises(ValueError):
        engine._validate(payload, units)


def test_changed_numeric_units_are_rejected():
    import unittest
    units = [{'id': 'u1', 'text': '收入20万元', 'source': 'body', 'decision': 'read', 'reason': '来源事实'}]
    with unittest.TestCase().assertRaises(ValueError):
        engine._validate({'text': '收入20亿元', 'source_ids': ['u1']}, units)


def test_rewrite_keeps_user_draft_when_model_unavailable():
    r = engine.rewrite_narration(source(), current_text='这是我修改后的讲解', instruction='扩写', model_config={})
    assert r['text'] == '这是我修改后的讲解'
    assert any('未执行' in w for w in r['warnings'])


def test_unknown_source_id_rejected():
    import unittest
    units = engine.classify_slides([source()])[1]
    with unittest.TestCase().assertRaises(ValueError):
        engine._validate({'text': source().body, 'source_ids': ['unknown']}, units)


def load_tests(loader, tests, pattern):
    import unittest
    return unittest.TestSuite(unittest.FunctionTestCase(value) for name, value in globals().items() if name.startswith('test_'))
