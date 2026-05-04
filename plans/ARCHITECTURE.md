# X-Validations Architecture

## Goal

Build a Pydantic-native authoring library that lets authors attach extra validation rules to a model, export those rules inside the model's JSON Schema, and validate JSON-compatible payloads from Python or browser JS with the same Rust core.

Python keeps the authoring/export API. Runtime validation is schema-driven and takes only:

- a JSON-compatible payload
- the exported schema

The library is for contract validation, not for inventing a new validation language. Static rules should stay in ordinary Pydantic and ordinary JSON Schema. The x-validation layer exists only for rules that need instance-derived schema fragments at validation time.

Conceptually, `x-validations` is an embedded meta-schema:

- first validate against the raw exported JSON Schema
- then use the input data to compile a second ordinary JSON Schema from `x-validations`
- then validate against a combination of the original schema and the compiled schema

## Principles

1. Static-first
   Rules that Pydantic can express directly should remain plain Pydantic fields, constrained types, discriminated unions, or schema hooks. The x-validation layer is only for rules that cannot be emitted statically.

2. Embedded meta-schema, not executor DSL
   An x-validator is data: `id`, `description`, `target`, and a plain JSON Schema `assert` fragment. The library does not support per-rule Python executors, `kind` registries, or custom operator trees.

3. Standard JSON Schema at runtime
   The runtime may temporarily use placeholders while compiling a derived schema, but the compiled schema must contain only standard JSON Schema.

4. Self-contained export
   The exported schema must contain everything a third party needs: the base schema, reusable constants in `$defs`, and the x-validation annotations. No access to model code should be required.

5. Decorated-model authoring, root export
   Any model that declares `@xvalidation` rules must inherit from `XValidatedModel`. Nested models with no x-validations can remain ordinary Pydantic `BaseModel`s. Export still emits one root-level `x-validations` list by collecting rules from reachable `XValidatedModel`s and rebasing their paths to the root instance.

6. Deterministic compilation
   Dynamic validation is a pure function of:
   - the exported schema
   - the canonical JSON instance being validated

7. Schema-only validation
   Runtime callers pass `xvalidate(payload, schema)`. Pydantic model instances are not accepted by the runtime; callers that need Pydantic parsing should run it before producing a JSON-compatible payload.

8. Full JSONPath, instance-specialized compilation
   The exported `target` and instance `$resolve` values are JSONPath strings. In Python authoring, v1 does not accept raw JSONPath strings; authors use `x.path` objects, and the exporter serializes those objects to JSONPath. The compiler evaluates paths against canonical dumped JSON, converts target matches into concrete instance locations, and generates a standard JSON Schema overlay specialized to that instance.

9. Path-based parity
   Internal and external validation paths must agree on pass/fail and failing instance paths. Exact message text is not contractual.

10. Contract over hidden Python behavior
   If acceptance or rejection depends on Python-only validators that are not reflected in the exported contract, schema-only consumers cannot reproduce behavior. Those rules must either move into static schema or into x-validations.

## Non-Goals

- Recreating arbitrary Pydantic runtime behavior in schema-only environments
- Allowing executable Python callables inside exported rules
- Accepting raw JSONPath strings in the Python authoring API for v1
- Building an autofix or migration engine in v1
- Requiring every nested model to inherit from `XValidatedModel`
- Python-side validation normalization
- Pydantic model input for `xvalidate`
- CLI/model code generation
- Browser filesystem or synchronous HTTP `$ref` resolution
- Python authoring code in Rust

## Core Concepts

### 1. `XValidationRule`

The atomic rule format is minimal on purpose.

```python
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

JsonValue = dict[str, Any] | list[Any] | str | int | float | bool | None


class XValidationRule(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    description: str
    target: str
    assert_: JsonValue = Field(alias="assert")
```

Semantics:

