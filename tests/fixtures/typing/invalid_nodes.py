"""Intentionally invalid node arguments, checked against diagnostic contracts."""

from pydantic_ajv import Rule
from pydantic_ajv.nodes import (
    EqualityOperator,
    Logical,
    LogicalOperator,
    Membership,
    Node,
    Ordering,
    OrderingOperator,
    Uniqueness,
)
from pydantic_ajv.references import LiteralValue, ObjectCollection, Reference


def wrong_comparison_enum() -> None:
    Ordering(EqualityOperator.EQ, LiteralValue(1), LiteralValue(2))


def wrong_logical_child(node: Node) -> None:
    Logical(LogicalOperator.AND, LiteralValue(True), node)


def wrong_logical_enum(node: Node) -> None:
    Logical(EqualityOperator.EQ, node, node)


def wrong_unique_projection(ref: Reference[ObjectCollection]) -> None:
    Uniqueness(ref, "id")


def wrong_rule_node() -> None:
    Rule(LiteralValue(1))


def wrong_numeric_reference(ref: Reference[str]) -> None:
    Ordering(OrderingOperator.GT, ref, LiteralValue(0))


def wrong_numeric_literal(ref: Reference[int]) -> None:
    Ordering(OrderingOperator.GT, ref, LiteralValue("zero"))


def wrong_ordering_predicate(node: Ordering) -> None:
    node.test("zero", 1)


def wrong_ordering_constraint(node: Ordering) -> None:
    node.constraint(1, 2)


def wrong_membership_predicate(node: Membership) -> None:
    node.test(1, 2)


def wrong_uniqueness_predicate(node: Uniqueness) -> None:
    node.test([], 1)
