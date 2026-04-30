<!-- pragma: no ai -->

# X-Validations v1 Impl Plan

Goal: build a Pydantic-native library that lets authors attach dynamic contract rules to models, export those rules inside JSON Schema, and validate either with the original model class or only with exported schema plus a generated/plain Pydantic model.

## Invariants

- Static-first: rules Pydantic can express directly stay as Pydantic fields, constrained types, unions, or schema hooks. `x-validations` handles only rules needing instance-derived schema at validation time.
- Pydantic v2 only. Runtime uses `model_validate`, `model_json_schema`, `model_dump(mode="json")`.
- Draft 2020-12 only. Runtime validates with `jsonschema.Draft202012Validator`.
- Dependency management uses `uv` only.
- Repo uses flat package layout: top module is `xvalidations/`. Do not create `src/`.
- Project metadata comes from uv package template. Do not embed template config in this plan.
- Python snippets omit imports by request. Implementation files still need normal imports and `from __future__ import annotations`.
- Follow Python guidelines: `uv run pytest`, `uv run prek run -a`, pytest fixtures by scope, parameterized tests with short ids, no nested test classes, no internal `# type: ignore`; use `cast()` where type checker needs proof.
- Export = ordinary Pydantic JSON Schema plus root `x-validations`.
- Export root keys:
    - Pydantic JSON Schema keywords at root and below.
    - `$defs` containing both Pydantic definitions and x-validation generated constant definitions.
    - `x-validations`, a root-level list of rule objects.
- Rule = data only: `id`, `description`, `target`, `assert`. No executor registry. No rule `kind`. No Python callable in export.
- `id` is stable for tests/debugging, `description` is human-readable, `target` is where assertion applies, `assert` is ordinary JSON Schema data before placeholder resolution.
- `target` and instance `$resolve` strings = RFC 9535 JSONPath.
- `$resolve` is the only placeholder mechanism. Values beginning with `$` resolve against canonical dumped instance JSON. Values beginning with `#/` resolve against exported schema JSON.
- Python authoring v1 accepts path objects only. No raw JSONPath strings in `x.target()` or `x.resolve()`.
- `$resolve` exists only before compile. Compiled schema contains zero `$resolve`.
- Target compile semantics:
    - Evaluate `target` against canonical dumped instance JSON.
    - Convert each match into concrete instance location segments like `("stores", 0, "sku")`.
    - Resolve every `$resolve` inside the rule assertion.
    - Lower each concrete location plus resolved assertion into a root JSON Schema overlay.
    - Combine overlays with `allOf`.
- Export and runtime dump share `by_alias=True` default.
- `x-validations` root list contains all reachable `XValidatedModel` rules. Nested plain `BaseModel` remains valid.
- `x.path` is rooted at the model declaring the rule. Model-local rules can reference same-model fields and descendants only; they cannot walk to parent/root data.
- Validation pure inputs: exported schema plus canonical dumped JSON instance.
- Internal/external parity required for pass/fail and failing paths. Message text non-contractual.
- Exported-schema errors raise `ExportedSchemaError` subclasses. User data failures raise `XValidationError`.
- Public runtime entrypoint is `xvalidate(model: BaseModel, *, schema: dict[str, object] | None = None) -> None`.
- If `schema is None`, `model` must be an `XValidatedModel`; runtime exports schema from `type(model)`.
- If `schema` is provided, `model` may be any Pydantic `BaseModel`; this supports generated models from stripped schemas.
- `strip_xvalidations()` removes root `x-validations` and x-validation-owned generated `$defs`, but keeps Pydantic-owned `$defs`.
- Runtime validates base schema first, compiled x-validation schema second.
- Error issues expose `path`, `message`, `keyword`, `source`, and `rule_id`; `source` is `"base"` or `"x-validation"`.
- Validation never mutates model or instance JSON.
- No documentation-writing milestone. Do not add docs files or rewrite README as part of this plan.

