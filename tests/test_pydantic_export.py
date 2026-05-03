import copy
from typing import Annotated, Literal

import pytest
from pydantic import AliasChoices, AliasPath, BaseModel, Field

from xvalidations import XValidatedModel, XValidationContext, export_schema, xvalidation
from xvalidations.authoring import AuthoredRule
from xvalidations.errors import InvalidRuleError

XVALIDATIONS_SCHEMA_URI = (
    "https://thearchitector.dev/xvalidations/meta/x-validations.schema.json"
)


class Article(XValidatedModel):
    tags: list[str]
    primary_tag: str

    @xvalidation(
        id="primary-tag-exists", description="Primary tag must be present in tags."
    )
    def primary_tag_exists(x: XValidationContext) -> AuthoredRule:
        return x.target(x.path.primary_tag).assert_schema({
            "enum": x.resolve(x.path.tags.each())
        })


def test_article_export_matches_readme_contract() -> None:
    schema = Article.model_json_schema()

    assert schema["$schema"] == XVALIDATIONS_SCHEMA_URI
    assert schema["x-validations"] == [
        {
            "id": "primary-tag-exists",
            "description": "Primary tag must be present in tags.",
            "target": "$.primary_tag",
            "assert": {"enum": {"$resolve": "$.tags[*]"}},
        }
    ]


def test_model_without_rules_has_no_xvalidations_key() -> None:
    class Plain(XValidatedModel):
        name: str

    assert "x-validations" not in Plain.model_json_schema()


def test_constant_resolve_lifted_to_xv_def() -> None:
    class ConstantRule(XValidatedModel):
        tag: str

        @xvalidation(id="constant-tag", description="Tag must be generated constant.")
        def constant_tag(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.tag).assert_schema({"enum": x.resolve(["python"])})

    schema = ConstantRule.model_json_schema()
    rule_assert = schema["x-validations"][0]["assert"]
    ref = rule_assert["enum"]["$resolve"]

    assert ref.startswith("#/$defs/xv_")
    assert schema["$defs"][ref.removeprefix("#/$defs/")] == ["python"]


def test_identical_constants_dedupe_to_same_def() -> None:
    class ConstantRule(XValidatedModel):
        first: str
        second: str

        @xvalidation(id="first-tag", description="First tag must match.")
        def first_tag(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.first).assert_schema({"enum": x.resolve(["python"])})

        @xvalidation(id="second-tag", description="Second tag must match.")
        def second_tag(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.second).assert_schema({
                "enum": x.resolve(["python"])
            })

    schema = ConstantRule.model_json_schema()
    refs = [rule["assert"]["enum"]["$resolve"] for rule in schema["x-validations"]]

    assert refs[0] == refs[1]
    assert len(schema["$defs"]) == 1


def test_different_constants_get_different_defs() -> None:
    class ConstantRule(XValidatedModel):
        first: str
        second: str

        @xvalidation(id="first-tag", description="First tag must match.")
        def first_tag(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.first).assert_schema({"enum": x.resolve(["python"])})

        @xvalidation(id="second-tag", description="Second tag must match.")
        def second_tag(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.second).assert_schema({
                "enum": x.resolve(["pydantic"])
            })

    schema = ConstantRule.model_json_schema()

    assert len(schema["$defs"]) == 2


def test_literals_not_wrapped_in_resolve_stay_inline() -> None:
    class LiteralRule(XValidatedModel):
        tag: str

        @xvalidation(id="literal-tag", description="Tag must match.")
        def literal_tag(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.tag).assert_schema({"const": "python"})

    schema = LiteralRule.model_json_schema()

    assert "$defs" not in schema
    assert schema["x-validations"][0]["assert"] == {"const": "python"}


def test_nested_xvalidated_model_rule_rebased_to_root() -> None:
    class Child(XValidatedModel):
        tags: list[str]
        primary_tag: str

        @xvalidation(id="child-primary-tag", description="Child tag must exist.")
        def child_primary_tag(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.primary_tag).assert_schema({
                "enum": x.resolve(x.path.tags.each())
            })

    class Parent(XValidatedModel):
        items: list[Child]

    rule = Parent.model_json_schema()["x-validations"][0]

    assert rule["target"] == "$.items[*].primary_tag"
    assert rule["assert"]["enum"]["$resolve"] == "$.items[*].tags[*]"


