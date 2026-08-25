from typing import Annotated, Any, ClassVar, Literal, override

import pytest
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    GetJsonSchemaHandler,
    WithJsonSchema,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema
from xvalidate import XValidationError, xvalidate

from xvalidations import (
    InvalidRuleError,
    InvalidSchemaError,
    ValidationRule,
    XValidationContext,
    xvalidation,
)

XVALIDATIONS_SCHEMA_URI = "https://thearchitector.dev/xvalidations/schema.json"


def test_validation_exports_are_deterministic_fresh_and_validation_only() -> None:
    calls = 0

    class Model(BaseModel):
        upper: int = Field(alias="upperAlias")
        value: int = Field(alias="valueAlias")

        @xvalidation(description="Value must be bounded.")
        @classmethod
        def bounded(cls, x: XValidationContext) -> ValidationRule:
            nonlocal calls
            calls += 1
            return x.target(x.path.value).assert_schema({"maximum": x.path.upper})

    first = Model.model_json_schema()
    first["x-validations"][0]["assert"]["maximum"]["$path"] = "mutated"
    second = Model.model_json_schema()

    assert calls == 2
    assert second["$schema"] == XVALIDATIONS_SCHEMA_URI
    assert second["$id"].startswith("urn:xvalidations:")
    assert len(second["$id"].rsplit(":", 1)[1]) == 64
    assert second["x-validations"] == [
        {
            "id": "bounded",
            "description": "Value must be bounded.",
            "target": "$.valueAlias",
            "assert": {"maximum": {"$path": "$.upperAlias"}},
        }
    ]
    assert "x-constants" not in second
    assert "x-validations" not in Model.model_json_schema(mode="serialization")


def test_inline_literals_are_owned_normalized_and_never_hoisted() -> None:
    assertion: dict[str, Any] = {"allOf": ({"enum": [1, 2]}, {"const": None})}

    class Model(BaseModel):
        value: int

        @xvalidation
        @classmethod
        def value_rule(cls, x: XValidationContext) -> ValidationRule:
            assertion["allOf"][1]["const"] = x.path.value
            return ValidationRule(x.path.value, assertion)  # type: ignore[arg-type]

    first = Model.model_json_schema()
    first["x-validations"][0]["assert"]["allOf"][0]["enum"].append(3)
    second = Model.model_json_schema()

    assert second["x-validations"][0]["assert"] == {
        "allOf": [{"enum": [1, 2]}, {"const": {"$path": "$.value"}}]
    }
    assert "x-constants" not in second


def test_nested_and_reused_resources_are_local() -> None:
    class Child(BaseModel):
        allowed: list[str]
        value: str

        @xvalidation
        @classmethod
        def value_allowed(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"enum": x.path.allowed.each()})

    class Parent(BaseModel):
        first: Child
        children: list[Child]

    schema = Parent.model_json_schema()
    child = schema["$defs"]["Child"]
    assert child["$schema"] == XVALIDATIONS_SCHEMA_URI
    assert child["x-validations"][0]["assert"] == {"enum": {"$path": "$.allowed[*]"}}

    with pytest.raises(XValidationError) as exc_info:
        xvalidate(
            {
                "first": {"allowed": ["a"], "value": "bad"},
                "children": [{"allowed": ["b"], "value": "bad"}],
            },
            schema,
        )
    assert [(error.path, error.rule_id) for error in exc_info.value.errors] == [
        ("$.children[0].value", "value-allowed"),
        ("$.first.value", "value-allowed"),
    ]


def test_forward_references_and_recursive_resources_export_after_rebuild() -> None:
    calls = 0

    class Node(BaseModel):
        allowed: list[str]
        value: str
        child: Node | None = None

        @xvalidation
        @classmethod
        def allowed_value(cls, x: XValidationContext) -> ValidationRule:
            nonlocal calls
            calls += 1
            return x.target(x.path.value).assert_schema({"enum": x.path.allowed.each()})

    Node.model_rebuild()
    schema = Node.model_json_schema()
    assert calls == 1
    assert schema["properties"]["child"]["anyOf"][0] == {"$dynamicRef": "#"}
    with pytest.raises(XValidationError) as exc_info:
        xvalidate(
            {
                "allowed": ["root"],
                "value": "root",
                "child": {"allowed": ["child"], "value": "bad"},
            },
            schema,
        )
    assert exc_info.value.errors[0].path == "$.child.value"