## Product Assumptions

- Repo is doc-only now. First implementation must use the available uv package template.
- First MVP slice = README `Article.tags` / `primary_tag`.
- `xvalidations-codegen` belongs in v1 after core authoring/export/runtime works.
- CLI uses `typer`.
- JSONPath helper surface matches README/architecture. Equality filters land in first complete pass.
- `jsonpath-rfc9535` exposes `find(query, value)` and match nodes with `.value`, `.location`, `.path()`. Temp probe on 2026-04-30 confirmed `[?(@.kind == "field")]`.
- Code blocks in this plan are design sketches, not copy-paste patches. Implementation agents must adapt names/imports/types to local code while preserving behavior and tests.

## Milestone 1: Uv Package Bootstrap

Brief: create uv-managed flat Python package. No engine logic.

Tasks:

1. Start from available uv package template. Keep generated `pyproject.toml`; modify through `uv add`, not by copying TOML from this plan.

```bash
uv add pydantic jsonschema referencing jsonpath-rfc9535 typer
uv add --dev pytest ruff prek
uv add --optional codegen datamodel-code-generator
```

2. Create flat package tree.

```text
xvalidations/
  __init__.py
  artifact.py
  authoring.py
  codegen.py
  compiler.py
  errors.py
  jsonpath.py
  models.py
  pydantic.py
  resolve.py
  runtime.py
  target.py
tests/
  conftest.py
  test_dependency_probe.py
```

3. Initial public package export.

```text
initial __all__ contains:
[
    "ExportedSchemaError",
    "InvalidRuleError",
    "JsonPathError",
    "ResolveError",
    "ValidationIssue",
    "XValidationError",
    "XValidationRule",
]
```

4. Dependency probe test. Keep imports in test file, not in snippet.

```text
dependency probe test:
    data has two items: one kind="field" id="a", one kind="note" id="b"
    query '$.items[?(@.kind == "field")].id'
    assert one match:
        value == "a"
        location == ("items", 0, "id")
        normalized path == "$['items'][0]['id']"
```

Tests:

- `test_jsonpath_rfc9535_returns_value_location_and_normalized_path`
- `test_project_imports_public_symbols`
- `test_package_layout_has_no_src_directory`

Acceptance:

- `uv run pytest tests/test_dependency_probe.py`
- `uv run prek run -a`
- `python -c 'import xvalidations; print(xvalidations.__all__)'` works through `uv run`.
- No `src/` directory exists.

## Milestone 2: Models, Errors, Artifact Helpers

Brief: define stable data contracts and root schema helper behavior.

Tasks:

1. Implement `models.py`.

```text
JsonValue := recursive JSON-compatible type alias
InstanceLocation := tuple of property names and array indexes

XValidationRule:
    pydantic model with populate_by_name
    id: stable string
    description: human-readable string
    target: exported JSONPath string
    assert_: JSON value with alias "assert"

XValidationBundle:
    defs: dict from generated def name to JSON value
    rules: list of XValidationRule

ValidationIssue:
    path: canonical JSONPath to failing instance node
    message: validator message
    keyword: JSON Schema keyword or None
    source: "base" or "x-validation"
    rule_id: stable id when source is x-validation
```

2. Implement `errors.py`.

```text
ExportedSchemaError := base class for broken schema artifacts
InvalidRuleError := invalid root x-validations shape or invalid authored rule
JsonPathError := invalid RFC 9535 query
ResolveError := missing/invalid $resolve pointer or path

XValidationError:
    stores list[ValidationIssue] on .errors
    message includes count only; callers inspect .errors for details
```

3. Implement `artifact.py`.

