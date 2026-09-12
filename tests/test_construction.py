"""References know model types while the rule factory is executing."""

from collections.abc import Callable
from typing import Annotated, Literal

import pytest
from pydantic import BaseModel, Field, RootModel, ValidationError

from pydantic_ajv import Rule, RuleDefinitionError, RuleModel, rule


@pytest.mark.parametrize(
    "expression",
    [lambda x: x.root > 0, lambda x: (x.root.when(int) > 0) | (x.root < 10)],
    ids=["unguarded", "guarded_sibling"],
)
def test_mixed_union_requires_narrowing(
    expression: Callable[[RuleModel], Rule],
) -> None:
    with pytest.raises(RuleDefinitionError):

        class Invalid(RootModel[int | str]):
            @rule
            @classmethod
            def check(cls, x: RuleModel) -> Rule:
                return expression(x)


def test_errors_are_raised_inside_factory() -> None:
    observed = []

    class Example(BaseModel):
        value: int | str

        @rule
        @classmethod
        def positive(cls, x: RuleModel) -> Rule:
            with pytest.raises(RuleDefinitionError):
                _ = x.value > 0
            with pytest.raises(RuleDefinitionError):
                _ = x.unknown
            observed.append(True)
            return x.value.when(int) > 0

    assert observed == [True]
    assert Example(value="skip")
    with pytest.raises(ValidationError):
        Example(value=-1)


def test_nested_narrowing_retains_parent_guard() -> None:
    class Numeric(BaseModel):
        kind: Literal["number"]
        value: int | str

    class Text(BaseModel):
        kind: Literal["text"]
        value: str

    class Choice(BaseModel):
        child: Annotated[Numeric | Text, Field(discriminator="kind")]

        @rule
        @classmethod
        def check(cls, x: RuleModel) -> Rule:
            return x.child.when(Numeric).value.when(int) > 0

    for _ in range(3):
        for tag, value in [("text", "hello"), ("number", "hello"), ("number", 2)]:
            assert Choice.model_validate({"child": {"kind": tag, "value": value}})
        with pytest.raises(ValidationError) as error:
            Choice.model_validate({"child": {"kind": "number", "value": -1}})
        assert error.value.errors()[0]["loc"] == ()
        assert "paths" not in error.value.errors()[0]["ctx"]


def test_both_operand_guards_must_match() -> None:
    class Pair(BaseModel):
        a: float | str
        b: int | str

        @rule
        @classmethod
        def check(cls, x: RuleModel) -> Rule:
            return x.a.when(float) < x.b.when(int)

    for a, b in [(1.0, 2), ("text", 0), (1.0, "text")]:
        assert Pair(a=a, b=b)
    for a, b in [(2.0, 1), (1.5, 0)]:
        with pytest.raises(ValidationError):
            Pair(a=a, b=b)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(float("inf"), True), (float("-inf"), False), (float("nan"), False)],
)
def test_python_ordering_uses_native_numeric_semantics(
    value: float, expected: bool
) -> None:
    class Number(RootModel[float]):
        pass

    expression = RuleModel.for_model(Number).root >= 0
    assert expression.resolve(Number(value)) is expected


def test_repeated_composite_diagnostics_do_not_retain_state() -> None:
    class Pair(BaseModel):
        a: int
        b: int

        @rule(error="invalid pair")
        @classmethod
        def check(cls, x: RuleModel) -> Rule:
            return ((x.a > 0) & (x.b > 0)) | (x.a == x.b)

    for _ in range(3):
        with pytest.raises(ValidationError) as error:
            Pair(a=-1, b=-2)
        diagnostic = error.value.errors()[0]
        assert diagnostic["loc"] == ()
        assert diagnostic["msg"] == "invalid pair"
        assert diagnostic["ctx"] == {"message": "invalid pair", "rule_id": "check"}
        assert Pair(a=1, b=2)
        Pair.model_json_schema()