def test_nested_plain_basemodel_does_not_need_xvalidatedmodel() -> None:
    class PlainChild(BaseModel):
        name: str

    class Parent(XValidatedModel):
        child: PlainChild

    schema = Parent.model_json_schema()

    assert "x-validations" not in schema
    assert "child" in schema["properties"]


def test_alias_export_uses_alias_in_target_and_resolve() -> None:
    class AliasArticle(XValidatedModel):
        tags: list[str] = Field(alias="tagList")
        primary_tag: str = Field(alias="primaryTag")

        @xvalidation(id="alias-primary-tag", description="Primary tag must exist.")
        def primary_tag_exists(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.primary_tag).assert_schema({
                "enum": x.resolve(x.path.tags.each())
            })

    rule = AliasArticle.model_json_schema()["x-validations"][0]

    assert rule["target"] == "$.primaryTag"
    assert rule["assert"]["enum"]["$resolve"] == "$.tagList[*]"


def test_validation_alias_export_uses_validation_alias() -> None:
    class AliasArticle(XValidatedModel):
        tags: list[str] = Field(
            validation_alias="inputTags", serialization_alias="tagList"
        )
        primary_tag: str = Field(
            validation_alias="inputPrimaryTag", serialization_alias="primaryTag"
        )

        @xvalidation(id="alias-primary-tag", description="Primary tag must exist.")
        def primary_tag_exists(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.primary_tag).assert_schema({
                "enum": x.resolve(x.path.tags.each())
            })

    rule = AliasArticle.model_json_schema(mode="validation")["x-validations"][0]

    assert rule["target"] == "$.inputPrimaryTag"
    assert rule["assert"]["enum"]["$resolve"] == "$.inputTags[*]"


def test_serialization_alias_export_uses_serialization_alias() -> None:
    class AliasArticle(XValidatedModel):
        tags: list[str] = Field(
            validation_alias="inputTags", serialization_alias="tagList"
        )
        primary_tag: str = Field(
            validation_alias="inputPrimaryTag", serialization_alias="primaryTag"
        )

        @xvalidation(id="alias-primary-tag", description="Primary tag must exist.")
        def primary_tag_exists(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.primary_tag).assert_schema({
                "enum": x.resolve(x.path.tags.each())
            })

    rule = AliasArticle.model_json_schema(mode="serialization")["x-validations"][0]

    assert rule["target"] == "$.primaryTag"
    assert rule["assert"]["enum"]["$resolve"] == "$.tagList[*]"


def test_alias_choices_export_uses_first_validation_alias_choice() -> None:
    class AliasArticle(XValidatedModel):
        tags: list[str] = Field(
            validation_alias=AliasChoices("inputTags", "legacyTags")
        )
        primary_tag: str = Field(
            validation_alias=AliasChoices("inputPrimaryTag", "legacyPrimaryTag")
        )

        @xvalidation(id="alias-primary-tag", description="Primary tag must exist.")
        def primary_tag_exists(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.primary_tag).assert_schema({
                "enum": x.resolve(x.path.tags.each())
            })

    rule = AliasArticle.model_json_schema()["x-validations"][0]

    assert rule["target"] == "$.inputPrimaryTag"
    assert rule["assert"]["enum"]["$resolve"] == "$.inputTags[*]"


def test_alias_path_export_uses_schema_field_name() -> None:
    class AliasArticle(XValidatedModel):
        tags: list[str] = Field(validation_alias=AliasPath("payload", "tags"))
        primary_tag: str = Field(validation_alias=AliasPath("payload", "primaryTag"))

        @xvalidation(id="alias-primary-tag", description="Primary tag must exist.")
        def primary_tag_exists(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.primary_tag).assert_schema({
                "enum": x.resolve(x.path.tags.each())
            })

    rule = AliasArticle.model_json_schema()["x-validations"][0]

    assert rule["target"] == "$.primary_tag"
    assert rule["assert"]["enum"]["$resolve"] == "$.tags[*]"


