"""Python runtime wrapper smoke tests."""

import json

import pytest
from xvalidate import XValidationError, xvalidate

from tests.conftest import Article


def test_xvalidate_accepts_payload_first_json_values() -> None:
    schema = Article.model_json_schema()
    payload = json.loads('{"tags": ["python"], "primary_tag": "python"}')
    assert xvalidate(payload, schema) is None


def test_xvalidate_reports_root_rule_failure() -> None:
    with pytest.raises(XValidationError) as exc_info:
        xvalidate(
            {"tags": ["python"], "primary_tag": "pydantic"}, Article.model_json_schema()
        )

    error = exc_info.value.errors[0]
    assert (error.path, error.rule_id) == ("$.primary_tag", "primary-tag-exists")


def test_xvalidate_reports_base_schema_failure() -> None:
    with pytest.raises(XValidationError) as exc_info:
        xvalidate({"tags": ["python"]}, Article.model_json_schema())

    assert exc_info.value.errors[0].rule_id is None


def test_xvalidate_accepts_an_ordinary_schema() -> None:
    assert xvalidate({}, {"type": "object"}) is None
