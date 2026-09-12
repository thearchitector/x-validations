"""Adding a node requires its own evaluation and schema methods, no registry."""

import pytest
from pydantic import BaseModel, Field, GetJsonSchemaHandler, ValidationError
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema

from pydantic_ajv import Node, Rule, RuleModel, rule


def test_rule_resolves_current_instance_without_capturing_state() -> None:
    class Example(BaseModel):
        value: int

    expression = RuleModel.for_model(Example).value > 0
    first, second = Example(value=1), Example(value=-1)
    assert expression.resolve(first) is True
    assert expression.resolve(second) is False
    second.value = 2
    first.value = -2
    assert expression.resolve(first) is False
    assert expression.resolve(second) is True


def test_custom_node_owns_both_targets_and_composites_short_circuit() -> None:
    evaluated: list[BaseModel] = []
    exports: list[JsonSchemaValue] = []

    class Reject(Node):
        def resolve(self, instance: BaseModel) -> bool:
            evaluated.append(instance)
            return False

        def dump(
            self, handler: GetJsonSchemaHandler, schema: JsonSchemaValue
        ) -> JsonSchemaValue:
            exports.append(schema)
            return {"not": {}}

    class Example(BaseModel):
        mode: str

        @rule
        @classmethod
        def reject(cls, x: RuleModel) -> Rule:
            return (x.mode == "skip") | Rule(Reject())

    assert Example(mode="skip")
    assert evaluated == []
    with pytest.raises(ValidationError) as error:
        Example(mode="checked")
    assert len(evaluated) == 1
    assert error.value.errors()[0]["loc"] == ()
    schema = Example.model_json_schema()
    assert schema["allOf"][0]["anyOf"][1] == {"not": {}}
    assert exports[0]["properties"] == schema["properties"]


def test_direct_rule_dump_uses_pydantic_handler_options() -> None:
    class Example(BaseModel):
        value: int = Field(alias="amount")

        @classmethod
        def __get_pydantic_json_schema__(
            cls, core: CoreSchema, handler: GetJsonSchemaHandler
        ) -> JsonSchemaValue:
            schema = handler.resolve_ref_schema(handler(core))
            expression = RuleModel.for_model(cls).value > 0
            schema["allOf"] = [expression.dump(handler, schema)]
            return schema

    for by_alias in [True, False, True]:
        fragment = Example.model_json_schema(by_alias=by_alias)["allOf"][0]
        assert fragment["title"] == "rule"
        assert fragment["then"]["properties"] == {
            "amount" if by_alias else "value": {"type": "number", "exclusiveMinimum": 0}
        }
