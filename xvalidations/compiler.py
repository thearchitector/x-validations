"""Compiler from x-validation rules to JSON Schema overlays."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from xvalidations.artifact import extract_xvalidations
from xvalidations.errors import ExportedSchemaError
from xvalidations.jsonpath import evaluate_jsonpath
from xvalidations.resolve import resolve_placeholders
from xvalidations.target import location_to_schema_overlay

if TYPE_CHECKING:
    from xvalidations.models import JsonValue


@dataclass(frozen=True)
class CompiledSchema:
    """Compiled JSON Schema and branch-to-rule mapping."""

    schema: "dict[str, JsonValue]"
    branch_rule_ids: list[str]


def generate_compiled_schema(
    base_schema: "dict[str, JsonValue]", instance_json: "JsonValue"
) -> CompiledSchema:
    """Generate an instance-specialized JSON Schema from x-validation rules."""
    overlays: "list[JsonValue]" = []
    branch_rule_ids: list[str] = []
    for rule in extract_xvalidations(base_schema):
        assertion = resolve_placeholders(rule.assert_, instance_json, base_schema)
        for target_match in evaluate_jsonpath(rule.target, instance_json):
            overlays.append(
                location_to_schema_overlay(target_match.location, assertion)
            )
            branch_rule_ids.append(rule.id)

    compiled: "dict[str, JsonValue]" = {
        "$schema": "https://json-schema.org/draft/2020-12/schema"
    }
    if overlays:
        compiled["allOf"] = overlays

    try:
        Draft202012Validator.check_schema(compiled)
    except SchemaError as exc:
        msg = "compiled x-validation schema is invalid"
        raise ExportedSchemaError(msg) from exc

    return CompiledSchema(schema=compiled, branch_rule_ids=branch_rule_ids)
