# xvalidations-core

Rust core implementation for compiling and evaluating x-validations schema
extensions.

Most Python users should install `xvalidations` or `xvalidate` instead of using
this crate directly.

The engine validates the Base Schema first, then discovers matching resources
and evaluates X-Validation Rules directly against their targets. It supports
RFC 9535 JSONPath, constant and JSON Pointer `$resolve` values, payload JSONPath
`$resolve` values, and `x-uniqueBy`.

Validation failures contain deterministically ordered `errors`; every error has
`path`, `message`, and `rule_id` fields. Base-schema errors have no `rule_id`.
