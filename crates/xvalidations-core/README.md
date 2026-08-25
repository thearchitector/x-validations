# xvalidations-core

Rust core implementation for compiling and evaluating x-validations schema
extensions.

Most Python users should install `xvalidations` or `xvalidate` instead of using
this crate directly.

The engine validates the Base Schema first, then discovers matching resources
and evaluates X-Validation Rules directly against their targets. It supports
RFC 9535 JSONPath `$path` interpolation and `x-uniqueBy`. Singular paths yield
one value; non-singular paths yield an array of all matches.
`x-uniqueBy` targets arrays, evaluates its projection independently for each
array item, and reports duplicate item paths.

Validation failures contain deterministically ordered `errors`; every error has
`path`, `message`, and `rule_id` fields. Base-schema errors have no `rule_id`.