- `id`: stable identifier for debugging and testing
- `description`: human-readable explanation
- `target`: the instance location where the assertion should be applied
- `assert`: plain JSON Schema data, except that it may temporarily contain `{"$resolve": ...}` placeholders before compilation

### 2. Internal `XValidationBundle`

Rules are normalized internally together with any reusable schema-owned constants.

```python
from pydantic import Field


class XValidationBundle(BaseModel):
    defs: dict[str, JsonValue] = Field(default_factory=dict)
    rules: list[XValidationRule] = Field(default_factory=list)
```

`defs` are merged into the root schema's `$defs`. In v1, authors do not write this bundle directly; constants enter it only by appearing inside returned rule objects through `x.resolve(...)`.

Decorators compile into `XValidationBundle` data during export. The bundle is an internal normalized representation used by the exporter.

### 3. `$resolve`

`$resolve` is the only special placeholder mechanism.

- `"$..."` resolves against the canonical instance JSON
- `"#..."` resolves against the exported schema JSON

Examples:

```json
{ "enum": { "$resolve": "$.fields[*].field_id" } }
{ "enum": { "$resolve": "#/$defs/xv_4f8b2a" } }
```

Rules:

- `$resolve` exists only before meta-schema compilation
- the compiled schema must contain no `$resolve` nodes
- a missing or invalid `$resolve` is an exported-schema error, not a user-input validation error

### 4. `target`

`target` is exported as a JSONPath expression evaluated against the canonical dumped instance. The assertion is applied independently to every matched node.

In Python authoring, `target` must be built from an `x.path` object:

```python
x.target(
    x.path.pages.each()
    .sections.each()
    .widgets.where(x.this.kind == "field")
    .field_id
)
```

The exporter serializes that path object to:

```json
"$.pages[*].sections[*].widgets[?(@.kind == \"field\")].field_id"
```

Examples:

- `$.pages[*].sections[*].widgets[?(@.kind == "field")].field_id`
- `$.stores[?(@.region == "west")].items[*].sku`
- `$..email`
- `$.views.list.columns[*]`
- `$.tables[*].column_field_ids[*]`
- `$.views.review.sections[*].contents[*]`

Compilation semantics:

1. evaluate `target` against the canonical instance
2. convert each match to a concrete instance location
3. resolve placeholders inside `assert`
4. generate a root schema overlay that places the resolved assertion at each concrete location
5. combine overlays with `allOf`

The compiled schema is valid standard JSON Schema, but it is intentionally specialized to the instance used during compilation.

## Exported Schema Contract

The exported schema is a normal JSON Schema document with a small extension surface at the root.

### Root keys

- ordinary JSON Schema emitted by Pydantic
- `$defs`: both Pydantic defs and x-validation defs
- `x-validations`: array of `XValidationRule` objects serialized with alias `assert`

Example shape:

```json
{
  "$defs": {
    "xv_4f8b2a": [
      "status",
      "created_at",
      "submitter"
    ]
  },
  "x-validations": [
    {
      "id": "widget-field-ref-exists",
      "description": "Field widgets must reference a configured field or builtin field.",
      "target": "$.pages[*].sections[*].widgets[?(@.kind == \"field\")].field_id",
      "assert": {
        "anyOf": [
          { "enum": { "$resolve": "$.fields[*].field_id" } },
          { "enum": { "$resolve": "#/$defs/xv_4f8b2a" } }
        ]
      }
    }
  ]
}
```

This structure is binding for the extension format. `x-validations` is a root-level list, and each rule object contains `id`, `description`, `target`, and `assert`.

Important constraint: the exported schema is self-contained. A third party with this schema and an input document has enough information to perform validation with this library.

## Authoring

### Decorator-first rules

Adding a new x-validator does not mean implementing a new validator class or runtime plugin. It means authoring another rule that compiles to the fixed `XValidationRule` export shape.

Extensibility happens by adding more rule data, not by extending the engine.

