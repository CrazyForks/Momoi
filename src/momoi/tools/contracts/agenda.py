from typing import Any

from ...contracts import OWNER_PROGRESS_BEFORE_FIRST_CALL, OWNER_PROGRESS_FIELD

AGENDA_TOOL_POLICY = """### 日程工具

需要将来继续执行的一次性或周期性任务，使用持久化 Goal，记录预期结果和执行时间，并随情况变化更新状态。现在能完成的工作无需创建 Goal。
"""

_REVIEW_TIME_SCHEMA = {
    "type": "string",
    "format": "date-time",
    "pattern": r"T.+(?:Z|[+-]\d{2}:\d{2})$",
}


def _schedule_schema(description: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["interval"]},
                    "every_seconds": {"type": "integer", "minimum": 60},
                },
                "required": ["kind", "every_seconds"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["daily"]},
                    "times": {
                        "type": "array",
                        "description": '应用程序配置时区内的每日次数。',
                        "items": {
                            "type": "string",
                            "pattern": r"^(?:[01]\d|2[0-3]):[0-5]\d$",
                        },
                        "minItems": 1,
                        "maxItems": 24,
                        "uniqueItems": True,
                    },
                },
                "required": ["kind", "times"],
                "additionalProperties": False,
            },
        ],
    }
    if description:
        schema["description"] = description
    return schema


AGENDA_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "goal_create",
        OWNER_PROGRESS_FIELD: OWNER_PROGRESS_BEFORE_FIRST_CALL,
        "description": '持续执行需在下一轮继续的工作。',
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "pattern": r"\S"},
                "success_criteria": {"type": "string", "pattern": r"\S"},
                "next_action": {"type": "string", "pattern": r"\S"},
                "next_review_at": {
                    **_REVIEW_TIME_SCHEMA,
                    "description": '一次性目标的下次检查时间。',
                },
                "schedule": _schedule_schema(
                    "周期安排；运行时计算下次检查时间。"
                ),
            },
            "required": ["title", "success_criteria", "next_action"],
            "oneOf": [
                {"required": ["next_review_at"], "properties": {"schedule": False}},
                {"required": ["schedule"], "properties": {"next_review_at": False}},
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "goal_update",
        "description": (
            '更新现有未结束的目标；省略的状态字段保留其当前值。'
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "goal_id": {"type": "string"},
                "status": {"type": "string", "enum": ["active", "waiting", "blocked"]},
                "next_action": {
                    "type": "string",
                    "description": '下一步具体行动；进行中的目标需要至少一个。',
                },
                "waiting_for": {
                    "type": "string",
                    "description": '未满足的条件；等待中的目标需要一个。',
                },
                "blocked_reason": {
                    "type": "string",
                    "description": '阻碍进展的障碍；受阻的目标需要一个。',
                },
                "result": {
                    "type": "string",
                    "description": (
                        '具体的检查、行动及已验证的结果。排除由记忆或对话提供的最新用户状态。'
                    ),
                },
                "next_review_at": {
                    **_REVIEW_TIME_SCHEMA,
                    "description": '下次检查时间；等待中或非重复性进行中的目标需要此项，重复性进行中的目标可省略。',
                },
                "schedule": _schedule_schema(),
                "clear_schedule": {
                    "type": "boolean",
                    "description": '移除现有重复周期。',
                },
            },
            "required": ["goal_id", "status"],
            "allOf": [
                {
                    "if": {"properties": {"status": {"const": "waiting"}}},
                    "then": {"required": ["next_review_at"]},
                },
                {
                    "if": {
                        "properties": {"clear_schedule": {"const": True}},
                        "required": ["clear_schedule"],
                    },
                    "then": {"properties": {"schedule": False}},
                },
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "goal_finish",
        "description": (
            '当所有成功标准达成时，成功关闭目标。'
        ),
        "input_schema": {
            "type": "object",
            "properties": {"goal_id": {"type": "string", "minLength": 1}, "result": {"type": "string", "minLength": 1, "maxLength": 2000, "pattern": r"\S"}},
            "required": ["goal_id", "result"],
            "additionalProperties": False,
        },
    },
    {
        "name": "goal_cancel",
        OWNER_PROGRESS_FIELD: OWNER_PROGRESS_BEFORE_FIRST_CALL,
        "description": (
            '当被放弃、过时或停止时，无成功结果地关闭目标。'
        ),
        "input_schema": {
            "type": "object",
            "properties": {"goal_id": {"type": "string", "minLength": 1}, "reason": {"type": "string", "minLength": 1, "maxLength": 2000, "pattern": r"\S"}},
            "required": ["goal_id", "reason"],
            "additionalProperties": False,
        },
    },
]


GOAL_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        '当前目标检查的结果；运行时提供目标 ID。'
    ),
    "properties": {
        **{
            key: value
            for key, value in AGENDA_TOOL_SPECS[1]["input_schema"]["properties"].items()
            if key not in {"goal_id", "status", "result"}
        },
        "next_review_at": {
            **_REVIEW_TIME_SCHEMA,
            "description": (
                '下次检查时间。进行中的目标若省略则复用现有重复周期；若无剩余重复周期（包括 clear_schedule 之后）则需要此项，重复性进行中的目标可省略。'
            ),
        },
        "status": {
            "type": "string",
            "enum": ["active", "waiting", "blocked", "done", "cancelled"],
        },
        "result": {
            "type": "string",
            "minLength": 1,
            "maxLength": 2000,
            "pattern": r"\S",
            "description": (
                '本次检查的具体检查、行动及已验证结果，或取消原因。'
            ),
        },
    },
    "required": ["status", "result"],
    "examples": [
        {
            "status": "active",
            "result": "本次检查已完成，已发送一条简短提醒。",
            "next_action": "下个时段继续核对是否需要提醒。",
        },
        {
            "status": "waiting",
            "result": "等待用户提供所需信息。",
            "waiting_for": "用户回复确认时间",
            "next_review_at": "2026-09-16T09:00:00+08:00",
        },
        {"status": "done", "result": "目标已完成并验证结果。"},
        {"status": "blocked", "result": "无法连接服务。", "blocked_reason": "等待恢复访问权限。"},
        {"status": "cancelled", "result": "用户取消此任务。"},
    ],
    "oneOf": [
        {
            "description": '继续工作。安排下次检查，或复用重复性计划。',
            "properties": {
                "status": {"enum": ["active"]},
                "next_action": {"pattern": r"\S"},
            },
            "required": ["next_action"],
        },
        {
            "description": '等待条件。',
            "properties": {
                "status": {"enum": ["waiting"]},
                "waiting_for": {"pattern": r"\S"},
                "next_review_at": {"pattern": r"\S"},
            },
            "required": ["waiting_for", "next_review_at"],
        },
        {
            "description": '无法继续。',
            "properties": {
                "status": {"enum": ["blocked"]},
                "blocked_reason": {"pattern": r"\S"},
                "next_review_at": False,
            },
            "required": ["blocked_reason"],
        },
        {
            "description": '满足成功标准时标记为 done；不再追求时标记为 cancelled。',
            "properties": {"status": {"enum": ["done", "cancelled"]}},
            "maxProperties": 2,
        },
    ],
    "allOf": [
        {
            "if": {
                "properties": {"clear_schedule": {"const": True}},
                "required": ["clear_schedule"],
            },
            "then": {"properties": {"schedule": False}},
        },
    ],
    "additionalProperties": False,
}
