# Treat resolve and unique-by as contract primitives

`$resolve` references—including payload JSONPaths and schema JSON Pointers—and `x-uniqueBy` assertions are official capabilities of the X-Validations Contract. Runtime implementations and Contract Fixtures must preserve these semantics across languages rather than treating them as authoring or Rust-only details.
