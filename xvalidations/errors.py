"""Authoring and export exceptions raised by x-validations."""


class XValidationAuthoringError(ValueError):
    """Raised when an authored x-validation declaration is invalid."""


class InvalidRuleError(XValidationAuthoringError):
    """Raised when an x-validation rule declaration is invalid."""


__all__ = ["InvalidRuleError", "XValidationAuthoringError"]
