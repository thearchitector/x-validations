"""Expression nodes own construction checks, evaluation, and schema output."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import combinations
from operator import ge, gt, le, lt

from pydantic import BaseModel, GetJsonSchemaHandler, InstanceOf
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import PydanticUndefinedType

from .references import (
    ArrayOperand,
    Data,
    LiteralCollection,
    LiteralValue,
    MembershipSubject,
    Number,
    NumericOperand,
    ObjectCollection,
    Operand,
    Primitive,
    PrimitiveArray,
    Projection,
    Reference,
    RuleDefinitionError,
    ScalarOperand,
    Schema,
    conjunction,
    lookup,
    uniqueness_inputs,
)
from .validation import definition


class EqualityOperator(StrEnum):
    EQ = "eq"
    NE = "ne"


class OrderingOperator(StrEnum):
    LT = "lt"
    LE = "le"
    GT = "gt"
    GE = "ge"

    def compare(self, left: Number, right: Number) -> bool:
        operation: Callable[[Number, Number], bool] = {
            self.LT: lt,
            self.LE: le,
            self.GT: gt,
            self.GE: ge,
        }[self]
        return operation(left, right)

    @property
    def reverse(self) -> OrderingOperator:
        return {self.LT: self.GT, self.LE: self.GE, self.GT: self.LT, self.GE: self.LE}[
            self
        ]

    @property
    def keyword(self) -> str:
        return {
            self.LT: "exclusiveMaximum",
            self.LE: "maximum",
            self.GT: "exclusiveMinimum",
            self.GE: "minimum",
        }[self]


class LogicalOperator(StrEnum):
    AND = "and"
    OR = "or"


class Node(ABC):
    """Implement both methods to add an operation; no backend registry exists."""

    @abstractmethod
    def resolve(self, instance: BaseModel) -> bool: ...

    @abstractmethod
    def dump(
        self, handler: GetJsonSchemaHandler, schema: JsonSchemaValue
    ) -> JsonSchemaValue: ...


class AtomicNode[Left, Right, SchemaLeft, SchemaRight](Node):
    """Local guards and missing operands skip only this predicate."""

    @property
    @abstractmethod
    def operands(self) -> tuple[Operand[Left], Operand[Right]]: ...

    @abstractmethod
    def test(self, left: Left, right: Right) -> bool: ...

    @abstractmethod
    def constraint(self, left: SchemaLeft, right: SchemaRight) -> Schema: ...

    def resolve(self, instance: BaseModel) -> bool:
        left_operand, right_operand = self.operands
        left, right = left_operand._resolve(instance), right_operand._resolve(instance)
        if isinstance(left, PydanticUndefinedType) or isinstance(
            right, PydanticUndefinedType
        ):
            return True
        return self.test(left, right)

    @abstractmethod
    def values(
        self, handler: GetJsonSchemaHandler, schema: JsonSchemaValue
    ) -> tuple[SchemaLeft, SchemaRight]: ...

    def dump(
        self, handler: GetJsonSchemaHandler, schema: JsonSchemaValue
    ) -> JsonSchemaValue:
        condition = conjunction([
            operand._condition(handler, schema) for operand in self.operands
        ])
        left, right = self.values(handler, schema)
        return {"if": condition, "then": self.constraint(left, right)}


@dataclass(frozen=True, slots=True)
class Equality(AtomicNode[Primitive, Primitive, Data, Primitive | Data]):
    operator: EqualityOperator
    left: Operand[Primitive]
    right: Operand[Primitive]
    _schema_operands: tuple[Reference[Primitive], Operand[Primitive]] = field(
        init=False, repr=False
    )

    def __post_init__(self) -> None:
        equality_inputs(self.operator, self.left, self.right)
        object.__setattr__(
            self, "_schema_operands", comparison_operands(self.left, self.right)
        )

    @property
    def operands(self) -> tuple[Operand[Primitive], Operand[Primitive]]:
        return self.left, self.right

    def test(self, left: Primitive, right: Primitive) -> bool:
        return left == right if self.operator is EqualityOperator.EQ else left != right

    def values(
        self, handler: GetJsonSchemaHandler, schema: JsonSchemaValue
    ) -> tuple[Data, Primitive | Data]:
        left, right = self._schema_operands
        return left._data(handler, schema), right._data(handler, schema)

    def constraint(self, left: Data, right: Primitive | Data) -> Schema:
        value = right.relative_to(left) if isinstance(right, Data) else right
        target = {"const": value}
        return left.constrain(
            {"not": target} if self.operator is EqualityOperator.NE else target
        )


@dataclass(frozen=True, slots=True)
class Ordering(AtomicNode[Number, Number, Data, Number | Data]):
    operator: OrderingOperator
    left: Operand[Number]
    right: Operand[Number]
    _schema_operands: tuple[Reference[Number], Operand[Number]] = field(
        init=False, repr=False
    )
    _schema_operator: OrderingOperator = field(init=False, repr=False)

    def __post_init__(self) -> None:
        ordering_inputs(self.operator, self.left, self.right)
        object.__setattr__(
            self, "_schema_operands", comparison_operands(self.left, self.right)
        )
        object.__setattr__(
            self,
            "_schema_operator",
            self.operator
            if isinstance(self.left, Reference)
            else self.operator.reverse,
        )

    @property
    def operands(self) -> tuple[Operand[Number], Operand[Number]]:
        return self.left, self.right

    def test(self, left: Number, right: Number) -> bool:
        return self.operator.compare(left, right)

    def values(
        self, handler: GetJsonSchemaHandler, schema: JsonSchemaValue
    ) -> tuple[Data, Number | Data]:
        left, right = self._schema_operands
        return left._data(handler, schema), right._data(handler, schema)

    def constraint(self, left: Data, right: Number | Data) -> Schema:
        value = right.relative_to(left) if isinstance(right, Data) else right
        return left.constrain({"type": "number", self._schema_operator.keyword: value})


@dataclass(frozen=True, slots=True)
class Membership(
    AtomicNode[Primitive, PrimitiveArray, Primitive | Data, LiteralCollection | Data]
):
    subject: Operand[Primitive]
    collection: Reference[PrimitiveArray] | LiteralValue[LiteralCollection]

    def __post_init__(self) -> None:
        membership_inputs(self.subject, self.collection)

    @property
    def operands(self) -> tuple[Operand[Primitive], Operand[PrimitiveArray]]:
        return self.subject, self.collection

    def test(self, left: Primitive, right: PrimitiveArray) -> bool:
        return left in right

    def values(
        self, handler: GetJsonSchemaHandler, schema: JsonSchemaValue
    ) -> tuple[Primitive | Data, LiteralCollection | Data]:
        return self.subject._data(handler, schema), self.collection._data(
            handler, schema
        )

    def constraint(
        self, left: Primitive | Data, right: LiteralCollection | Data
    ) -> Schema:
        if isinstance(right, Data):
            if isinstance(left, Data):
                return left.constrain({"enum": right.relative_to(left)})
            return right.constrain({"type": "array", "contains": {"const": left}})
        # JSON enum uniqueness distinguishes booleans from numbers, unlike Python.
        values = [
            item
            for index, item in enumerate(right)
            if not any(
                isinstance(item, bool) == isinstance(prior, bool) and item == prior
                for prior in right[:index]
            )
        ]
        if isinstance(left, Data):
            return left.constrain({"enum": values}) if values else False
        return left in values


@dataclass(frozen=True, slots=True)
class Uniqueness(AtomicNode[ObjectCollection, str, Data, str]):
    collection: Reference[ObjectCollection]
    projection: Projection
    _property: LiteralValue[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        uniqueness_inputs(self.collection, self.projection)
        object.__setattr__(self, "_property", LiteralValue(self.projection.key))

    @property
    def operands(self) -> tuple[Operand[ObjectCollection], Operand[str]]:
        return self.collection, self._property

    def test(self, left: ObjectCollection, right: str) -> bool:
        return not any(
            a == b
            for a, b in combinations((lookup(item, (right,)) for item in left), 2)
        )

    def values(
        self, handler: GetJsonSchemaHandler, schema: JsonSchemaValue
    ) -> tuple[Data, str]:
        return self.collection._data(handler, schema), self.projection.dump(handler)

    def constraint(self, left: Data, right: str) -> Schema:
        return left.constrain({"type": "array", "uniqueItemProperties": [right]})


def comparison_operands[T](
    left: Operand[T], right: Operand[T]
) -> tuple[Reference[T], Operand[T]]:
    if isinstance(left, Reference):
        return left, right
    if isinstance(right, Reference):
        return right, left
    raise RuleDefinitionError("A comparison requires a model reference")


@definition("Comparison operands must be JSON primitives")
def equality_inputs(
    operator: EqualityOperator, left: ScalarOperand, right: ScalarOperand
) -> None:
    pass


@definition("Numeric comparisons require numeric operands; narrow unions with .when()")
def ordering_inputs(
    operator: OrderingOperator, left: NumericOperand, right: NumericOperand
) -> None:
    pass


@definition("Membership requires an array of primitive elements")
def membership_inputs(subject: MembershipSubject, collection: ArrayOperand) -> None:
    pass


@dataclass(frozen=True, slots=True)
class Logical(Node):
    operator: LogicalOperator
    left: Node
    right: Node

    def __post_init__(self) -> None:
        logical_inputs(self.operator, self.left, self.right)

    def resolve(self, instance: BaseModel) -> bool:
        if self.operator is LogicalOperator.AND:
            return self.left.resolve(instance) and self.right.resolve(instance)
        return self.left.resolve(instance) or self.right.resolve(instance)

    def dump(
        self, handler: GetJsonSchemaHandler, schema: JsonSchemaValue
    ) -> JsonSchemaValue:
        return {
            "allOf" if self.operator is LogicalOperator.AND else "anyOf": [
                self.left.dump(handler, schema),
                self.right.dump(handler, schema),
            ]
        }


@definition("Logical operations require an operator and two nodes")
def logical_inputs(
    operator: LogicalOperator, left: InstanceOf[Node], right: InstanceOf[Node]
) -> None:
    pass
