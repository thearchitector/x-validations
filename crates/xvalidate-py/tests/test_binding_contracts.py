"""Python binding happy-path contract tests."""

import json
from pathlib import Path
from typing import Any, cast

import pytest
from xvalidate import XValidationError, xvalidate

CONTRACT_DIR = Path(__file__).parents[3] / "tests" / "fixtures" / "contracts"
CONTRACTS = tuple(
    (path.name, cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8"))))
    for path in sorted(CONTRACT_DIR.glob("*.json"))
)


@pytest.mark.parametrize(("name", "contract"), CONTRACTS)
def test_contract_valid_payloads_return_none(
    name: str, contract: dict[str, Any]
) -> None:
    assert xvalidate(contract["valid_payload"], contract["schema"]) is None, name


@pytest.mark.parametrize(("name", "contract"), CONTRACTS)
def test_contract_base_failures_have_no_rule_id(
    name: str, contract: dict[str, Any]
) -> None:
    with pytest.raises(XValidationError) as exc_info:
        xvalidate(contract["base_invalid_payload"], contract["schema"])

    assert exc_info.value.errors, name
    assert all(error.rule_id is None for error in exc_info.value.errors)
    assert exc_info.value.errors[0].path == contract["expected_base_error"]["path"]


@pytest.mark.parametrize(("name", "contract"), CONTRACTS)
def test_contract_rule_failures_match_expected_error(
    name: str, contract: dict[str, Any]
) -> None:
    with pytest.raises(XValidationError) as exc_info:
        xvalidate(contract["x_invalid_payload"], contract["schema"])

    error = exc_info.value.errors[0]
    expected = contract["expected_x_error"]
    assert (error.path, error.rule_id) == (expected["path"], expected["rule_id"]), name
