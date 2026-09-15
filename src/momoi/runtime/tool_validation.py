"""Structural validation for model supplied tool arguments."""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field, ValidationError, create_model


def _annotation(schema: dict[str, Any]) -> Any:
    kind = schema.get("type")
    if kind == "string":
        return str
    if kind == "integer":
        return int
    if kind == "number":
        return float
    if kind == "boolean":
        return bool
    if kind == "array":
        return list
    if kind == "object":
        return dict
    return Any


def validate_tool_arguments(
    tool_name: str, arguments: object, schema: dict[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return normalized arguments or a model-readable structural error."""
    if not isinstance(arguments, dict):
        return None, {
            "ok": False,
            "error": "invalid_tool_arguments",
            "message": f"{tool_name} 参数必须是 JSON 对象。",
            "invalid_fields": ["<arguments>"],
        }
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    fields: dict[str, tuple[Any, Any]] = {}
    for name, definition in properties.items():
        annotation = _annotation(definition)
        fields[name] = (annotation, Field(...) if name in required else None)
    model = create_model(
        f"{tool_name.title().replace('_', '')}Arguments",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )
    try:
        parsed = model.model_validate(arguments)
    except ValidationError as error:
        unexpected: list[str] = []
        missing: list[str] = []
        invalid: list[str] = []
        details: list[dict[str, Any]] = []
        for item in error.errors():
            location = item.get("loc", ())
            field = str(location[0]) if location else "<arguments>"
            kind = str(item.get("type", "validation_error"))
            if kind == "extra_forbidden":
                unexpected.append(field)
                message = "不允许此字段"
            elif kind == "missing":
                missing.append(field)
                message = "缺少必填字段"
            else:
                invalid.append(field)
                message = "字段类型或格式无效"
            details.append({"field": field, "type": kind, "message": message})
        return None, {
            "ok": False,
            "error": "invalid_tool_arguments",
            "message": f"{tool_name} 参数校验失败。请根据 details 修正后重试。",
            "details": details,
            "unexpected_fields": unexpected,
            "missing_fields": missing,
            "invalid_fields": invalid,
            "allowed_fields": list(properties),
            "required_fields": list(schema.get("required", [])),
        }
    return parsed.model_dump(exclude_none=True), None
