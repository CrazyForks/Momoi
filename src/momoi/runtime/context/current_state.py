"""Live state is attached to current input, never to historical transcripts."""

from xml.sax.saxutils import escape, quoteattr

from ...storage import Store
from ...storage.memory.current_state_contract import (
    CURRENT_STATE_SOURCE_STAGES,
    MAX_SLOTS,
    SLOT_SOFT_WARNING_THRESHOLD,
)
from ..turn_support import pack_user_context

CURRENT_STATE_STAGES = CURRENT_STATE_SOURCE_STAGES


def pack_current_turn_context(
    store: Store,
    stage: str,
    *items: tuple[str, str],
    include_empty: bool = False,
    maintenance: bool = False,
) -> str:
    if stage not in CURRENT_STATE_STAGES:
        raise ValueError(f"current state is not available in {stage}")
    snapshot = store.current_state.snapshot()
    slots = []
    for slot in snapshot.slots:
        attributes = {
            "key": f"{slot.subject}.{slot.key}",
            "status": slot.status,
            "observed_at": (
                store.context_timestamp(slot.observed_at)
                if slot.observed_at
                else "unknown"
            ),
        }
        if slot.evidence_turn_id:
            attributes["source_turn"] = slot.evidence_turn_id
        if maintenance:
            attributes.update(
                id=slot.id,
                subject=slot.subject,
                expires_at=store.context_timestamp(slot.expires_at),
            )
            attributes["key"] = slot.key
        rendered = "".join(
            f" {key}={quoteattr(value)}" for key, value in attributes.items()
        )
        body = f"<value>{escape(slot.value)}</value>"
        if slot.source_quote:
            body += f"<source role={quoteattr(slot.source_role)}>{escape(slot.source_quote)}</source>"
        if slot.uncertainty:
            body += f"<uncertainty>{escape(slot.uncertainty)}</uncertainty>"
        slots.append(f"<state{rendered}>{body}</state>")
    if len(slots) > SLOT_SOFT_WARNING_THRESHOLD:
        slots.append(
            f"<capacity used={quoteattr(str(len(slots)))} "
            f"limit={quoteattr(str(MAX_SLOTS))}>Approaching the slot limit: "
            "tighten, merge, or delete weak slots before adding new ones.</capacity>"
        )
    packed = pack_user_context(("current_state", "\n".join(slots)), *items)
    # Mid-Turn owner updates must explicitly invalidate a prior nonempty snapshot.
    if include_empty and not slots:
        return "<current_state />\n\n" + packed
    return packed
