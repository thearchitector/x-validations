"""Public authored value type tests."""

from dataclasses import FrozenInstanceError

import pytest
from pydantic import BaseModel

from xvalidations import ValidationRule, XValidationContext


def test_validation_rule_is_frozen_and_slotted() -> None:
    class Model(BaseModel):
        value: str

    context = XValidationContext()
    rule = ValidationRule(target=context.path.value, assertion={"const": "a"})

    assert rule.target == context.path.value
    assert rule.assertion == {"const": "a"}
    assert not hasattr(rule, "assert_")
    assert not hasattr(rule, "__dict__")
    with pytest.raises(FrozenInstanceError):
        rule.assertion = {"const": "b"}  # type: ignore[misc]
