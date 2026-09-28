"""Tool contract and instructions for the Episode relation workflow."""

from __future__ import annotations

from xml.etree.ElementTree import Element, SubElement, tostring
from ...turn_support import PROMPT_ROOT

SYSTEM = PROMPT_ROOT.joinpath("episode_relation.md").read_text(encoding="utf-8").strip()

FINISH_SPEC = {
    "name": "episode_relation_finish",
    "description": "提交有具体逻辑依据的话题关系；无关联则提交空数组并结束。",
    "input_schema": {
        "type": "object",
        "properties": {"relations": {
            "type": "array", "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "target_episode_id": {"type": "string"},
                    "relation": {"type": "string", "enum": ["follows_up", "revises", "context"]},
                    "explanation": {"type": "string", "minLength": 1, "maxLength": 300},
                    "source_evidence": {"type": "string", "minLength": 1, "maxLength": 300},
                    "target_evidence": {"type": "string", "minLength": 1, "maxLength": 300},
                },
                "required": ["target_episode_id", "relation", "explanation", "source_evidence", "target_evidence"],
                "additionalProperties": False,
            },
        }},
        "required": ["relations"],
        "additionalProperties": False,
    },
}


def render_source(episode, messages):
    root = Element("episode_relation_source", {"id": str(episode["id"])})
    SubElement(root, "title").text = str(episode["title"])
    SubElement(root, "summary").text = str(episode["narrative_summary"] or "")
    conversation = SubElement(root, "conversation")
    for message in messages:
        item = SubElement(conversation, "message", {
            "id": str(message["id"]),
            "role": str(message["role"]),
            "time": str(message["timestamp"]),
        })
        item.text = str(message["content"])
    return tostring(root, encoding="unicode")