@pytest.mark.parametrize("validated", [False, True])
def test_defaults_are_owned_by_pydantic(validated: bool) -> None:
    class Leaf(BaseModel):
        value: int = 3

    class Middle(BaseModel):
        leaf: Leaf = Field(default={}, validate_default=validated)

    class Parent(BaseModel):
        middle: Middle = Field(default={}, validate_default=True)

        @rule
        @classmethod
        def check(cls, x: RuleModel) -> Rule:
            return x.middle.leaf.value > 3

    if validated:
        with pytest.raises(ValidationError):
            Parent()
    else:
        assert Parent()
    with pytest.raises(ValidationError):
        Parent.model_validate({"middle": {"leaf": {}}})
    assert Parent.model_validate({"middle": {"leaf": {"value": 4}}})


@pytest.mark.parametrize(
    ("annotation", "expression"),
    [
        (list[int], lambda x: x.unique_by("id")),
        (int, lambda x: x.unique_by("id")),
        (list, lambda x: x.unique_by("id")),
        (list[dict[str, list[int]]], lambda x: x.unique_by("id")),
        (tuple[int, str], lambda x: x[2] == 1),
        (list[int], lambda x: x["key"] == 1),
        (dict[int, int], lambda x: x["key"] == 1),
        (int, lambda x: x["key"] == 1),
    ],
    ids=[
        "scalar_items",
        "scalar_unique",
        "untyped_unique",
        "object_projection",
        "tuple_bounds",
        "list_key",
        "nonstring_dictionary",
        "scalar_index",
    ],
)
def test_invalid_structural_operations(
    annotation: object, expression: Callable[[RuleModel], Rule]
) -> None:
    with pytest.raises(RuleDefinitionError):

        class Invalid(RootModel[annotation]):
            @rule
            @classmethod
            def check(cls, x: RuleModel) -> Rule:
                return expression(x.root)


def test_symbolic_objects_reject_python_truth_testing() -> None:
    class Example(BaseModel):
        value: int

    context = RuleModel.for_model(Example)
    with pytest.raises(RuleDefinitionError):
        bool(context.value)
    with pytest.raises(RuleDefinitionError):
        bool(context.value > 0)
    with pytest.raises(AttributeError):
        _ = context._private


def test_reused_factory_receives_each_owners_metadata() -> None:
    owners = []

    class First(BaseModel):
        value: int = Field(alias="first")

        @rule
        @classmethod
        def check(cls, x: RuleModel) -> Rule:
            owners.append(cls)
            return x.value > 0

    class Second(First):
        value: int = Field(alias="second")

    assert First in owners
    assert Second in owners
    for owner, key in [(First, "first"), (Second, "second"), (First, "first")]:
        assert owner.model_validate({key: 1})
        with pytest.raises(ValidationError):
            owner.model_validate({key: 0})
        for by_alias in [True, False, True]:
            schema = owner.model_json_schema(by_alias=by_alias)
            assert (key if by_alias else "value") in schema["properties"]


def test_sibling_branch_guards_are_local() -> None:
    class Number(BaseModel):
        kind: Literal["number"]
        value: int = Field(default=1, alias="numberValue")

    class Text(BaseModel):
        kind: Literal["text"]
        value: str = Field(default="ok", alias="textValue")

    class Choice(BaseModel):
        child: Annotated[Number | Text, Field(discriminator="kind")]

        @rule
        @classmethod
        def check(cls, x: RuleModel) -> Rule:
            return (x.child.when(Number).value > 0) & (x.child.when(Text).value == "ok")

    for _ in range(2):
        for kind in ["number", "text"]:
            assert Choice.model_validate({"child": {"kind": kind}})
        for child in [
            {"kind": "number", "numberValue": 0},
            {"kind": "text", "textValue": "bad"},
        ]:
            with pytest.raises(ValidationError):
                Choice.model_validate({"child": child})
