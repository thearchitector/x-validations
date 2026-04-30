"""Shared test fixtures."""

from typing import Literal

import pytest
from pydantic import BaseModel, Field

from xvalidations import XValidatedModel, XValidationContext, xvalidation
from xvalidations.authoring import AuthoredRule


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


class FieldWidget(BaseModel):
    kind: Literal["field"]
    field_id: str


class TextWidget(BaseModel):
    kind: Literal["text"]
    text: str


class Section(XValidatedModel):
    fields: list[str]
    widgets: list[FieldWidget | TextWidget]

    @xvalidation(
        id="section-widget-field-exists",
        description="Field widgets must reference existing fields.",
    )
    def widget_field_exists(x: XValidationContext) -> AuthoredRule:
        return x.target(
            x.path.widgets.where(x.this.kind == "field").field_id
        ).assert_schema({"enum": x.resolve(x.path.fields.each())})


class Form(XValidatedModel):
    sections: list[Section]


class GeneratedFieldWidget(BaseModel):
    kind: Literal["field"]
    field_id: str


class GeneratedTextWidget(BaseModel):
    kind: Literal["text"]
    text: str


class GeneratedSection(BaseModel):
    fields: list[str]
    widgets: list[GeneratedFieldWidget | GeneratedTextWidget]


class GeneratedForm(BaseModel):
    sections: list[GeneratedSection]


class GeneratedStaticArticle(BaseModel):
    tags: list[str]
    primary_tag: str


class StaticArticle(XValidatedModel):
    tags: list[str] = Field(min_length=1)
    primary_tag: str


@pytest.fixture
def article_schema() -> dict[str, object]:
    return Article.model_json_schema()


@pytest.fixture
def good_article_payload() -> dict[str, object]:
    return {"tags": ["python", "pydantic"], "primary_tag": "python"}


@pytest.fixture
def bad_article_payload() -> dict[str, object]:
    return {"tags": ["python"], "primary_tag": "pydantic"}


@pytest.fixture
def good_form_payload() -> dict[str, object]:
    return {
        "sections": [
            {
                "fields": ["title"],
                "widgets": [
                    {"kind": "field", "field_id": "title"},
                    {"kind": "text", "text": "Intro"},
                ],
            }
        ]
    }


@pytest.fixture
def bad_form_payload() -> dict[str, object]:
    return {
        "sections": [
            {
                "fields": ["title"],
                "widgets": [
                    {"kind": "field", "field_id": "missing"},
                    {"kind": "text", "text": "Intro"},
                ],
            }
        ]
    }


@pytest.fixture
def good_static_article_payload() -> dict[str, object]:
    return {"tags": ["python"], "primary_tag": "anything"}


@pytest.fixture
def bad_static_article_payload() -> dict[str, object]:
    return {"tags": [], "primary_tag": "anything"}
