import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

from momoi.storage import Store


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
            targets = store.episode_relation_candidates(candidate, ["old"])
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
            assert store.episode_relation_candidates(candidate, [])[-1]["id"] == "old"
            store.finish_episode_relations("new", 2, [], {"old"})
            assert store._db.execute("SELECT count(*) FROM episode_relations").fetchone()[0] == 0
        finally:
            store.close()