def test_structural_definitions_are_bundled_without_schema_data_heuristics() -> None:
    metadata = {
        "examples": [
            {
                "$ref": "instance data",
                "properties": {"not": "a schema"},
                "items": {"also": "data"},
            }
        ]
    }

    class Vendor(BaseModel):
        country: str

    class Order(BaseModel):
        model_config = ConfigDict(json_schema_extra=metadata)
        vendor: Vendor

        @xvalidation
        @classmethod
        def country(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.vendor.country).assert_schema({
                "const": x.path.vendor.country
            })

    schema = Order.model_json_schema()
    assert schema["properties"]["vendor"]["$dynamicRef"].startswith("#/$defs/")
    assert schema["examples"] == metadata["examples"]


def test_alias_choices_apply_to_targets_predicates_and_operands() -> None:
    class Item(BaseModel):
        kind: str = Field(validation_alias=AliasChoices("kindAlias", "kind"))
        value: str = Field(alias="valueAlias")

    class Model(BaseModel):
        allowed: list[str] = Field(alias="allowedAlias")
        items: list[Item] = Field(alias="itemsAlias")

        @xvalidation
        @classmethod
        def item_allowed(cls, x: XValidationContext) -> ValidationRule:
            return x.target(
                x.path.items.where(x.this.kind == "selected").value
            ).assert_schema({"enum": x.path.allowed.each()})

    rule = Model.model_json_schema()["x-validations"][0]
    assert rule["target"] == '$.itemsAlias[?(@.kindAlias == "selected")].valueAlias'
    assert rule["assert"] == {"enum": {"$path": "$.allowedAlias[*]"}}


def test_paths_retain_reachable_union_branches() -> None:
    class WithValue(BaseModel):
        value: int

    class WithoutValue(BaseModel):
        other: str

    class Model(BaseModel):
        upper: int
        item: WithValue | WithoutValue

        @xvalidation
        @classmethod
        def bounded(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.item.value).assert_schema({"maximum": x.path.upper})

    assert Model.model_json_schema()["x-validations"][0]["target"] == "$.item.value"

    class Impossible(BaseModel):
        item: WithValue | WithoutValue

        @xvalidation
        @classmethod
        def missing(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.item.missing).assert_schema({
                "const": x.path.item.value
            })

    with pytest.raises(InvalidRuleError):
        Impossible.model_json_schema()

    CompatibleAllOf = Annotated[
        Any,
        WithJsonSchema({
            "allOf": [{"type": "integer"}, {"type": ["integer", "number"]}]
        }),
    ]

    class Compatible(BaseModel):
        limit: int
        value: CompatibleAllOf

        @xvalidation
        @classmethod
        def bounded(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"maximum": x.path.limit})

    assert Compatible.model_json_schema()["x-validations"]


def test_operand_and_target_compatibility_use_existential_union_semantics() -> None:
    class Accepted(BaseModel):
        upper: int | str
        value: int | str

        @xvalidation
        @classmethod
        def maximum(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"maximum": x.path.upper})

    assert Accepted.model_json_schema()["x-validations"]

    class BadOperand(BaseModel):
        upper: str
        value: int

        @xvalidation
        @classmethod
        def maximum(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"maximum": x.path.upper})

    with pytest.raises(InvalidRuleError):
        BadOperand.model_json_schema()

    class BadTarget(BaseModel):
        upper: int
        value: str

        @xvalidation
        @classmethod
        def maximum(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"maximum": x.path.upper})

    with pytest.raises(InvalidRuleError):
        BadTarget.model_json_schema()


