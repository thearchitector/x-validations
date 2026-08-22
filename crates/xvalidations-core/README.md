# xvalidations-core

Rust core implementation for compiling and evaluating x-validations schema
extensions.

Most Python users should install `xvalidations` or `xvalidate` instead of using
this crate directly.

The engine validates the Base Schema first, then compiles and evaluates
X-Validation Rules. It supports RFC 9535 JSONPath, constant and JSON Pointer
`$resolve` values, payload JSONPath `$resolve` values, and `x-uniqueBy`.

Validation failures contain deterministically ordered `errors`; every error has
`path`, `message`, `keyword`, `source`, and `rule_id` fields.
