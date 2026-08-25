class InvalidSchemaError(ValueError):
    """Raised when authoring would produce an invalid JSON Schema resource."""


class InvalidRuleError(InvalidSchemaError):
    """Raised when an authored validation rule is invalid."""
