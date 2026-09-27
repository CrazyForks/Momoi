import json
import time
from types import SimpleNamespace

import pytest

from momoi.storage import Store
from momoi.runtime.agent.context_window import ContextWindow
from momoi.runtime.turn_support import context_data_message


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "memory.sqlite3")
    yield value
    value.close()


def add(store, text, activation="always", key="test"):
    with store._db:
        return store._db.execute(
            """INSERT INTO memories(kind,key,content,activation,authority,
               source_event_id,evidence_quote,created_at,updated_at)
               VALUES('preference',?,?,?,'owner','test','test',?,?)""",
            (key, text, activation, time.time(), time.time()),
        ).lastrowid


def test_dashboard_replace_delete_and_restart_preserve_snapshot(store):
    identifier = add(store, "旧偏好")
    first = store.transcript_memory_context(["a"])
    store.update_memory_content(identifier, "新偏好")
    changed = store.transcript_memory_context(["a", "b"])
    assert changed["snapshot"] == first["snapshot"]
    assert 'replace' in changed["events"][0]["content"]
    assert "新偏好" in changed["events"][0]["content"]
    assert store.active_memory("preference", "test")["content"] == "新偏好"
    store.forget_memory_by_id(identifier, "撤销")
    deleted = store.transcript_memory_context(["a", "b"])
    assert deleted["snapshot"] == first["snapshot"]
    assert '<delete' in deleted["events"][1]["content"]
    assert store.active_memory("preference", "test") is None
    # Read durable state through another connection, as after a restart.
    other = Store(store._db.execute("PRAGMA database_list").fetchone()[2])
    assert other.transcript_memory_context(["a", "b"]) == deleted
    folded = other.transcript_memory_context(["b"], compact=True)
    assert not folded["snapshot"]
    assert not folded["events"]
    assert '<delete' in folded["snapshot_overrides"][str(identifier)]
    other.close()


def test_add_activation_expiry_and_recall_only_changes(store):
    first = store.transcript_memory_context(["a"])
    identifier = add(store, "仅检索记忆", activation="recall")
    added = store.transcript_memory_context(["a"])
    assert added["snapshot"] == first["snapshot"]
    assert '<add' in added["events"][0]["content"]
    with store._db:
        store._db.execute("UPDATE memories SET activation='always' WHERE id=?", (identifier,))
    promoted = store.transcript_memory_context(["a"])
    assert '<replace' in promoted["events"][-1]["content"]
    with store._db:
        store._db.execute("UPDATE memories SET expires_at=1 WHERE id=?", (identifier,))
    expired = store.transcript_memory_context(["a"])
    assert '<delete' in expired["events"][-1]["content"]


def test_running_turn_appends_changes_then_compaction_folds_them(store):
    identifier = add(store, "旧偏好")
    state = store.transcript_memory_context(["a"])
    prefix = context_data_message(("long_term_memories", "旧偏好"), required=True)
    prefix["_memory_snapshot"] = {
        "revision": state["revision"], "turn_ids": ["a"],
        "current": "旧偏好", "goals": "", "overrides": "",
    }
    messages = [prefix, {"role": "user", "content": "历史" * 1000, "_history_turn_ids": ["a"]},
                {"role": "user", "content": "当前"}]
    original = json.dumps(prefix["content"])
    window = ContextWindow(SimpleNamespace(max_input_tokens=100000, context_compaction_ratio=1), store, None)
    store.update_memory_content(identifier, "新偏好")
    count = window.fit([], messages, [], 2)
    assert count == 2
    assert json.dumps(prefix["content"]) == original
    assert messages[-1]["_memory_change"]
    assert "新偏好" in messages[-1]["content"]
    length = len(messages)
    window.fit([], messages, [], 2)
    assert len(messages) == length
    window.config.max_input_tokens = 800
    count = window.fit([], messages, [], 2)
    assert count == 1
    assert "新偏好" in json.dumps(prefix["content"], ensure_ascii=False)
    assert not any(m.get("_memory_change") for m in messages)
    persisted = store.transcript_memory_context(["a"])
    assert not persisted["events"]
    assert persisted["snapshot"][str(identifier)]["content"] == "新偏好"


