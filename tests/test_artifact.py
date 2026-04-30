import copy

import pytest

from xvalidations.artifact import (
    extract_xvalidations,
    strip_xvalidations,
    xvalidation_owned_defs,
)
from xvalidations.errors import InvalidRuleError
from xvalidations.models import XValidationRule


def test_extract_xvalidations_missing_key_returns_empty_list() -> None:
    assert extract_xvalidations({}) == []


def test_extract_xvalidations_none_returns_empty_list() -> None:
    assert extract_xvalidations({"x-validations": None}) == []


def test_extract_xvalidations_non_list_raises_invalid_rule_error() -> None:
    with pytest.raises(InvalidRuleError):
        extract_xvalidations({"x-validations": {"id": "bad"}})


def test_extract_xvalidations_invalid_rule_raises_invalid_rule_error() -> None:
    with pytest.raises(InvalidRuleError):
        extract_xvalidations({"x-validations": [{}]})


def test_strip_removes_root_xvalidations() -> None:
    schema = {"type": "object", "x-validations": []}

    assert strip_xvalidations(schema) == {"type": "object"}


def test_strip_removes_only_defs_referenced_by_rule_resolve() -> None:
    schema = {
        "$defs": {
            "ArticleTagEnum": {"enum": ["python"]},
            "PydanticOwned": {"type": "object"},
        },
        "x-validations": [
            {
                "id": "primary-tag-exists",
                "description": "Primary tag must be present in tags.",
                "target": "$.primary_tag",
                "assert": {"enum": {"$resolve": "#/$defs/ArticleTagEnum"}},
            }
        ],
    }
    original = copy.deepcopy(schema)

    assert strip_xvalidations(schema) == {
        "$defs": {"PydanticOwned": {"type": "object"}}
    }
    assert schema == original


def test_strip_keeps_pydantic_defs_not_referenced_by_rule() -> None:
    schema = {
        "$defs": {"PydanticOwned": {"type": "object"}},
        "x-validations": [
            {
                "id": "primary-tag-exists",
                "description": "Primary tag must be present in tags.",
                "target": "$.primary_tag",
                "assert": {"enum": {"$resolve": "$.tags[*]"}},
            }
        ],
    }

    assert strip_xvalidations(schema) == {
        "$defs": {"PydanticOwned": {"type": "object"}}
    }


def test_strip_handles_escaped_json_pointer_def_name() -> None:
    schema = {
        "$defs": {
            "path/with~tilde": {"enum": ["python"]},
            "PydanticOwned": {"type": "object"},
        },
        "x-validations": [
            {
                "id": "primary-tag-exists",
                "description": "Primary tag must be present in tags.",
                "target": "$.primary_tag",
                "assert": {"enum": {"$resolve": "#/$defs/path~1with~0tilde"}},
            }
        ],
    }

    assert strip_xvalidations(schema) == {
        "$defs": {"PydanticOwned": {"type": "object"}}
    }


def test_xvalidation_owned_defs_ignores_instance_paths() -> None:
    rules = [
        XValidationRule.model_validate({
            "id": "primary-tag-exists",
            "description": "Primary tag must be present in tags.",
            "target": "$.primary_tag",
            "assert": {"enum": {"$resolve": "$.tags[*]"}},
        })
    ]

    assert xvalidation_owned_defs(rules) == set()
