import json

import pytest
from jsonschema import Draft202012Validator

from xvalidations import XValidatedModel, XValidationContext, xvalidation
from xvalidations.authoring import AuthoredRule
from xvalidations.compiler import CompiledSchema, generate_compiled_schema
from xvalidations.errors import ExportedSchemaError, JsonPathError


class Article(XValidatedModel):
    tags: list[str]
    primary_tag: str

    @xvalidation(
        id="primary-tag-exists", description="Primary tag must be present in tags."
    )
    def primary_tag_exists(x: XValidationContext) -> AuthoredRule:
        return x.target(x.path.primary_tag).assert_schema({
            "enum": x.resolve(x.path.tags.each())
        })


def test_generate_compiled_schema_has_no_resolve() -> None:
    schema = Article.model_json_schema()
    compiled = generate_compiled_schema(
        schema, {"tags": ["python"], "primary_tag": "python"}
    )

    assert '"$resolve"' not in json.dumps(compiled.schema)


def test_generate_compiled_schema_rule_ids_match_allof_branches() -> None:
    schema = Article.model_json_schema()
    compiled = generate_compiled_schema(
        schema, {"tags": ["python"], "primary_tag": "python"}
    )

    assert compiled.branch_rule_ids == ["primary-tag-exists"]
    assert len(compiled.schema["allOf"]) == 1


def test_generate_compiled_schema_without_rules_is_valid_true_schema() -> None:
    compiled = generate_compiled_schema({"type": "object"}, {})

    assert compiled == CompiledSchema(
        schema={"$schema": "https://json-schema.org/draft/2020-12/schema"},
        branch_rule_ids=[],
    )
    Draft202012Validator.check_schema(compiled.schema)


def test_generate_compiled_schema_without_target_matches_is_valid_true_schema() -> None:
    compiled = generate_compiled_schema(
        {
            "x-validations": [
                {
                    "id": "missing-target",
                    "description": "Missing target is skipped.",
                    "target": "$.missing",
                    "assert": {"type": "string"},
                }
            ]
        },
        {},
    )

    assert compiled == CompiledSchema(
        schema={"$schema": "https://json-schema.org/draft/2020-12/schema"},
        branch_rule_ids=[],
    )
    Draft202012Validator.check_schema(compiled.schema)


def test_generated_compiled_schema_passes_draft_2020_12_check() -> None:
    schema = Article.model_json_schema()
    compiled = generate_compiled_schema(
        schema, {"tags": ["python"], "primary_tag": "python"}
    )

    Draft202012Validator.check_schema(compiled.schema)


def test_valid_article_instance_has_zero_compiled_errors() -> None:
    schema = Article.model_json_schema()
    compiled = generate_compiled_schema(
        schema, {"tags": ["python"], "primary_tag": "python"}
    )

    errors = list(
        Draft202012Validator(compiled.schema).iter_errors({
            "tags": ["python"],
            "primary_tag": "python",
        })
    )

    assert errors == []


def test_invalid_article_instance_errors_at_primary_tag() -> None:
    schema = Article.model_json_schema()
    compiled = generate_compiled_schema(
        schema, {"tags": ["python"], "primary_tag": "pydantic"}
    )
    errors = list(
        Draft202012Validator(compiled.schema).iter_errors({
            "tags": ["python"],
            "primary_tag": "pydantic",
        })
    )

    assert len(errors) == 1
    assert tuple(errors[0].absolute_path) == ("primary_tag",)


def test_invalid_exported_schema_inputs_raise_exported_schema_error() -> None:
    with pytest.raises(ExportedSchemaError):
        generate_compiled_schema(
            {
                "x-validations": [
                    {
                        "id": "bad-target",
                        "description": "Bad target.",
                        "target": "$[",
                        "assert": {"type": "string"},
                    }
                ]
            },
            {},
        )


def test_generate_compiled_schema_returns_compiled_schema() -> None:
    schema = Article.model_json_schema()

    assert isinstance(
        generate_compiled_schema(schema, {"tags": ["python"], "primary_tag": "python"}),
        CompiledSchema,
    )


def test_jsonpath_errors_are_exported_schema_errors() -> None:
    assert issubclass(JsonPathError, ExportedSchemaError)
