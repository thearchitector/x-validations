import copy
from contextlib import suppress
from typing import Any

import pytest
from pydantic import BaseModel
from xvalidate import ExportedSchemaError, XValidationError, xvalidate

from tests.conftest import Article, Form, Section, StaticArticle
from xvalidations import ValidationRule, XValidationContext, xvalidation

XVALIDATIONS_SCHEMA_URI = "https://thearchitector.dev/xvalidations/schema.json"


def test_path_based_parity_article(
    article_schema: dict[str, object],
    good_article_payload: dict[str, object],
    bad_article_payload: dict[str, object],
) -> None:
    assert xvalidate(good_article_payload, article_schema) is None
    assert _xvalidation_failures(bad_article_payload, article_schema) == [
        ("$.primary_tag", "primary-tag-exists")
    ]


def test_path_based_parity_nested_form(
    good_form_payload: dict[str, object], bad_form_payload: dict[str, object]
) -> None:
    schema = Form.model_json_schema()

    assert xvalidate(good_form_payload, schema) is None
    assert _xvalidation_failures(bad_form_payload, schema) == [
        ("$.sections[0].widgets[0].field_id", "section-widget-field-exists")
    ]


def test_local_rule_resource_exports_once_independent_of_parent_path() -> None:
    rule = Form.model_json_schema()["$defs"]["Section"]["x-validations"][0]

    assert rule["target"] == '$.widgets[?(@.kind == "field")].field_id'
    assert rule["assert"]["enum"]["$path"] == "$.fields[*]"
    assert len(Form.model_json_schema()["$defs"]["Section"]["x-validations"]) == 1


def test_local_rule_cannot_reference_parent_path() -> None:
    rule = Section.model_json_schema()["x-validations"][0]

    assert rule["target"] == '$.widgets[?(@.kind == "field")].field_id'
    assert rule["assert"]["enum"]["$path"] == "$.fields[*]"


def test_constant_rules_enforce_their_declared_values() -> None:
    class ConstantRule(BaseModel):
        first: str
        second: str

        @xvalidation(id="first", description="First constant.")
        @classmethod
        def first_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.first).assert_schema({
                "allOf": [{"enum": ["same"]}, {"const": x.path.first}]
            })

        @xvalidation(id="second", description="Second constant.")
        @classmethod
        def second_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.second).assert_schema({
                "allOf": [{"enum": ["same"]}, {"const": x.path.second}]
            })

    schema = ConstantRule.model_json_schema()
    assert xvalidate({"first": "same", "second": "same"}, schema) is None

    for field, rule_id in (("first", "first"), ("second", "second")):
        payload = {"first": "same", "second": "same", field: "different"}
        assert _xvalidation_failures(payload, schema) == [(f"$.{field}", rule_id)]


def test_static_rule_external_schema_enforces_bad_payload() -> None:
    schema = StaticArticle.model_json_schema()

    with pytest.raises(XValidationError) as exc_info:
        xvalidate({"tags": [], "primary_tag": "anything"}, schema)

    assert [(error.path, error.rule_id) for error in exc_info.value.errors] == [
        ("$.tags", None)
    ]


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
def test_each_example_schema_has_positive_and_negative_fixture(
    model_cls: type[Any], good_payload: dict[str, Any], bad_payload: dict[str, Any]
) -> None:
    schema = model_cls.model_json_schema()

    assert xvalidate(good_payload, schema) is None
    with pytest.raises(XValidationError):
        xvalidate(bad_payload, schema)


def test_exported_schema_errors_are_not_xvalidation_errors() -> None:
    with pytest.raises(ExportedSchemaError) as exc_info:
        xvalidate(
            {},
            {
                "$id": "urn:test:bad-jsonpath",
                "$schema": XVALIDATIONS_SCHEMA_URI,
                "type": "object",
                "x-validations": [
                    {
                        "id": "bad",
                        "description": "Bad schema.",
                        "target": "$[",
                        "assert": {"type": "string"},
                    }
                ],
            },
        )

    assert not isinstance(exc_info.value, XValidationError)


@pytest.mark.parametrize(
    ("payload", "schema"),
    [
        pytest.param(
            {"tags": ["python"], "primary_tag": "python"},
            Article.model_json_schema(),
            id="article-pass",
        ),
        pytest.param(
            {"tags": ["python"], "primary_tag": "bad"},
            Article.model_json_schema(),
            id="article-fail",
        ),
        pytest.param(
            {
                "sections": [
                    {
                        "fields": ["title"],
                        "widgets": [{"kind": "field", "field_id": "title"}],
                    }
                ]
            },
            Form.model_json_schema(),
            id="form-pass",
        ),
        pytest.param(
            {
                "sections": [
                    {
                        "fields": ["title"],
                        "widgets": [{"kind": "field", "field_id": "missing"}],
                    }
                ]
            },
            Form.model_json_schema(),
            id="form-fail",
        ),
    ],
)
def test_validation_never_mutates_inputs(
    payload: dict[str, Any], schema: dict[str, Any]
) -> None:
    original_payload = copy.deepcopy(payload)
    original_schema = copy.deepcopy(schema)

    with suppress(XValidationError):
        xvalidate(payload, schema)

    assert payload == original_payload
    assert schema == original_schema


def _xvalidation_failures(
    payload: dict[str, object], schema: dict[str, object]
) -> list[tuple[str, str | None]]:
    with pytest.raises(XValidationError) as exc_info:
        xvalidate(payload, schema)
    return [(error.path, error.rule_id) for error in exc_info.value.errors]
