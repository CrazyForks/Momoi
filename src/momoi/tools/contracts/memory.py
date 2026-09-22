from typing import Any


MEMORY_TOOL_POLICY = """### Memory tools

Use memory_operation only when authenticated owner evidence warrants adding,
correcting, or forgetting memory. Do not record every message or fetch old
memories merely to repeat them as arguments. Pending requests are not confirmed
facts or completed deletions.
Use scope=current_state for temporary facts or owner-requested temporary behavior,
with subject/key and an evidence-based TTL; these changes bypass memory review.
The background review handles durable memory classification, activation, and duplicates.
"""


MEMORY_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "memory_search",
        "description": (
            "Search committed memory for earlier facts, people, preferences, events, "
            "or vague references not already resolved by supplied context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Concise subject; use `|` for alternative names of the same subject."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 6,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "episode_search",
        "description": (
            "Search archived Episodes by keyword or time. "
            "Returns paginated summaries and evidence locations, not raw messages."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Concise subject, optionally with `|` aliases; empty browses "
                        "time_range chronologically."
                    ),
                },
                "time_range": {
                    "type": "object",
                    "description": (
                        "Window; defaults to 30 days. Use all only when older history matters."
                    ),
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": ["recent", "range", "all"],
                        },
                        "days": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 3650,
                        },
                        "from": {"type": "string"},
                        "to": {"type": "string"},
                    },
                    "required": ["kind"],
                    "additionalProperties": False,
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 5,
                },
                "cursor": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Offset returned as next_cursor.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "episode_read",
        "description": (
            "Read paginated raw Episode messages with role, time, delivery state, "
            "and evidence locations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "episode_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 200,
                    "description": "Episode id from recall or episode_search.",
                },
                "before_ordinal": {
                    "type": "integer",
                    "minimum": 2,
                    "description": (
                        "next_before_ordinal for an older page; omit for newest."
                    ),
                },
                "time_range": {
                    "type": "object",
                    "description": (
                        "Exact message-time window; prefer a narrow range because raw "
                        "messages are verbose."
                    ),
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": ["recent", "range", "all"],
                        },
                        "days": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 3650,
                        },
                        "from": {"type": "string"},
                        "to": {"type": "string"},
                    },
                    "required": ["kind"],
                    "additionalProperties": False,
                },
                "message_id": {
                    "type": "integer",
                    "minimum": 1,
                    "description": ("Message id returned with next_content_offset."),
                },
                "content_offset": {
                    "type": "integer",
                    "minimum": 0,
                    "description": ("next_content_offset for the same message_id."),
                },
            },
            "required": ["episode_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_operation",
        "description": (
            "Change durable memory (default scope=memory) or temporary state (scope=current_state). "
            "For temporary facts, explicit state corrections, or behavior limited to at most 24 hours, "
            "use current_state: writes directly without waiting for background maintenance. "
            "Use subject/key from current_state; add creates, replace updates, forget removes that dimension. "
            "Provide ttl_seconds for add/replace, omit it for forget. Do not renew without fresh evidence. "
            "Only record temporary facts or behavior directly supported by current owner input, not your guesses. "
            "In current_state_maintenance use current_state_finish instead. "
            "The following review rules apply only to durable memory: "
            "The runtime attaches recalled memories and conversation; private review runs "
            "after this Turn commits. Acceptance does not mean the change is effective. "
            "Do not repeat an accepted request."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string", "enum": ["add", "replace", "forget"],
                    "description": "add for a new fact; replace for correction; forget for deletion or explicit disproof.",
                },
                "content": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 2000,
                    "description": "New scoped fact for add/replace; subject to forget for forget. Preserve the owner's polarity, object, conditions, and duration.",
                },
                "evidence": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 500,
                    "description": "Exact contiguous quote from a current authenticated owner message.",
                },
                "scope": {"type": "string", "enum": ["memory", "current_state"],
                          "description": "Defaults to memory. Temporary facts and time-limited behavior use current_state."},
                "subject": {"type": "string", "minLength": 1, "maxLength": 128,
                            "description": "current_state only: owner, assistant, or an established entity."},
                "key": {"type": "string", "minLength": 1, "maxLength": 64,
                        "pattern": "^[a-z][a-z0-9_.-]*$",
                        "description": "current_state only: dimension without the subject prefix; reuse the existing key."},
                "ttl_seconds": {"type": "integer", "minimum": 1, "maximum": 86400,
                                "description": "current_state add/replace only: evidence-supported remaining duration from this write."},
                "target_id": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Optional memory_id already displayed in this Turn. Omit when unknown.",
                },
            },
            "required": ["type", "content", "evidence"],
            "allOf": [{
                "if": {"properties": {"scope": {"const": "current_state"}}, "required": ["scope"]},
                "then": {
                    "required": ["subject", "key"],
                    "properties": {"target_id": False, "content": {"maxLength": 512}},
                    "allOf": [{
                        "if": {"properties": {"type": {"const": "forget"}}},
                        "then": {"properties": {"ttl_seconds": False}},
                        "else": {"required": ["ttl_seconds"]},
                    }],
                },
                "else": {"properties": {"subject": False, "key": False, "ttl_seconds": False}},
            }],
            "additionalProperties": False,
        },
    },
]
