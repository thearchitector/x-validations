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
The pure-Python, Pydantic-based API for producing Exported Schemas.
_Avoid_: Runtime, validation engine

**Exported Schema**:
A JSON Schema document carrying the `x-validations` extension.
_Avoid_: Contract, artifact

**X-Validation Rule**:
A declaration containing an identifier, target, and assertion, with an optional description.
_Avoid_: Validation, check

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
