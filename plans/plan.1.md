# Rust Shared Schema Validation Plan

Status: draft. No immutability pragma until human approves.

Goal: move whole schema-validation chain to Rust. Python keeps authoring/export only. Browser JS/TS gets same validator through WASM. CLI/codegen dies.

## Decisions

- JSON Schema dialect: Draft 2020-12 only.
- Validator: Rust `jsonschema` crate.
- X-extension shape: keep root `x-validations`, each rule `{id, description?, target, assert}`.
- Runtime input: JSON-compatible payload from `json.loads(...)` plus exported schema dict.
- Runtime no longer accepts `BaseModel`; no runtime `model_validate`, `model_dump`, or `model_json_schema`.
- Schema preflight runs before payload validation:
  1. validate original schema against bundled x-validations structural meta-schema.
  2. strip root `x-validations` and x-validation-owned `$defs`; set derived base `$schema` to Draft 2020-12; validate derived base schema against Draft 2020-12 meta-schema.
- Runtime validation is 2 phase:
  1. derive base schema by stripping `x-validations` and setting Draft 2020-12 `$schema`; validate payload vs base schema with standard JSON Schema validator.
  2. compile x-validations using same payload; validate payload vs compiled schema with same validator.
- `x-validations` may contain compile-time assertion primitives that are not JSON Schema keywords, starting with `x-uniqueBy`.
- Compile-time operators must be removed during phase 2; compiled schema must be valid Draft 2020-12 accepted by a standard JSON Schema validator.
- If phase 1 fails, skip phase 2.
- Inputs never mutate. Schema copy/derived docs stay in memory.
- Core Rust exposes one validation fn returning structured errors.
- Python binding converts Rust structured errors to Python exceptions.
- WASM binding converts Rust structured errors to `JsValue` exceptions.
- Cargo workspace crates:
  - `xvalidations-core`: pure Rust validation.
  - `xvalidations-py`: PyO3/maturin wrapper.
  - `xvalidations-js`: wasm-bindgen/wasm-pack wrapper.
- Python package not released yet; breaking API ok.
- Remove `xvalidations-codegen` CLI, `xvalidations/codegen.py`, `tests/test_codegen.py`, codegen optional deps, codegen docs.

## Current Repo Anchors

- `pyproject.toml:1` package = `xvalidations`; current deps include Python `jsonschema`, `jsonpath-rfc9535`, `pydantic`.
- `pyproject.toml:12` has `[project.optional-dependencies].codegen`.
- `pyproject.toml:18` registers `xvalidations-codegen`.
- `xvalidations/runtime.py:26` current `xvalidate(model: BaseModel, schema: dict | None)`.
- `xvalidations/runtime.py:35` current implicit `type(model).model_json_schema(...)`.
- `xvalidations/runtime.py:39` current `_canonical_model_dump(model)`.
- `xvalidations/compiler.py:27` current `generate_compiled_schema(base_schema, instance_json)`.
- `xvalidations/models.py:13` current `XValidationRule` fields.
- `xvalidations/models.py:31` current `ValidationIssue` fields.
- `xvalidations/errors.py:25` current `XValidationError.errors`.
- `xvalidations/codegen.py:1` CLI module.
- `tests/test_codegen.py:12` imports CLI module.
- `plans/ARCHITECTURE.md:468` documents `xvalidations-codegen`.

## External Docs Anchors

- `jsonschema` Rust crate supports Draft 2020-12 modules and validator creation: <https://docs.rs/jsonschema/latest/jsonschema/draft202012/index.html>.
- `jsonschema::draft202012::meta` validates schemas against Draft 2020-12 meta-schema: <https://docs.rs/jsonschema/latest/jsonschema/draft202012/meta/index.html>.
- `jsonschema` docs say browser `wasm32-unknown-unknown` needs no file/http resolver features: <https://docs.rs/jsonschema/latest/jsonschema/>.
- `jsonpath-rust` targets RFC 9535 JSONPath and returns matched values with normalized paths through `query_with_path`: <https://github.com/besok/jsonpath-rust/blob/main/README.md>.
- Maturin mixed Rust/Python layout supports `module-name = "package._native"`: <https://www.maturin.rs/project_layout.html>.
- Maturin build backend config uses `[build-system] requires = ["maturin>=1.0,<2.0"] build-backend = "maturin"`: <https://www.maturin.rs/distribution.html>.
- PyO3 `#[pyfunction]` exports Rust fns into Python modules: <https://pyo3.rs/main/function>.
- PyO3 `PyResult` crossing into Python raises stored `PyErr`: <https://pyo3.rs/main/function/error-handling>.
- PyO3 `PyErr::from_type` constructs a Python exception from a Python exception type and args: <https://docs.rs/pyo3/latest/pyo3/struct.PyErr.html>.
- wasm-pack `build --target web` emits browser ESM artifacts: <https://drager.github.io/wasm-pack/book/commands/build.html>.
- wasm-bindgen + `serde_wasm_bindgen` moves arbitrary serde data across `JsValue`: <https://wasm-bindgen.github.io/wasm-bindgen/reference/arbitrary-data-with-serde.html>.

