"""Strict authoring validation preserves JSON values and definition errors."""

from collections.abc import Callable
from decimal import Decimal
from enum import IntEnum, StrEnum
from operator import gt

import pytest
from pydantic import BaseModel, RootModel, ValidationError

from pydantic_ajv import Rule, RuleDefinitionError, RuleModel, rule


class NumericTag(IntEnum):
    ONE = 1


class TextTag(StrEnum):
    NAME = "name"


class IntegerSubclass(int):
    pass


@pytest.mark.parametrize(
    "expression",
    [
        lambda x: x > "1",
        lambda x: x > True,
        lambda x: x > Decimal("1.5"),
        lambda x: x > float("inf"),
        lambda x: gt(x, float("nan")),
        lambda x: x == b"name",
        lambda x: x == NumericTag.ONE,
        lambda x: x == TextTag.NAME,
        lambda x: x == IntegerSubclass(1),
        lambda x: x[b"name"] == 1,
        lambda x: x[NumericTag.ONE] == 1,
        lambda x: x[TextTag.NAME] == 1,
        lambda x: x.in_([b"name"]),
        lambda x: x.in_([NumericTag.ONE]),
        lambda x: x.in_([float("inf")]),
        lambda x: x.in_([float("nan")]),
        lambda x: x.in_({1, 2}),
        lambda x: x.in_(iter([1, 2])),
        lambda x: x.unique_by(1),
        lambda x: x.unique_by(b"name"),
        lambda x: x.unique_by(None),
    ],
    ids=[
        "numeric_string",
        "numeric_boolean",
        "decimal",
        "infinity",
        "nan",
        "bytes_literal",
        "integer_enum",
        "string_enum",
        "integer_subclass",
        "bytes_key",
        "integer_enum_key",
        "string_enum_key",
        "bytes_item",
        "enum_item",
        "infinite_item",
        "nan_item",
        "set",
        "iterator",
        "numeric_property",
        "bytes_property",
        "null_property",
    ],
)
def test_authoring_rejects_coercion_with_definition_errors(
    expression: Callable[[RuleModel], Rule],
) -> None:
    with pytest.raises(RuleDefinitionError) as error:
        expression(RuleModel.for_model(RootModel[int]).root)
    assert not isinstance(error.value, ValidationError)


@pytest.mark.parametrize("as_tuple", [False, True])
def test_membership_preserves_types_precision_and_snapshot(as_tuple: bool) -> None:
    source = [9007199254740993, True, 1.5, None, "1"]
    choices = tuple(source) if as_tuple else source

    class Value(RootModel[int | float | bool | str | None]):
        @rule
        @classmethod
        def check(cls, x: RuleModel) -> Rule:
            return x.root.in_(choices)

    source.append("later")
    for value in [9007199254740993, True, 1, 1.5, None, "1"]:
        assert Value(value).root == value
    for value in [9007199254740992, False, "later"]:
        with pytest.raises(ValidationError):
            Value(value)
    exported = Value.model_json_schema()["allOf"][0]["then"]["enum"]
    assert exported == [9007199254740993, True, 1.5, None, "1"]
    assert [type(item) for item in exported] == [int, bool, float, type(None), str]


def test_empty_property_name_is_a_valid_projection() -> None:
    class Items(BaseModel):
        items: list[dict[str, int]]

        @rule
        @classmethod
        def check(cls, x: RuleModel) -> Rule:
            return x.items.unique_by("")

    assert Items(items=[{"": 1}, {"": 2}])
    with pytest.raises(ValidationError):
        Items(items=[{"": 1}, {"": 1}])
    assert Items.model_json_schema()["allOf"][0]["then"] == {
        "type": "object",
        "properties": {"items": {"type": "array", "uniqueItemProperties": [""]}},
    }
