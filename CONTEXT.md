# X-Validations

X-Validations defines a portable validation contract that extends JSON Schema with rules for constraints involving related values.

## Language

**X-Validations Contract**:
The portable agreement shared by authoring tools, validation engines, and runtime wrappers.
_Avoid_: Contract fixture, Python API

**Validation Engine**:
The Rust implementation that evaluates payloads against the X-Validations Contract.
_Avoid_: Runtime, compiler

**Runtime Wrapper**:
A thin host-language bridge published as `xvalidate` that exposes the Validation Engine without owning validation semantics.
_Avoid_: Binding implementation, validation library

**Authoring Library**:
The pure-Python, Pydantic-based API for declaring Validation Rules and producing Exported Schemas.
_Avoid_: Runtime, validation engine

**Exported Schema**:
A JSON Schema document whose model schemas may carry the `x-validations` extension.
_Avoid_: Contract, artifact

**Validation Rule**:
A model-scoped authored condition containing a target and Rule Assertion. Its declaration supplies an identifier unique within the defining model and an optional description.
_Avoid_: X-Validation Rule, validation, check

**Rule Assertion**:
A JSON Schema object applied to every value selected by a Validation Rule's target. It may contain Path Operands interpolated from the current Schema Resource instance.
_Avoid_: Authored rule, assertion value

**Model Schema**:
The JSON Schema node representing a Pydantic model. Validation Rules on that node apply independently to every matching model instance.
_Avoid_: Root schema, definition

**Schema Resource**:
An independently identified Model Schema embedded in an Exported Schema. Its `$id` establishes the resource root for local references, while its X-Validations members are owned by the Authoring Library.
_Avoid_: Definition, schema fragment

**X-Validations Dialect**:
The Draft 2020-12-derived JSON Schema dialect that defines `x-validations`, `$path`, and `x-uniqueBy` semantics.
_Avoid_: Meta-schema, Base Schema

**Validation Context**:
The authoring view of the Pydantic model that defines a Validation Rule. Its path root is the defining model.
_Avoid_: Export context, root context

**Compiled Validation Rule**:
The schema-facing form of a Validation Rule with its identifier and model-relative Paths rendered as contract markers.
_Avoid_: Authored rule, Compiled Schema

**Rule Path**:
An RFC 9535 JSONPath evaluated from an instance of the Validation Rule's defining Model Schema. Its `$` identifies that local model instance.
_Avoid_: Error Path, payload path

**Path Operand**:
A Rule Assertion value authored as a Path and rendered as the exact singleton `$path` object. At runtime it becomes one selected value for singular syntax or an array of all selected values for non-singular syntax.
_Avoid_: Resolved Value, placeholder, binding

**Assertion Meta-Schema**:
The Authoring Library's packaged schema for its private target/assertion document. It constrains the assertion vocabulary and checks generated-schema compatibility before a ruled resource is exported.
_Avoid_: Contract meta-schema, representative value

**Error Path**:
An absolute path reported in a Validation Error. Its `$` identifies the root of the complete payload.
_Avoid_: Rule Path, target

**Invalid Schema Error**:
An Authoring Library exception raised when user-authored schema input violates X-Validations authoring constraints.
_Avoid_: XValidationError, authoring error

**Base Schema**:
The ordinary JSON Schema represented by an Exported Schema after extension-only material is removed.
_Avoid_: Original schema, plain schema

**Compiled Schema**:
The transient, payload-specific schema generated from X-Validation Rules for validation.
_Avoid_: Generated schema, overlay schema

**Contract Fixture**:
A test document containing an Exported Schema, representative payloads, and expected Validation Errors.
_Avoid_: Contract, schema fixture

**Validation Error**:
A structured validation result produced by the Validation Engine and attributed to either the Base Schema or an X-Validation Rule. Runtime Wrappers propagate Validation Errors without redefining them.
_Avoid_: Generic validation record, failure