```text
extract_xvalidations(schema):
    raw_rules = schema.get("x-validations", [])
    if raw_rules is None: return []
    if raw_rules is not list: raise InvalidRuleError
    parse every item through XValidationRule
    convert pydantic parsing failures to InvalidRuleError

strip_xvalidations(schema):
    deep-copy input
    parse rules from copy
    remove root x-validations key
    remove only $defs referenced by rule assert.$resolve "#/$defs/<name>"
    remove empty $defs
    return cleaned copy
```

4. Implement `$defs` ownership detection. Only defs reached by rule `$resolve` refs are removed.

```text
xvalidation_owned_defs(rules):
    walk each rule.assert recursively
    whenever node == {"$resolve": "#/$defs/<escaped-name>..."}:
        unescape first JSON Pointer token
        add def name to owned set
    ignore instance paths like "$.tags[*]"
```

Tests:

- `test_rule_accepts_assert_alias_and_dumps_assert_alias`
- `test_rule_rejects_missing_id_description_target_assert`
- `test_extract_xvalidations_missing_key_returns_empty_list`
- `test_extract_xvalidations_none_returns_empty_list`
- `test_extract_xvalidations_non_list_raises_invalid_rule_error`
- `test_strip_removes_root_xvalidations`
- `test_strip_removes_only_defs_referenced_by_rule_resolve`
- `test_strip_keeps_pydantic_defs_not_referenced_by_rule`
- `test_strip_handles_escaped_json_pointer_def_name`
- `test_xvalidation_error_exposes_errors_list`

Acceptance:

- `uv run pytest tests/test_models.py tests/test_artifact.py tests/test_errors.py`
- `uv run prek run -a`
- No mutation of input schema; compare original schema before/after `strip_xvalidations`.

## Milestone 3: Authoring DSL

Brief: owned path/filter AST, `$resolve` markers, decorator declarations. No Pydantic hook yet.

Tasks:

1. Implement path selectors.

```text
Selector variants:
    KeySelector(name)
    WildcardSelector()
    IndexSelector(index)
    SliceSelector(start=None, stop=None, step=None)
    FilterSelector(predicate)

Constructor helpers:
    key(name)
    wildcard()
    index_selector(index)
    slice_selector(start=None, stop=None, step=None)
    filter_selector(predicate)
```

2. Implement immutable `Path`.

```text
Path:
    immutable tuple of segments
    select(*selectors) appends child segment; rejects empty selectors
    desc(*selectors_or_names) appends recursive segment; rejects empty selectors
    each() -> wildcard selector
    at(index) -> index selector
    slice(start, stop, step) -> slice selector
    where(predicate) -> filter selector
    attribute access -> key selector
    bracket access -> key selector
    to_jsonpath() delegates to serializer
```

3. Implement serializer.

```text
path_to_jsonpath(path):
    start with "$"
    render child key `name` as `.name` when identifier-safe
    render unsafe key with JSON string brackets, e.g. `$["field-id"]`
    render union selectors as `$["a","b"]`
    render wildcard as `[*]`
    render slice step as `[start:stop:step]`
    render recursive key shortcut as `$..field_id`
    render filters as `[?(<predicate>)]`
```

4. Implement predicate AST for equality filters.

```text
Expr:
    immutable relative path rooted at "@"
    attribute access appends child key
    == returns Comparison(expr, "==", json_scalar)
    != returns Comparison(expr, "!=", json_scalar)

predicate_to_jsonpath(x.this.kind == "field") -> '@.kind == "field"'
reject list/dict/object right-hand values
```

5. Implement context, decorator, markers.

```text
XValidationContext exposes:
    path, this, key, wildcard, index, slice, filter
    target(path_object) -> RuleBuilder
    resolve(path_object_or_json_constant) -> ResolveMarker

RuleBuilder.assert_schema(schema_json) -> authored rule data

xvalidation(id, description):
    stores declaration metadata on decorated function
    function body is schema annotation factory, not runtime validator
```

Tests:

- `test_path_shortcuts_serialize_to_jsonpath`, parameterized ids: `attr`, `bracket`, `each`, `index`, `slice`, `desc`
- `test_selector_union_serializes_as_bracket_list`
- `test_filter_equality_serializes_to_rfc9535`
- `test_filter_inequality_serializes_to_rfc9535`
- `test_filter_rejects_non_json_scalar_rhs`
- `test_select_without_selectors_raises_type_error`
- `test_desc_without_selectors_raises_type_error`
- `test_target_rejects_raw_jsonpath_string`
- `test_resolve_rejects_raw_jsonpath_string`
- `test_resolve_allows_plain_non_path_string_constant`
- `test_xvalidation_attaches_rule_declaration_to_function`
- `test_paths_are_immutable_after_chaining`

Acceptance:

- Expected serializations:
    - `x.path.primary_tag` -> `$.primary_tag`
    - `x.path["primary-tag"]` -> `$["primary-tag"]`
    - `x.path.tags.each()` -> `$.tags[*]`
    - `x.path.tags.at(0)` -> `$.tags[0]`
    - `x.path.tags.slice(0, 10, 2)` -> `$.tags[0:10:2]`
    - `x.path.desc("field_id")` -> `$..field_id`
    - `x.path.items.where(x.this.kind == "field").id` -> `$.items[?(@.kind == "field")].id`
- `uv run pytest tests/test_authoring.py`
- `uv run prek run -a`

## Milestone 4: Pydantic Export

Brief: collect decorators, generate root `x-validations`, deterministic `$defs`, nested rebasing.

Tasks:

1. Implement `XValidatedModel`.

```text
XValidatedModel:
    subclasses BaseModel
    on subclass creation, collect decorated rule declarations from class dict
    model_json_schema defaults by_alias=True
    base schema must come from BaseModel implementation to avoid recursion
    return export_schema(cls, base_schema=base, by_alias=by_alias)
```

2. Implement `export_schema`.

```text
export_schema(model_cls, base_schema=None, by_alias=True):
    copy supplied base schema or build pydantic base schema
    walk every reachable XValidatedModel with root prefix path
    execute each rule factory with XValidationContext
    compile authored local rule into root XValidationRule
    merge generated constant defs into root $defs
    write root x-validations only when rules exist
    return copied schema; never mutate caller object
```

3. Implement deterministic constant defs.

```text
definition_name(value):
    JSON dump with stable key order and compact separators
    hash content
    return "xv_" plus short deterministic hex digest

replace_markers(node, prefix, defs):
    ResolveMarker(Path) -> {"$resolve": joined(prefix, path).to_jsonpath()}
    ResolveMarker(JSON constant) -> lift constant into defs and return {"$resolve": "#/$defs/<name>"}
    dict/list -> recursive replacement
    scalar -> unchanged
```

4. Implement graph traversal.

```text
iter_xvalidated_models(root, by_alias):
    depth-first walk pydantic model fields
    emit (prefix, model_cls) for every reachable XValidatedModel
    include root at prefix "$" when root is XValidatedModel
    list[T] adds wildcard suffix
    union/discriminated union visits each model alternative
    field alias determines exported path when by_alias=True
    seen key includes model class plus prefix to avoid cycles
```

Tests:

- `test_article_export_matches_readme_contract`
- `test_model_without_rules_has_no_xvalidations_key`
- `test_constant_resolve_lifted_to_xv_def`
- `test_identical_constants_dedupe_to_same_def`
- `test_different_constants_get_different_defs`
- `test_literals_not_wrapped_in_resolve_stay_inline`
- `test_nested_xvalidated_model_rule_rebased_to_root`
- `test_nested_plain_basemodel_does_not_need_xvalidatedmodel`
- `test_alias_export_uses_alias_in_target_and_resolve`
- `test_duplicate_rule_ids_raise_invalid_rule_error`
- `test_rule_factory_returning_non_rule_builder_raises_invalid_rule_error`
- `test_export_does_not_mutate_base_schema_argument`

