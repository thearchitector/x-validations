import copy

import pytest
from pydantic import BaseModel, Field, ValidationError

from xvalidations import (
    XValidatedModel,
    XValidationContext,
    XValidationError,
    xvalidate,
    xvalidation,
)
from xvalidations.authoring import AuthoredRule
from xvalidations.runtime import validate_base_schema


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


class GeneratedArticle(BaseModel):
    tags: list[str]
    primary_tag: str


def test_xvalidate_internal_article_passes() -> None:
    model = Article.model_validate({"tags": ["python"], "primary_tag": "python"})

    assert xvalidate(model) is None


def test_xvalidate_internal_article_fails_with_rule_id_and_path() -> None:
    model = Article.model_validate({"tags": ["python"], "primary_tag": "pydantic"})

    with pytest.raises(XValidationError) as exc_info:
        xvalidate(model)

    issue = exc_info.value.errors[0]
    assert (issue.path, issue.rule_id, issue.source) == (
        "$.primary_tag",
        "primary-tag-exists",
        "x-validation",
    )


def test_xvalidate_external_generated_article_matches_internal_failure() -> None:
    schema = Article.model_json_schema()
    internal = Article.model_validate({"tags": ["python"], "primary_tag": "pydantic"})
    external = GeneratedArticle.model_validate({
        "tags": ["python"],
        "primary_tag": "pydantic",
    })

    with pytest.raises(XValidationError) as internal_exc_info:
        xvalidate(internal)
    with pytest.raises(XValidationError) as external_exc_info:
        xvalidate(external, schema=schema)

    assert [
        (issue.path, issue.rule_id, issue.source)
        for issue in internal_exc_info.value.errors
    ] == [
        (issue.path, issue.rule_id, issue.source)
        for issue in external_exc_info.value.errors
    ]


def test_xvalidate_external_generated_article_passes() -> None:
    schema = Article.model_json_schema()
    model = GeneratedArticle.model_validate({
        "tags": ["python"],
        "primary_tag": "python",
    })

    assert xvalidate(model, schema=schema) is None


def test_xvalidate_plain_basemodel_without_schema_raises_type_error() -> None:
    model = GeneratedArticle.model_validate({
        "tags": ["python"],
        "primary_tag": "python",
    })

    with pytest.raises(TypeError):
        xvalidate(model)


def test_xvalidate_non_model_raises_type_error() -> None:
    with pytest.raises(TypeError):
        xvalidate({"tags": ["python"], "primary_tag": "python"})


def test_base_schema_failure_source_base_rule_id_none() -> None:
    schema = Article.model_json_schema()

    with pytest.raises(XValidationError) as exc_info:
        validate_base_schema(schema, {"tags": ["python"]})

    issue = exc_info.value.errors[0]
    assert issue.source == "base"
    assert issue.rule_id is None


def test_xvalidation_failure_source_xvalidation_rule_id_present() -> None:
    model = Article.model_validate({"tags": ["python"], "primary_tag": "pydantic"})

    with pytest.raises(XValidationError) as exc_info:
        xvalidate(model)

    issue = exc_info.value.errors[0]
    assert issue.source == "x-validation"
    assert issue.rule_id == "primary-tag-exists"


def test_error_paths_are_sorted_deterministically() -> None:
    class MultiRuleArticle(XValidatedModel):
        tags: list[str]
        primary_tag: str
        secondary_tag: str

        @xvalidation(id="secondary-tag-exists", description="Secondary tag exists.")
        def secondary_tag_exists(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.secondary_tag).assert_schema({
                "enum": x.resolve(x.path.tags.each())
            })

        @xvalidation(id="primary-tag-exists", description="Primary tag exists.")
        def primary_tag_exists(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.primary_tag).assert_schema({
                "enum": x.resolve(x.path.tags.each())
            })

    model = MultiRuleArticle.model_validate({
        "tags": ["python"],
        "primary_tag": "bad",
        "secondary_tag": "bad",
    })

    with pytest.raises(XValidationError) as exc_info:
        xvalidate(model)

    assert [issue.path for issue in exc_info.value.errors] == [
        "$.primary_tag",
        "$.secondary_tag",
    ]


def test_runtime_does_not_mutate_model_or_schema() -> None:
    model = Article.model_validate({"tags": ["python"], "primary_tag": "python"})
    schema = Article.model_json_schema()
    original_schema = copy.deepcopy(schema)
    original_dump = model.model_dump(mode="json")

    xvalidate(model, schema=schema)

    assert schema == original_schema
    assert model.model_dump(mode="json") == original_dump


def test_runtime_uses_alias_dump_for_alias_model() -> None:
    class AliasArticle(XValidatedModel):
        tags: list[str] = Field(alias="tagList")
        primary_tag: str = Field(alias="primaryTag")

        @xvalidation(id="alias-primary-tag", description="Primary tag must exist.")
        def primary_tag_exists(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.primary_tag).assert_schema({
                "enum": x.resolve(x.path.tags.each())
            })

    model = AliasArticle.model_validate({"tagList": ["python"], "primaryTag": "python"})

    assert xvalidate(model) is None


def test_runtime_internal_schema_matches_serialization_alias_dump() -> None:
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

    model = AliasArticle.model_validate({
        "inputTags": ["python"],
        "inputPrimaryTag": "python",
    })

    assert xvalidate(model) is None


def test_pydantic_model_validate_errors_are_not_caught_by_xvalidate() -> None:
    with pytest.raises(ValidationError):
        Article.model_validate({"tags": "python", "primary_tag": "python"})
