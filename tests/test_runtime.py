import copy
import json

import pytest

from tests.conftest import Article
from xvalidations import ExportedSchemaError, XValidationError, xvalidate


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


def test_xvalidate_rejects_base_schema_failure() -> None:
    schema = Article.model_json_schema()

    with pytest.raises(XValidationError) as exc_info:
        xvalidate({"tags": ["python"]}, schema)

    issue = exc_info.value.errors[0]
    assert issue.source == "base"
    assert issue.rule_id is None


def test_xvalidate_rejects_invalid_schema_shape() -> None:
    with pytest.raises(ExportedSchemaError):
        xvalidate({}, {"type": "object"})


def test_runtime_does_not_mutate_payload_or_schema() -> None:
    payload = {"tags": ["python"], "primary_tag": "python"}
    schema = Article.model_json_schema()
    original_payload = copy.deepcopy(payload)
    original_schema = copy.deepcopy(schema)

    xvalidate(payload, schema)

    assert payload == original_payload
    assert schema == original_schema
