import copy
import json
from contextlib import suppress
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel

from tests.conftest import (
    Article,
    Form,
    GeneratedArticle,
    GeneratedForm,
    GeneratedStaticArticle,
    Section,
    StaticArticle,
)
from xvalidations import (
    XValidatedModel,
    XValidationContext,
    XValidationError,
    xvalidate,
    xvalidation,
)
from xvalidations.authoring import AuthoredRule
from xvalidations.compiler import generate_compiled_schema
from xvalidations.errors import ExportedSchemaError
from xvalidations.jsonpath import evaluate_jsonpath


@pytest.mark.parametrize(
    ("model_cls", "payload"),
    [
        pytest.param(
            Article, {"tags": ["python"], "primary_tag": "python"}, id="article"
        ),
        pytest.param(
            Form,
            {
                "sections": [
                    {
                        "fields": ["title"],
                        "widgets": [{"kind": "field", "field_id": "title"}],
                    }
                ]
            },
            id="form",
        ),
        pytest.param(
            StaticArticle, {"tags": ["python"], "primary_tag": "anything"}, id="static"
        ),
    ],
)
def test_exported_schema_validity_for_all_fixtures(
    model_cls: type[BaseModel], payload: dict[str, Any]
) -> None:
    schema = model_cls.model_json_schema()

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(payload)


@pytest.mark.parametrize(
    ("model_cls", "payload"),
    [
        pytest.param(
            Article, {"tags": ["python"], "primary_tag": "python"}, id="article"
        ),
        pytest.param(
            Form,
            {
                "sections": [
                    {
                        "fields": ["title"],
                        "widgets": [{"kind": "field", "field_id": "title"}],
                    }
                ]
            },
            id="form",
        ),
        pytest.param(
            StaticArticle, {"tags": ["python"], "primary_tag": "anything"}, id="static"
        ),
    ],
)
def test_compiled_schemas_contain_no_resolve_for_all_fixtures(
    model_cls: type[BaseModel], payload: dict[str, Any]
) -> None:
    compiled = generate_compiled_schema(model_cls.model_json_schema(), payload)

    assert '"$resolve"' not in json.dumps(compiled.schema)


@pytest.mark.parametrize(
    ("model_cls", "payload"),
    [
        pytest.param(
            Article, {"tags": ["python"], "primary_tag": "python"}, id="article"
        ),
        pytest.param(
            Form,
            {
                "sections": [
                    {
                        "fields": ["title"],
                        "widgets": [{"kind": "field", "field_id": "title"}],
                    }
                ]
            },
            id="form",
        ),
        pytest.param(
            StaticArticle, {"tags": ["python"], "primary_tag": "anything"}, id="static"
        ),
    ],
)
def test_compiled_schemas_are_valid_draft_2020_12_for_all_fixtures(
    model_cls: type[BaseModel], payload: dict[str, Any]
) -> None:
    compiled = generate_compiled_schema(model_cls.model_json_schema(), payload)

    Draft202012Validator.check_schema(compiled.schema)


def test_full_jsonpath_target_filter_selects_only_matching_nodes() -> None:
    payload = {
        "sections": [
            {
                "fields": ["title"],
                "widgets": [
                    {"kind": "field", "field_id": "title"},
                    {"kind": "text", "text": "Intro", "field_id": "decoy"},
                ],
            }
        ]
    }
    matches = evaluate_jsonpath(
        '$.sections[*].widgets[?(@.kind == "field")].field_id', payload
    )

    assert [match.location for match in matches] == [
        ("sections", 0, "widgets", 0, "field_id")
    ]


