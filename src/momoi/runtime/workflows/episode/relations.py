"""Independent background workflow for relationships between Episodes."""

from __future__ import annotations

import asyncio
import logging
import uuid

from ....observability.context import log_context
from ....observability.events import log_event
from ....semantic.episode_relations import review_episode_relations
from ....storage.episode.episode_ranking import EpisodeRecallQuery

logger = logging.getLogger(__name__)


class EpisodeRelationWorkflow:
    async def _run_episode_relation_once(self) -> bool:
        episode = self.store.claim_episode_relation_candidate()
        if episode is None:
            return False
        episode_id = str(episode["id"])
        ordinal = int(episode["summarized_through_ordinal"])
        turn_id = self._turn_id("episode-relation", episode_id, ordinal)
        state = self.store.begin_turn(
            turn_id, "episode_relation", [f"episode-relation:{episode_id}:{ordinal}"],
        )
        if state == "cancelled":
            turn_id = self._turn_id("episode-relation", episode_id, ordinal, uuid.uuid4().hex)
            state = self.store.begin_turn(
                turn_id, "episode_relation", [f"episode-relation:{episode_id}:{ordinal}"],
            )
        if state != "running":
            self.store.release_episode_relation_candidate(episode_id)
            return False
        try:
            expressions = list(dict.fromkeys(
                [str(episode["title"]),
                 *(str(value) for value in episode.get("entities", [])),
                 *(str(value) for value in episode.get("topics", []))]
            ))[:4]
            queries = [EpisodeRecallQuery(value, priority=index)
                       for index, value in enumerate(expressions) if value.strip()]
            with log_context(turn_id=turn_id, stage="episode_relation"):
                evidence = await self.semantic_recall.prepare(
                    queries, include_memory=False, output_limit=12,
                )
                ranked = self.store.search_topic_queries(
                    queries, 16, dense_evidence=evidence, minimum_confidence=0,
                )
                candidates = self.store.episode_relation_candidates(
                    episode, [str(item["id"]) for item in ranked],
                )
                decisions = (await review_episode_relations(
                    self.provider, episode, candidates,
                    thinking_effort=self.config.thinking_stages.get("episode_relation", ""),
                )) if candidates else []
            self.store.finish_episode_relations(
                episode_id, ordinal, decisions,
                {str(item["id"]) for item in candidates},
            )
            self.store.complete_background_turn(turn_id)
            log_event(logger, logging.INFO, "episode_relations_reviewed",
                      stage="episode_relation", turn_id=turn_id, episode_id=episode_id,
                      candidate_count=len(candidates), relation_count=len(decisions))
            return True
        except asyncio.CancelledError:
            self.store.cancel_turn(turn_id, reason="episode_relation_interrupted")
            self.store.release_episode_relation_candidate(episode_id, failed=False)
            raise
        except Exception as error:
            self.store.cancel_turn(turn_id, reason=type(error).__name__)
            self.store.release_episode_relation_candidate(episode_id)
            raise