## Technical Invariants

- `xvalidations-core` has no PyO3, wasm-bindgen, maturin, or Python import dependency.
- `xvalidations-core` compiles for native targets and `wasm32-unknown-unknown`.
- `xvalidations-core` uses `serde_json::Value` as boundary data model.
- `xvalidations-core::xvalidate(payload, schema)` is the only core validation entrypoint.
- Core error shape is stable JSON-serializable data.
- Exported input schemas must declare `"$schema": "https://thearchitector.dev/xvalidations/meta/x-validations.schema.json"`.
- Bundled x-validations meta-schema enforces the exported input schema `$schema`; no separate Rust `$schema` guard runs on user input.
- Derived base schema is an in-memory copy that strips only root `x-validations` and x-validation-owned `$defs`, then sets `"$schema": "https://json-schema.org/draft/2020-12/schema"` before Draft 2020-12 meta validation.
- Core ships a bundled pure Draft 2020-12 x-validations meta-schema at `crates/xvalidations-core/src/meta/xvalidations.schema.json`.
- Bundled x-validations meta-schema validates only the structure needed before compilation: optional root `x-validations`, rule field shape, optional `description`, `target`, `assert`, and known top-level compile-time primitives such as `x-uniqueBy`.
- Bundled x-validations meta-schema does not attempt to prove every non-primitive `assert` is valid Draft 2020-12 before `$resolve` runs. After `$resolve` replacement and primitive compilation, the compiled schema must pass ordinary Draft 2020-12 meta-schema validation before phase 2 payload validation.
- Bundled x-validations meta-schema is trusted internal input. Future work may add a bootstrapped self-validating variant, but this plan validates the bundled meta-schema with standard `jsonschema`.
- Bundled x-validations meta-schema does not replace semantic compiler errors for JSONPath parsing, `$resolve` reachability, target evaluation, primitive compilation, duplicate detection, or compiled overlay validation.
- `$resolve` marker validation is compiler-owned, not meta-schema-owned. Inside an x-validation assertion, an object containing `$resolve` must be exactly `{ "$resolve": "<ref>" }`; otherwise compilation raises `Resolve`.
- Because `$resolve` is reserved inside x-validation assertions, schemas cannot use `$resolve` as a literal property name inside assertion schema fragments.
- Standard JSON Schema extension keywords may remain in derived base schema and non-primitive compiled assertion fragments; JSON Schema validator ignores unknown keywords per spec behavior.
- `$ref` support is in-memory only for plan 1. Internal references such as `#/$defs/Foo` are supported; remote/file references are not fetched and surface as `InvalidSchema` from `jsonschema`.
- Phase 2 compiled schema is a valid Draft 2020-12 schema with no x-validations-owned markers such as `$resolve` or root `x-validations`.
- Phase 2 compiled schema contains no recognized root-level compile-time x-validation assertion primitives such as exact `{"x-uniqueBy": ...}` rule assertions.
- Phase 2 compiled schema has `"$schema": "https://json-schema.org/draft/2020-12/schema"`.
- JSONPath target eval dedupes concrete locations in first-seen order.
- `$resolve` supports JSONPath refs starting `$` against payload and JSON Pointer refs `#`/`#/...` against original schema.
- JSON Pointer tokens unescape `~1` to `/`, `~0` to `~`; array index token valid only `0` or nonzero decimal with no leading zero.
- Object-location overlays use `{"type":"object","properties":{...}}`.
- Array-index overlays use `{"type":"array","minItems":index+1,"prefixItems":[true,...,assertion]}`.
- Compile-time assertion primitives are an internal extension point, not JSON Schema vocabularies.
- Compile-time assertion primitives are recognized only when a rule's `assert` value is an exact single-key object at the assertion root, such as `{"x-uniqueBy":"$.field_id"}`. Nested `x-*` keys inside ordinary JSON Schema assertions are not x-validation primitives and follow normal JSON Schema unknown-keyword behavior.
- Each primitive owns parsing, compilation, error construction, and tests. Adding a primitive must not change the binding APIs or require a custom JSON Schema validator.
- `x-uniqueBy` is the only primitive in scope for this plan. Future primitives such as `x-orderBy` may be added later through the same internal interface.
- `x-uniqueBy` validates projected uniqueness across all target matches. It evaluates its JSONPath value relative to each target match value; duplicate projection values fail at concrete duplicate target locations.
- `x-uniqueBy` never appears in compiled schemas. Duplicate failures compile into ordinary false/impossible schemas at concrete instance locations.
- Python runtime exception classes stay import-compatible: `ExportedSchemaError`, `InvalidRuleError`, `JsonPathError`, `ResolveError`, `XValidationError`.
- `XValidationError.errors` stays list-like and contains issue objects or dicts with `path`, `message`, `keyword`, `source`, `rule_id`.
- `source` values stay `"base"` and `"x-validation"`.
- Python authoring/export modules stay Python and keep exporting root `x-validations`.
- CLI/codegen removal means no installed console scripts.
- Browser API package name is `xvalidations-js`.

