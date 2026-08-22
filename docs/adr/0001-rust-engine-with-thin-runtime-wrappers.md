# Use a Rust validation engine with thin runtime wrappers

The X-Validations Contract is implemented by a Rust validation engine exposed through thin runtime-specific wrappers, while authoring remains pure Python and is underpinned by Pydantic models. The Validation Engine produces canonical Validation Errors that Runtime Wrappers propagate without reinterpretation, and the Authoring Library does not depend on a Runtime Wrapper. This keeps contract semantics in one cross-language engine without coupling authoring to a native runtime package.
