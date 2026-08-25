"""Public decorated-classmethod authoring tests."""

from typing import Any, get_type_hints

import pytest
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

import xvalidations
from xvalidations import (
    InvalidRuleError,
    RuleAssertion,
    ValidationRule,
    XValidationContext,
    xvalidation,
)


def test_root_exports_are_the_settled_hard_cutover_api() -> None:
    assert xvalidations.__all__ == [
        "InvalidRuleError",
        "InvalidSchemaError",
        "RuleAssertion",
        "ValidationRule",
        "XValidationContext",
        "xvalidation",
    ]


def test_public_annotations_resolve_at_runtime() -> None:
    rule_hints = get_type_hints(ValidationRule)
    context_hints = get_type_hints(XValidationContext)

    assert rule_hints["assertion"] is RuleAssertion
    assert rule_hints["target"].__name__ == "Path"
    assert context_hints["path"].__name__ == "Path"
    assert context_hints["this"].__name__ == "Expr"


def test_bare_and_configured_decorators_normalize_ids() -> None:
    class Model(BaseModel):
        value: str

        @xvalidation
        @classmethod
        def __Implicit___Rule__(cls, x: XValidationContext) -> ValidationRule:
            """This docstring is not a description."""
            return x.target(x.path.value).assert_schema({"const": x.path.value})

        @xvalidation(id="EXPLICIT", description="Configured.")
        @classmethod
        def configured(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"const": x.path.value})

    rules = Model.model_json_schema()["x-validations"]
    assert [rule["id"] for rule in rules] == ["EXPLICIT", "implicit-rule"]
    assert rules[0]["description"] == "Configured."
    assert "description" not in rules[1]


def test_factory_runs_for_each_export_and_exported_data_is_owned() -> None:
    calls = 0

    class Model(BaseModel):
        value: str

        @xvalidation
        @classmethod
        def allowed(cls, x: XValidationContext) -> ValidationRule:
            nonlocal calls
            calls += 1
            assertion: dict[str, Any] = {"const": x.path.value, "enum": ["a"]}
            return x.target(x.path.value).assert_schema(assertion)  # type: ignore[arg-type]

    first = Model.model_json_schema()
    first["x-validations"][0]["assert"]["enum"].append("caller")
    second = Model.model_json_schema()

    assert calls == 2
    assert second["x-validations"][0]["assert"] == {
        "const": {"$path": "$.value"},
        "enum": ["a"],
    }


def test_forward_reference_runs_factory_during_schema_export() -> None:
    calls = 0

    class Deferred(BaseModel):
        child: Later

        @xvalidation
        @classmethod
        def child_name(cls, x: XValidationContext) -> ValidationRule:
            nonlocal calls
            calls += 1
            return x.target(x.path.child.name).assert_schema({
                "allOf": [{"minLength": 1}, {"const": x.path.child.name}]
            })

    assert calls == 0

    class Later(BaseModel):
        name: str

    Deferred.model_rebuild()
    assert calls == 0
    Deferred.model_json_schema()
    assert calls == 1


def test_factory_exception_propagates_naturally() -> None:
    class FactoryFailure(RuntimeError):
        pass

    class Broken(BaseModel):
        value: str

        @xvalidation
        @classmethod
        def broken(cls, x: XValidationContext) -> ValidationRule:
            raise FactoryFailure

    with pytest.raises(FactoryFailure):
        Broken.model_json_schema()


def test_invalid_factory_return_and_assertion_are_rejected_at_export() -> None:
    class BadReturn(BaseModel):
        value: str

        @xvalidation
        @classmethod
        def bad(cls, x: XValidationContext) -> ValidationRule:
            return "bad"  # type: ignore[return-value]

    with pytest.raises(InvalidRuleError):
        BadReturn.model_json_schema()

    class BadAssertion(BaseModel):
        value: str

        @xvalidation
        @classmethod
        def bad(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({
                "maximum": x.path.value,
                "type": 42,
            })  # type: ignore[arg-type]

    with pytest.raises(InvalidRuleError):
        BadAssertion.model_json_schema()


def test_incorrect_decorator_order_and_non_classmethod_fail() -> None:
    with pytest.raises(TypeError):

        class WrongOrder(BaseModel):
            value: str

            @classmethod
            @xvalidation
            def rule(cls, x: XValidationContext) -> ValidationRule:
                return x.target(x.path.value).assert_schema({"const": "a"})

    with pytest.raises(TypeError):
        xvalidation(lambda: None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        xvalidation(id=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        xvalidation(description=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        xvalidation(override=1)  # type: ignore[arg-type]


def test_context_selector_helpers_and_path_boundary() -> None:
    x = XValidationContext()

    assert x.path.select(x.key("odd key"), x.index(2)).to_jsonpath() == (
        '$["odd key",2]'
    )
    assert x.path.desc("name").to_jsonpath() == "$..name"
    assert x.path.desc(x.key("odd key"), x.index(1)).to_jsonpath() == (
        '$..["odd key",1]'
    )
    assert x.path.each().to_jsonpath() == "$[*]"
    assert x.path.at(2).to_jsonpath() == "$[2]"
    assert x.path.slice(1, 4, 2).to_jsonpath() == "$[1:4:2]"
    assert x.path.slice().to_jsonpath() == "$[:]"
    assert x.path.where(x.this["odd key"] != "value").to_jsonpath() == (
        '$[?(@["odd key"] != "value")]'
    )
    assert hash(x.this.name) == hash(x.this.name)
    assert x.wildcard() == x.wildcard()
    assert x.slice(1, 2, 1).step == 1
    assert x.filter(x.this.name == "a").predicate.value == "a"

    with pytest.raises(AttributeError):
        _ = x.path.__missing__
    with pytest.raises(AttributeError):
        _ = x.this.__missing__
    assert not hasattr(x, "resolve")
    with pytest.raises(PydanticValidationError):
        x.index("1")  # type: ignore[arg-type]


def test_union_rejects_non_key_or_index_selectors() -> None:
    x = XValidationContext()
    with pytest.raises(TypeError):
        x.path.select(x.wildcard(), x.index(1)).to_jsonpath()
