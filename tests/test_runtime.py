import copy
import json
from typing import TYPE_CHECKING, cast

import pytest
from xvalidate import XValidationError, XValidationTypeError, xvalidate

from tests.conftest import Article

if TYPE_CHECKING:
    from xvalidate import JsonValue


def test_xvalidate_accepts_json_loaded_dict() -> None:
    schema = Article.model_json_schema()
    payload = json.loads('{"tags": ["python"], "primary_tag": "python"}')

    assert xvalidate(payload, schema) is None


def test_xvalidate_rejects_xvalidation_failure() -> None:
    schema = Article.model_json_schema()

    with pytest.raises(XValidationError) as exc_info:
        xvalidate({"tags": ["python"], "primary_tag": "pydantic"}, schema)

    error = exc_info.value.errors[0]
    assert (error.path, error.rule_id) == ("$.primary_tag", "primary-tag-exists")
    assert exc_info.value.kind == "validation"
    assert str(exc_info.value) == "1 validation error(s)"
    assert exc_info.value.failure["kind"] == "validation"
    assert exc_info.value.failure["errors"][0]["path"] == "$.primary_tag"


def test_xvalidate_rejects_base_schema_failure() -> None:
    schema = Article.model_json_schema()

    with pytest.raises(XValidationError) as exc_info:
        xvalidate({"tags": ["python"]}, schema)

    error = exc_info.value.errors[0]
    assert error.path == "$"
    assert error.rule_id is None


def test_xvalidate_accepts_an_undecorated_compound_schema_root() -> None:
    assert xvalidate({}, {"type": "object"}) is None


def test_xvalidate_rejects_non_json_payload_with_structured_type_error() -> None:
    schema = Article.model_json_schema()

    with pytest.raises(XValidationTypeError) as exc_info:
        xvalidate(cast("JsonValue", object()), schema)

    assert isinstance(exc_info.value, TypeError)
    assert exc_info.value.kind == "invalid_payload"
    assert exc_info.value.failure["kind"] == "invalid_payload"
    assert exc_info.value.failure["message"] == str(exc_info.value)
    assert "payload must be JSON-compatible" in str(exc_info.value)


def test_xvalidate_rejects_non_json_schema_with_structured_type_error() -> None:
    with pytest.raises(XValidationTypeError) as exc_info:
        xvalidate({}, cast("dict[str, JsonValue]", object()))

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