The primary Python API should be a decorator on the model whose fields the rule validates. The decorated function receives an authoring context and returns a rule builder. That function is not a runtime validator; it is a schema annotation factory evaluated during schema export.

Recommended context helpers:

- `x.path`: local model path builder
- `x.resolve(value)`: emits `{"$resolve": ...}` for path objects and JSON-compatible constants
- `x.target(path).assert_schema(schema)`: returns a rule using arbitrary JSON Schema data

### Path builder helpers

`x.path` produces immutable path objects used by `x.target(...)` and `x.resolve(...)`.
The Python authoring API does not accept raw JSONPath strings in v1; helper calls are serialized to JSONPath during schema export.
String arguments to helpers are property names or scalar values, not raw path fragments.

The path API has two layers: complete selector constructors and ergonomic shortcuts.
The selector constructors are the canonical surface because they map directly to JSONPath selector kinds:

| Helper | Meaning | Example | Exported JSONPath |
| --- | --- | --- | --- |
| `x.key(name)` | Object member selector. | `x.path.select(x.key("field-id"))` | `$["field-id"]` |
| `x.wildcard()` | Wildcard selector for all child values. | `x.path.fields.select(x.wildcard()).field_id` | `$.fields[*].field_id` |
| `x.index(index)` | Array index selector. | `x.path.fields.select(x.index(0)).field_id` | `$.fields[0].field_id` |
| `x.slice(start=None, stop=None, step=None)` | RFC 9535 array slice selector, including `step`. | `x.path.fields.select(x.slice(0, 10)).field_id` | `$.fields[0:10].field_id` |
| `x.filter(predicate)` | Filter selector with an expression rooted at `x.this`. | `x.path.fields.select(x.filter(x.this.type == "text")).field_id` | `$.fields[?(@.type == "text")].field_id` |
| `.select(*selectors)` | Child segment with one or more selectors, including selector lists/unions. | `x.path.select(x.key("a"), x.key("b"))` | `$["a","b"]` |
| `.desc(*selectors)` | Recursive descent segment with one or more selectors. | `x.path.desc(x.key("field_id"))` | `$..field_id` |

The ergonomic shortcuts are aliases over the selector constructors:

| Shortcut | Equivalent canonical form | Example | Exported JSONPath |
| --- | --- | --- | --- |
| Attribute access | `.select(x.key(name))` | `x.path.fields` | `$.fields` |
| Bracket access | `.select(x.key(name))` | `x.path["field-id"]` | `$["field-id"]` |
| `.each()` | `.select(x.wildcard())` | `x.path.fields.each().field_id` | `$.fields[*].field_id` |
| `.at(index)` | `.select(x.index(index))` | `x.path.fields.at(0).field_id` | `$.fields[0].field_id` |
| `.slice(...)` | `.select(x.slice(...))` | `x.path.fields.slice(0, 10).field_id` | `$.fields[0:10].field_id` |
| `.where(predicate)` | `.select(x.filter(predicate))` | `x.path.fields.where(x.this.type == "text").field_id` | `$.fields[?(@.type == "text")].field_id` |
| `.desc(name)` | `.desc(x.key(name))` | `x.path.desc("field_id")` | `$..field_id` |

Filter predicates should be explicit expression objects, not raw predicate strings.
The minimum predicate helper set is:

- `x.this`: current candidate node inside `.where(...)`, serialized as `@`.
- Attribute and bracket access from `x.this`, matching the same object-key rules as `x.path`.
- Comparison operators: `==`, `!=`, `<`, `<=`, `>`, `>=`.
- Boolean composition: `&`, `|`, and `~` for `and`, `or`, and `not`.
- Existence checks: `x.this.foo.exists()`, serialized as a JSONPath existence predicate if the backend supports it.

The builder should reject any expression it cannot serialize as RFC 9535 JSONPath.
There is no helper for walking above the decorated model in v1: `x.path` is rooted at the model that declares the rule. Model-local validations can address that model's dumped object and descendants only.