## Product Assumptions

- Users validate already-loaded JSON, not Python model instances.
- Python users call `xvalidate(payload, schema)` after `payload = json.loads(text)`.
- Python authoring users still write Pydantic `XValidatedModel` and call `model_json_schema()` / `export_schema(...)`.
- Python authoring/export sets exported schema `$schema` to `https://thearchitector.dev/xvalidations/meta/x-validations.schema.json`.
- Browser users pass plain JS values: object/array/string/number/bool/null.
- Browser package throws real JS exceptions on validation or schema errors.
- Python package throws real Python exceptions on validation or schema errors.
- Cross-language errors are inspectable, not only string messages.

## Milestone 1: Shared Contract Fixtures

Scope: lock behavior before port.

Tasks:

1. Add `tests/fixtures/contracts/article.json` with schema, payloads, and expected issues. Include same root `x-validations` shape current export emits.

```json
{
  "schema": {
    "$schema": "https://thearchitector.dev/xvalidations/meta/x-validations.schema.json",
    "type": "object",
    "required": ["tags", "primary_tag"],
    "properties": {
      "tags": {"type": "array", "items": {"type": "string"}},
      "primary_tag": {"type": "string"}
    },
    "x-validations": [
      {
        "id": "primary-tag-exists",
        "description": "Primary tag must be present in tags.",
        "target": "$.primary_tag",
        "assert": {"enum": {"$resolve": "$.tags[*]"}}
      }
    ]
  },
  "valid_payload": {"tags": ["python"], "primary_tag": "python"},
  "base_invalid_payload": {"tags": ["python"]},
  "x_invalid_payload": {"tags": ["python"], "primary_tag": "rust"},
  "expected_x_issue": {
    "path": "$.primary_tag",
    "source": "x-validation",
    "rule_id": "primary-tag-exists"
  }
}
```

2. Add `tests/fixtures/contracts/jsonpath_nested.json` for nested array/object overlays.

```json
{
  "schema": {
    "$schema": "https://thearchitector.dev/xvalidations/meta/x-validations.schema.json",
    "type": "object",
    "properties": {
      "items": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "kind": {"type": "string"},
            "id": {"type": "string"},
            "primary": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}}
          }
        }
      }
    },
    "x-validations": [
      {
        "id": "item-primary-in-tags",
        "description": "Each field primary must be in same item tags.",
        "target": "$.items[?(@.kind == \"field\")].primary",
        "assert": {"enum": {"$resolve": "$.items[?(@.kind == \"field\")].tags[*]"}}
      }
    ]
  },
  "payload": {
    "items": [
      {"kind": "field", "id": "a", "primary": "blue", "tags": ["blue"]},
      {"kind": "field", "id": "b", "primary": "red", "tags": ["green"]}
    ]
  },
  "expected_issue": {
    "path": "$.items[1].primary",
    "source": "x-validation",
    "rule_id": "item-primary-in-tags"
  }
}
```

3. Add Python fixture loader test that proves fixtures are valid JSON and current authoring can still emit same extension shape.

```python
def test_contract_fixture_shape(article_contract: dict[str, object]) -> None:
    schema = article_contract["schema"]
    assert schema["$schema"] == "https://thearchitector.dev/xvalidations/meta/x-validations.schema.json"
    rules = schema["x-validations"]
    assert rules[0]["id"] == "primary-tag-exists"
    assert rules[0]["target"] == "$.primary_tag"
    assert rules[0]["assert"] == {"enum": {"$resolve": "$.tags[*]"}}
```

Acceptance:

- `uv run pytest tests/test_pydantic_export.py tests/test_authoring.py` passes.
- Contract fixture test passes.
- No Rust code required yet.

## Milestone 2: Cargo Workspace + Core API

Scope: add Rust workspace and phase 1 validation in pure Rust.

Tasks:

1. Add root `Cargo.toml`.

```toml
[workspace]
members = [
  "crates/xvalidations-core",
  "crates/xvalidations-py",
  "crates/xvalidations-js"
]
resolver = "2"

[workspace.package]
edition = "2021"
license = "MIT"
rust-version = "1.82"
```

2. Add `crates/xvalidations-core/Cargo.toml`.

