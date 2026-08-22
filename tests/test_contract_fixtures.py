"""Contract fixture tests."""

import json
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from tests.conftest import Article
from xvalidations import XValidatedModel, XValidationContext, xvalidation
from xvalidations.authoring import AuthoredRule

CONTRACTS_DIR = Path("tests/fixtures/contracts")
XVALIDATIONS_SCHEMA_URI = (
    "https://thearchitector.dev/xvalidations/meta/x-validations.schema.json"
)


def _load_contract(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((CONTRACTS_DIR / name).read_text()))


def test_current_authoring_emits_contract_extension_shape() -> None:
    """Compare current authoring output with the shared article contract."""
    article_contract = _load_contract("article.json")
    exported = Article.model_json_schema()

    assert exported["$schema"] == XVALIDATIONS_SCHEMA_URI
    assert exported["x-validations"] == article_contract["schema"]["x-validations"]


def test_authoring_emits_shared_unique_by_contract() -> None:
    class FieldRecord(BaseModel):
        field_id: str

    class UniqueFields(XValidatedModel):
        fields: list[FieldRecord]

        @xvalidation(id="unique-field-ids")
        def unique_field_ids(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.fields.each()).assert_schema({
                "x-uniqueBy": "$.field_id"
            })

    contract = _load_contract("unique_by.json")

    assert (
        UniqueFields.model_json_schema()["x-validations"]
        == contract["schema"]["x-validations"]
    )