Acceptance:

- README Article export equals:

```json
{
    "id": "primary-tag-exists",
    "description": "Primary tag must be present in tags.",
    "target": "$.primary_tag",
    "assert": {
        "enum": {
            "$resolve": "$.tags[*]"
        }
    }
}
```

- Nested `items: list[Child]` rule target rebases to `$.items[*]...`.
- Nested local `$resolve` rebases to same prefix as target.
- Duplicate rule ids in one exported schema raise `InvalidRuleError`.
- `uv run pytest tests/test_pydantic_export.py`
- `uv run prek run -a`

## Milestone 5: Meta-Schema Compiler

Brief: evaluate targets, resolve placeholders, lower concrete locations to standard JSON Schema overlays.

Tasks:

1. Implement JSONPath adapter.

```text
JsonPathMatch:
    value from matched node
    location tuple from jsonpath-rfc9535 node.location
    normalized_path from node.path()

evaluate_jsonpath(query, value):
    call jsonpath-rfc9535 find()
    convert parser/evaluator exceptions to JsonPathError
    dedupe identical locations while preserving first-seen order
    return list[JsonPathMatch]
```

2. Implement placeholder resolution.

```text
resolve_placeholders(node, instance_json, base_schema):
    if node is exactly {"$resolve": ref}:
        require ref is string
        replace with resolve_ref(ref)
    if dict/list:
        recursively resolve children
    else:
        return scalar unchanged
```

3. Implement ref resolution.

```text
resolve_ref(ref):
    "$..." -> evaluate JSONPath against canonical instance; return list of matched values
    "#/..." -> evaluate JSON Pointer against exported schema; return pointed JSON value
    anything else -> ResolveError
```

4. Implement location overlay.

```text
location_to_schema_overlay(location, assertion):
    empty location -> assertion applies at root
    string segment -> object schema with properties[segment] = child overlay
    int segment -> array schema with minItems and prefixItems placing child at index
    untouched siblings use boolean true in prefixItems
```

5. Implement compiled schema generation.

```text
generate_compiled_schema(base_schema, instance_json):
    overlays = []
    branch_rule_ids = []
    for each extracted rule:
        resolve rule.assert once against instance/schema
        evaluate rule.target against instance
        for each target match:
            append location overlay to overlays
            append rule.id to branch_rule_ids at same index
    compiled = draft-2020-12 schema with allOf overlays
    check compiled schema validity
    return compiled schema plus branch_rule_ids
```

Tests:

- `test_evaluate_jsonpath_returns_deduped_locations_in_order`
- `test_evaluate_jsonpath_invalid_syntax_raises_jsonpath_error`
- `test_resolve_instance_jsonpath_returns_values_list`
- `test_resolve_schema_pointer_returns_def_value`
- `test_resolve_missing_schema_pointer_raises_resolve_error`
- `test_resolve_invalid_prefix_raises_resolve_error`
- `test_resolve_non_string_resolve_value_raises_resolve_error`
- `test_location_overlay_object_property`
- `test_location_overlay_array_index_uses_prefix_items_and_min_items`
- `test_location_overlay_nested_array_object_path`
- `test_generate_compiled_schema_has_no_resolve`
- `test_generate_compiled_schema_rule_ids_match_allof_branches`
- `test_generated_compiled_schema_passes_draft_2020_12_check`

Acceptance:

- Compiled schema for valid Article instance validates with zero errors.
- Compiled schema for invalid Article instance produces one error at `$.primary_tag`.
- `"$resolve"` absent from `json.dumps(compiled.schema)`.
- Invalid exported-schema inputs raise `ExportedSchemaError` subclasses before user-data `XValidationError`.
- `uv run pytest tests/test_jsonpath.py tests/test_resolve.py tests/test_target.py tests/test_compiler.py`
- `uv run prek run -a`

## Milestone 6: Runtime Validation

