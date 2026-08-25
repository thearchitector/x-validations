"""Authoring exception hierarchy tests."""

from xvalidations import InvalidRuleError, InvalidSchemaError


def test_invalid_rule_is_a_specialized_schema_error() -> None:
    assert issubclass(InvalidRuleError, InvalidSchemaError)
    assert issubclass(InvalidSchemaError, ValueError)