def test_scalar_collection_optional_literal_and_unknown_operands() -> None:
    class Accepted(BaseModel):
        allowed: list[str]
        allowed_type: Literal["string"]
        limit: int | None
        value: str

        @xvalidation(id="enum-many")
        @classmethod
        def enum_many(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"enum": x.path.allowed.each()})

        @xvalidation(id="enum-list")
        @classmethod
        def enum_list(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"enum": x.path.allowed})

        @xvalidation(id="dynamic-type")
        @classmethod
        def dynamic_type(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({
                "type": x.path.allowed_type,
                "const": x.path.value,
            })

    assert len(Accepted.model_json_schema()["x-validations"]) == 3

    class TypeOnly(BaseModel):
        allowed_type: Literal["string"]
        value: str

        @xvalidation
        @classmethod
        def type_only(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"type": x.path.allowed_type})

    with pytest.raises(InvalidRuleError):
        TypeOnly.model_json_schema()

    class Unknown(BaseModel):
        operand: Any
        value: str

        @xvalidation
        @classmethod
        def unknown(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"const": x.path.operand})

    assert Unknown.model_json_schema()["x-validations"]

    class DynamicType(BaseModel):
        type_name: str
        value: str

        @xvalidation
        @classmethod
        def dynamic_type(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({
                "allOf": [
                    {"type": ["string"]},
                    {"type": x.path.type_name},
                    {"const": x.path.value},
                ]
            })

    with pytest.raises(InvalidRuleError):
        DynamicType.model_json_schema()

    class UnknownItems(BaseModel):
        allowed: list[Any]
        value: str

        @xvalidation
        @classmethod
        def unknown_items(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"enum": x.path.allowed})

    assert UnknownItems.model_json_schema()["x-validations"]


def test_logical_conditional_contains_and_unique_by_are_supported() -> None:
    class Model(BaseModel):
        expected: int
        values: list[int]

        @xvalidation
        @classmethod
        def contains_expected(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.values).assert_schema({
                "allOf": [
                    {"contains": {"const": x.path.expected}},
                    {"if": {"minItems": 1}, "then": {"minContains": 1}, "else": False},
                ]
            })

    schema = Model.model_json_schema()
    assert schema["x-validations"][0]["assert"]["allOf"][0] == {
        "contains": {"const": {"$path": "$.expected"}}
    }

    class Unique(BaseModel):
        rows: list[dict[str, str]]

        @xvalidation
        @classmethod
        def unique(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.rows).assert_schema({"x-uniqueBy": "$.id"})

    assert Unique.model_json_schema()["x-validations"][0]["assert"] == {
        "x-uniqueBy": "$.id"
    }


def test_all_validation_operand_families_accept_compatible_paths() -> None:
    class Model(BaseModel):
        count: int
        pattern: str
        enabled: bool
        names: list[str]
        dependencies: dict[str, list[str]]
        text: str
        values: list[int]
        data: dict[str, int]

        @xvalidation(id="string")
        @classmethod
        def string_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.text).assert_schema({
                "maxLength": x.path.count,
                "minLength": x.path.count,
                "pattern": x.path.pattern,
            })

        @xvalidation(id="array")
        @classmethod
        def array_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.values).assert_schema({
                "maxItems": x.path.count,
                "minItems": x.path.count,
                "uniqueItems": x.path.enabled,
                "contains": {"maximum": x.path.count},
                "maxContains": x.path.count,
                "minContains": x.path.count,
            })

        @xvalidation(id="object")
        @classmethod
        def object_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.data).assert_schema({
                "maxProperties": x.path.count,
                "minProperties": x.path.count,
                "required": x.path.names,
                "dependentRequired": x.path.dependencies,
            })

    assert len(Model.model_json_schema()["x-validations"]) == 3

    class BadRequired(BaseModel):
        names: list[int]
        data: dict[str, int]

        @xvalidation
        @classmethod
        def bad(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.data).assert_schema({"required": x.path.names})

    with pytest.raises(InvalidRuleError):
        BadRequired.model_json_schema()

    class BadDependentRequired(BaseModel):
        dependencies: dict[str, list[int]]
        data: dict[str, int]

        @xvalidation
        @classmethod
        def bad(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.data).assert_schema({
                "dependentRequired": x.path.dependencies
            })

    with pytest.raises(InvalidRuleError):
        BadDependentRequired.model_json_schema()


