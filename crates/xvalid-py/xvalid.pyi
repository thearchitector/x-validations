from collections.abc import Mapping
from typing import Any, Literal

class ValidationIssue:
    path: str
    message: str
    keyword: str | None
    source: Literal["base", "x-validation"]
    rule_id: str | None

    def __init__(
        self,
        path: str,
        message: str,
        keyword: str | None,
        source: Literal["base", "x-validation"],
        rule_id: str | None,
    ) -> None: ...

class ExportedSchemaError(ValueError):
    failure: Mapping[str, Any] | None
    kind: str | None

class InvalidRuleError(ExportedSchemaError): ...
class JsonPathError(ExportedSchemaError): ...
class ResolveError(ExportedSchemaError): ...

class XValidationTypeError(TypeError):
    failure: Mapping[str, Any]
    kind: Literal["invalid_payload", "invalid_schema_input"]

class XValidationError(ValueError):
    failure: Mapping[str, Any] | None
    kind: Literal["validation"]
    errors: list[ValidationIssue]

def xvalidate(payload: Any, schema: dict[str, Any]) -> None: ...
