"""Exception types raised by x-validations."""


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