Model-local rules are deliberately scoped downward. A rule may reference fields on the same model or descendants of that model, but it may not look up to a parent/root model. If a rule needs to compare a nested model value against sibling or parent data, author that rule on the nearest common ancestor model.

Example:

```python
from typing import Literal

from pydantic import BaseModel

from xvalidations import XValidatedModel, XValidationContext, xvalidation


class FieldDefinition(BaseModel):
    field_id: str
    label: str
    kind: Literal["text", "number", "date"]


class FieldWidget(BaseModel):
    kind: Literal["field"]
    field_id: str
    required: bool = False


class MarkdownWidget(BaseModel):
    kind: Literal["markdown"]
    markdown: str


class Section(BaseModel):
    section_id: str
    widgets: list[FieldWidget | MarkdownWidget]


class Page(BaseModel):
    page_id: str
    sections: list[Section]


class IntakeForm(XValidatedModel):
    fields: list[FieldDefinition]
    pages: list[Page]

    @xvalidation(
        id="widget-field-ref-exists",
        description="Field widgets must reference a configured field or builtin field.",
    )
    def widget_field_ref_exists(x: XValidationContext):
        builtin_field_ids = ["status", "created_at", "submitter"]

        return x.target(
            x.path.pages.each()
            .sections.each()
            .widgets.where(x.this.kind == "field")
            .field_id
        ).assert_schema(
            {
                "anyOf": [
                    {"enum": x.resolve(x.path.fields.each().field_id)},
                    {"enum": x.resolve(builtin_field_ids)},
                ]
            }
        )
```

This compiles to the binding export shape:

```json
{
  "id": "widget-field-ref-exists",
  "description": "Field widgets must reference a configured field or builtin field.",
  "target": "$.pages[*].sections[*].widgets[?(@.kind == \"field\")].field_id",
  "assert": {
    "anyOf": [
      { "enum": { "$resolve": "$.fields[*].field_id" } },
      { "enum": { "$resolve": "#/$defs/xv_4f8b2a" } }
    ]
  }
}
```

The Python builder is intentionally incomplete as a JSON Schema DSL. `assert_schema(...)` accepts arbitrary JSON-compatible schema data, and helpers only cover this library's own concepts: model paths, automatic defs, and `$resolve` placeholders.

### Automatic definitions

JSON-compatible constants wrapped with `x.resolve(...)` are lifted into root `$defs` during export. Authors should not need to manually register defs for ordinary constants, but they must mark constants that should become `$resolve` values.

```python
class IntakeForm(XValidatedModel):
    fields: list[FieldDefinition]
    pages: list[Page]

    @xvalidation(id="widget-field-ref-exists")
    def widget_field_ref_exists(x: XValidationContext):
        builtin_field_ids = ["status", "created_at", "submitter"]

        return x.target(
            x.path.pages.each()
            .sections.each()
            .widgets.where(x.this.kind == "field")
            .field_id
        ).assert_schema(
            {
                "anyOf": [
                    {"enum": x.resolve(x.path.fields.each().field_id)},
                    {"enum": x.resolve(builtin_field_ids)},
                ]
            }
        )
```

The compiler sees `builtin_field_ids` because it is passed to `x.resolve(...)` in the returned rule graph. It does not inspect function bodies, closures, globals, or AST nodes, and it does not lift unused constants.

Generated definition names are deterministic and content-based. If the same JSON value appears more than once, export should deduplicate it to the same `$defs` entry.

Raw `assert_schema(...)` is mostly opaque. Literals inside arbitrary schema fragments stay inline unless wrapped with `x.resolve(...)`. This keeps automatic definition registration predictable.

### Model-local rules

Only models that declare `@xvalidation` rules need to inherit from `XValidatedModel`. Nested models without rules can be ordinary `BaseModel`s.

Rules are authored against the declaring model's dumped JSON object. During root schema export, rules from reachable `XValidatedModel`s are rebased to the root path:

```python
class IntakeForm(XValidatedModel):
    fields: list[FieldDefinition]
    pages: list[Page]

    @xvalidation(id="widget-field-ref-exists")
    def widget_field_ref_exists(x: XValidationContext):
        return x.target(
            x.path.pages.each()
            .sections.each()
            .widgets.where(x.this.kind == "field")
            .field_id
        ).assert_schema(
            {
                "enum": x.resolve(x.path.fields.each().field_id)
            }
        )
```

This keeps the common case light: most nested models stay plain Pydantic models, while decorated nested models opt into `XValidatedModel` only where they need local x-validations.

### Pydantic integration

The recommended integration surface is a mixin plus an explicit export helper.

### `XValidatedModel`

`XValidatedModel` extends `BaseModel` and is required only for models that declare `@xvalidation` rules.
Nested models with no x-validations can remain ordinary `BaseModel`s.
It exposes a class variable:

```python
from typing import ClassVar

__xvalidation_rule_factories__: ClassVar[tuple[XValidationFactory, ...]] = ()
```

It implements `__get_pydantic_json_schema__` to:

1. obtain the base schema from Pydantic
2. collect decorated x-validation rule factories from every reachable `XValidatedModel`
3. rebase model-local path objects to root instance paths before serializing to JSONPath
4. lift JSON-compatible constants wrapped with `x.resolve(...)` into root `$defs`
5. serialize all collected rules to root `x-validations`

This makes `Model.model_json_schema()` capable of returning the full contract, including x-validations.

### `export_schema()`

The library should still provide:

```python
export_schema(model: type[BaseModel], *, by_alias: bool = True) -> dict[str, Any]
```

Why keep an explicit exporter if the mixin already injects schema fields:

- it pins export options in one place
- it can validate the emitted schema structure
- it can enforce root-level export shape for v1
- it gives the library a stable public entrypoint

### Canonical naming

`target` and `$resolve` paths must be written against the same key space used by the exported schema.

For that reason, schema export should describe the wire-format keys that runtime payloads use. Defaulting to `by_alias=True` is preferred because the exported schema should describe the data seen by external consumers.

## Runtime Architecture

The runtime has two inputs:

- an exported schema
- a JSON-compatible payload

The fundamental design constraint is:

> x-validations may use the canonical instance to fill in or specialize JSON Schema, but the final compiled validation must be expressible as standard JSON Schema.

Rules that require arbitrary computation, external state, arithmetic, date math, or pairwise comparison are only supported if the library adds an explicit compiler operation that reduces them to standard JSON Schema for the current canonical instance.

### Main components

- `xvalidations/authoring.py`
  Implements `@xvalidation`, `XValidationContext`, the owned JSONPath/filter builder AST, and `$resolve` helpers.
- `xvalidations/pydantic.py`
  Implements `XValidatedModel`, model traversal, root-level export, and the bundled x-validations meta-schema URI.
- `xvalidations/errors.py`
  Defines authoring/export errors raised while declaring or exporting x-validations.
- `crates/xvalidations-core`
  Owns artifact extraction, schema preflight, JSONPath evaluation, `$resolve`, overlay lowering, compiled schema generation, and validation issue normalization.
- `crates/xvalid-py`
  Standalone pure-Rust Python package `xvalid-py`/`xvalid`. Converts Python objects to `serde_json::Value`, calls the core, and exposes schema-checking exceptions plus validation issues from PyO3.
- `crates/xvalid-js`
  Converts JS values through `serde-wasm-bindgen`, calls the core, and throws JavaScript `Error` objects that carry the serialized core failure.

## Validation pipeline

### Public validation API

```python
from xvalid import xvalidate

def xvalidate(payload: Any, schema: dict[str, Any]) -> None: ...
```

`xvalid.xvalidate(...)` is the single public Python runtime entrypoint.

