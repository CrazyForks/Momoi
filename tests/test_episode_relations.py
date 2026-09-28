import tempfile
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from pathlib import Path

import pytest

from momoi.storage import Store
from momoi.models import ToolCall
from momoi.runtime.workflows.episode.relations import EpisodeRelationWorkflow


def _summarize(store, identifier, title, summary, created_at):
    store.create_episode(title, episode_id=identifier)
    with store._db:
        store._db.execute(
            """UPDATE conversation_episodes SET narrative_summary=?,
               summarized_through_ordinal=1, created_at=? WHERE id=?""",
            (summary, created_at, identifier),
        )


def test_new_episode_only_and_empty_review_is_durable():
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory) / "db")
        try:
            enabled_at = store._db.execute(
                "SELECT enabled_at FROM episode_relation_settings WHERE id=1"
            ).fetchone()[0]
            _summarize(store, "old", "此前分手", "老师此前说自己分手了", enabled_at - 10)
            _summarize(store, "new", "发现戒指", "发现仍戴着前女友做的戒指", enabled_at + 10)
            candidate = store.claim_episode_relation_candidate()
            assert candidate["id"] == "new"
            targets = store.episode_relation_targets(candidate, ["old"])
            assert [item["id"] for item in targets] == ["old"]
            store.finish_episode_relations("new", 1, [], {"old"})
            assert store.claim_episode_relation_candidate() is None
            assert store._db.execute("SELECT count(*) FROM episode_relations").fetchone()[0] == 0
        finally:
            store.close()


def test_relation_validation_and_updated_summary_rechecks():
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory) / "db")
        try:
            enabled_at = store._db.execute(
                "SELECT enabled_at FROM episode_relation_settings WHERE id=1"
            ).fetchone()[0]
            _summarize(store, "old", "此前分手", "老师此前说自己分手了", enabled_at - 10)
            _summarize(store, "new", "发现戒指", "发现仍戴着前女友做的戒指", enabled_at + 10)
            candidate = store.claim_episode_relation_candidate()
            decision = {
                "target_episode_id": "old", "relation": "follows_up",
                "explanation": "新经历谈到此前的分手", "source_evidence": "前女友做的戒指",
                "target_evidence": "自己分手了",
            }
            with pytest.raises(ValueError):
                store.finish_episode_relations("new", 1, [decision], set())
            store.finish_episode_relations("new", 1, [decision], {"old"})
            assert store._db.execute("SELECT relation FROM episode_relations").fetchone()[0] == "follows_up"
            with store._db:
                store._db.execute(
                    "UPDATE conversation_episodes SET summarized_through_ordinal=2 WHERE id='new'"
                )
            candidate = store.claim_episode_relation_candidate()
            assert candidate["id"] == "new"
            assert store.episode_relation_targets(candidate, ["old"])[-1]["id"] == "old"
            store.finish_episode_relations("new", 2, [], {"old"})
            assert store._db.execute("SELECT count(*) FROM episode_relations").fetchone()[0] == 0
        finally:
            store.close()


def test_heartbeat_and_webhook_archives_are_not_summarized_or_linked():
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory) / "db")
        try:
            enabled_at = store._db.execute(
                "SELECT enabled_at FROM episode_relation_settings WHERE id=1"
            ).fetchone()[0]
            for kind in ("heartbeat", "webhook"):
                _summarize(store, kind, f"{kind}归档", "归档摘要", enabled_at + 1)
                with store._db:
                    store._db.execute(
                        "UPDATE conversation_episodes SET archive_kind=? WHERE id=?",
                        (kind, kind),
                    )
            _summarize(store, "owner", "用户话题", "用户话题摘要", enabled_at + 2)
            assert store.claim_episode_relation_candidate()["id"] == "owner"
            owner = store.episode("owner")
            assert store.episode_relation_targets(owner, ["heartbeat", "webhook"]) == []
            assert store.claim_episode_annealing_candidate(1, 1000) is None
        finally:
            store.close()


def test_workflow_model_chooses_query_then_finishes():
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory) / "db")
        try:
            enabled_at = store._db.execute("SELECT enabled_at FROM episode_relation_settings").fetchone()[0]
            _summarize(store, "old", "此前分手", "老师此前说自己分手了", enabled_at - 10)
            _summarize(store, "new", "发现戒指", "发现仍戴着前女友做的戒指", enabled_at + 10)

            class Runner(EpisodeRelationWorkflow):
                async def _run_agent_workflow(self, system, messages, tools, turn_id, workflow):
                    assert "发现仍戴着前女友做的戒指" in messages[0]["content"]
                    assert not semantic.prepare.called
                    result = await workflow.execute_tool(ToolCall("recall", "recall", {"query": "分手"}))
                    assert result["results"][0]["id"] == "old"
                    result = await workflow.execute_tool(ToolCall("finish", "episode_relation_finish", {"relations": [{
                        "target_episode_id": "old", "relation": "follows_up",
                        "explanation": "分手后的物件回忆", "source_evidence": "前女友做的戒指",
                        "target_evidence": "自己分手了",
                    }]}))
                    assert result["ok"] and workflow.is_complete()
                    return workflow.completion_result()

            semantic = SimpleNamespace(prepare=AsyncMock(return_value=None))
            runner = Runner()
            runner.store = store
            runner.semantic_recall = semantic
            asyncio.run(runner._build_episode_relations(store.episode("new"), 1, "test"))
            assert semantic.prepare.call_args.args[0][0].expression == "分手"
            assert store._db.execute("SELECT count(*) FROM episode_relations").fetchone()[0] == 1
        finally:
            store.close()