def test_fold_does_not_consume_newer_revision(store):
    identifier = add(store, "一")
    state = store.transcript_memory_context(["a"])
    store.update_memory_content(identifier, "二")
    updated = store.transcript_memory_context(["a"])
    store.fold_transcript_memory(state["revision"])
    assert store.transcript_memory_context(["a"]) == updated


def test_shared_workflows_replay_identical_prefix_and_changes(tmp_path):
    from momoi.models import IncomingMessage, AgentReply
    from momoi.config.models import AppConfig
    from momoi.integrations.models import LLMConfig
    from momoi.channel.napcat import NapCatConfig
    from momoi.runtime import MomoiDaemon
    from tests.support import provider_catalog

    daemon = MomoiDaemon(AppConfig(
        providers=provider_catalog(LLMConfig("http://localhost", "test", "model", 100, 0, 1, 0)),
        channel=NapCatConfig("ws://localhost", "123", 1, 60, 30, 30, 20),
        system_prompt="test", transcript_turns_min=8, transcript_turns_max=16,
        episode_unsummarized_tail_turns=2, memory_results=2,
        database=tmp_path / "shared.sqlite3", log_level="INFO",
    ))
    store = daemon.store
    identifier = add(store, "旧记忆")
    event = IncomingMessage("past", "1", "过去", 1, 1)
    store.add_event(event)
    store.commit_turn([event], event.text, AgentReply(["回答"]), turn_id="past")
    store.append_turn_journal("past", "assistant_exchange", {
        "content": "内部判断", "results": [],
    }, trust="runtime")
    stages = ("owner", "heartbeat", "goal", "webhook", "reply_followup",
              "plan_step", "current_state_maintenance")
    for stage in stages:
        store.begin_turn(stage, stage, [stage])
    with store._db:
        store._db.execute("UPDATE turns SET started_at=? WHERE id != 'past'", (time.time(),))
    baseline = daemon.shared_turn_context("owner")["messages"]
    store.update_memory_content(identifier, "新记忆")
    contexts = [daemon.shared_turn_context(stage)["messages"] for stage in stages]
    assert len({json.dumps(c, sort_keys=True) for c in contexts}) == 1
    assert contexts[0][0]["content"] == baseline[0]["content"]
    assert contexts[0][:-1][1:] == baseline[1:]
    assert contexts[0][-1]["_memory_change"]
    assert "新记忆" in contexts[0][-1]["content"]
    store.transcript_window_turn_limit(8, 16, force_compact=True)
    compacted = daemon.shared_turn_context("owner")["messages"]
    assert "新记忆" in json.dumps(compacted[0]["content"], ensure_ascii=False)
    assert not any(m.get("_memory_change") for m in compacted)
    store.close()


def test_running_request_sees_changes_folded_by_another_executor(store):
    identifier = add(store, "旧偏好")
    state = store.transcript_memory_context(["a"])
    prefix = context_data_message(("long_term_memories", "旧偏好"), required=True)
    prefix["_memory_snapshot"] = {
        "revision": state["revision"], "turn_ids": ["a"],
        "current": "旧偏好", "goals": "", "overrides": "",
    }
    store.forget_memory_by_id(identifier, "撤销")
    folded = store.transcript_memory_context(["b"], compact=True)
    assert not folded["events"]
    messages = [prefix, {"role": "user", "content": "当前"}]
    window = ContextWindow(SimpleNamespace(max_input_tokens=100000, context_compaction_ratio=1), store, None)
    window.fit([], messages, [], 1)
    assert '<delete' in messages[-1]["content"]
    assert messages[-1]["_memory_change"] == folded["revision"]
    assert store.transcript_memory_context(["b"])["boundary"] == "b"


def test_existing_window_adopts_history_format_only_after_compaction(tmp_path):
    import json
    from momoi.storage import Store
    store = Store(tmp_path / 'format.db')
    state = store.transcript_memory_context(['old'])
    del state['history_format']
    store._db.execute('UPDATE transcript_memory_state SET data_json=? WHERE id=1', (json.dumps(state),))
    store._db.commit()
    assert store.transcript_memory_context(['old'])['history_format'] == 1
    assert store.transcript_memory_context(['old'], compact=True)['history_format'] == 3
    assert store.transcript_memory_context(['old'])['history_format'] == 3
    store.close()
