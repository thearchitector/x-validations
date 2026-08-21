import pytest
from pydantic import ValidationError

from xvalidations import XValidationRule


def test_rule_round_trips_assert_alias() -> None:
    rule = XValidationRule.model_validate({
        "id": "primary-tag-exists",
        "description": "Primary tag must be present in tags.",
        "target": "$.primary_tag",
        "assert": {"enum": {"$resolve": "$.tags[*]"}},
    })

    assert rule.model_dump(by_alias=True) == {
        "id": "primary-tag-exists",
        "description": "Primary tag must be present in tags.",
        "target": "$.primary_tag",
        "assert": {"enum": {"$resolve": "$.tags[*]"}},
    }


def test_rule_rejects_missing_id_description_target_assert() -> None:
    with pytest.raises(ValidationError):
        XValidationRule.model_validate({})
