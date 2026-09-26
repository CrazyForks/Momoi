import json
from copy import deepcopy

from momoi.runtime.transcript.rendering import _native_exchange_messages


def exchange(identifier, name, result):
    return {'content': [{'type': 'tool_use', 'id': identifier, 'name': name,
                         'input': {'path': 'test.txt'}}],
            'results': [{'type': 'tool_result', 'tool_use_id': identifier,
                         'content': json.dumps(result, ensure_ascii=False)}]}


def results(messages):
    return [json.loads(b['content']) for m in messages for b in m['content']
            if b.get('type') == 'tool_result']


def test_history_preview_keeps_edges_reference_and_does_not_mutate_live_result():
    body = '开' * 80 + 'MIDDLE_SECRET' * 100 + '尾' * 80
    source = [exchange('a', 'read_tool_result', {
        'ok': True, 'content': body, 'result_ref': 'tr_original',
        'chunk_start': 100, 'chunk_end': 1500, 'next_cursor': 'cursor',
    })]
    original = deepcopy(source)
    replay = _native_exchange_messages(source)
    result = results(replay)[0]
    assert result['preview'] == '开' * 80 + '\n[...truncated...]\n' + '尾' * 80
    assert result['result_ref'] == 'tr_original'
    assert result['chunk_start'] == 100 and result['next_cursor'] == 'cursor'
    assert source == original
    assert replay == _native_exchange_messages(source)
    assert replay[0]['content'] == source[0]['content']


def test_error_run_preserves_pairing_distinct_errors_and_stops_at_success():
    source = [exchange(str(i), 'read_file', {
        'ok': False, 'error': error, 'message': 'details', 'result_ref': f'tr_{i}',
    }) for i, error in enumerate(['missing', 'missing', 'denied'])]
    source += [exchange('ok', 'read_file', {'ok': True}),
               exchange('next', 'read_file', {'ok': False, 'error': 'missing'}),
               exchange('other', 'exec', {'ok': False, 'error': 'missing'})]
    replay = _native_exchange_messages(source)
    output = results(replay)
    assert output[0]['error_run_count'] == 3
    assert [e['count'] for e in output[0]['errors']] == [2, 1]
    assert output[1]['error_summary_tool_use_id'] == '0'
    assert output[2]['result_ref'] == 'tr_2'
    assert output[3] == {'ok': True}
    assert output[4]['error'] == output[5]['error'] == 'missing'
    assert len(replay) == len(source) * 2
    for i, item in enumerate(source):
        assert replay[i * 2 + 1]['content'][0]['tool_use_id'] == item['content'][0]['id']


def test_structured_large_result_retains_failure_and_reference():
    source = [exchange('x', 'exec', {
        'ok': False, 'error': 'exit_nonzero', 'result_ref': 'tr_exec',
        'stdout': 'start' + 'x' * 3000 + 'end',
    })]
    result = results(_native_exchange_messages(source))[0]
    assert result['ok'] is False
    assert result['error'] == 'exit_nonzero'
    assert result['result_ref'] == 'tr_exec'
    assert '[...truncated...]' in result['preview']
    assert len(result['preview']) < 200


def test_recall_search_reuse_and_errors_are_never_compacted():
    source = [exchange(str(i), 'recall', payload) for i, payload in enumerate([
        {'ok': True, 'memory': 'evidence' * 1000, 'episodes': 'episode' * 1000},
        {'ok': True, 'status': 'reuse', 'memory': '', 'episodes': ''},
        {'ok': False, 'error': 'invalid_recall', 'message': 'details' * 1000},
        {'ok': False, 'error': 'invalid_recall', 'message': 'details' * 1000},
    ])]
    replay = _native_exchange_messages(source)
    for i, item in enumerate(source):
        assert replay[i * 2 + 1]['content'] == item['results']
