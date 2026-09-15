"""Structural validation for model supplied tool arguments."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationError,
    create_model,
)


def _annotation(schema: dict[str, Any]) -> Any:
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return Literal[tuple(enum)]
    kind = schema.get("type")
    if kind == "string":
        return StrictStr
    if kind == "integer":
        return StrictInt
    if kind == "number":
        return StrictFloat
    if kind == "boolean":
        return StrictBool
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
        constraints = {
            "min_length": definition.get("minLength"),
            "max_length": definition.get("maxLength"),
            "pattern": definition.get("pattern"),
            "ge": definition.get("minimum"),
            "le": definition.get("maximum"),
        }
        fields[name] = (
            annotation,
            Field(
                ... if name in required else definition.get("default", None),
                **{key: value for key, value in constraints.items() if value is not None},
            ),
        )
    model = create_model(
        f"{tool_name.title().replace('_', '')}Arguments",
        __config__=ConfigDict(
            extra="forbid"
            if schema.get("additionalProperties") is False
            else "allow"
        ),
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
