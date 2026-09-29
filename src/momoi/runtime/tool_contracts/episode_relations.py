"""Read-only graph traversal tool for archived topic relationships."""

EPISODE_RELATIONS_TOOL_SPEC = {
    "name": "episode_relations",
    "description": "按话题 ID 查看已有的全部关联，包含该话题指向别人的关系和别人指向该话题的关系。可展开一层或两层；仅返回有效的已建关系，不包含无关审阅记录。",
    "input_schema": {
        "type": "object",
        "properties": {
            "episode_id": {"type": "string", "minLength": 1, "description": "要查看的话题 ID。"},
            "depth": {"type": "integer", "enum": [1, 2], "default": 1,
                      "description": "沿关系展开的层数，默认 1。"},
        },
        "required": ["episode_id"],
        "additionalProperties": False,
    },
}
