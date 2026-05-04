import copy
import json

import pytest
from xvalid import (
    ExportedSchemaError,
    XValidationError,
    XValidationTypeError,
    xvalidate,
)

from tests.conftest import Article


def test_xvalidate_accepts_json_loaded_dict() -> None:
    schema = Article.model_json_schema()
    payload = json.loads('{"tags": ["python"], "primary_tag": "python"}')

    assert xvalidate(payload, schema) is None


def test_xvalidate_rejects_xvalidation_failure() -> None:
    schema = Article.model_json_schema()

    with pytest.raises(XValidationError) as exc_info:
        xvalidate({"tags": ["python"], "primary_tag": "pydantic"}, schema)

    issue = exc_info.value.errors[0]
    assert (issue.path, issue.source, issue.rule_id) == (
        "$.primary_tag",
        "x-validation",
        "primary-tag-exists",
    )
    assert exc_info.value.kind == "validation"
    assert str(exc_info.value) == "1 validation issue(s)"
    assert exc_info.value.failure["kind"] == "validation"
    assert exc_info.value.failure["issues"][0]["path"] == "$.primary_tag"


def test_xvalidate_rejects_base_schema_failure() -> None:
    schema = Article.model_json_schema()

    with pytest.raises(XValidationError) as exc_info:
        xvalidate({"tags": ["python"]}, schema)

    issue = exc_info.value.errors[0]
    assert issue.source == "base"
    assert issue.rule_id is None


def test_xvalidate_rejects_invalid_schema_shape() -> None:
    with pytest.raises(ExportedSchemaError) as exc_info:
        xvalidate({}, {"type": "object"})

    assert exc_info.value.kind == "invalid_schema"
    assert exc_info.value.failure["kind"] == "invalid_schema"
    assert isinstance(exc_info.value.failure["message"], str)


def test_xvalidate_rejects_non_json_payload_with_structured_type_error() -> None:
    schema = Article.model_json_schema()

    with pytest.raises(XValidationTypeError) as exc_info:
        xvalidate(object(), schema)

    assert isinstance(exc_info.value, TypeError)
    assert exc_info.value.kind == "invalid_payload"
    assert exc_info.value.failure["kind"] == "invalid_payload"
    assert exc_info.value.failure["message"] == str(exc_info.value)
    assert "payload must be JSON-compatible" in str(exc_info.value)


def test_xvalidate_rejects_non_json_schema_with_structured_type_error() -> None:
    with pytest.raises(XValidationTypeError) as exc_info:
        xvalidate({}, object())

    assert exc_info.value.kind == "invalid_schema_input"
    assert exc_info.value.failure["kind"] == "invalid_schema_input"
    assert exc_info.value.failure["message"] == str(exc_info.value)
    assert "schema must be JSON-compatible" in str(exc_info.value)


def test_runtime_does_not_mutate_payload_or_schema() -> None:
    payload = {"tags": ["python"], "primary_tag": "python"}
    schema = Article.model_json_schema()
    original_payload = copy.deepcopy(payload)
    original_schema = copy.deepcopy(schema)

    xvalidate(payload, schema)

    assert payload == original_payload
    assert schema == original_schema
