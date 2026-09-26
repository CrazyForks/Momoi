from typing import Any

THINKING_TOOL_POLICY = """### 思考记录工具

用户询问助手为什么做了或没做某事，或最近某个 Turn 如何作出决定时，使用 `thinking_search` 和 `thinking_read`。这些记录是过去模型调用留下的、可能有误的线索，不是当前规则，也不是已发送给用户的消息。以发件箱和对话中的事实为准。不要向用户倾倒原始思考记录；说明结论和必要证据。
"""

THINKING_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "thinking_search",
        "description": (
            "Search recorded model thinking by Turn, keyword, or time. Returns "
            "compact excerpts, not full reasoning."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "turn_id": {
                    "type": "string",
                    "description": "Exact Turn id.",
                },
                "query": {
                    "type": "string",
                    "description": (
                        "Exact keyword or `|`-separated alternatives."
                    ),
                },
                "time_range": {
                    "type": "object",
                    "description": (
                        "Window; defaults to 30 days without turn_id."
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
                "stage": {
                    "type": "string",
                    "description": (
                        "Call stage, e.g. owner, webhook, heartbeat, goal, reflection."
                    ),
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
            "additionalProperties": False,
        },
    },
    {
        "name": "thinking_read",
        "description": (
            "Read recorded thinking for a Turn from thinking_search."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "turn_id": {
                    "type": "string",
                    "minLength": 1,
                },
                "call_id": {
                    "type": "string",
                    "description": "Call id from thinking_search; omit to read all calls in the Turn.",
                },
            },
            "required": ["turn_id"],
            "additionalProperties": False,
        },
    },
]
