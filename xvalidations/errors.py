"""Exception types raised by x-validations."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xvalidations.models import ValidationIssue


class ExportedSchemaError(ValueError):
    """Raised when an exported schema artifact is invalid."""


class InvalidRuleError(ExportedSchemaError):
    """Raised when an x-validation rule is invalid."""


class JsonPathError(ExportedSchemaError):
    """Raised when a JSONPath expression is invalid."""


class ResolveError(ExportedSchemaError):
    """Raised when a resolve marker cannot be resolved."""


class XValidationError(ValueError):
    """Raised when model data fails validation."""

    def __init__(self, errors: list["ValidationIssue"]) -> None:
        self.errors = errors
        super().__init__(f"{len(errors)} validation issue(s)")
