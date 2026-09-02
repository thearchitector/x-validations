"""Public decorated-classmethod authoring tests."""

from typing import get_type_hints

import pytest
from pydantic import BaseModel

import xvalidations
from xvalidations import ValidationRule, XValidationContext, xvalidation


def test_public_api_is_unchanged() -> None:
    assert xvalidations.__all__ == [
        "InvalidRuleError",
        "InvalidSchemaError",
        "RuleAssertion",
        "ValidationRule",
        "XValidationContext",
        "xvalidation",
    ]
    assert get_type_hints(ValidationRule)["target"].__name__ == "Path"


def test_bare_and_configured_decorators_serialize_in_declaration_order() -> None:
    class Model(BaseModel):
        value: str

        @xvalidation
        @classmethod
        def implicit_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"const": x.path.value})

        @xvalidation(id="explicit", description="Configured.")
        @classmethod
        def configured(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"const": x.path.value})

    rules = Model.model_json_schema()["x-validations"]
    assert [rule["id"] for rule in rules] == ["implicit-rule", "explicit"]
    assert rules[1]["description"] == "Configured."


def test_factory_runs_for_each_validation_export() -> None:
    calls = 0

    class Model(BaseModel):
        value: str

        @xvalidation
        @classmethod
        def allowed(cls, x: XValidationContext) -> ValidationRule:
            nonlocal calls
            calls += 1
            return x.target(x.path.value).assert_schema({"const": x.path.value})

    Model.model_json_schema()
    Model.model_json_schema()
    Model.model_json_schema(mode="serialization")
    assert calls == 2


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


def test_path_helpers_serialize_current_jsonpath() -> None:
    x = XValidationContext()
    assert x.path.items.where(x.this.kind == "field").name.to_jsonpath() == (
        '$.items[?(@.kind == "field")].name'
    )
    assert x.path.desc("field_id").to_jsonpath() == "$..field_id"