def test_logical_union_assertions_and_literal_json_types() -> None:
    class Model(BaseModel):
        expected: None | bool | int | float | str | list[int] | dict[str, int]
        value: None | bool | int | float | str | list[int] | dict[str, int]

        @xvalidation
        @classmethod
        def dynamic(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({
                "allOf": [
                    {
                        "anyOf": [
                            False,
                            {"enum": [None, True, 1, 1.5, "x", [1], {"x": 1}]},
                            {"const": x.path.expected},
                        ]
                    },
                    {
                        "oneOf": [
                            {"not": {"const": x.path.expected}},
                            {"const": x.path.expected},
                        ]
                    },
                ]
            })

    assert Model.model_json_schema()["x-validations"]


def test_mapping_tuple_slice_union_recursive_and_wildcard_traversal() -> None:
    class Child(BaseModel):
        value: int

    class Model(BaseModel):
        limit: int
        mapping: dict[str, Child]
        pair: tuple[Child, Child]
        children: list[Child]
        first: int
        second: int

        @xvalidation(id="mapping")
        @classmethod
        def mapping_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.mapping["chosen"].value).assert_schema({
                "maximum": x.path.limit
            })

        @xvalidation(id="tuple-index")
        @classmethod
        def tuple_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.pair.at(-1).value).assert_schema({
                "maximum": x.path.limit
            })

        @xvalidation(id="tuple-slice")
        @classmethod
        def tuple_slice_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.pair.slice().value).assert_schema({
                "maximum": x.path.limit
            })

        @xvalidation(id="recursive")
        @classmethod
        def recursive_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.desc("value")).assert_schema({
                "maximum": x.path.limit
            })

        @xvalidation(id="union")
        @classmethod
        def union_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(
                x.path.select(x.key("first"), x.key("second"))
            ).assert_schema({"maximum": x.path.limit})

        @xvalidation(id="wildcard")
        @classmethod
        def wildcard_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.children.each().value).assert_schema({
                "maximum": x.path.limit
            })

    rules = Model.model_json_schema()["x-validations"]
    assert len(rules) == 6
    assert next(rule for rule in rules if rule["id"] == "union")["target"] == (
        '$["first","second"]'
    )

    class Record(BaseModel):
        first: int
        second: int

    class Wildcards(BaseModel):
        limit: int
        record: Record
        mapping: dict[str, int]

        @xvalidation(id="record")
        @classmethod
        def record_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.record.each()).assert_schema({
                "maximum": x.path.limit
            })

        @xvalidation(id="mapping")
        @classmethod
        def mapping_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.mapping.each()).assert_schema({
                "maximum": x.path.limit
            })

    assert len(Wildcards.model_json_schema()["x-validations"]) == 2


def test_generated_schema_forms_require_explicit_type_declarations() -> None:
    Pattern = Annotated[Any, WithJsonSchema({"type": "string", "pattern": "^x"})]
    Array = Annotated[
        Any, WithJsonSchema({"type": "array", "items": {"type": "integer"}})
    ]
    Object = Annotated[
        Any,
        WithJsonSchema({"type": "object", "properties": {"x": {"type": "integer"}}}),
    ]
    Numeric = Annotated[Any, WithJsonSchema({"type": "integer", "maximum": 10})]

    class Inferred(BaseModel):
        pattern: Pattern
        array: Array
        object: Object
        numeric: Numeric

        @xvalidation(id="pattern")
        @classmethod
        def pattern_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.pattern).assert_schema({"const": x.path.pattern})

        @xvalidation(id="array")
        @classmethod
        def array_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.array).assert_schema({"const": x.path.array})

        @xvalidation(id="object")
        @classmethod
        def object_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.object).assert_schema({"const": x.path.object})

        @xvalidation(id="numeric")
        @classmethod
        def numeric_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.numeric).assert_schema({"const": x.path.numeric})

    assert len(Inferred.model_json_schema()["x-validations"]) == 4

    for generated_schema in (
        {"pattern": "^x"},
        {"items": {"type": "integer"}},
        {"properties": {"x": {"type": "integer"}}},
        {"maximum": 10},
        {},
    ):
        Untyped = Annotated[Any, WithJsonSchema(generated_schema)]

        class Indeterminate(BaseModel):
            unknown: Untyped

            @xvalidation
            @classmethod
            def unknown_rule(cls, x: XValidationContext) -> ValidationRule:
                return x.target(x.path.unknown).assert_schema({"const": x.path.unknown})

        with pytest.raises(InvalidRuleError):
            Indeterminate.model_json_schema()

    Contradictory = Annotated[
        Any, WithJsonSchema({"allOf": [{"type": "string"}, {"type": "integer"}]})
    ]

    class Impossible(BaseModel):
        value: Contradictory

        @xvalidation
        @classmethod
        def impossible(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"const": x.path.value})

    with pytest.raises(InvalidRuleError):
        Impossible.model_json_schema()


