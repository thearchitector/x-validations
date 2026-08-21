"""Contract fixture tests."""

import json
from pathlib import Path
from typing import Any, cast

import pytest
from xvalid import XValidationError, xvalidate

from tests.conftest import Article

CONTRACTS_DIR = Path("tests/fixtures/contracts")
XVALIDATIONS_SCHEMA_URI = (
    "https://thearchitector.dev/xvalidations/meta/x-validations.schema.json"
)


def _load_contract(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((CONTRACTS_DIR / name).read_text()))


def _load_contracts() -> list[tuple[str, dict[str, Any]]]:
    return [
        (path.name, cast(dict[str, Any], json.loads(path.read_text())))
        for path in sorted(CONTRACTS_DIR.glob("*.json"))
    ]


def test_current_authoring_emits_contract_extension_shape() -> None:
    """Compare current authoring output with the shared article contract."""
    article_contract = _load_contract("article.json")
    exported = Article.model_json_schema()

    assert exported["$schema"] == XVALIDATIONS_SCHEMA_URI
    assert exported["x-validations"] == article_contract["schema"]["x-validations"]


@pytest.mark.parametrize(("name", "contract"), _load_contracts())
def test_contract_valid_payloads_pass(name: str, contract: dict[str, Any]) -> None:
    """Check valid contract fixtures against the Rust-backed Python runtime."""
    if "valid_payload" not in contract:
        pytest.skip(f"{name} has no valid payload")

    assert xvalidate(contract["valid_payload"], contract["schema"]) is None


@pytest.mark.parametrize(("name", "contract"), _load_contracts())
def test_contract_base_invalid_payloads_have_only_base_issues(
    name: str, contract: dict[str, Any]
) -> None:
    """Check phase 1 failures do not report x-validation issues."""
    if "base_invalid_payload" not in contract:
        pytest.skip(f"{name} has no base-invalid payload")

    with pytest.raises(XValidationError) as exc_info:
        xvalidate(contract["base_invalid_payload"], contract["schema"])

    assert exc_info.value.errors
    assert all(
        issue.source == "base" and issue.rule_id is None
        for issue in exc_info.value.errors
    )


@pytest.mark.parametrize(("name", "contract"), _load_contracts())
def test_contract_x_invalid_payloads_match_expected_issue(
    name: str, contract: dict[str, Any]
) -> None:
    """Check x-invalid contract fixtures against the Rust-backed Python runtime."""
    payload = contract.get("x_invalid_payload", contract.get("payload"))
    expected_issue = contract.get("expected_x_issue", contract.get("expected_issue"))
    if payload is None or expected_issue is None:
        pytest.skip(f"{name} has no x-invalid payload")

    with pytest.raises(XValidationError) as exc_info:
        xvalidate(payload, contract["schema"])

    assert [
        {"path": issue.path, "source": issue.source, "rule_id": issue.rule_id}
        for issue in exc_info.value.errors
    ] == [expected_issue]
