"""Root-only Pydantic export behavior."""

from pydantic import BaseModel

from xvalidations import ValidationRule, XValidationContext, xvalidation

XVALIDATIONS_SCHEMA_URI = "https://thearchitector.dev/xvalidations/schema.json"


def test_root_rule_serializes_target_path_operands_and_metadata() -> None:
    class Order(BaseModel):
        maximum_price: int
        prices: list[int]

        @xvalidation(id="price-limit", description="Prices stay under the limit.")
        @classmethod
        def price_limit(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.prices.each()).assert_schema({
                "maximum": x.path.maximum_price
            })

    schema = Order.model_json_schema()
    assert schema["$schema"] == XVALIDATIONS_SCHEMA_URI
    assert schema["$id"].startswith("urn:xvalidations:")
    assert schema["x-validations"] == [
        {
            "id": "price-limit",
            "description": "Prices stay under the limit.",
            "target": "$.prices[*]",
            "assert": {"maximum": {"$path": "$.maximum_price"}},
        }
    ]


def test_nested_model_rules_are_not_embedded_in_root_defs() -> None:
    class Line(BaseModel):
        price: int

        @xvalidation
        @classmethod
        def positive(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.price).assert_schema({"minimum": 0})

    class Order(BaseModel):
        maximum_price: int
        lines: list[Line]

        @xvalidation
        @classmethod
        def line_price_limit(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.lines.each().price).assert_schema({
                "maximum": x.path.maximum_price
            })

    schema = Order.model_json_schema()
    assert schema["x-validations"][0]["target"] == "$.lines[*].price"
    assert "x-validations" not in repr(schema["$defs"])
    assert "$schema" not in schema["$defs"]["Line"]


def test_inheritance_uses_normal_method_resolution() -> None:
    class Base(BaseModel):
        value: int

        @xvalidation
        @classmethod
        def value_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"minimum": 0})

    class Child(Base):
        @xvalidation(override=True)
        @classmethod
        def value_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"maximum": 10})

    assert Child.model_json_schema()["x-validations"] == [
        {"id": "value-rule", "target": "$.value", "assert": {"maximum": 10}}
    ]


def test_serialization_and_rule_free_schemas_remain_ordinary() -> None:
    class Plain(BaseModel):
        value: int

    assert "x-validations" not in Plain.model_json_schema()

    class Ruled(Plain):
        @xvalidation
        @classmethod
        def value_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"minimum": 0})

    assert "x-validations" not in Ruled.model_json_schema(mode="serialization")
