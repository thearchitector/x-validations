"""Python binding contract tests matching the JS binding cases."""

import json
from pathlib import Path
from typing import Any, cast

import pytest
from xvalid import XValidationError, XValidationTypeError, xvalidate

CONTRACT_NAMES = ("article.json", "jsonpath_nested.json")
CONTRACT_DIR = Path(__file__).parents[3] / "tests" / "fixtures" / "contracts"
CONTRACTS = tuple(
    (
        name,
        cast(
            dict[str, Any],
            json.loads((CONTRACT_DIR / name).read_text(encoding="utf-8")),
        ),
    )
    for name in CONTRACT_NAMES
)


def contract_ids() -> list[str]:
    """Return fixture names for parameterized test IDs."""
    return [name for name, _contract in CONTRACTS]


def failure_issues(error: XValidationError) -> list[dict[str, Any]]:
    """Return serialized validation issues from a Python binding error."""
    failure = error.failure
    assert failure is not None
    issues = failure["issues"]
    assert isinstance(issues, list)
    return cast(list[dict[str, Any]], issues)


@pytest.mark.parametrize(("name", "contract"), CONTRACTS, ids=contract_ids())
def test_contract_valid_payloads_return_ok(name: str, contract: dict[str, Any]) -> None:
    valid_payload = contract.get("valid_payload")
    if valid_payload is None:
        pytest.skip(f"{name} has no valid payload")

    xvalidate(valid_payload, contract["schema"])


@pytest.mark.parametrize(("name", "contract"), CONTRACTS, ids=contract_ids())
def test_contract_base_invalid_payloads_have_only_base_issues(
    name: str, contract: dict[str, Any]
) -> None:
    base_invalid_payload = contract.get("base_invalid_payload")
    if base_invalid_payload is None:
        pytest.skip(f"{name} has no base-invalid payload")

    with pytest.raises(XValidationError) as exc_info:
        xvalidate(base_invalid_payload, contract["schema"])

    error = exc_info.value
    assert error.kind == "validation"
    issues = failure_issues(error)

    assert issues
    assert all(
        issue["source"] == "base" and issue["rule_id"] is None for issue in issues
    )


@pytest.mark.parametrize(("name", "contract"), CONTRACTS, ids=contract_ids())
def test_contract_x_invalid_payloads_match_expected_issue(
    name: str, contract: dict[str, Any]
) -> None:
    payload = contract.get("x_invalid_payload", contract.get("payload"))
    expected_issue = contract.get("expected_x_issue", contract.get("expected_issue"))
    if payload is None or expected_issue is None:
        pytest.skip(f"{name} has no x-invalid payload")

    with pytest.raises(XValidationError) as exc_info:
        xvalidate(payload, contract["schema"])

    error = exc_info.value
    assert error.kind == "validation"
    issues = failure_issues(error)

    failure = error.failure
    assert failure is not None
    assert failure["kind"] == "validation"
    assert len(error.errors) == 1
    assert len(issues) == 1
    assert issues[0]["path"] == expected_issue["path"]
    assert issues[0]["source"] == expected_issue["source"]
    assert issues[0]["rule_id"] == expected_issue["rule_id"]
    assert error.errors[0].path == expected_issue["path"]
    assert error.errors[0].source == expected_issue["source"]
    assert error.errors[0].rule_id == expected_issue["rule_id"]


def test_invalid_payload_conversion_returns_machine_readable_kind() -> None:
    _name, contract = CONTRACTS[0]

    with pytest.raises(XValidationTypeError) as exc_info:
        xvalidate(object(), contract["schema"])

    error = exc_info.value
    assert error.kind == "invalid_payload"
    assert error.failure["kind"] == "invalid_payload"
    assert isinstance(error.failure["message"], str)


def test_invalid_schema_conversion_returns_machine_readable_kind() -> None:
    _name, contract = CONTRACTS[0]

    with pytest.raises(XValidationTypeError) as exc_info:
        xvalidate(contract["valid_payload"], cast(dict[str, Any], object()))

    error = exc_info.value
    assert error.kind == "invalid_schema_input"
    assert error.failure["kind"] == "invalid_schema_input"
    assert isinstance(error.failure["message"], str)