def test_static_structural_reference_annotation_and_resource_assertions_are_rejected() -> (
    None
):
    assertions = [
        {"const": "static"},
        {"properties": {}},
        {"items": {}},
        {"$ref": "#/$defs/X"},
        {"title": "annotation"},
        {"$id": "urn:assertion"},
        {"x-unknown": True},
        {"pattern": "[", "const": XValidationContext().path.value},
    ]
    for assertion in assertions:

        class Invalid(BaseModel):
            value: str

            @xvalidation
            @classmethod
            def invalid(
                cls, x: XValidationContext, authored: object = assertion
            ) -> ValidationRule:
                return ValidationRule(x.path.value, authored)  # type: ignore[arg-type]

        with pytest.raises(InvalidRuleError):
            Invalid.model_json_schema()

    malformed_applicators = [
        {"not": 1, "const": XValidationContext().path.value},
        {"allOf": {}, "const": XValidationContext().path.value},
    ]
    for assertion in malformed_applicators:

        class InvalidApplicator(BaseModel):
            value: str

            @xvalidation
            @classmethod
            def invalid(
                cls, x: XValidationContext, authored: object = assertion
            ) -> ValidationRule:
                return ValidationRule(x.path.value, authored)  # type: ignore[arg-type]

        with pytest.raises(InvalidRuleError):
            InvalidApplicator.model_json_schema()

    class NestedUniqueBy(BaseModel):
        rows: list[dict[str, str]]

        @xvalidation
        @classmethod
        def nested(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.rows.each()).assert_schema({
                "allOf": [{"x-uniqueBy": "$.id"}]
            })

    with pytest.raises(InvalidRuleError):
        NestedUniqueBy.model_json_schema()


@pytest.mark.parametrize(
    "assertion",
    [
        pytest.param({1: "value"}, id="non-string-key"),
        pytest.param({"const": float("inf")}, id="non-finite"),
        pytest.param({"const": object()}, id="non-json"),
        pytest.param({"$path": "$.value"}, id="reserved-marker"),
        pytest.param({"const": {"$resolve": "$.value"}}, id="removed-resolve-marker"),
        pytest.param({"x-uniqueBy": 1}, id="bad-unique-by"),
    ],
)
def test_malformed_authored_json_fails_during_export(assertion: object) -> None:
    class Invalid(BaseModel):
        value: str

        @xvalidation
        @classmethod
        def invalid(cls, x: XValidationContext) -> ValidationRule:
            return ValidationRule(x.path.value, assertion)  # type: ignore[arg-type]

    with pytest.raises(InvalidRuleError):
        Invalid.model_json_schema()


def test_inherited_rules_require_explicit_replacement() -> None:
    class Base(BaseModel):
        value: str

        @xvalidation
        @classmethod
        def value_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"const": x.path.value})

    class Inherited(Base):
        pass

    assert Inherited.model_json_schema()["x-validations"]

    class Specialized(Base):
        @xvalidation(id="specialized")
        @classmethod
        @override
        def value_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"const": x.path.value})

    assert Specialized.model_json_schema()["x-validations"][0]["id"] == "specialized"

    class MissingOverride(Base):
        @xvalidation
        @classmethod
        def value_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"const": x.path.value})

    with pytest.raises(InvalidRuleError):
        MissingOverride.model_json_schema()

    class Shadowed(Base):
        value_rule: ClassVar[str] = "shadowed"

    with pytest.raises(InvalidRuleError):
        Shadowed.model_json_schema()


