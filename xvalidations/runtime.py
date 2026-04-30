"""Runtime validation API."""

import copy
import json
from typing import TYPE_CHECKING, Any, Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel

from xvalidations.artifact import strip_xvalidations
from xvalidations.compiler import generate_compiled_schema
from xvalidations.errors import XValidationError
from xvalidations.models import ValidationIssue
from xvalidations.pydantic import XValidatedModel

if TYPE_CHECKING:
    from collections.abc import Iterable

    from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

    from xvalidations.models import JsonValue

type IssueSource = Literal["base", "x-validation"]


def xvalidate(model: BaseModel, schema: "dict[str, JsonValue] | None" = None) -> None:
    """Validate a Pydantic model against exported x-validation rules."""
    if not isinstance(model, BaseModel):
        msg = "xvalidate() requires a Pydantic BaseModel instance"
        raise TypeError(msg)
    if schema is None:
        if not isinstance(model, XValidatedModel):
            msg = "schema is required for plain BaseModel instances"
            raise TypeError(msg)
        schema = type(model).model_json_schema(mode="serialization")
    else:
        schema = copy.deepcopy(schema)

    instance_json = _canonical_model_dump(model)
    validate_base_schema(schema, instance_json)
    validate_compiled_schema(schema, instance_json)


def validate_base_schema(
    schema: "dict[str, JsonValue]", instance_json: "JsonValue"
) -> None:
    """Validate the canonical instance against the stripped base schema."""
    base_schema = strip_xvalidations(schema)
    errors = Draft202012Validator(base_schema).iter_errors(instance_json)
    issues = issues_from_errors(errors, source="base")
    if issues:
        raise XValidationError(issues)


def validate_compiled_schema(
    schema: "dict[str, JsonValue]", instance_json: "JsonValue"
) -> None:
    """Validate the canonical instance against compiled x-validation schema."""
    compiled = generate_compiled_schema(schema, instance_json)
    errors = Draft202012Validator(compiled.schema).iter_errors(instance_json)
    issues = issues_from_errors(
        errors, source="x-validation", branch_rule_ids=compiled.branch_rule_ids
    )
    if issues:
        raise XValidationError(issues)


def issues_from_errors(
    errors: "Iterable[JsonSchemaValidationError]",
    source: IssueSource,
    branch_rule_ids: list[str] | None = None,
) -> list[ValidationIssue]:
    """Normalize JSON Schema errors into validation issues."""
    sorted_errors = sorted(errors, key=lambda error: tuple(error.absolute_path))
    return [
        ValidationIssue(
            path=_location_to_jsonpath(tuple(error.absolute_path)),
            message=error.message,
            keyword=error.validator if isinstance(error.validator, str) else None,
            source=source,
            rule_id=(
                None
                if source == "base"
                else _rule_id_from_schema_path(
                    tuple(error.absolute_schema_path), branch_rule_ids
                )
            ),
        )
        for error in sorted_errors
    ]


def _canonical_model_dump(model: BaseModel) -> "JsonValue":
    return model.model_dump(
        mode="json",
        by_alias=True,
        exclude_unset=False,
        exclude_defaults=False,
        exclude_none=False,
    )


def _rule_id_from_schema_path(
    schema_path: tuple[Any, ...], branch_rule_ids: list[str] | None
) -> str | None:
    if branch_rule_ids is None:
        return None
    try:
        all_of_index = schema_path.index("allOf")
        branch_index = schema_path[all_of_index + 1]
    except ValueError, IndexError:
        return None
    if isinstance(branch_index, int) and 0 <= branch_index < len(branch_rule_ids):
        return branch_rule_ids[branch_index]
    return None


def _location_to_jsonpath(location: tuple[Any, ...]) -> str:
    if not location:
        return "$"
    parts = ["$"]
    for segment in location:
        if isinstance(segment, int):
            parts.append(f"[{segment}]")
        elif isinstance(segment, str) and segment.isidentifier():
            parts.append(f".{segment}")
        else:
            parts.append(f"[{json.dumps(str(segment))}]")
    return "".join(parts)
