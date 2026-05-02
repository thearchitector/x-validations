"""Contract fixture tests."""

import json
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator

from tests.conftest import Article
from xvalidations.compiler import generate_compiled_schema
from xvalidations.runtime import issues_from_errors

CONTRACTS_DIR = Path("tests/fixtures/contracts")
XVALIDATIONS_SCHEMA_URI = (
    "https://thearchitector.dev/xvalidations/meta/x-validations.schema.json"
)


def _load_contract(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((CONTRACTS_DIR / name).read_text()))


def test_contract_fixtures_are_valid_json() -> None:
    """Load every contract fixture as JSON."""
    for path in sorted(CONTRACTS_DIR.glob("*.json")):
        assert json.loads(path.read_text())


def test_contract_fixture_shape() -> None:
    """Check the shared article contract shape."""
    article_contract = _load_contract("article.json")
    schema = article_contract["schema"]

    assert schema["$schema"] == XVALIDATIONS_SCHEMA_URI
    rules = schema["x-validations"]
    assert rules[0]["id"] == "primary-tag-exists"
    assert rules[0]["target"] == "$.primary_tag"
    assert rules[0]["assert"] == {"enum": {"$resolve": "$.tags[*]"}}


def test_current_authoring_emits_contract_extension_shape() -> None:
    """Compare current authoring output with the shared article contract."""
    article_contract = _load_contract("article.json")
    exported = Article.model_json_schema()

    assert exported["x-validations"] == article_contract["schema"]["x-validations"]


@pytest.mark.parametrize(
    ("contract_name", "payload_key", "issue_key"),
    [
        pytest.param("article.json", "x_invalid_payload", "expected_x_issue", id="article"),
        pytest.param(
            "jsonpath_nested.json", "payload", "expected_issue", id="jsonpath-nested"
        ),
    ],
)
def test_contract_expected_x_issue(
    contract_name: str, payload_key: str, issue_key: str
) -> None:
    """Check contract fixtures against the current Python compiler."""
    contract = _load_contract(contract_name)
    payload = contract[payload_key]
    expected_issue = contract[issue_key]
    compiled = generate_compiled_schema(contract["schema"], payload)
    errors = Draft202012Validator(compiled.schema).iter_errors(payload)

    issues = issues_from_errors(
        errors, source="x-validation", branch_rule_ids=compiled.branch_rule_ids
    )

    assert [
        {
            "path": issue.path,
            "source": issue.source,
            "rule_id": issue.rule_id,
        }
        for issue in issues
    ] == [expected_issue]
