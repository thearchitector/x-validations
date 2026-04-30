"""Helpers for exported schema artifacts."""

import copy
from typing import TYPE_CHECKING, Any, cast

from pydantic import ValidationError

from xvalidations.errors import InvalidRuleError
from xvalidations.models import XValidationRule

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from xvalidations.models import JsonValue


def extract_xvalidations(schema: "Mapping[str, Any]") -> list[XValidationRule]:
    """Extract and parse root x-validation rules."""
    raw_rules = schema.get("x-validations", [])
    if raw_rules is None:
        return []
    if not isinstance(raw_rules, list):
        msg = "x-validations must be a list"
        raise InvalidRuleError(msg)

    try:
        return [XValidationRule.model_validate(rule) for rule in raw_rules]
    except ValidationError as exc:
        msg = "invalid x-validation rule"
        raise InvalidRuleError(msg) from exc


def strip_xvalidations(schema: "Mapping[str, Any]") -> "dict[str, JsonValue]":
    """Return schema without x-validation metadata owned by this package."""
    copied = cast("dict[str, JsonValue]", copy.deepcopy(schema))
    rules = extract_xvalidations(copied)
    copied.pop("x-validations", None)

    owned_defs = xvalidation_owned_defs(rules)
    raw_defs = copied.get("$defs")
    if isinstance(raw_defs, dict):
        for def_name in owned_defs:
            raw_defs.pop(def_name, None)
        if not raw_defs:
            copied.pop("$defs", None)

    return copied


def xvalidation_owned_defs(rules: "Iterable[XValidationRule]") -> set[str]:
    """Return $defs names referenced by rule resolve markers."""
    owned: set[str] = set()
    for rule in rules:
        _collect_owned_defs(rule.assert_, owned)
    return owned


def _collect_owned_defs(node: "JsonValue", owned: set[str]) -> None:
    if isinstance(node, dict):
        if set(node) == {"$resolve"}:
            ref = node["$resolve"]
            if isinstance(ref, str):
                def_name = _def_name_from_ref(ref)
                if def_name is not None:
                    owned.add(def_name)
        for value in node.values():
            _collect_owned_defs(value, owned)
    elif isinstance(node, list):
        for value in node:
            _collect_owned_defs(value, owned)


def _def_name_from_ref(ref: str) -> str | None:
    prefix = "#/$defs/"
    if not ref.startswith(prefix):
        return None
    escaped_name = ref.removeprefix(prefix).split("/", maxsplit=1)[0]
    return _unescape_json_pointer_token(escaped_name)


def _unescape_json_pointer_token(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")
