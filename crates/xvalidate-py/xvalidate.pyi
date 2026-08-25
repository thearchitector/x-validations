from typing import Literal, TypedDict

type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonSchema = bool | dict[str, JsonValue]

class ValidationErrorData(TypedDict):
    path: str
    message: str
    rule_id: str | None

class ValidationFailure(TypedDict):
    kind: Literal["validation"]
    errors: list[ValidationErrorData]

class ExportedSchemaFailure(TypedDict):
    kind: Literal["invalid_schema", "invalid_rule", "json_path"]
    message: str

class ConversionFailure(TypedDict):
    kind: Literal["invalid_payload", "invalid_schema_input"]
    message: str

class ValidationError:
    path: str
    message: str
    rule_id: str | None

class ExportedSchemaError(ValueError):
    failure: ExportedSchemaFailure
    kind: Literal["invalid_schema", "invalid_rule", "json_path"]

class InvalidRuleError(ExportedSchemaError): ...
class JsonPathError(ExportedSchemaError): ...
class XValidationTypeError(TypeError):
    failure: ConversionFailure
    kind: Literal["invalid_payload", "invalid_schema_input"]

class XValidationError(ValueError):
    failure: ValidationFailure
    kind: Literal["validation"]
    errors: list[ValidationError]

def xvalidate(payload: JsonValue, schema: JsonSchema) -> None: ...
