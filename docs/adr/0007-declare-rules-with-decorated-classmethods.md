# Declare rules with decorated classmethods

Any Pydantic `BaseModel` may declare a Validation Rule using `@xvalidation` on a classmethod. The descriptor installs only a tagged `__get_pydantic_json_schema__` wrapper. Validation-mode schema generation invokes every effective factory, locates Paths in Pydantic's generated schema, validates the private target/assertion document, and renders the resource. Nested or third-party models can therefore be governed at the application's model boundary without a completion hook or a special base class.

## Consequences

Rule factories may run repeatedly and are expected to be pure. Invalid factories, targets, and assertions fail during validation-schema export, once Pydantic can generate the model schema. No compiled-rule cache crosses exports. Inherited replacements require explicit override markers, serialization schemas remain unchanged, and subclass JSON Schema hook overrides must delegate with `super()`.
