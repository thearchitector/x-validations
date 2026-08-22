"""Python binding contract tests matching the JS binding cases."""

import json
from pathlib import Path
from typing import Literal, NotRequired, TypedDict, cast

import pytest
from xvalidate import XValidationError, XValidationTypeError, xvalidate

type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


class ValidationErrorData(TypedDict):
    path: str
    message: str
    keyword: str | None
    source: Literal["base", "x-validation"]
    rule_id: str | None


class ExpectedError(TypedDict):
    path: str
    source: Literal["base", "x-validation"]
    rule_id: str | None


class Contract(TypedDict):
    schema: dict[str, JsonValue]
    valid_payload: NotRequired[JsonValue]
    base_invalid_payload: NotRequired[JsonValue]
    expected_base_error: NotRequired[ExpectedError]
    x_invalid_payload: NotRequired[JsonValue]
    expected_x_error: NotRequired[ExpectedError]


CONTRACT_DIR = Path(__file__).parents[3] / "tests" / "fixtures" / "contracts"
CONTRACTS = tuple(
    (path.name, cast(Contract, json.loads(path.read_text(encoding="utf-8"))))
    for path in sorted(CONTRACT_DIR.glob("*.json"))
)


def contract_ids() -> list[str]:
    """Return fixture names for parameterized test IDs."""
    return [name for name, _contract in CONTRACTS]


def failure_errors(error: XValidationError) -> list[ValidationErrorData]:
    """Return serialized validation errors from a Python binding error."""
    return cast(list[ValidationErrorData], error.failure["errors"])


@pytest.mark.parametrize(("name", "contract"), CONTRACTS, ids=contract_ids())
def test_contract_valid_payloads_return_ok(name: str, contract: Contract) -> None:
    valid_payload = contract.get("valid_payload")
    if valid_payload is None:
        pytest.skip(f"{name} has no valid payload")

    xvalidate(valid_payload, contract["schema"])


@pytest.mark.parametrize(("name", "contract"), CONTRACTS, ids=contract_ids())
def test_contract_base_invalid_payloads_have_only_base_errors(
    name: str, contract: Contract
) -> None:
    base_invalid_payload = contract.get("base_invalid_payload")
    if base_invalid_payload is None:
        pytest.skip(f"{name} has no base-invalid payload")

    with pytest.raises(XValidationError) as exc_info:
        xvalidate(base_invalid_payload, contract["schema"])

    error = exc_info.value
    assert error.kind == "validation"
    errors = failure_errors(error)

    assert errors
    assert all(item["source"] == "base" and item["rule_id"] is None for item in errors)
    assert errors[0]["path"] == contract["expected_base_error"]["path"]


@pytest.mark.parametrize(("name", "contract"), CONTRACTS, ids=contract_ids())
def test_contract_x_invalid_payloads_match_expected_error(
    name: str, contract: Contract
) -> None:
    payload = contract.get("x_invalid_payload")
    expected_error = contract.get("expected_x_error")
    if payload is None or expected_error is None:
        pytest.skip(f"{name} has no x-invalid payload")

    with pytest.raises(XValidationError) as exc_info:
        xvalidate(payload, contract["schema"])

    error = exc_info.value
    assert error.kind == "validation"
    errors = failure_errors(error)

    failure = error.failure
    assert failure["kind"] == "validation"
    assert error.errors
    assert errors
    assert errors[0]["path"] == expected_error["path"]
    assert errors[0]["source"] == expected_error["source"]
    assert errors[0]["rule_id"] == expected_error["rule_id"]
    assert error.errors[0].path == expected_error["path"]
    assert error.errors[0].source == expected_error["source"]
    assert error.errors[0].rule_id == expected_error["rule_id"]


def test_invalid_payload_conversion_returns_machine_readable_kind() -> None:
    _name, contract = CONTRACTS[0]

    with pytest.raises(XValidationTypeError) as exc_info:
        xvalidate(cast(JsonValue, object()), contract["schema"])

    error = exc_info.value
    assert error.kind == "invalid_payload"
    assert error.failure["kind"] == "invalid_payload"
    assert error.failure["message"]


def test_invalid_schema_conversion_returns_machine_readable_kind() -> None:
    _name, contract = CONTRACTS[0]

    with pytest.raises(XValidationTypeError) as exc_info:
        xvalidate(contract["valid_payload"], cast(dict[str, JsonValue], object()))

    error = exc_info.value
    assert error.kind == "invalid_schema_input"
    assert error.failure["kind"] == "invalid_schema_input"
    assert error.failure["message"]
