# x-validations

Portable cross-field validation rules authored on Pydantic models and exported as self-describing JSON Schema resources.

## Install

```bash
uv add xvalidations
```

The complementary validation engine is published as `xvalidate` on PyPI and npm.

## Author a rule

Use an ordinary Pydantic model. A rule target is an RFC 9535 JSONPath, and a `Path` used anywhere in its assertion becomes a runtime `$path` operand.

```python
from pydantic import BaseModel
from xvalidations import ValidationRule, XValidationContext, xvalidation


class Article(BaseModel):
    tags: list[str]
    primary_tag: str

    @xvalidation(
        id="primary-tag-exists", description="Primary tag must be present in tags."
    )
    @classmethod
    def primary_tag_exists(cls, x: XValidationContext) -> ValidationRule:
        return x.target(x.path.primary_tag).assert_schema({"enum": x.path.tags.each()})
```

Exporting a validation-mode schema runs every effective rule factory and produces a deterministic resource:

```python
schema = Article.model_json_schema()
```

```json
{
  "$id": "urn:xvalidations:example.Article:<sha256>",
  "$schema": "https://thearchitector.dev/xvalidations/schema.json",
  "properties": {
    "tags": {"items": {"type": "string"}, "type": "array"},
    "primary_tag": {"type": "string"}
  },
  "x-validations": [
    {
      "id": "primary-tag-exists",
      "description": "Primary tag must be present in tags.",
      "target": "$.primary_tag",
      "assert": {"enum": {"$path": "$.tags[*]"}}
    }
  ]
}
```

Literals stay inline. The authoring library never emits `x-constants`, and the contract rejects both legacy `x-constants` resources and `$resolve` markers.

Serialization-mode schemas are unchanged. Rule-free models also retain ordinary Pydantic schema behavior.

## Validate a payload

```python
from xvalidate import XValidationError, xvalidate

try:
    xvalidate(payload, schema)
except XValidationError as error:
    assert error.errors[0].rule_id == "primary-tag-exists"
    assert error.errors[0].path == "$.primary_tag"
```

The engine validates the ordinary base schema first. It evaluates rules only for successful resource occurrences, attributes failures to selected targets, and reports error paths from the complete payload root.

## Path cardinality

Cardinality comes from JSONPath syntax, not the Pydantic field type.

- A path made only of name and index selectors is singular. `$.limits.upper` interpolates the selected JSON value.
- Wildcards, slices, filters, selector lists, and recursive descent are non-singular. `$.tags[*]` interpolates an array containing every match, including an empty array.
- A missing singular operand cannot produce a value. If a rule selected targets, assertion construction fails those targets.
- Paths are evaluated independently. The engine does not zip, pair, or infer correlation between two result sets.

For example, a dynamic numeric bound uses a singular operand:

```python
return x.target(x.path.value).assert_schema({"maximum": x.path.upper})
```

## Resource-local evaluation

Every ruled model is an independent Schema Resource. Its target and operand paths start from the current instance of that model, even when the resource is nested, recursive, or referenced more than once.

This establishes the correlation boundary. If a child rule must correlate `value` with `allowed`, both fields belong on the child model. A child rule cannot reach into its parent resource.

## Assertion compatibility

During validation-schema export, the authoring library uses Pydantic's generated schema to locate target and operand fragments. Compatibility is existential across `anyOf` and `oneOf` branches:

- `int | str` may be targeted by `maximum` through its integer branch.
- An operand `int | str` may supply `maximum` through its integer branch.
- A path that exists in at least one union branch is valid; a path unreachable in every branch is rejected.
- Compatibility is derived only from explicit `type` declarations on the schema or through `allOf`, `anyOf`, and `oneOf`; keyword-based type inference is not used.
- Contradictory `allOf` type declarations are rejected, as are schema forms whose possible JSON types cannot be determined.

Runtime behavior remains ordinary Draft 2020-12 behavior after interpolation. A valid `maximum`, for example, is inapplicable to a string target. If interpolation instead creates an invalid schema—such as a string-valued `maximum`—the rule fails each selected target.

## Assertion-only vocabulary

Rule assertions support Draft 2020-12 validation keywords, `allOf`, `anyOf`, `oneOf`, `not`, `if`/`then`/`else`, `contains`, and the singleton `x-uniqueBy` assertion.

`x-uniqueBy` targets an array and applies its JSONPath projection to each array item. Duplicate failures are attributed to the duplicate item paths. A bare `type` keyword does not qualify as a root rule assertion; express ordinary type constraints on the Pydantic field.

Assertions deliberately exclude structural traversal (`properties`, `items`, and related keywords), references and definitions, annotations, and resource keywords. Put ordinary structural constraints on Pydantic fields. A rule must contain at least one `Path` or be an `x-uniqueBy` assertion; wholly static rules are rejected for the same reason.

The exact singleton object `{"$path": "..."}` is reserved contract syntax. Payload data selected by a path is returned opaquely, so marker-looking selected data is not interpreted a second time.

## Inheritance and hooks

Inherited rule methods remain effective. Replacing one requires an explicit marker:

```python
from typing import override


class Specialized(BaseArticle):
    @xvalidation(id="specialized")
    @classmethod
    @override
    def primary_tag_exists(cls, x: XValidationContext) -> ValidationRule:
        return x.target(x.path.primary_tag).assert_schema({"enum": x.path.tags.each()})
```

A class-local `__get_pydantic_json_schema__` hook is composed once. A subclass that overrides that hook must delegate with `super()` so inherited X-Validations behavior runs.

## Path helpers

| Helper | Example | JSONPath |
| --- | --- | --- |
| Attribute or bracket key | `x.path.primary_tag`, `x.path["field-id"]` | `$.primary_tag`, `$["field-id"]` |
| `.each()` / `x.wildcard()` | `x.path.tags.each()` | `$.tags[*]` |
| `.at(index)` / `x.index(index)` | `x.path.tags.at(0)` | `$.tags[0]` |
| `.slice(...)` / `x.slice(...)` | `x.path.tags.slice(0, 10)` | `$.tags[0:10]` |
| `.where(...)` / `x.filter(...)` | `x.path.items.where(x.this.kind == "text")` | `$.items[?(@.kind == "text")]` |
| `.select(*selectors)` | `x.path.select(x.key("a"), x.key("b"))` | `$["a","b"]` |
| `.desc(...)` | `x.path.desc("field_id")` | `$..field_id` |
