"""Stable visible schema; the harness grants execution only during maintenance."""

from ...storage.memory.current_state import CurrentStateManager


def current_state_finish_spec() -> dict:
    return {
        "name": "current_state_finish",
        "description": (
            "Commit the current-state change set and finish the private maintenance "
            "phase after a conversation Turn has committed. Only callable in "
            "current_state_maintenance; unavailable during the conversation itself. "
            "This is the sole state-writing tool in maintenance; memory_operation is for durable memory here. "
            "Foreground memory_operation(scope=current_state) may already have changed the snapshot. "
            "Use the current snapshot, not old tool results; do not repeat completed changes or renew their TTL."
        ),
        "input_schema": CurrentStateManager.change_schema(),
    }
