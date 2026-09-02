"""Shared happy-path fixtures."""

import pytest
from pydantic import BaseModel

from xvalidations import ValidationRule, XValidationContext, xvalidation


class Article(BaseModel):
    tags: list[str]
    primary_tag: str

    @xvalidation(
        id="primary-tag-exists", description="Primary tag must be present in tags."
    )
    @classmethod
    def primary_tag_exists(cls, x: XValidationContext) -> ValidationRule:
        return x.target(x.path.primary_tag).assert_schema({"enum": x.path.tags.each()})


@pytest.fixture
def article_schema() -> dict[str, object]:
    return Article.model_json_schema()


@pytest.fixture
def good_article_payload() -> dict[str, object]:
    return {"tags": ["python", "pydantic"], "primary_tag": "python"}


@pytest.fixture
def bad_article_payload() -> dict[str, object]:
    return {"tags": ["python"], "primary_tag": "pydantic"}