It takes JSON-compatible data, not a Pydantic model. Callers that want Pydantic parsing should call `Model.model_validate(...)` themselves and then pass a JSON-compatible dump to `xvalidate(payload, schema)`.

Browser usage has the same contract:

```ts
import init, { xvalidate } from "./pkg/xvalid_js.js";

await init();
xvalidate({ tags: ["python"], primary_tag: "python" }, schema);
```

Flow:

1. Convert the host-language payload and schema to `serde_json::Value`.
2. Validate the exported schema against the x-validations meta-schema.
3. Strip `x-validations` and x-validation-owned `$defs` from the base schema.
4. Validate the payload against the stripped base schema.
5. If base validation fails, return only base-schema issues.
6. Evaluate each rule's `target` JSONPath against the payload.
7. Convert target matches into concrete instance locations.
8. Resolve all placeholders in every x-validation rule.
9. Lower each concrete location plus resolved assertion into a JSON Schema overlay.
10. Combine overlays into a compiled Draft 2020-12 schema.
11. Validate the payload against the compiled schema.
12. Return `Ok(())`/`None` on success; otherwise return or raise a structured `XValidationFailure`.

This keeps validation behavior identical in native Rust, Python, and browser JS.

## Meta-Schema Compilation

Core Rust modules drive the runtime:

```rust
resolve_placeholders(assertion, payload, schema) -> serde_json::Value
evaluate_jsonpath(query, payload) -> Vec<JsonPathMatch>
location_to_schema_overlay(location, assertion) -> serde_json::Value
generate_compiled_schema(schema, payload) -> CompiledSchema
xvalidate(payload, schema) -> Result<(), XValidationFailure>
```

### `resolve_placeholders`

Responsibilities:

- recursively walk the `assert` fragment
- replace every `{"$resolve": ...}` object with a concrete JSON value
- preserve ordinary JSON Schema structure untouched

Resolution rules:

- instance references are authored as `x.path` objects and exported as JSONPath strings
- schema references use JSON Pointer with `#...`
- wildcard instance paths return a list of matched values in document order
- non-JSON results are rejected

`x.resolve(...)` is mandatory for dynamic assertion values in Python authoring:

- `x.resolve(x.path.fields.each().field_id)` becomes `{"$resolve": "$.fields[*].field_id"}`
- `x.resolve(["status", "created_at", "submitter"])` lifts the literal into `$defs` and emits a `$resolve` pointer to that generated definition

Plain strings that look like JSONPath are treated as ordinary JSON string values unless passed through a future explicit raw-path API. v1 does not include that API.

### `evaluate_target`

This function evaluates the target JSONPath against the canonical instance and returns matched values with concrete instance locations.

Requirements:

- use the Rust JSONPath evaluator for target and `$resolve` evaluation
- preserve deterministic match order
- deduplicate identical locations
- reject non-RFC JSONPath extensions in exported schema artifacts
- expose locations as path segments such as `["stores", 0, "items", 1, "sku"]`

### `location_to_schema_overlay`

This function converts a concrete instance location into a nested schema fragment that applies the resolved assertion at exactly that point.

Example:

- location: `["pages", 0, "sections", 0, "widgets", 2, "field_id"]`
- resolved assertion: `{"anyOf": [{"enum": ["priority"]}, {"enum": ["status", "created_at", "submitter"]}]}`

Generated overlay:

```json
{
  "properties": {
    "pages": {
      "prefixItems": [
        {
          "properties": {
            "sections": {
              "prefixItems": [
                {
                  "properties": {
                    "widgets": {
                      "prefixItems": [
                        true,
                        true,
                        {
                          "properties": {
                            "field_id": {
                              "anyOf": [
                                { "enum": ["priority"] },
                                { "enum": ["status", "created_at", "submitter"] }
                              ]
                            }
                          }
                        }
                      ]
                    }
                  }
                }
              ]
            }
          }
        }
      ]
    }
  }
}
```

