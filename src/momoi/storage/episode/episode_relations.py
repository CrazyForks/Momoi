"""Independent, evidence-backed relations between summarized Episodes."""

from __future__ import annotations

import json
import time

from .episode_sql import runtime_archive_kind_sql


class EpisodeRelationStore:
    def claim_episode_relation_candidate(self) -> dict[str, object] | None:
        now = time.time()
        with self._db:
            row = self._db.execute(
                f"""SELECT e.* FROM conversation_episodes e
                   LEFT JOIN episode_relation_jobs j ON j.episode_id=e.id
                   WHERE e.created_at >= (SELECT enabled_at FROM episode_relation_settings WHERE id=1)
                     AND COALESCE({runtime_archive_kind_sql('e')}, '') NOT IN ('webhook', 'heartbeat')
                     AND e.narrative_summary<>''
                     AND e.summarized_through_ordinal>COALESCE(j.processed_ordinal, 0)
                     AND COALESCE(j.retry_at, 0)<=?
                     AND j.claimed_at IS NULL
                   ORDER BY e.created_at LIMIT 1""",
                (now,),
            ).fetchone()
            if row is None:
                return None
            self._db.execute(
                """INSERT INTO episode_relation_jobs(episode_id, claimed_at)
                   VALUES (?, ?) ON CONFLICT(episode_id) DO UPDATE SET claimed_at=excluded.claimed_at""",
                (row["id"], now),
            )
        return self._episode_dict(row)

    def finish_episode_relations(self, episode_id: str, ordinal: int,
                                 decisions: list[dict[str, str]], candidate_ids: set[str],
                                 *, evidence_records: dict[str, dict] | None = None) -> None:
        now = time.time()
        source = self.episode(episode_id)
        if source is None or int(source["summarized_through_ordinal"]) != ordinal:
            raise ValueError("episode summary changed during relation review")
        if len(decisions) > 4:
            raise ValueError("too many episode relations")
        seen: set[str] = set()
        for item in decisions:
            target_id = item["target_episode_id"]
            if target_id not in candidate_ids or target_id in seen:
                raise ValueError("unknown or duplicate relation target")
            target = self.episode(target_id)
            if (target is None or float(target["created_at"]) >= float(source["created_at"])
                    or self._runtime_archive_kind(target_id) in {"heartbeat", "webhook"}):
                raise ValueError("relation must point to an older episode")
            if item["relation"] not in {"follows_up", "revises", "context"}:
                raise ValueError("invalid relation")
            if any(not item[key].strip() or len(item[key]) > 300
                   for key in ("explanation", "source_evidence", "target_evidence")):
                raise ValueError("relation requires short evidence on both sides")
            source_fields = [str(source["narrative_summary"]), str(source["title"])]
            target_fields = [str(target["narrative_summary"]), str(target["title"])]
            if evidence_records is not None:
                source_fields = list(_evidence_text(evidence_records.get(episode_id, {})))
                target_fields = list(_evidence_text(evidence_records.get(target_id, {})))
            if not any(item["source_evidence"] in value for value in source_fields):
                raise ValueError("source evidence is not in the supplied episode")
            if not any(item["target_evidence"] in value for value in target_fields):
                raise ValueError("target evidence is not in the recalled episode")
            seen.add(target_id)
        with self._db:
            self._db.execute("DELETE FROM episode_relations WHERE source_episode_id=?", (episode_id,))
            for item in decisions:
                self._db.execute(
                    """INSERT INTO episode_relations
                       (source_episode_id,target_episode_id,relation,explanation,evidence_json,
                        source_summary_ordinal,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (episode_id, item["target_episode_id"], item["relation"], item["explanation"],
                     json.dumps({"source": item["source_evidence"], "target": item["target_evidence"]}, ensure_ascii=False),
                     ordinal, now, now),
                )
            self._db.execute(
                """UPDATE episode_relation_jobs SET processed_ordinal=?, claimed_at=NULL,
                   retry_at=0, failure_count=0, updated_at=? WHERE episode_id=?""",
                (ordinal, now, episode_id),
            )

    def release_episode_relation_candidate(self, episode_id: str, *, failed: bool = True) -> None:
        with self._db:
            row = self._db.execute("SELECT failure_count FROM episode_relation_jobs WHERE episode_id=?", (episode_id,)).fetchone()
            count = int(row[0]) + 1 if row and failed else 0
            self._db.execute(
                """UPDATE episode_relation_jobs SET claimed_at=NULL, failure_count=?, retry_at=?
                   WHERE episode_id=?""",
                (count, time.time() + min(3600, 60 * 2 ** min(count, 6)) if failed else 0, episode_id),
            )

    def next_episode_relation_retry_at(self) -> float | None:
        row = self._db.execute(
            """SELECT MIN(j.retry_at) FROM episode_relation_jobs j
               JOIN conversation_episodes e ON e.id=j.episode_id
               WHERE j.claimed_at IS NULL AND j.retry_at>0
                 AND e.summarized_through_ordinal>j.processed_ordinal"""
        ).fetchone()
        return float(row[0]) if row and row[0] is not None else None


def _evidence_text(value):
    """Use only text actually supplied to the relation model, including recall truncation."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"title", "summary", "content", "text", "assistant_text", "result", "arguments"}:
                if isinstance(child, str):
                    yield child
            if isinstance(child, (dict, list)):
                yield from _evidence_text(child)
    elif isinstance(value, list):
        for child in value:
            yield from _evidence_text(child)