```toml
[package]
name = "xvalidations-core"
version = "0.1.0"
edition.workspace = true
license.workspace = true
rust-version.workspace = true

[dependencies]
jsonschema = { version = "0.46.3", default-features = false }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
jsonpath-rust = "1.0.4"
thiserror = "2"

[dev-dependencies]
pretty_assertions = "1"
```

3. Add `crates/xvalidations-core/src/types.rs` with the public structured error contract.

Required public shapes:

- `IssueSource`: serialized source values are exactly `"base"` and `"x-validation"`.
- `ValidationIssue`: fields `path: String`, `message: String`, `keyword: Option<String>`, `source: IssueSource`, `rule_id: Option<String>`.
- `XValidationRule`: fields `id: String`, optional `description: Option<String>`, `target: String`, `assertion: serde_json::Value` serialized/deserialized as JSON key `"assert"`.
- `XValidationFailure`: JSON-serializable tagged enum with variants `InvalidSchema { message }`, `InvalidRule { message }`, `JsonPath { message }`, `Resolve { message }`, `Validation { issues }`.

4. Add the core public entrypoint in `crates/xvalidations-core/src/lib.rs`.

Required API:

- `xvalidations_core::xvalidate(payload: &serde_json::Value, schema: &serde_json::Value) -> Result<(), XValidationFailure>`.
- Milestone 2 implementation runs only schema preflight, derived base schema validation, and base payload validation.
- Milestone 3 extends the same function with x-validation compilation and phase 2 payload validation.

5. Add `artifact` behavior for immutable schema derivation.

Required behavior:

- Extract `x-validations` from root only. Missing or `null` root `x-validations` means no rules.
- Deserialize rule objects into `XValidationRule`; malformed rules surface as `InvalidRule` unless rejected earlier by the x-validations meta-schema.
- Produce a derived base schema without mutating the input schema.
- Derived base schema removes root `x-validations`.
- Derived base schema removes only `$defs` entries referenced by exact `$resolve` markers under rule assertions with refs beginning `#/$defs/`.
- Derived base schema sets `"$schema": "https://json-schema.org/draft/2020-12/schema"` before Draft 2020-12 meta validation.

6. Add base-schema meta validation, payload validation, and validation issue normalization.

Required behavior:

- Validate the bundled x-validations meta-schema itself with `jsonschema::draft202012::meta::validate`.
- Validate user schemas against the bundled x-validations meta-schema before deriving the base schema.
- Validate derived base schemas with Draft 2020-12 meta validation before validating payloads.
- Validate payloads with `jsonschema::draft202012`.
- Normalize validation errors into stable `ValidationIssue` values.
- Sort issues by normalized instance path and then message for deterministic cross-language output.
- Normalize instance paths to JSONPath-like strings: root `$`, object property `.name` when identifier-safe, bracket string notation for non-identifiers, array index `[N]`.
- Base validation issues use `source = "base"` and `rule_id = None`.
- Phase 2 rule-id mapping is specified in Milestone 3; Milestone 2 exposes a reusable validation helper that can accept optional `branch_rule_ids`.

