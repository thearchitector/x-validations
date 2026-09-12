"""Checked with mypy to exercise public construction and evaluation contracts."""

from typing import assert_type

from pydantic import BaseModel, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import PydanticUndefinedType

from pydantic_ajv import Node, Rule, RuleModel, rule
from pydantic_ajv.nodes import (
    AtomicNode,
    Logical,
    LogicalOperator,
    Membership,
    Ordering,
    OrderingOperator,
    Uniqueness,
)
from pydantic_ajv.references import (
    Data,
    LiteralCollection,
    LiteralValue,
    Number,
    Primitive,
    Reference,
)


class TypedExample(BaseModel):
    low: int
    high: int

    @rule
    @classmethod
    def ordered(cls, x: RuleModel) -> Rule:
        return x.low <= x.high

    @rule(id="positive", error="low must be positive")
    @classmethod
    def positive(cls, x: RuleModel) -> Rule:
        return x.low > 0


def authoring_inputs(
    x: RuleModel, numbers: list[int], names: list[str], mixed: list[Primitive]
) -> Rule:
    return (
        (x.low < 1)
        & (x.low <= 1.5)
        & (x.high > x.low)
        & (x.high >= 0)
        & x.number.in_(numbers)
        & x.name.in_(names)
        & x.value.in_(mixed)
        & x.value.in_([1, "one", None])
        & x.value.in_((1, "one", None))
        & x.value.in_(x.values)
        & (x.value.when(int | float) > 0)
    )


def composed_nodes(number: Reference[Number], other: Node) -> Node:
    order = Ordering(OrderingOperator.GT, number, LiteralValue(0))
    return Logical(LogicalOperator.AND, order, other)


def evaluate(expression: Rule, instance: TypedExample) -> bool:
    return expression.resolve(instance)


def export(
    expression: Rule, handler: GetJsonSchemaHandler, schema: JsonSchemaValue
) -> JsonSchemaValue:
    return expression.dump(handler, schema)


def direct_context() -> Rule:
    x = RuleModel.for_model(TypedExample)
    return x.low < x.high


def generic_contracts(
    number: Reference[Number],
    order: Ordering,
    member: Membership,
    unique: Uniqueness,
    instance: TypedExample,
    handler: GetJsonSchemaHandler,
    schema: JsonSchemaValue,
) -> None:
    literal = LiteralValue(1)
    assert_type(literal._resolve(instance), int)
    assert_type(literal._data(handler, schema), int)
    assert_type(number._resolve(instance), Number | PydanticUndefinedType)
    assert_type(number._data(handler, schema), Data)
    assert_type(order.values(handler, schema), tuple[Data, Number | Data])
    assert_type(
        member.values(handler, schema),
        tuple[Primitive | Data, LiteralCollection | Data],
    )
    assert_type(unique.values(handler, schema), tuple[Data, str])
    atomic: AtomicNode[Number, Number, Data, Number | Data] = order
    assert_type(atomic.test(1, 2.0), bool)