The overlay intentionally carries only the needed constraint. It does not restate unrelated base-schema structure. Array indexes are addressed with Draft 2020-12 `prefixItems`, so the compiled schema is specialized to the current instance shape.

### `generate_compiled_schema`

Recommended output shape:

```json
{
  "allOf": [
    {
      "properties": {
        "pages": {
          "prefixItems": [
            {
              "properties": {
                "sections": {
                  "prefixItems": [
                    {
                      "properties": {
                        "widgets": {
                          "prefixItems": [
                            true,
                            true,
                            {
                              "properties": {
                                "field_id": {
                                  "anyOf": [
                                    { "enum": ["priority"] },
                                    { "enum": ["status", "created_at", "submitter"] }
                                  ]
                                }
                              }
                            }
                          ]
                        }
                      }
                    }
                  ]
                }
              }
            }
          ]
        }
      }
    }
  ]
}
```

The compiled schema should remain plain JSON Schema. If the runtime wants `rule_id` for error attribution, it should keep that mapping out of band by tracking which compiled `allOf` entry came from which x-validation rule.

## Error Model

The Rust core owns the serializable error payloads. Bindings preserve those shapes and only wrap them in host-language error types:

- `XValidationFailure` represents schema-checking failures from the core.
- `XValidationBindingFailure` represents host-language value conversion failures with `{ "kind", "message" }`.
- Python maps validation failures to `XValidationError`, exported-schema failures to `ExportedSchemaError` subclasses, and conversion failures to `XValidationTypeError`.
- WASM returns `Ok(())` on success and throws a JavaScript `Error` with `name`, `kind`, and `failure` properties on failure.

Validation failure shape:

```json
{
  "kind": "validation",
  "issues": [
    {
      "path": "$.primary_tag",
      "message": "...",
      "keyword": "enum",
      "source": "x-validation",
      "rule_id": "primary-tag-exists"
    }
  ]
}
```

Python exposes validation issues as PyO3 classes and includes the serialized core failure on every schema-checking exception:

```python
from typing import Literal


class ValidationIssue:
    path: str
    message: str
    keyword: str | None
    source: Literal["base", "x-validation"]
    rule_id: str | None


class XValidationError(Exception):
    kind: Literal["validation"]
    failure: dict[str, object]
    errors: list[ValidationIssue]
```

Behavior:

- `xvalidate(...)` returns `None` on success
- `xvalidate(...)` raises `XValidationError` on validation failure
- `path` is the canonical instance path
- `source` distinguishes base-schema failures from x-validation failures
- `rule_id` is present when the failing compiled `allOf` branch can be attributed to a rule
- Pydantic parsing is outside this runtime. Callers who use Pydantic call `model_validate(...)` themselves.

Exported-schema errors are different from validation errors and should raise exceptions:

- invalid rule shape
- invalid target syntax
- missing `$resolve` path
- generated definition pointer that resolves outside JSON-compatible data

Those conditions indicate a broken exported schema, not bad user input.

## Build Commands

```bash
cargo test -p xvalidations-core
uv run maturin develop --manifest-path crates/xvalid-py/Cargo.toml
uv run pytest
wasm-pack test --node crates/xvalid-js
wasm-pack build crates/xvalid-js --target web --out-dir pkg
```

## Package Layout

Recommended v1 layout:

```text
xvalidations/
  __init__.py
  models.py        # exported rule models
  authoring.py     # xvalidation decorator, XValidationContext, path builders
  pydantic.py      # XValidatedModel, export_schema
  errors.py        # authoring/export errors

crates/
  xvalidations-core/  # schema artifact handling, compiler, validator
  xvalid-py/          # standalone pure-Rust PyO3-backed xvalid package
  xvalid-js/          # wasm-bindgen extension
```

## External Dependencies

Runtime dependencies:

- `pydantic`
  Required for Python authoring/export.
- Rust `jsonschema`
  Required in `xvalidations-core` for Draft 2020-12 base and compiled schema validation.