Brief: expose `xvalidate(model, schema=None)` and normalize JSON Schema errors.

Tasks:

1. Implement runtime API.

```text
xvalidate(model, schema=None):
    require model is pydantic BaseModel
    if schema missing:
        require model is XValidatedModel
        export schema from model class
    dump canonical JSON with:
        mode="json"
        by_alias=True
        exclude_unset/defaults/none=False
    validate stripped base schema
    compile and validate x-validation schema
    return None on success
```

2. Implement base and compiled validation split.

```text
validate_base_schema(schema, instance_json):
    strip x-validations
    run Draft202012Validator.iter_errors
    on errors -> XValidationError with source="base", rule_id=None

validate_compiled_schema(schema, instance_json):
    generate compiled schema
    run Draft202012Validator.iter_errors
    on errors -> XValidationError with source="x-validation"
    map allOf branch index to compiled.branch_rule_ids
```

3. Implement issue mapping.

```text
issues_from_errors(errors, source, branch_rule_ids):
    sort by absolute instance path
    convert deque path segments to canonical JSONPath string
    keyword = error.validator when string
    source = supplied source
    rule_id = None for base errors
    rule_id = branch_rule_ids[allOf_index] for x-validation errors when available
```

Tests:

- `test_xvalidate_internal_article_passes`
- `test_xvalidate_internal_article_fails_with_rule_id_and_path`
- `test_xvalidate_external_generated_article_matches_internal_failure`
- `test_xvalidate_external_generated_article_passes`
- `test_xvalidate_plain_basemodel_without_schema_raises_type_error`
- `test_xvalidate_non_model_raises_type_error`
- `test_base_schema_failure_source_base_rule_id_none`
- `test_xvalidation_failure_source_xvalidation_rule_id_present`
- `test_error_paths_are_sorted_deterministically`
- `test_runtime_does_not_mutate_model_or_schema`
- `test_runtime_uses_alias_dump_for_alias_model`
- `test_pydantic_model_validate_errors_are_not_caught_by_xvalidate`

Acceptance:

- Internal and external Article failures both report `("$.primary_tag", "primary-tag-exists", "x-validation")`.
- Base schema failure reports `source="base"` and `rule_id is None`.
- `xvalidate()` returns `None` on success.
- `uv run pytest tests/test_runtime.py`
- `uv run prek run -a`

## Milestone 7: Typer Codegen CLI

Brief: provide `xvalidations-codegen --input schema.json --output model.py` using Typer.

Tasks:

1. Add Typer-powered command in `codegen.py`.

```text
Typer command:
    options: --input existing JSON schema file, --output model.py path
    load full schema JSON
    strip x-validation metadata into temp schema file
    invoke datamodel-codegen with JSON Schema input and pydantic_v2.BaseModel output
    preserve subprocess exit code on failure
    main() calls typer.run(command_function)
```

2. Add script entrypoint through uv project config/template, not by embedding config in this plan.

```text
xvalidations-codegen -> xvalidations.codegen:main
```

3. Keep stripped schema temp file private and deterministic.

```text
stripped_schema_text(schema):
    strip_xvalidations(schema)
    dump JSON with stable key ordering and compact separators

codegen_command(schema_path, output_path):
    return datamodel-codegen argv using:
        --input <temp schema>
        --input-file-type jsonschema
        --output <output path>
        --output-model-type pydantic_v2.BaseModel
```

Tests:

- `test_typer_cli_help_lists_input_and_output`
- `test_codegen_strips_xvalidations_before_invoking_datamodel_codegen`
- `test_codegen_invokes_datamodel_codegen_with_pydantic_v2_output`
- `test_codegen_missing_datamodel_codegen_exits_nonzero`
- `test_codegen_invalid_input_json_exits_nonzero`
- `test_generated_plain_model_validates_with_xvalidate_external_schema`

Acceptance:

- `uv run xvalidations-codegen --help` exits 0 and shows `--input` and `--output`.
- `uv run xvalidations-codegen --input article.schema.json --output generated_article.py` writes plain Pydantic v2 model.
- Generated model contains no `x-validations` text.
- Generated model can run through `xvalidate(model, schema=full_schema)`.
- `uv run pytest tests/test_codegen.py`
- `uv run prek run -a`

## Milestone 8: Correctness Matrix

Brief: cover architecture requirements across fixtures. No documentation writes.

Tasks:

1. Add shared Article fixtures in `tests/conftest.py`: `Article`, `GeneratedArticle`, `article_schema`, `good_article_payload`, `bad_article_payload`.

```text
Article fixture sketch:
    XValidatedModel with fields:
        tags: list of strings
        primary_tag: string
    rule id: primary-tag-exists
    target: x.path.primary_tag
    assertion: enum resolves from x.path.tags.each()
```

2. Add nested rebasing fixture.

```text
Section fixture sketch:
    FieldWidget plain model has kind and field_id
    Section XValidatedModel has fields and widgets
    rule id: section-widget-field-exists
    target: widgets where kind == "field", then field_id
    assertion: enum resolves from fields.each()
```

3. Add static-rule separation fixture.

```text
StaticArticle fixture sketch:
    XValidatedModel with tags constrained by Pydantic min_length=1
    primary_tag is plain string
    no xvalidation decorator
```

4. Add contract tests by architecture requirement.

Tests:

- `test_exported_schema_validity_for_all_fixtures`
- `test_compiled_schemas_contain_no_resolve_for_all_fixtures`
- `test_compiled_schemas_are_valid_draft_2020_12_for_all_fixtures`
- `test_full_jsonpath_target_filter_selects_only_matching_nodes`
- `test_path_based_parity_internal_external_article`
- `test_path_based_parity_nested_form`
- `test_local_rule_rebasing_exports_once_per_reachable_root_path`
- `test_local_rule_cannot_reference_parent_path`
- `test_automatic_defs_deduplicate_constants`
- `test_unused_constants_are_not_exported`
- `test_static_rule_separation_keeps_min_length_in_base_schema`
- `test_each_example_rule_has_positive_and_negative_fixture`
- `test_exported_schema_errors_are_not_xvalidation_errors`
- `test_validation_never_mutates_input_model`

Acceptance:

- Every fixture has one pass payload and one fail payload.
- Internal/external parity asserted on pass/fail and failing paths, not messages.
- Nested rule target equals `$.sections[*].widgets[?(@.kind == "field")].field_id`.
- Nested rule `$resolve` equals `$.sections[*].fields[*]`.
- Static `Field(min_length=1)` emits base schema constraint and no x-validation rule.
- `uv run pytest`
- `uv run prek run -a`

## Milestone 9: Final Verification

Brief: prove package is ready for first v1 implementation merge. No docs.

Tasks:

1. Verify public API surface.

```text
public API expected __all__ set:
    {
        "ExportedSchemaError",
        "InvalidRuleError",
        "JsonPathError",
        "ResolveError",
        "ValidationIssue",
        "XValidatedModel",
        "XValidationContext",
        "XValidationError",
        "XValidationRule",
        "export_schema",
        "xvalidate",
        "xvalidation",
    }
```

2. Verify fresh install flow.

```bash
uv sync --all-extras
uv run pytest
uv run prek run -a
uv run xvalidations-codegen --help
```

3. Verify no forbidden architecture regressions.

```bash
grep -R "kind.*executor\\|jsonpath-ng\\|autofix\\|migration engine" xvalidations tests
test ! -d src
```

Acceptance:

- All tests pass from clean uv sync.
- Pre-commit via `prek` passes.
- CLI help works.
- No `src/` layout.
- No docs files are added or edited by this plan.
- Plan remains self-contained for implementation using `README.md` and `plans/ARCHITECTURE.md` as anchors.
