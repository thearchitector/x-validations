"""Model-shaped symbolic authoring with eager operator type checks."""

from dataclasses import dataclass
from typing import Annotated, Any, ClassVar

from pydantic import BaseModel, GetJsonSchemaHandler, InstanceOf, ValidateAs
from pydantic.json_schema import JsonSchemaValue

from .nodes import (
    Equality,
    EqualityOperator,
    Logical,
    LogicalOperator,
    Membership,
    Node,
    Ordering,
    OrderingOperator,
    Uniqueness,
)
from .references import (
    LiteralValue,
    Narrowing,
    Number,
    Operand,
    Primitive,
    Projection,
    Reference,
    RuleDefinitionError,
    Step,
    TypeShape,
    is_model,
)
from .validation import (
    JsonCollection,
    JsonLiteral,
    JsonNumber,
    PathKey,
    PropertyName,
    definition,
)


@dataclass(frozen=True, slots=True)
class Rule:
    """A named expression evaluated as a boolean or dumped as a constraint."""

    node: Node
    id: str = "rule"
    description: str | None = None
    error: str | None = None

    def resolve(self, instance: BaseModel) -> bool:
        return self.node.resolve(instance)

    def dump(
        self, handler: GetJsonSchemaHandler, schema: JsonSchemaValue
    ) -> JsonSchemaValue:
        fragment = dict(self.node.dump(handler, schema))
        fragment["title"] = self.id
        if self.description is not None:
            fragment["description"] = self.description
        if self.error is not None:
            fragment["errorMessage"] = self.error.replace("${", "\\$\\{")
        return fragment

    def __bool__(self) -> bool:
        raise RuleDefinitionError(
            "Rules have no Python truth value; use & or |, and split chained comparisons"
        )

    def __and__(self, other: Rule) -> Rule:
        return Rule(Logical(LogicalOperator.AND, self.node, other.node))

    def __or__(self, other: Rule) -> Rule:
        return Rule(Logical(LogicalOperator.OR, self.node, other.node))


@dataclass(frozen=True, slots=True)
class ModelAttribute:
    """A generated model field, constructed lazily to support recursive models."""

    name: str

    def __get__(
        self, instance: RuleModel | None, owner: type[RuleModel]
    ) -> RuleModel | ModelAttribute:
        return self if instance is None else instance[self.name]


class RuleModel(Reference[Any]):
    """A typed symbolic value; concrete models have generated field descriptors.

    A rule factory receives the model-specific root automatically. Use
    ``RuleModel.for_model(Model)`` when constructing a standalone expression.
    """

    __slots__ = ()
    _model_types: ClassVar[dict[type[BaseModel], type[RuleModel]]] = {}

    @classmethod
    def for_model(cls, model: type[BaseModel]) -> RuleModel:
        return cls._new(TypeShape(model))

    @classmethod
    def _new(
        cls,
        shape: TypeShape,
        steps: tuple[Step, ...] = (),
        guards: tuple[Narrowing, ...] = (),
    ) -> RuleModel:
        symbolic = RuleModel
        if is_model(shape.annotation):
            model = shape.annotation
            if model not in cls._model_types:
                cls._model_types[model] = type(
                    f"{model.__name__}RuleModel",
                    (RuleModel,),
                    {
                        "__slots__": (),
                        "__module__": model.__module__,
                        "__annotations__": dict.fromkeys(model.model_fields, RuleModel),
                        **{name: ModelAttribute(name) for name in model.model_fields},
                    },
                )
            symbolic = cls._model_types[model]
        return symbolic(shape, steps, guards)

    def __getattr__(self, name: str) -> RuleModel:
        if name.startswith("_"):
            raise AttributeError(name)
        if not is_model(self._shape.concrete()):
            raise RuleDefinitionError(
                "Attribute access requires a model; use indexing for containers"
            )
        return self[name]

    @definition("Paths require string keys or nonnegative indexes")
    def __getitem__(self, key: PathKey) -> RuleModel:
        shape, steps = Reference._child(self, key)
        return RuleModel._new(shape, steps, self._guards)

    def when(self, target: object) -> RuleModel:
        shape, targets = self._shape.select(target)
        guard = Narrowing(self, targets)
        return RuleModel._new(shape, self._steps, (*self._guards, guard))

    def __bool__(self) -> bool:
        raise RuleDefinitionError("Compare a reference to construct a rule")

    @definition("Unsupported rule literal: {value!r}")
    def _equality(
        self,
        operator: EqualityOperator,
        other: Annotated[
            object, ValidateAs(InstanceOf[RuleModel] | JsonLiteral, lambda value: value)
        ],
    ) -> Rule:
        return Rule(Equality(operator, self, _operand(other)))

    @definition(
        "Numeric comparisons require numeric operands; narrow unions with .when()"
    )
    def _ordering(
        self, operator: OrderingOperator, other: InstanceOf[RuleModel] | JsonNumber
    ) -> Rule:
        return Rule(Ordering(operator, self, _operand(other)))

    def __eq__(self, other: object) -> Rule:  # type: ignore[override]
        return self._equality(EqualityOperator.EQ, other)

    def __ne__(self, other: object) -> Rule:  # type: ignore[override]
        return self._equality(EqualityOperator.NE, other)

    def __lt__(self, other: RuleModel | Number) -> Rule:
        return self._ordering(OrderingOperator.LT, other)

    def __le__(self, other: RuleModel | Number) -> Rule:
        return self._ordering(OrderingOperator.LE, other)

    def __gt__(self, other: RuleModel | Number) -> Rule:
        return self._ordering(OrderingOperator.GT, other)

    def __ge__(self, other: RuleModel | Number) -> Rule:
        return self._ordering(OrderingOperator.GE, other)

    @definition("Membership requires an array of primitive elements")
    def in_[T: Primitive](
        self, collection: InstanceOf[RuleModel] | JsonCollection[T]
    ) -> Rule:
        operand = (
            collection
            if isinstance(collection, RuleModel)
            else LiteralValue(tuple(collection))
        )
        return Rule(Membership(self, operand))

    @definition("unique_by requires a string property name")
    def unique_by(self, property_name: PropertyName) -> Rule:
        return Rule(Uniqueness(self, Projection.for_collection(self, property_name)))


def _operand(value: object) -> Operand[Any]:
    # Dynamic model authoring cannot statically know a field's value type.
    # Each node validates this operand against its declared shape on construction.
    return value if isinstance(value, RuleModel) else LiteralValue(value)
