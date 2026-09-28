import json

from momoi.storage import Store
from momoi.storage.episode.execution_evidence import execution_turns, eligible
from momoi.storage.episode.episode_ranking import EpisodeRecallQuery
from momoi.runtime.context.rendering import episode_recall_records


def setup(store, turn='t', ordinal=1):
    if not store.episode('e'):
        store.create_episode('一次操作', episode_id='e')
    store.begin_turn(turn, 'owner', [])
    store._db.execute('INSERT INTO episode_turns(episode_id,turn_id,ordinal,relation) VALUES(?,?,?,?)',
                      ('e', turn, ordinal, 'primary'))
    store._db.commit()


def record(store, name, text='', args=None, turn='t', identifier='c', result=None):
    store.append_turn_journal(turn, 'assistant_exchange', {
        'content': [{'type': 'text', 'text': text}, {'type': 'tool_use', 'id': identifier,
                    'name': name, 'input': args or {}}],
        'results': [{'type': 'tool_result', 'tool_use_id': identifier,
                     'content': json.dumps(result or {'ok': True, 'result_ref': 'tr_x'})}]},
        visibility='internal', trust='runtime')


def test_execution_only_keyword_admits_topic_and_returns_paired_evidence(tmp_path):
    store = Store(tmp_path / 'db')
    setup(store)
    record(store, 'write_file', '热量账写在这里', {'path': '/diet.md', 'content': 'x' * 1000})
    hits = store.search_topic_queries([EpisodeRecallQuery('diet.md')], 5, minimum_confidence=0)
    assert [h['id'] for h in hits] == ['e']
    assert hits[0]['execution_evidence']['turns'][0]['execution'][0]['tools'][0]['name'] == 'write_file'
    records = episode_recall_records(store, [{'episode_id': 'e', 'matched_keywords': ['diet.md']}], 3000)
    call = records[0]['turns'][0]['execution'][0]['tools'][0]
    assert call['arguments']['path'] == '/diet.md'
    assert call['arguments_truncated']
    assert call['result']['result_ref'] == 'tr_x'
    assert call['call_id'] == 'c'
    assert '热量账' in records[0]['turns'][0]['execution'][0]['assistant_text']
    assert store.search_topic_queries([EpisodeRecallQuery('热量账')], 5, minimum_confidence=0)
    store.close()


def test_excluded_calls_and_their_commentary_never_searchable(tmp_path):
    store = Store(tmp_path / 'db'); setup(store)
    for name in ['recall', 'end_turn', 'send_bubbles', 'send_voice']:
        record(store, name, '不能检索的开场', {'query': '禁止关键词'})
    assert not store.search_topic_queries([EpisodeRecallQuery('禁止关键词')], 5, minimum_confidence=0)
    assert not store.search_topic_queries([EpisodeRecallQuery('不能检索的开场')], 5, minimum_confidence=0)
    assert 'execution' not in execution_turns(store, 'e')['turns'][0]
    store.close()


def test_missing_journal_distinct_from_no_eligible_tools_and_time_filter(tmp_path):
    store = Store(tmp_path / 'db'); setup(store)
    assert execution_turns(store, 'e')['turns'][0]['journal_available'] is False
    record(store, 'end_turn')
    assert 'journal_available' not in execution_turns(store, 'e')['turns'][0]
    assert execution_turns(store, 'e', before=1)['turns'] == []
    store.close()


def test_deep_read_pages_execution_and_preserves_source(tmp_path):
    store = Store(tmp_path / 'db'); setup(store)
    for i in range(15):
        record(store, 'exec', args={'command': f'command{i}'}, identifier=str(i))
    first = execution_turns(store, 'e', turn_id='t', tool_limit=12)['turns'][0]
    assert len(first['execution']) == 12
    second = execution_turns(store, 'e', turn_id='t', after_sequence=first['next_after_sequence'], tool_limit=12)['turns'][0]
    assert len(second['execution']) == 3
    assert second['execution'][0]['tools'][0]['call_id'] == '12'
    assert len(store.turn_exchanges(['t'])['t']) == 15
    assert 'turns' in store.conversation_episode('e')
    store.close()


def test_matching_middle_content_is_preserved_and_budget_keeps_valid_json(tmp_path):
    store = Store(tmp_path / 'db'); setup(store)
    record(store, 'exec', '开' * 300 + '特定操作' + '尾' * 300,
           {'command': 'x' * 300 + '特定操作' + 'y' * 300})
    entry = execution_turns(store, 'e', ['特定操作'])['turns'][0]['execution'][0]
    assert '特定操作' in entry['assistant_text'] and len(entry['assistant_text']) <= 100
    assert '特定操作' in entry['tools'][0]['arguments']['command']
    data = episode_recall_records(store, [{'episode_id': 'e', 'matched_keywords': ['特定操作']}], 150)
    assert json.loads(json.dumps(data)) == data
    store.close()


def test_deep_read_keeps_batched_calls_together_at_page_boundary(tmp_path):
    store = Store(tmp_path / 'db'); setup(store)
    for i in range(11):
        record(store, 'exec', identifier=str(i))
    store.append_turn_journal('t', 'assistant_exchange', {
        'content': [{'type': 'tool_use', 'id': str(i), 'name': 'exec', 'input': {}} for i in range(11, 14)],
        'results': []}, visibility='internal', trust='runtime')
    first = execution_turns(store, 'e', turn_id='t', tool_limit=12)['turns'][0]
    second = execution_turns(store, 'e', turn_id='t', after_sequence=first['next_after_sequence'])['turns'][0]
    assert len(first['execution']) == 11
    assert [c['call_id'] for c in second['execution'][0]['tools']] == ['11', '12', '13']
    assert all(c['result']['error'] == 'result_not_recorded' for c in second['execution'][0]['tools'])
    store.close()


def test_episode_read_tool_execution_cursor_validation(tmp_path):
    from momoi.tools.memory import MemoryTools
    store = Store(tmp_path / 'db'); setup(store); record(store, 'exec')
    tool = MemoryTools(store)
    result = tool._episode_read({'episode_id': 'e', 'turn_id': 't'})
    assert result['ok'] and result['turns'][0]['execution'][0]['tools'][0]['name'] == 'exec'
    for args, error in [({'after_sequence': 1}, 'turn_id_required'),
                        ({'turn_id': 'missing'}, 'episode_turn_not_found'),
                        ({'turn_id': 't', 'after_sequence': -1}, 'invalid_execution_cursor'),
                        ({'turn_id': 't', 'message_id': 1}, 'conflicting_execution_cursor')]:
        assert tool._episode_read({'episode_id': 'e', **args})['error'] == error
    store.close()
