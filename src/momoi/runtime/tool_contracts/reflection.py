from typing import Any

from ...storage import MEMORY_KINDS


REFLECTION_FINISH_SPEC: dict[str, Any] = {
    "name": "reflection_finish",
    "description": (
        '存储每日反思、持久记忆和对话结束内容，然后结束此私有 Turn。'
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "minLength": 1,
                "maxLength": 6000,
                "description": (
                    '有意义经历、感受、观点、理解变化及未决问题的中文日记。'
                ),
            },
            "conversation_actions": {
                "type": "array",
                "maxItems": 32,
                "description": (
                    '<open_conversations>的维护工作；无需时为空。'
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "episode_id": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 128,
                            "description": '来自<open_conversations>的话题 ID。',
                        },
                        "action": {
                            "type": "string",
                            "enum": ["close"],
                        },
                        "reason": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 400,
                        },
                    },
                    "required": ["episode_id", "action", "reason"],
                    "additionalProperties": False,
                },
            },
            "memories": {
                "type": "array",
                "maxItems": 12,
                "description": (
                    '值得保留至今天的持久主张。可为空；不要编造教训以填充列表。不要记录特定或共享的经历/事件；这些属于话题摘要。'
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": sorted(MEMORY_KINDS),
                            "description": (
                                'profile：用户身份、背景、节奏与习惯；preference：用户的需求，包括约束条件及既定措辞；relationship：关系纽带及其边界、称呼方式与约定；third_party：关于他人的稳定事实；practice：可复用的方法或决策流程（含工具使用）；world_knowledge：对世界的观察所得知识；self_insight：对自身感受或倾向的主观理解；cross_event_state：超越产生它的事件而持续存在的状态。具体或共享的经历属于当天的 Episode，不在此记录；仅记录符合所选类型的持久性主张。'
                            ),
                        },
                        "key": {
                            "type": "string",
                            "description": '稳定的小写点分隔键。',
                        },
                        "content": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 1000,
                            "description": (
                                '根据类型，在证据范围内简明描述发生、被理解或被学习的内容。对于 practice，需包含适用性及可观察的结果；未受批评并非成功的证据。'
                            ),
                        },
                        "evidence": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 500,
                            "description": (
                                '支持该结论的来自所提供当日或工具证据的精确连续引文，而非仅其主题。'
                            ),
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                            "description": (
                                '证据支持所记录主张（含其范围）的确信度；非其重要性或你的决心。'
                            ),
                        },
                    },
                    "required": [
                        "kind",
                        "key",
                        "content",
                        "evidence",
                        "confidence",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["summary", "memories"],
        "additionalProperties": False,
    },
}
