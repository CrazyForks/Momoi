"""Durable memory snapshot and append-only changes for the shared transcript."""
import json
import time
from xml.sax.saxutils import quoteattr

from ..core.transactions import transaction
from .memory_values import format_memory


class TranscriptMemoryStore:
    def transcript_memory_context(self, turn_ids, *, compact=False, track_boundary=True):
        """Observe committed effective memory, retaining the prefix until compaction.

        Compare the complete effective inventory so dashboard edits, tombstones,
        supersession, expiry and background review share the same path.
        """
        with transaction(self._db):
            current = {
                str(row["id"]): dict(row)
                for row in self.maintenance_memory_inventory()
            }
            raw = self._db.execute(
                "SELECT data_json FROM transcript_memory_state WHERE id=1"
            ).fetchone()
            state = json.loads(raw[0]) if raw else None
            boundary = turn_ids[0] if turn_ids else ""
            if track_boundary and state and state.pop("pending_compact", False):
                compact = True
            if track_boundary and state and state["boundary"] and boundary != state["boundary"]:
                compact = True
            if state is None:
                state = {"revision": 0, "snapshot_revision": 0, "snapshot": current, "observed": current,
                         "history_format": 3, "events": [], "boundary": boundary, "overrides": {}, "snapshot_overrides": {}}
            else:
                state.setdefault("history_format", 1)
                previous = state["observed"]
                changes = []
                for identifier in sorted(previous.keys() | current.keys(), key=int):
                    old, new = previous.get(identifier), current.get(identifier)
                    # Only semantic fields affect LLM context, not access/ranking timestamps.
                    fields = ("kind", "key", "content", "activation")
                    if old and new and all(old.get(k) == new.get(k) for k in fields):
                        continue
                    if old is None and new is None:
                        continue
                    state["revision"] += 1
                    operation = "delete" if new is None else ("add" if old is None else "replace")
                    body = (
                        format_memory(new) if new else
                        "此记忆已撤销。旧快照及历史检索中的同 ID 内容不再作为当前事实或偏好依据。"
                    )
                    changes.append(
                        f'<{operation} id={quoteattr(identifier)} revision="{state["revision"]}"'
                        f' key={quoteattr(str((new or old)["key"]))}>'
                        f'{body}</{operation}>'
                    )
                    if old is not None or identifier in state["overrides"]:
                        state.setdefault("overrides", {})[identifier] = changes[-1]
                if changes:
                    state["events"].append({
                        "anchor": turn_ids[-1] if turn_ids else "",
                        "revision": state["revision"],
                        "content": '<memory_changes at=' + quoteattr(self.context_timestamp(time.time()))
                        + '>\n' + "\n".join(changes) + '\n</memory_changes>',
                    })
                state["observed"] = current
            if compact:
                state["history_format"] = 3
                state["snapshot_revision"] = state["revision"]
                state["snapshot"] = current
                state["snapshot_overrides"] = dict(state["overrides"])
                state["events"] = []
            if track_boundary:
                state["boundary"] = boundary
            self._db.execute(
                "INSERT INTO transcript_memory_state(id,data_json) VALUES(1,?) "
                "ON CONFLICT(id) DO UPDATE SET data_json=excluded.data_json",
                (json.dumps(state, ensure_ascii=False),),
            )
        return state

    def fold_transcript_memory(self, revision):
        """Fold only a request's observed revision; never consume concurrent updates."""
        with transaction(self._db):
            row = self._db.execute(
                "SELECT data_json FROM transcript_memory_state WHERE id=1"
            ).fetchone()
            if not row:
                return
            state = json.loads(row[0])
            if state["revision"] != revision:
                return
            state["history_format"] = 3
            state["snapshot_revision"] = state["revision"]
            state["snapshot"] = state["observed"]
            state["snapshot_overrides"] = dict(state["overrides"])
            state["events"] = []
            self._db.execute(
                "UPDATE transcript_memory_state SET data_json=? WHERE id=1",
                (json.dumps(state, ensure_ascii=False),),
            )
