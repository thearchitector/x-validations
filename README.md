# x-validations

Portable cross-field validation rules for a trusted Pydantic and JSON Schema
ecosystem.

## Install

```bash
uv add xvalidations
```

The complementary validation engine is published as `xvalidate` on PyPI and
npm.

## Trusted-input contract

x-validations is a happy-path system for schemas and rules authored by trusted
code. It validates payloads; it does not certify schemas, diagnose authoring
mistakes, or protect against adversarial inputs.

Before calling the library, ensure that:

- the schema is a self-contained JSON Schema 2020-12 schema accepted by the
  upstream compiler;
- the x-validations dialect URI and root `x-validations` array use the current
  wire format;
- extension rules occur only on the root schema resource and have unique IDs;
- targets and `$path` operands are valid, unambiguous JSONPaths with the
  cardinality and JSON types expected by their assertions;
- interpolated assertions are valid JSON Schema 2020-12 schemas compatible
  with every selected target;
- Python and JavaScript values are finite, acyclic, JSON-compatible values
  handled losslessly by the runtime converters.

Nested extension resources, malformed or untrusted schemas, ambiguous model
layouts, incompatible assertions, invalid paths, exotic host values, and
resource exhaustion are unsupported. Their errors and behavior are not stable.

## Author a root rule

Use an ordinary Pydantic model. A rule target is an RFC 9535 JSONPath, and a
`Path` used in its assertion becomes a runtime `$path` operand.

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


schema = Article.model_json_schema()
```

Validation-mode export asks Pydantic for the root schema, executes declarations
applicable to that root model, serializes their paths, and adds the root
`$schema`, `$id`, and `x-validations` fields. Pydantic's `$defs` and
`$ref` structure is left intact. Serialization-mode and rule-free schemas
remain ordinary Pydantic output.

Rules on a nested model are not discovered when its parent is exported. Put the
applicable rule on the root model and target nested data from the root:

```python
class Order(BaseModel):
    maximum_line_price: int
    lines: list[Line]

    @xvalidation(id="line-price-limit")
    @classmethod
    def line_price_limit(cls, x: XValidationContext) -> ValidationRule:
        return x.target(x.path.lines.each().price).assert_schema({
            "maximum": x.path.maximum_line_price
        })
```

Inheritance follows normal Python method resolution when it yields one
unambiguous declaration. The existing `override` decorator argument remains
accepted, but x-validations does not validate override consistency or
collisions.

## Validate a payload

```python
from xvalidate import XValidationError, xvalidate

try:
    xvalidate(payload, schema)
except XValidationError as error:
    assert error.errors[0].rule_id == "primary-tag-exists"
    assert error.errors[0].path == "$.primary_tag"
```

`xvalidate(payload, schema)` validates the ordinary base schema first. If the
payload passes and the root declares the x-validations dialect, it evaluates
root rules in declaration order. Success returns `None`; payload failures
raise the existing validation error type. Only payload validation failures have
a supported error contract.

For an ordinary schema whose root does not declare the x-validations URI, the
runtime performs normal JSON Schema validation and does not search for nested
extension declarations.

## Path operands

Cardinality comes from JSONPath syntax:

- name and index selectors are singular and interpolate the selected value;
- wildcards, slices, filters, selector lists, and recursive descent interpolate
  an array of all matches;
- separate paths are evaluated independently and are not zipped or correlated.

These cardinality rules are preconditions. A missing scalar operand or an
otherwise malformed dynamic assertion has unspecified behavior.

## `x-uniqueBy`

`x-uniqueBy` retains its current singleton assertion form:

```python
return x.target(x.path.fields).assert_schema({"x-uniqueBy": "$.field_id"})
```

The target must be an array and the projection must select exactly one
JSON-comparable value from every element. Duplicate failures are attributed to
the duplicate item paths. Violating these preconditions is unsupported.

## Path helpers

| Helper                          | Example                                     | JSONPath                         |
| ------------------------------- | ------------------------------------------- | -------------------------------- |
| Attribute or bracket key        | `x.path.primary_tag`, `x.path["field-id"]`  | `$.primary_tag`, `$["field-id"]` |
| `.each()` / `x.wildcard()`      | `x.path.tags.each()`                        | `$.tags[*]`                      |
| `.at(index)` / `x.index(index)` | `x.path.tags.at(0)`                         | `$.tags[0]`                      |
| `.slice(...)` / `x.slice(...)`  | `x.path.tags.slice(0, 10)`                  | `$.tags[0:10]`                   |
| `.where(...)` / `x.filter(...)` | `x.path.items.where(x.this.kind == "text")` | `$.items[?(@.kind == "text")]`   |
| `.select(*selectors)`           | `x.path.select(x.key("a"), x.key("b"))`     | `$["a","b"]`                     |
| `.desc(...)`                    | `x.path.desc("field_id")`                   | `$..field_id`                    |
