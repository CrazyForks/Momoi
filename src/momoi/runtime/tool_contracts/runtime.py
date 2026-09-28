from typing import Any


def tool_enable_spec(group_descriptions: dict[str, str]) -> dict[str, Any]:
    groups = {
        group: str(description).strip()
        for group, description in sorted(group_descriptions.items())
    }
    return {
        "name": "tool_enable",
        "description": '启用下一行动所需的 MCP 组。',
        "input_schema": {
            "type": "object",
            "properties": {
                "groups": {
                    "type": "array",
                    "description": "; ".join(
                        f"{group}: {description}" for group, description in groups.items()
                    ),
                    "minItems": 1,
                    "maxItems": max(1, len(groups)),
                    "uniqueItems": True,
                    "items": {"type": "string", "enum": list(groups)},
                }
            },
            "required": ["groups"],
            "additionalProperties": False,
        },
    }


READ_TOOL_RESULT_SPEC: dict[str, Any] = {
    "name": "read_tool_result",
    "description": (
        '继续截断的工具结果快照，无需重新运行工具。无法读取工作区文件。'
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "result_ref": {
                "type": "string",
                "pattern": "^tr_[0-9a-f]{32}$",
                "description": '从截断的结果中复制未更改的 result_ref。',
            },
            "cursor": {
                "type": "string",
                "minLength": 1,
                "description": '前一个分片中的最新 next_cursor；首个分片可省略。',
            },
        },
        "required": ["result_ref"],
        "additionalProperties": False,
    },
}
