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

    def episode_relation_messages(self, episode_id: str) -> list[dict[str, object]]:
        """All delivered dialogue belonging to one Episode, in original order."""
        rows = self._db.execute(
            """SELECT m.id, m.role, m.content, m.created_at
               FROM episode_turns et JOIN messages m ON m.turn_id=et.turn_id
               WHERE et.episode_id=? AND (m.role='user' OR
                 (m.role='assistant' AND m.delivery_state IN ('delivered','uncertain')))
               ORDER BY et.ordinal, m.id""",
            (episode_id,),
        ).fetchall()
        return [{**dict(row), "timestamp": self.context_timestamp(row["created_at"])} for row in rows]

    def episode_relation_targets(self, source: dict[str, object], ranked_ids: list[str],
                                 limit: int = 8) -> list[dict[str, object]]:
        result = []
        for identifier in dict.fromkeys(ranked_ids):
            target = self.episode(identifier)
            if (target and target["created_at"] < source["created_at"]
                    and self._runtime_archive_kind(identifier) not in {"webhook", "heartbeat"}):
                result.append(target)
            if len(result) >= limit:
                break
        return result

    def finish_episode_relations(self, episode_id: str, ordinal: int,
                                 decisions: list[dict[str, str]], candidate_ids: set[str]) -> None:
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
            if target is None or float(target["created_at"]) >= float(source["created_at"]):
                raise ValueError("relation must point to an older episode")
            if item["relation"] not in {"follows_up", "revises", "context"}:
                raise ValueError("invalid relation")
            if any(not item[key].strip() or len(item[key]) > 300
                   for key in ("explanation", "source_evidence", "target_evidence")):
                raise ValueError("relation requires short evidence on both sides")
            source_text = str(source["narrative_summary"]) + " " + str(source["title"]) + " " + " ".join(
                str(message["content"]) for message in self.episode_relation_messages(episode_id))
            target_text = str(target["narrative_summary"]) + " " + str(target["title"]) + " " + " ".join(
                str(message["content"])[:500] for message in self.episode_relation_messages(target_id)[-6:])
            if item["source_evidence"] not in source_text:
                raise ValueError("source evidence is not in the source summary")
            if item["target_evidence"] not in target_text:
                raise ValueError("target evidence is not in the target summary")
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