- Rust JSONPath evaluator
  Required in `xvalidations-core` for target and `$resolve` evaluation with concrete match locations.
- `pyo3` and `pythonize`
  Required only by the Python native extension.
- `wasm-bindgen` and `serde-wasm-bindgen`
  Required only by the browser JS/WASM extension.

The library should not depend on `jsonpath-ng` for v1.
It has a useful programmatic AST, but its dialect is not the exported contract this library needs:

- it is not strict RFC 9535 JSONPath
- its filter syntax and extension functions differ from RFC 9535
- its slice support is incomplete for RFC 9535 because slice `step` is not fully supported
- its serialized output would still need auditing or replacement before embedding in exported schemas

Instead, `x-validations` owns a small JSONPath/filter builder AST that serializes to RFC 9535 JSONPath strings.
The Rust core is the runtime truth for whether those strings parse and evaluate correctly.

## v1 Decisions

1. Pydantic v2 only
   The Python authoring/export API depends on `model_json_schema` semantics from Pydantic v2.

2. Decorated-model authoring, root-scoped export
   X-validations may be authored on any reachable `XValidatedModel`. Nested models without x-validations can be ordinary Pydantic models. Export collects local rules and rebases them into one root-level `x-validations` list.

3. Draft-2020-12-compatible validation
   The Rust runtime targets the same JSON Schema dialect that Pydantic emits for validation schemas. Instance-specific array overlays rely on Draft 2020-12 `prefixItems`.

4. Owned JSONPath builder, external JSONPath evaluator
   The public authoring API uses an owned path/filter AST. Export serializes that AST to JSONPath strings. Runtime evaluation happens in Rust; unsupported extensions are rejected.

5. No custom execution registry
   There is no `kind -> executor` dispatch table. New rules are new data, not new engine plugins.

6. No mutation during validation
   Validation raises errors only. Automatic migration or repair is a later concern.

## Correctness Requirements

The library should be tested against the following contract:

1. Exported-schema validity
   `export_schema()` emits a valid schema with well-formed root `x-validations`.

2. Resolution validity
   For real fixtures, compiled schemas contain no `$resolve` nodes.

3. Standard-schema validity
   Compiled schemas are valid JSON Schema documents.

4. JSONPath target compilation
   Full JSONPath targets are evaluated against canonical JSON and compiled into concrete location overlays with deterministic ordering and deduplication.

5. Behavioral parity
   Rust, Python, and WASM `xvalidate(payload, schema)` agree on:
   - pass/fail
   - failing instance paths
   - `source`
   - `rule_id`

6. Local-rule rebasing
   Rules authored on nested `XValidatedModel`s are exported once per reachable root path, with targets and local `$resolve` placeholders rebased deterministically.

7. Local scope enforcement
   Model-local rule authoring exposes only same-model and descendant paths. Parent/root lookup is unavailable.

8. Automatic definition export
   JSON-compatible constants wrapped with `x.resolve(...)` are lifted into root `$defs`, unused constants are omitted, and generated names are deterministic.

9. Rule coverage
   Every shipped example rule gets at least:
   - one positive fixture
   - one negative fixture

10. Static-rule separation
   Rules that can be expressed statically must stay in the base schema rather than being duplicated as x-validations.

## Summary

The library treats x-validations as schema-generation annotations authored on Pydantic models, not as executable Python validators. Authors extend the system by adding decorated model-local rules that compile to the fixed export shape. The runtime is shared Rust core:

- export one self-contained schema
- collect and rebase local rules into a root `x-validations` list
- validate base constraints normally
- evaluate JSONPath targets against canonical JSON
- resolve placeholders from the schema plus the instance
- compile an instance-specialized standard JSON Schema from `x-validations`
- validate again and return a structured failure on failure

That gives native Rust, Python, and browser consumers the same contract surface, while keeping Pydantic as the source of truth for authoring and everything that can already be expressed statically.
