"""Exception types raised by x-validations."""

from collections.abc import Mapping
from typing import Any

from xvalidations.models import ValidationIssue

type NativeFailure = Mapping[str, Any]


def _is_native_failure(value: object) -> bool:
    return isinstance(value, Mapping) and isinstance(value.get("kind"), str)


def _failure_message(failure: NativeFailure) -> str:
    message = failure.get("message")
    if isinstance(message, str):
        return message
    if failure.get("kind") == "validation":
        issues = failure.get("issues")
        if isinstance(issues, list):
            return f"{len(issues)} validation issue(s)"
    return str(failure.get("kind", "validation failure"))


def _coerce_issue(issue: object) -> "ValidationIssue":
    if isinstance(issue, ValidationIssue):
        return issue
    return ValidationIssue.model_validate(issue)


class ExportedSchemaError(ValueError):
    """Raised when an exported schema artifact is invalid."""

    def __init__(self, message_or_failure: object = "") -> None:
        self.failure: NativeFailure | None
        self.kind: str | None
        if _is_native_failure(message_or_failure):
            self.failure = message_or_failure
            self.kind = message_or_failure["kind"]
            message = _failure_message(message_or_failure)
        else:
            self.failure = None
            self.kind = None
            message = str(message_or_failure)
        super().__init__(message)


class InvalidRuleError(ExportedSchemaError):
    """Raised when an x-validation rule is invalid."""


class JsonPathError(ExportedSchemaError):
    """Raised when a JSONPath expression is invalid."""


class ResolveError(ExportedSchemaError):
    """Raised when a resolve marker cannot be resolved."""


class XValidationError(ValueError):
    """Raised when model data fails validation."""

    def __init__(self, errors: list["ValidationIssue"] | NativeFailure) -> None:
        self.failure: NativeFailure | None
        self.kind: str | None
        if _is_native_failure(errors):
            self.failure = errors
            self.kind = errors["kind"]
            raw_errors = errors.get("issues", [])
            if not isinstance(raw_errors, list):
                raw_errors = []
        else:
            self.failure = None
            self.kind = "validation"
            raw_errors = errors
        self.errors = [_coerce_issue(issue) for issue in raw_errors]
        super().__init__(f"{len(self.errors)} validation issue(s)")