Add `crates/xvalidations-core/src/meta/xvalidations.schema.json`. This schema validates only the exported schema document's x-validation container and compiler input shape. It intentionally does not validate full Draft 2020-12 keyword grammar inside non-primitive assertions because `$resolve` may temporarily occupy keyword values before compile.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://thearchitector.dev/xvalidations/meta/x-validations.schema.json",
  "title": "x-validations exported schema structural contract",
  "type": "object",
  "required": ["$schema"],
  "properties": {
    "$schema": {
      "const": "https://thearchitector.dev/xvalidations/meta/x-validations.schema.json"
    },
    "$defs": {
      "type": "object"
    },
    "x-validations": {
      "anyOf": [
        { "type": "null" },
        {
          "type": "array",
          "items": { "$ref": "#/$defs/rule" }
        }
      ]
    }
  },
  "$defs": {
    "rule": {
      "type": "object",
      "required": ["id", "target", "assert"],
      "properties": {
        "id": { "type": "string", "minLength": 1 },
        "description": { "type": "string" },
        "target": { "type": "string", "minLength": 1 },
        "assert": {
          "anyOf": [
            { "$ref": "#/$defs/xUniqueByPrimitive" },
            { "$ref": "#/$defs/assertionInput" }
          ]
        }
      },
      "additionalProperties": false
    },
    "xUniqueByPrimitive": {
      "type": "object",
      "required": ["x-uniqueBy"],
      "properties": {
        "x-uniqueBy": { "type": "string", "minLength": 1 }
      },
      "additionalProperties": false
    },
    "assertionInput": {
      "anyOf": [
        { "type": "boolean" },
        {
          "type": "object",
          "propertyNames": {
            "not": { "pattern": "^x-" }
          }
        }
      ]
    }
  }
}
```

The `assertionInput` branch is deliberately permissive. It rejects every top-level `x-*` key unless the whole assertion is an exact known primitive such as `{"x-uniqueBy":"$.field_id"}`. It allows ordinary JSON Schema-looking objects through compile preflight. Invalid keyword shapes such as `{"type": 42}` are caught later when `generate_compiled_schema(...)` resolves `$resolve`, emits the phase-2 schema, and calls `validate_schema_document(&compiled)`.

7. Add phase 1 tests in `crates/xvalidations-core/tests/base_schema.rs`.

Required tests:

- `phase1_rejects_base_schema_failure_and_skips_xvalidation`: payload missing base-required field returns `Validation` issues with `source = "base"` and `rule_id = None`.
- `schema_preflight_requires_schema_field`: missing `$schema` returns `InvalidSchema`.
- `schema_preflight_requires_xvalidations_meta_schema_uri`: Draft 2020-12 `$schema` on user input returns `InvalidSchema`.
- `schema_preflight_rejects_invalid_xvalidation_rule_shape`: rule missing `assert` returns `InvalidSchema`.
- `schema_preflight_allows_optional_description_and_unique_by_primitive`: rule without `description` and with exact `{"x-uniqueBy":"$.field_id"}` passes preflight.
- `schema_preflight_rejects_unknown_top_level_x_assertion_primitive`: exact `{"x-notSupported":"$.id"}` assertion returns `InvalidSchema`.
- `schema_preflight_allows_resolve_hole_where_json_schema_expects_array`: `{"enum":{"$resolve":"$.allowed_tags"}}` passes preflight and base validation; Milestone 3 proves resolved assertion validity.

Acceptance:

- `cargo test -p xvalidations-core --test base_schema` passes.
- Core compiles native without PyO3 or wasm-bindgen.
- `rg "pyo3|wasm_bindgen" crates/xvalidations-core` prints no matches.
- Exported schema with missing or non-x-validations `$schema` fails as `InvalidSchema` before base schema derivation.
- Invalid x-validation rule shape fails as `InvalidSchema` before payload validation.
- Unknown top-level `x-*` assertion primitive fails as `InvalidSchema` before payload validation.
- Exact `$resolve` marker objects are accepted by x-validations preflight; Milestone 3 rechecks resolved assertions against ordinary Draft 2020-12.

## Milestone 3: Rust X-Validation Compiler

Scope: port Python schema-validation internals to `xvalidations-core`.

Tasks:

1. Add `jsonpath.rs` with an internal match representation.

Required behavior:

- Use `jsonpath-rust` for RFC 9535 JSONPath evaluation.
- Return matches containing matched value, normalized path string, and concrete instance-location segments.
- Convert normalized paths into `Property(String)` / `Index(usize)` segments for overlay generation.
- Deduplicate repeated result locations in first-seen order.
- Invalid JSONPath syntax or unsupported normalized output conversion surfaces as `XValidationFailure::JsonPath`.

2. Add `resolve.rs` for `$resolve` markers.

Required behavior:

- Recursively walk non-primitive assertion JSON.
- Exact object `{ "$resolve": "<ref>" }` is the only marker form.
- Any object containing `$resolve` plus other keys raises `XValidationFailure::Resolve`.
- Non-string `$resolve` values raise `Resolve`.
- `$` refs evaluate as JSONPath against the current payload and resolve to an array of matched values.
- `#` and `#/...` refs resolve as JSON Pointer against the original exported schema.
- JSON Pointer token unescaping follows RFC 6901: `~1` becomes `/`, `~0` becomes `~`.
- JSON Pointer array tokens must be `0` or nonzero decimal with no leading zero.
- Unsupported ref prefixes, missing tokens, missing indexes, and scalar traversal raise `Resolve`.

3. Add `target.rs` for concrete location overlay generation.

Required behavior:

- For object properties, emit nested `{"type":"object","properties":{...}}` overlays.
- For array indexes, emit nested `{"type":"array","minItems": index + 1, "prefixItems": [true, ..., assertion]}` overlays.
- Root target location returns the assertion unchanged.
- The overlay generator must not mutate assertion inputs.

4. Add `compiler.rs` and wire it into `xvalidate`.

Required behavior:

- `generate_compiled_schema(schema, payload)` returns `{ schema, branch_rule_ids }`.
- Iterate rules in exported order.
- Evaluate each rule `target` against the payload.
- If a rule assertion is an exact known primitive, dispatch to that primitive compiler.
- Otherwise resolve `$resolve` markers in the assertion, validate the resolved assertion against Draft 2020-12 meta-schema, and create one overlay per target match.
- The compiled schema shape is `{"$schema":"https://json-schema.org/draft/2020-12/schema"}` with `allOf` only when overlays exist.
- Each `allOf` branch has a same-index entry in `branch_rule_ids`.
- Validate the final compiled schema against Draft 2020-12 before phase 2 payload validation.
- Update `xvalidate` so phase 2 runs only after base payload validation succeeds.

