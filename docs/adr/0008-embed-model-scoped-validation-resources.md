# Embed model-scoped validation resources

Each model that declares rules exports a self-contained Schema Resource with an absolute `$id`, the X-Validations dialect `$schema`, and local `x-validations`. Rule targets and `$path` operands are evaluated from each successfully validated instance of that resource, while reported error paths remain absolute from the payload root. Literals remain inline and `x-constants` is prohibited.

## Consequences

The Contract meta-schema is a Draft 2020-12-derived dialect shared by Python and Rust. Runtime validation discovers successful resource occurrences from Base Schema evaluation, interpolates paths from each local instance, compiles each concrete assertion as Draft 2020-12, and prefixes target locations to absolute payload paths. Nested resources establish correlation boundaries, and rule identifiers need only be unique within an effective model rule set.
