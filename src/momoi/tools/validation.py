"""One Pydantic boundary backed by the complete model-visible JSON Schema."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import RootModel, ValidationError, ValidationInfo, model_validator
from pydantic_core import PydanticCustomError


@lru_cache(maxsize=256)
def _validator(encoded: str) -> Draft202012Validator:
    schema = json.loads(encoded)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _actionable_errors(error):
    # Select a tagged union branch only when its literal discriminator matches.
    # Otherwise retain the complete union error rather than guess a repair.
    if error.validator in {"oneOf", "anyOf"} and isinstance(error.instance, dict):
        matches = []
        for index, branch in enumerate(error.validator_value):
            tags = {
                key: rule
                for key, rule in branch.get("properties", {}).items()
                if isinstance(rule, dict) and ("const" in rule or "enum" in rule)
            }
            if tags and all(
                key in error.instance
                and (
                    error.instance[key] == rule["const"]
                    if "const" in rule
                    else error.instance[key] in rule["enum"]
                )
                for key, rule in tags.items()
            ):
                matches.append(index)
        if len(matches) == 1:
            for child in error.context:
                if child.schema_path[0] == matches[0]:
                    yield from _actionable_errors(child)
            return
    yield error


class ToolArguments(RootModel[dict[str, Any]]):
    @model_validator(mode="after")
    def check_contract(self, info: ValidationInfo) -> ToolArguments:
        validator = info.context["validator"]
        errors = list(validator.iter_errors(self.root))
        if errors:
            raise PydanticCustomError(
                "tool_schema",
                "Arguments do not match the tool schema",
                {"errors": errors},
            )
        return self


def validate_tool_arguments(
    tool_name: str, arguments: object, schema: dict[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Validate without inserting defaults, coercing types, or dropping nulls."""
    validator = _validator(json.dumps(schema, sort_keys=True))
    try:
        parsed = ToolArguments.model_validate(
            arguments, context={"validator": validator}
        )
        return parsed.root, None
    except ValidationError as exc:
        details = []
        for item in exc.errors(include_url=False):
            errors = item.get("ctx", {}).get("errors", [])
            if not errors:
                details.append(
                    {
                        "field": "<arguments>",
                        "type": item["type"],
                        "message": item["msg"],
                    }
                )
            for error in (
                leaf for error in errors for leaf in _actionable_errors(error)
            ):
                path = ".".join(map(str, error.absolute_path))
                kind = error.validator
                if kind == "required":
                    for field in error.validator_value:
                        if field not in error.instance:
                            details.append(
                                {
                                    "field": ".".join(filter(None, [path, field])),
                                    "type": "missing",
                                    "message": error.message,
                                }
                            )
                elif kind == "additionalProperties" and error.validator_value is False:
                    for field in (
                        error.instance.keys()
                        - error.schema.get("properties", {}).keys()
                    ):
                        details.append(
                            {
                                "field": ".".join(filter(None, [path, field])),
                                "type": "extra_forbidden",
                                "message": error.message,
                            }
                        )
                else:
                    details.append(
                        {
                            "field": path or "<arguments>",
                            "type": str(kind),
                            "message": error.message,
                            "branches": [
                                {
                                    "field": ".".join(map(str, child.absolute_path)),
                                    "message": child.message,
                                }
                                for child in error.context
                            ],
                        }
                    )
        return None, {
            "ok": False,
            "error": "invalid_tool_arguments",
            "message": f"{tool_name}: "
            + "; ".join(f"{d['field']}: {d['message']}" for d in details)
            + ". Correct arguments only; do not repeat completed actions.",
            "details": details,
            "unexpected_fields": sorted(
                {d["field"] for d in details if d["type"] == "extra_forbidden"}
            ),
            "missing_fields": sorted(
                {d["field"] for d in details if d["type"] == "missing"}
            ),
            "invalid_fields": sorted(
                {
                    d["field"]
                    for d in details
                    if d["type"] not in {"missing", "extra_forbidden"}
                }
            ),
            "allowed_fields": list(schema.get("properties", {})),
            "required_fields": schema.get("required", []),
            "examples": schema.get("examples", []),
        }