5. Add `x-uniqueBy` as the first compile-time primitive.

Required behavior:

- Recognized only as an exact root assertion object: `{"x-uniqueBy":"<jsonpath>"}`.
- Evaluate projection path relative to each target match value.
- Each target must project to exactly one value; zero or multiple values raise `InvalidRule`.
- Group targets by projected JSON value equality.
- Duplicate groups compile into ordinary false/impossible overlays at every duplicate target location.
- `x-uniqueBy` never appears in the compiled schema.

6. Add an internal primitive extension boundary.

Required behavior:

- Primitive recognition, parsing, compilation, and error construction stay isolated from binding APIs.
- Unknown exact root `x-*` primitives are rejected by preflight meta-schema.
- Future primitives add one compiler branch/implementation plus contract fixtures and tests, without changing Python or WASM APIs.

Example future primitive shape, out of scope for this plan:

```json
{
  "id": "sections-ordered",
  "description": "Sections must be ordered by order.",
  "target": "$.views.review.sections",
  "assert": {"x-orderBy": {"path": "$.order", "direction": "asc"}}
}
```

7. Add Rust unit tests matching existing Python semantics.

Required tests:

- `compile_resolves_payload_values_into_enum`: compiled schema has no `$resolve`, and `branch_rule_ids` maps first branch to `primary-tag-exists`.
- `xvalidation_failure_has_rule_id_and_path`: invalid `primary_tag` returns `source = "x-validation"`, `rule_id = "primary-tag-exists"`, and path `$.primary_tag`.
- `unique_by_compiles_duplicate_targets_to_false_overlays`: duplicate `field_id` values return x-validation issues at `$.fields[...]` paths with `rule_id = "unique-field-ids"`.
- `compiled_schema_validation_rejects_invalid_json_schema_keyword_shape_inside_assertion`: unresolved assertion `{"type": 42}` fails as `InvalidSchema` after compile-time processing and before phase 2 payload validation.
- `resolve_rejects_non_exact_marker_object`: `{"enum":{"$resolve":"$.allowed","fallback":[]}}` fails as `Resolve`.
- `bad_resolve_pointer_reports_resolve`: missing `#/$defs/...` token fails as `Resolve`.
- `jsonpath_syntax_error_reports_jsonpath`: malformed target or projection path fails as `JsonPath`.
- `unique_by_non_singleton_projection_reports_invalid_rule`: projection returning zero or multiple values fails as `InvalidRule`.

Acceptance:

- `cargo test -p xvalidations-core` passes.
- Contract fixtures pass from Rust tests.
- Phase 2 compiled schema has no `$resolve`, no `x-validations`, and no recognized root-level primitive assertion branches.
- Invalid JSONPath produces `XValidationFailure::JsonPath`.
- Bad `$resolve` produces `XValidationFailure::Resolve`.
- Invalid Draft 2020-12 keyword shapes inside non-primitive assertions fail as `InvalidSchema` after `$resolve` replacement and before phase-2 payload validation.
- Duplicate `x-uniqueBy` projections produce `x-validation` issues with the originating `rule_id`.
- Non-singleton `x-uniqueBy` projections produce `InvalidRule`.

## Milestone 4: Python Binding + Runtime API Break

Scope: route Python `xvalidate(payload, schema)` through Rust.

Tasks:

1. Add `crates/xvalidations-py/Cargo.toml`.

```toml
[package]
name = "xvalidations-py"
version = "0.1.0"
edition.workspace = true
license.workspace = true
rust-version.workspace = true

[lib]
name = "_xvalidations"
crate-type = ["cdylib"]

[dependencies]
pyo3 = { version = "0.28.3", features = ["extension-module"] }
pythonize = "0.28"
serde_json = "1"
xvalidations-core = { path = "../xvalidations-core" }
```

2. Add PyO3 module `crates/xvalidations-py/src/lib.rs`.

Required behavior:

- Export a private Python extension module named `xvalidations._xvalidations`.
- Export function `_xvalidations.xvalidate(payload, schema) -> None`.
- Convert Python payload/schema values to `serde_json::Value` using `pythonize`.
- Call `xvalidations_core::xvalidate`.
- Convert every `XValidationFailure` into a real Python exception, not a success return value.

3. Update `pyproject.toml` for maturin mixed project and remove CLI/codegen deps.

```toml
[build-system]
requires = ["maturin>=1.0,<2.0"]
build-backend = "maturin"

[project]
dependencies = [
    "pydantic>=2.13.3"
]

[tool.maturin]
manifest-path = "crates/xvalidations-py/Cargo.toml"
module-name = "xvalidations._xvalidations"
python-source = "."
bindings = "pyo3"
```