def test_alias_choices_skips_alias_path_for_schema_alias() -> None:
    class AliasArticle(XValidatedModel):
        tags: list[str] = Field(
            validation_alias=AliasChoices(AliasPath("payload", "tags"), "inputTags")
        )
        primary_tag: str = Field(
            validation_alias=AliasChoices(
                AliasPath("payload", "primaryTag"), "inputPrimaryTag"
            )
        )

        @xvalidation(id="alias-primary-tag", description="Primary tag must exist.")
        def primary_tag_exists(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.primary_tag).assert_schema({
                "enum": x.resolve(x.path.tags.each())
            })

    rule = AliasArticle.model_json_schema()["x-validations"][0]

    assert rule["target"] == "$.inputPrimaryTag"
    assert rule["assert"]["enum"]["$resolve"] == "$.inputTags[*]"


def test_nested_alias_after_wildcard_uses_child_alias() -> None:
    class Child(XValidatedModel):
        child_value: str = Field(alias="childValue")

        @xvalidation(id="child-value", description="Child value must be string.")
        def child_value_rule(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.child_value).assert_schema({"type": "string"})

    class Parent(XValidatedModel):
        items: list[Child]

    rule = Parent.model_json_schema()["x-validations"][0]

    assert rule["target"] == "$.items[*].childValue"


def test_inherited_rule_exports_once_for_grandchild() -> None:
    class ParentRule(XValidatedModel):
        tag: str

        @xvalidation(id="parent-tag", description="Parent tag must be string.")
        def parent_tag(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.tag).assert_schema({"type": "string"})

    class ChildRule(ParentRule):
        child_value: str

    class GrandChildRule(ChildRule):
        grandchild_value: str

    assert [
        rule["id"] for rule in GrandChildRule.model_json_schema()["x-validations"]
    ] == ["parent-tag"]


def test_union_xvalidated_models_are_visited() -> None:
    class TextItem(XValidatedModel):
        kind: Literal["text"]
        value: str

        @xvalidation(id="text-value", description="Text value must be string.")
        def text_value(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.value).assert_schema({"type": "string"})

    class ImageItem(XValidatedModel):
        kind: Literal["image"]
        url: str

        @xvalidation(id="image-url", description="Image URL must be string.")
        def image_url(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.url).assert_schema({"type": "string"})

    class Feed(XValidatedModel):
        items: list[TextItem | ImageItem]

    rules = Feed.model_json_schema()["x-validations"]

    assert {rule["target"] for rule in rules} == {"$.items[*].value", "$.items[*].url"}


def test_discriminated_union_xvalidated_models_are_visited() -> None:
    class TextItem(XValidatedModel):
        kind: Literal["text"]
        value: str

        @xvalidation(id="text-value", description="Text value must be string.")
        def text_value(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.value).assert_schema({"type": "string"})

    class ImageItem(XValidatedModel):
        kind: Literal["image"]
        url: str

        @xvalidation(id="image-url", description="Image URL must be string.")
        def image_url(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.url).assert_schema({"type": "string"})

    class Feed(XValidatedModel):
        items: list[Annotated[TextItem | ImageItem, Field(discriminator="kind")]]

    rules = Feed.model_json_schema()["x-validations"]

    assert {rule["target"] for rule in rules} == {"$.items[*].value", "$.items[*].url"}


def test_recursive_model_does_not_recurse_forever() -> None:
    class Tree(XValidatedModel):
        name: str
        children: list["Tree"] = Field(default_factory=list)

    Tree.model_rebuild()

    assert "x-validations" not in Tree.model_json_schema()


def test_duplicate_rule_ids_raise_invalid_rule_error() -> None:
    class DuplicateRule(XValidatedModel):
        first: str
        second: str

        @xvalidation(id="duplicate", description="First.")
        def first_rule(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.first).assert_schema({"type": "string"})

        @xvalidation(id="duplicate", description="Second.")
        def second_rule(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.second).assert_schema({"type": "string"})

    with pytest.raises(InvalidRuleError):
        DuplicateRule.model_json_schema()


def test_rule_factory_returning_non_rule_builder_raises_invalid_rule_error() -> None:
    class BadRule(XValidatedModel):
        tag: str

        @xvalidation(id="bad-rule", description="Bad rule.")
        def bad_rule(x: XValidationContext) -> Literal["bad"]:
            return "bad"

    with pytest.raises(InvalidRuleError):
        BadRule.model_json_schema()


def test_export_does_not_mutate_base_schema_argument() -> None:
    base_schema = Article.model_json_schema()
    base_schema.pop("x-validations")
    original = copy.deepcopy(base_schema)

    exported = export_schema(Article, base_schema=base_schema)

    assert base_schema == original
    assert "x-validations" in exported