def test_path_based_parity_internal_external_article(
    article_schema: dict[str, object],
    good_article_payload: dict[str, object],
    bad_article_payload: dict[str, object],
) -> None:
    internal_good = Article.model_validate(good_article_payload)
    external_good = GeneratedArticle.model_validate(good_article_payload)
    internal_bad = Article.model_validate(bad_article_payload)
    external_bad = GeneratedArticle.model_validate(bad_article_payload)

    assert xvalidate(internal_good) is None
    assert xvalidate(external_good, schema=article_schema) is None
    assert _xvalidation_failure_triples(internal_bad) == [
        ("$.primary_tag", "primary-tag-exists", "x-validation")
    ]
    assert _xvalidation_failure_triples(external_bad, article_schema) == [
        ("$.primary_tag", "primary-tag-exists", "x-validation")
    ]


def test_path_based_parity_nested_form(
    good_form_payload: dict[str, object], bad_form_payload: dict[str, object]
) -> None:
    schema = Form.model_json_schema()
    internal_good = Form.model_validate(good_form_payload)
    external_good = GeneratedForm.model_validate(good_form_payload)
    internal_bad = Form.model_validate(bad_form_payload)
    external_bad = GeneratedForm.model_validate(bad_form_payload)

    assert xvalidate(internal_good) is None
    assert xvalidate(external_good, schema=schema) is None
    expected = [
        (
            "$.sections[0].widgets[0].field_id",
            "section-widget-field-exists",
            "x-validation",
        )
    ]
    assert _xvalidation_failure_triples(internal_bad) == expected
    assert _xvalidation_failure_triples(external_bad, schema) == expected


def test_local_rule_rebasing_exports_once_per_reachable_root_path() -> None:
    rule = Form.model_json_schema()["x-validations"][0]

    assert rule["target"] == '$.sections[*].widgets[?(@.kind == "field")].field_id'
    assert rule["assert"]["enum"]["$resolve"] == "$.sections[*].fields[*]"
    assert len(Form.model_json_schema()["x-validations"]) == 1


def test_local_rule_cannot_reference_parent_path() -> None:
    rule = Section.model_json_schema()["x-validations"][0]

    assert rule["target"] == '$.widgets[?(@.kind == "field")].field_id'
    assert rule["assert"]["enum"]["$resolve"] == "$.fields[*]"


def test_automatic_defs_deduplicate_constants() -> None:
    class ConstantRule(XValidatedModel):
        first: str
        second: str

        @xvalidation(id="first", description="First constant.")
        def first_rule(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.first).assert_schema({"enum": x.resolve(["same"])})

        @xvalidation(id="second", description="Second constant.")
        def second_rule(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.second).assert_schema({"enum": x.resolve(["same"])})

    schema = ConstantRule.model_json_schema()
    refs = [rule["assert"]["enum"]["$resolve"] for rule in schema["x-validations"]]

    assert len(schema["$defs"]) == 1
    assert refs[0] == refs[1]
    assert refs[0].removeprefix("#/$defs/") in schema["$defs"]


def test_unused_constants_are_not_exported() -> None:
    class NoConstantRule(XValidatedModel):
        value: str

        @xvalidation(id="inline", description="Inline assertion.")
        def inline_rule(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.value).assert_schema({"type": "string"})

    assert "$defs" not in NoConstantRule.model_json_schema()


def test_static_rule_separation_keeps_min_length_in_base_schema() -> None:
    schema = StaticArticle.model_json_schema()

    assert schema["properties"]["tags"]["minItems"] == 1
    assert "x-validations" not in schema


def test_static_rule_external_schema_enforces_bad_payload() -> None:
    schema = StaticArticle.model_json_schema()
    model = GeneratedStaticArticle.model_validate({
        "tags": [],
        "primary_tag": "anything",
    })

    with pytest.raises(XValidationError) as exc_info:
        xvalidate(model, schema=schema)

    assert [
        (issue.path, issue.source, issue.rule_id) for issue in exc_info.value.errors
    ] == [("$.tags", "base", None)]