4. Replace `xvalidations/runtime.py` with thin wrapper. No Pydantic imports.

```python
from typing import Any

from xvalidations import _xvalidations

def xvalidate(payload: Any, schema: dict[str, Any]) -> None:
    """Validate JSON-compatible payload against exported x-validations schema."""
    _xvalidations.xvalidate(payload, schema)
```

5. Convert Rust failures to existing Python exceptions.

Required mapping:

- `Validation` -> `XValidationError`
- `InvalidSchema` -> `ExportedSchemaError`
- `InvalidRule` -> `InvalidRuleError`
- `JsonPath` -> `JsonPathError`
- `Resolve` -> `ResolveError`

Requirements:

- Use real `PyErr` exceptions, e.g. via `PyErr::from_type`.
- Preserve structured failure data on Python exception instances.
- `XValidationError.errors` stays list-like and exposes issue dicts/objects with `path`, `message`, `keyword`, `source`, `rule_id`.
- Existing direct Python construction in tests still works.

6. Update `xvalidations/errors.py` to parse native structured failures while preserving current exception class names and `.errors` semantics.

7. Rewrite runtime tests to use dict/list/scalar payloads, not `BaseModel` instances.

Required tests:

- `test_xvalidate_accepts_json_loaded_dict`: `json.loads(...)` payload plus exported schema returns `None`.
- `test_xvalidate_rejects_xvalidation_failure`: bad `primary_tag` raises `XValidationError`; first issue has `source = "x-validation"` and `rule_id = "primary-tag-exists"`.
- `test_xvalidate_rejects_base_schema_failure`: missing base-required field raises `XValidationError`; issue has `source = "base"` and `rule_id is None`.
- `test_xvalidate_rejects_invalid_schema_shape`: missing or wrong x-validations `$schema` raises `ExportedSchemaError`.

8. Delete or rewrite tests that import Python validation internals:
   - `tests/test_artifact.py` -> Rust `artifact` tests.
   - `tests/test_compiler.py` -> Rust `compiler` tests plus Python binding smoke tests.
   - `tests/test_jsonpath.py` -> Rust `jsonpath` tests.
   - `tests/test_resolve.py` -> Rust `resolve` tests.
   - `tests/test_target.py` -> Rust `target` tests.

9. Update Python authoring/export to declare the x-validations meta-schema URI on exported schemas. In `xvalidations/pydantic.py`, exported schemas must contain:

```python
copied["$schema"] = "https://thearchitector.dev/xvalidations/meta/x-validations.schema.json"
```

10. Add or update Python authoring/export tests so `Article.model_json_schema()["$schema"]` equals `https://thearchitector.dev/xvalidations/meta/x-validations.schema.json`.

Acceptance:

- `uv run maturin develop` succeeds.
- `uv run pytest tests/test_runtime.py tests/test_correctness_matrix.py` passes after dict-based rewrites.
- `rg "BaseModel|model_dump|model_json_schema" xvalidations/runtime.py` prints no matches.
- Python authoring/export tests still pass.
- Python authoring/export emits `$schema = "https://thearchitector.dev/xvalidations/meta/x-validations.schema.json"`.
- Python validation path imports no Python `jsonschema`.

## Milestone 5: WASM Browser Binding

Scope: expose same core to browser-compatible JS/TS.

Tasks:

1. Add `crates/xvalidations-js/Cargo.toml`.

```toml
[package]
name = "xvalidations-js"
version = "0.1.0"
edition.workspace = true
license.workspace = true
rust-version.workspace = true

[lib]
crate-type = ["cdylib", "rlib"]

[dependencies]
serde_json = "1"
serde-wasm-bindgen = "0.6"
wasm-bindgen = "0.2"
xvalidations-core = { path = "../xvalidations-core" }

[dev-dependencies]
wasm-bindgen-test = "0.3"
```

2. Add wasm binding `crates/xvalidations-js/src/lib.rs`.

Required behavior:

- Export browser-compatible `xvalidate(payload, schema)` through `wasm-bindgen`.
- Convert JS payload/schema values to `serde_json::Value` with `serde-wasm-bindgen`.
- Call `xvalidations_core::xvalidate`.
- Return `Ok(())` for valid payloads.
- Return thrown `JsValue` objects for conversion failures and core failures.
- Core failures serialize as the same structured `XValidationFailure` shape used by Rust/Python.
- JS conversion failures include machine-readable `kind` values `invalid_payload` or `invalid_schema_input`.

3. Add JS package metadata for generated output through Cargo package metadata.

```toml
[package.metadata.wasm-pack.profile.release]
wasm-opt = false
```

4. Add wasm tests under `crates/xvalidations-js/tests/web.rs`.

Required tests:

- Valid article fixture returns `Ok(())`.
- Invalid article fixture returns a structured `Validation` failure when converted back from `JsValue`.
- Invalid JS payload/schema conversion returns a thrown object with `kind = "invalid_payload"` or `kind = "invalid_schema_input"`.

5. Add package build command to docs/CI scripts.

```bash
wasm-pack build crates/xvalidations-js --target web --out-dir pkg
```

Acceptance:

- `wasm-pack build crates/xvalidations-js --target web --out-dir pkg` succeeds.
- Generated package name is `xvalidations-js`.
- Browser-target build contains no Python deps.
- WASM invalid payload/schema conversion returns thrown `JsValue` object with `kind`.

## Milestone 6: Remove CLI/Codegen

Scope: delete codegen tool surface.

Tasks:

1. Remove pyproject codegen optional deps and scripts.

```toml
# delete
[project.optional-dependencies]
codegen = [
    "typer>=0.25.1",
    "datamodel-code-generator>=0.56.1",
]

[project.scripts]
xvalidations-codegen = "xvalidations.codegen:main"
```

2. Delete files:

```text
xvalidations/codegen.py
tests/test_codegen.py
```

3. Remove docs references in `README.md`, `plans/ARCHITECTURE.md`, and old `plans/plan.md`.

```text
delete text that mentions:
xvalidations-codegen
datamodel-codegen
codegen optional dependency
plain Pydantic model generation CLI
```

4. Update package dependency expectations:

```bash
rg "typer|datamodel-code-generator|xvalidations-codegen|codegen" pyproject.toml README.md plans xvalidations tests
```

Acceptance:

- `rg "xvalidations-codegen|datamodel-codegen|typer" .` finds no live code/config refs.
- No console script installed by package metadata.
- Test suite no longer imports `xvalidations.codegen`.

## Milestone 7: Cross-Language Parity Tests

Scope: prove Python and WASM bindings match Rust core.

Tasks:

1. Add Rust fixture runner in `crates/xvalidations-core/tests/contracts.rs`.

Required behavior:

- Load every `tests/fixtures/contracts/*.json` contract.
- Valid payloads pass.
- Base-invalid payloads fail with only `source = "base"` issues.
- X-invalid payloads fail with expected `source`, `rule_id`, and normalized path from the fixture.

2. Add Python fixture runner with the same contracts and assertions.

3. Add WASM fixture runner that serializes the same fixtures into JS values and checks the same structured failure fields after converting thrown `JsValue` back to JSON/Rust data.

4. Add command matrix to docs.

```bash
cargo test -p xvalidations-core
uv run maturin develop
uv run pytest
wasm-pack test crates/xvalidations-js --headless --firefox
wasm-pack build crates/xvalidations-js --target web --out-dir pkg
```

Acceptance:

- Same fixture yields same `source`, `rule_id`, and normalized path in Rust, Python, WASM.
- Base schema errors have `source = "base"` and `rule_id = null`.
- Phase 1 failure fixture shows no x-validation issue.

## Milestone 8: Docs + Release Shape

Scope: make new API obvious, remove old runtime mental model.

Tasks:

1. Update `README.md` runtime section.

```python
import json
from xvalidations import xvalidate

payload = json.loads('{"tags":["python"],"primary_tag":"python"}')
schema = Article.model_json_schema()
xvalidate(payload, schema)
```

2. Add JS usage docs.

```ts
import init, { xvalidate } from "./pkg/xvalidations_js.js";

await init();
xvalidate(
  { tags: ["python"], primary_tag: "python" },
  schema
);
```

3. Document failure shape.

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

4. Document non-goals.

```text
No Python-side validation normalization.
No Pydantic model input for xvalidate.
No CLI/model codegen.
No browser filesystem or sync HTTP $ref resolution.
No Python authoring code in Rust.
```

Acceptance:

- README has Python dict payload API.
- README has browser JS API.
- README has no codegen CLI refs.
- `uv run pytest`, `cargo test --workspace`, and wasm build/test commands pass.

## Implementation Order

1. Milestone 1 fixtures.
2. Milestone 2 core phase 1.
3. Milestone 3 core x-validation compiler.
4. Milestone 4 Python binding and API break.
5. Milestone 5 WASM binding.
6. Milestone 6 CLI/codegen removal.
7. Milestone 7 parity tests.
8. Milestone 8 docs.

## Done Definition

- `xvalidate(payload, schema)` in Python validates dict/list/scalar payloads only.
- Same core Rust validation powers Python and browser JS.
- Full Draft 2020-12 schema validation comes from Rust `jsonschema`.
- Exported x-validations schema structure is checked by bundled pure Draft 2020-12 x-validations meta-schema before payload validation.
- Runtime never calls Pydantic normalization APIs.
- Python authoring/export remains available.
- CLI/codegen removed.
- Rust core has no binding-specific deps.
- Native Rust, Python/maturin, and WASM/wasm-pack checks pass.