def test_override_without_base_ambiguity_and_duplicate_ids_fail() -> None:
    class NothingToOverride(BaseModel):
        value: str

        @xvalidation(override=True)
        @classmethod
        def value_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"const": x.path.value})

    with pytest.raises(InvalidRuleError):
        NothingToOverride.model_json_schema()

    class Left(BaseModel):
        value: str

        @xvalidation
        @classmethod
        def value_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"const": x.path.value})

    class Right(BaseModel):
        value: str

        @xvalidation
        @classmethod
        def value_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"const": x.path.value})

    class Ambiguous(Left, Right):
        pass

    with pytest.raises(InvalidRuleError):
        Ambiguous.model_json_schema()

    class Duplicate(BaseModel):
        first: str
        second: str

        @xvalidation(id="same")
        @classmethod
        def first_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.first).assert_schema({"const": x.path.first})

        @xvalidation(id="same")
        @classmethod
        def second_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.second).assert_schema({"const": x.path.second})

    with pytest.raises(InvalidRuleError):
        Duplicate.model_json_schema()


def test_invalid_factories_targets_and_ids_fail_at_export() -> None:
    class BadReturn(BaseModel):
        value: str

        @xvalidation
        @classmethod
        def bad(cls, x: XValidationContext) -> ValidationRule:
            return "bad"  # type: ignore[return-value]

    class BadTarget(BaseModel):
        value: str

        @xvalidation
        @classmethod
        def bad(cls, x: XValidationContext) -> ValidationRule:
            return ValidationRule("$.value", {"const": x.path.value})  # type: ignore[arg-type]

    class EmptyId(BaseModel):
        value: str

        @xvalidation
        @classmethod
        def ___(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"const": x.path.value})

    class BadAssertion(BaseModel):
        value: str

        @xvalidation
        @classmethod
        def bad(cls, x: XValidationContext) -> ValidationRule:
            return ValidationRule(x.path.value, [])  # type: ignore[arg-type]

    for model in (BadReturn, BadTarget, EmptyId, BadAssertion):
        with pytest.raises(InvalidRuleError):
            model.model_json_schema()


@pytest.mark.parametrize("reserved", ["$schema", "$id", "x-validations", "x-constants"])
def test_ruled_resources_reject_author_supplied_owned_keys(reserved: str) -> None:
    class Reserved(BaseModel):
        model_config = ConfigDict(json_schema_extra={reserved: {}})
        value: str

        @xvalidation
        @classmethod
        def value_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"const": x.path.value})

    with pytest.raises(InvalidSchemaError):
        Reserved.model_json_schema()


def test_existing_class_local_hook_is_composed_once_and_subclass_uses_super() -> None:
    calls: list[str] = []

    class Base(BaseModel):
        value: str

        @classmethod
        def __get_pydantic_json_schema__(
            cls, core_schema: CoreSchema, handler: GetJsonSchemaHandler
        ) -> JsonSchemaValue:
            calls.append(f"base:{handler.mode}")
            schema = super().__get_pydantic_json_schema__(core_schema, handler)
            schema["base-hook"] = True
            return schema

        @xvalidation
        @classmethod
        def value_rule(cls, x: XValidationContext) -> ValidationRule:
            return x.target(x.path.value).assert_schema({"const": x.path.value})

    class Child(Base):
        @classmethod
        def __get_pydantic_json_schema__(
            cls, core_schema: CoreSchema, handler: GetJsonSchemaHandler
        ) -> JsonSchemaValue:
            schema = super().__get_pydantic_json_schema__(core_schema, handler)
            schema["child-hook"] = True
            return schema

    schema = Child.model_json_schema()
    assert schema["base-hook"] is True
    assert schema["child-hook"] is True
    assert schema["x-validations"]
    assert calls == ["base:validation"]


def test_rule_free_models_retain_ordinary_pydantic_behavior() -> None:
    class Plain(BaseModel):
        value: str

    assert Plain.model_json_schema() == {
        "properties": {"value": {"title": "Value", "type": "string"}},
        "required": ["value"],
        "title": "Plain",
        "type": "object",
    }
    assert Plain.model_json_schema(mode="serialization") == Plain.model_json_schema()