@pytest.mark.parametrize(
    ("model_cls", "good_payload", "bad_payload"),
    [
        pytest.param(
            Article,
            {"tags": ["python"], "primary_tag": "python"},
            {"tags": ["python"], "primary_tag": "bad"},
            id="article",
        ),
        pytest.param(
            Form,
            {
                "sections": [
                    {
                        "fields": ["title"],
                        "widgets": [{"kind": "field", "field_id": "title"}],
                    }
                ]
            },
            {
                "sections": [
                    {
                        "fields": ["title"],
                        "widgets": [{"kind": "field", "field_id": "missing"}],
                    }
                ]
            },
            id="form",
        ),
        pytest.param(
            StaticArticle,
            {"tags": ["python"], "primary_tag": "anything"},
            {"tags": [], "primary_tag": "anything"},
            id="static",
        ),
    ],
)
def test_each_example_rule_has_positive_and_negative_fixture(
    model_cls: type[BaseModel],
    good_payload: dict[str, Any],
    bad_payload: dict[str, Any],
) -> None:
    assert xvalidate(model_cls.model_validate(good_payload)) is None
    try:
        model = model_cls.model_validate(bad_payload)
    except ValueError:
        return

    with pytest.raises(XValidationError):
        xvalidate(model)


def test_exported_schema_errors_are_not_xvalidation_errors() -> None:
    with pytest.raises(ExportedSchemaError) as exc_info:
        generate_compiled_schema(
            {
                "x-validations": [
                    {
                        "id": "bad",
                        "description": "Bad schema.",
                        "target": "$[",
                        "assert": {"type": "string"},
                    }
                ]
            },
            {},
        )

    assert not isinstance(exc_info.value, XValidationError)


@pytest.mark.parametrize(
    ("model", "schema"),
    [
        pytest.param(
            Article.model_validate({"tags": ["python"], "primary_tag": "python"}),
            None,
            id="article-internal-pass",
        ),
        pytest.param(
            Article.model_validate({"tags": ["python"], "primary_tag": "bad"}),
            None,
            id="article-internal-fail",
        ),
        pytest.param(
            GeneratedArticle.model_validate({
                "tags": ["python"],
                "primary_tag": "python",
            }),
            Article.model_json_schema(),
            id="article-external-pass",
        ),
        pytest.param(
            GeneratedArticle.model_validate({"tags": ["python"], "primary_tag": "bad"}),
            Article.model_json_schema(),
            id="article-external-fail",
        ),
        pytest.param(
            Form.model_validate({
                "sections": [
                    {
                        "fields": ["title"],
                        "widgets": [{"kind": "field", "field_id": "title"}],
                    }
                ]
            }),
            None,
            id="form-internal-pass",
        ),
        pytest.param(
            Form.model_validate({
                "sections": [
                    {
                        "fields": ["title"],
                        "widgets": [{"kind": "field", "field_id": "missing"}],
                    }
                ]
            }),
            None,
            id="form-internal-fail",
        ),
        pytest.param(
            GeneratedForm.model_validate({
                "sections": [
                    {
                        "fields": ["title"],
                        "widgets": [{"kind": "field", "field_id": "title"}],
                    }
                ]
            }),
            Form.model_json_schema(),
            id="form-external-pass",
        ),
        pytest.param(
            GeneratedForm.model_validate({
                "sections": [
                    {
                        "fields": ["title"],
                        "widgets": [{"kind": "field", "field_id": "missing"}],
                    }
                ]
            }),
            Form.model_json_schema(),
            id="form-external-fail",
        ),
    ],
)
def test_validation_never_mutates_input_model(
    model: BaseModel, schema: dict[str, object] | None
) -> None:
    original_dump = copy.deepcopy(model.model_dump(mode="json"))
    original_schema = copy.deepcopy(schema)

    with suppress(XValidationError):
        xvalidate(model, schema=schema)

    assert model.model_dump(mode="json") == original_dump
    assert schema == original_schema


def _xvalidation_failure_triples(
    model: BaseModel, schema: dict[str, object] | None = None
) -> list[tuple[str, str | None, str]]:
    with pytest.raises(XValidationError) as exc_info:
        xvalidate(model, schema=schema)
    return [
        (issue.path, issue.rule_id, issue.source) for issue in exc_info.value.errors
    ]
