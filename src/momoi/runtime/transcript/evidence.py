"""Read-only evidence projection for turns without a complete replayable journal.

Used for old data, review-window fragments and turns interleaved with new input.
This does not reconstruct native tool calls or claim unseen actions occurred.
"""
import json
from collections.abc import Mapping, Sequence
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from .models import DEFAULT_ACTION_LIMIT, TranscriptGroup, text_value
from .records import part_bubble, text_message

def _action_line(records: Sequence[Mapping[str, object]]) -> str:
    """Render one run of calls to the same tool as a single trace line."""

    first = records[0]
    name = text_value(first.get("name"))
    subject = text_value(first.get("subject"))
    head = f"{name}({subject})" if subject else f"{name}()"
    if len(records) > 1:
        head += f" ×{len(records)}"
    failed = [record for record in records if not record.get("ok")]
    if failed:
        error = text_value(failed[0].get("error"))
        outcome = f"failed: {error}" if error else "failed"
        if len(failed) < len(records):
            outcome = f"{len(failed)} of {len(records)} {outcome}"
    else:
        outcome = "ok"
    refs = [
        text_value(record.get("ref"))
        for record in records
        if text_value(record.get("ref"))
    ]
    if refs:
        outcome += f" · ref={refs[0]}"
    return f"[tool_call] {head} -> {outcome}"

def _assistant_body(
    group: TranscriptGroup,
    records: Sequence[Mapping[str, object]],
    action_limit: int,
    timezone: ZoneInfo,
    turn: str,
) -> list[str]:
    """Interleave what a Turn said with what it did, in the order it happened.

    Momoi narrates work as it goes, so the bubbles only make sense next to the
    calls they refer to. Consecutive calls to the same tool collapse into one
    line and a long run is truncated, because a Turn can issue ninety calls and
    the point is the shape of the work, not a full replay of it.
    """

    events: list[tuple[float, int, object]] = []
    for index in range(len(group.parts)):
        at = group.part_times[index] if index < len(group.part_times) else 0.0
        events.append((at, 1, part_bubble(group, index, timezone, turn)))
    for record in records:
        events.append((float(record.get("at") or 0.0), 0, record))
    events.sort(key=lambda item: (item[0], item[1]))

    lines: list[str] = []
    run: list[Mapping[str, object]] = []
    shown = 0
    dropped = 0

    def flush_run() -> None:
        nonlocal run, shown, dropped
        if not run:
            return
        if shown < action_limit:
            lines.append(_action_line(run))
            shown += 1
        else:
            dropped += len(run)
        run = []

    for _at, _kind, item in events:
        if isinstance(item, str):
            flush_run()
            lines.append(item)
            continue
        if text_value(item.get("name")) == "recall":
            flush_run()
            lines.append("<historical_recall>" + escape(json.dumps({
                "arguments": item.get("recall_arguments"),
                "result": item.get("recall_result"),
            }, ensure_ascii=False)) + "</historical_recall>")
            continue
        if run and text_value(run[0].get("name")) != text_value(item.get("name")):
            flush_run()
        run.append(item)
    flush_run()
    if dropped:
        lines.append(f"[tool_call] … {dropped} further calls]")
    return lines


def render_group_evidence(
    groups: Sequence[TranscriptGroup], group_index: int, *,
    timezone: ZoneInfo,
    tool_activity: Mapping[str, Sequence[Mapping[str, object]]] | None = None,
    action_limit: int = DEFAULT_ACTION_LIMIT,
    labels: Mapping[str, str] | None = None,
) -> dict[str, object]:
    group = groups[group_index]
    group_labels = [
        str((labels or {}).get(turn_id) or "")
        for turn_id in group.turn_ids
        if (labels or {}).get(turn_id)
    ]
    turn = ",".join(dict.fromkeys(group_labels))
    annotations = []
    if group.uncertain:
        annotations.append("delivery uncertain")
    lines: list[str] = []
    if annotations:
        lines.append(f"[{' · '.join(annotations)}]")
    records = (
        [
            record
            for turn_id in group.turn_ids
            for record in (tool_activity or {}).get(turn_id, ())
        ]
        if group.role == "assistant"
        else []
    )
    if records:
        # An event may split one Turn's speech into several groups. Assign
        # each tool record to the corresponding interval exactly once.
        same_turn = [
            index for index, candidate in enumerate(groups)
            if candidate.role == "assistant"
            and set(candidate.turn_ids).intersection(group.turn_ids)
        ]
        earlier = [index for index in same_turn if index < group_index]
        later = [index for index in same_turn if index > group_index]
        lower = groups[earlier[-1] + 1].started_at if earlier else float("-inf")
        upper = groups[group_index + 1].started_at if later else float("inf")
        records = [
            record for record in records
            if lower <= float(record.get("at") or 0.0) < upper
        ]
    if records:
        lines.extend(_assistant_body(group, records, action_limit, timezone, turn))
    else:
        lines.extend(
            part_bubble(group, index, timezone, turn)
            for index in range(len(group.parts))
        )
    return text_message(group.role, "\n".join(lines))
