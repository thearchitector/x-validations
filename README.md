<!-- pragma: no ai -->
# x-validations

Supplemental validators in your Pydantic models for better self-describing JSON schemas.

## Example Usage

### 1. Add a validation rule

Start with a normal Pydantic model, then add an `@xvalidation` rule for checks that involve more than one field.

```python
from xvalidations import XValidatedModel, XValidationContext, xvalidation


class Article(XValidatedModel):
    tags: list[str]
    primary_tag: str

    @xvalidation(
        id="primary-tag-exists",
        description="Primary tag must be present in tags.",
    )
    def primary_tag_exists(x: XValidationContext):
        return x.target(x.path.primary_tag).assert_schema(
            {"enum": x.resolve(x.path.tags.each())}
        )
```

### 2. Export the schema

Export the model schema when you want to share the contract with another service or generate a standalone model.

```python
schema = Article.model_json_schema()
```

The exported schema includes your validation rule:

```json
{
  "properties": {
    "tags": {
      "items": {
        "type": "string"
      },
      "title": "Tags",
      "type": "array"
    },
    "primary_tag": {
      "title": "Primary Tag",
      "type": "string"
    }
  },
  "x-validations": [
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
  ]
}
```

### 3. Generate a model from the schema

In external systems, generate a plain Pydantic model from the exported schema:

```bash
xvalidations-codegen --input article.schema.json --output generated_article.py
```

### 4. Validate data

Parse with the generated model, then run the schema's x-validations.

```python
from generated_article import Article as GeneratedArticle
from xvalidations import XValidationError, xvalidate


model = GeneratedArticle.model_validate(payload)

try:
    xvalidate(model, schema=schema)
except XValidationError as exc:
    assert exc.errors[0].source == "x-validation"
    assert exc.errors[0].rule_id == "primary-tag-exists"
    assert exc.errors[0].path == "$.primary_tag"
```

## `x.path` Reference

Use these helpers inside `x.target(...)` and `x.resolve(...)`.

| Helper | Meaning | Example | Exported JSONPath |
| --- | --- | --- | --- |
| `x.key(name)` | Object member selector. | `x.path.select(x.key("field-id"))` | `$["field-id"]` |
| `x.wildcard()` | Wildcard selector for child values. | `x.path.tags.select(x.wildcard())` | `$.tags[*]` |
| `x.index(index)` | Array index selector. | `x.path.tags.select(x.index(0))` | `$.tags[0]` |
| `x.slice(start=None, stop=None, step=None)` | Array slice selector. | `x.path.tags.select(x.slice(0, 10))` | `$.tags[0:10]` |
| `x.filter(predicate)` | Filter selector rooted at `x.this`. | `x.path.items.select(x.filter(x.this.kind == "text"))` | `$.items[?(@.kind == "text")]` |
| `.select(*selectors)` | Child segment, including selector lists. | `x.path.select(x.key("a"), x.key("b"))` | `$["a","b"]` |
| `.desc(*selectors)` | Recursive descent segment. | `x.path.desc(x.key("field_id"))` | `$..field_id` |
| Attribute access | Shorthand for `.select(x.key(name))`. | `x.path.primary_tag` | `$.primary_tag` |
| Bracket access | Shorthand for `.select(x.key(name))`. | `x.path["primary-tag"]` | `$["primary-tag"]` |
| `.each()` | Shorthand for `.select(x.wildcard())`. | `x.path.tags.each()` | `$.tags[*]` |
| `.at(index)` | Shorthand for `.select(x.index(index))`. | `x.path.tags.at(0)` | `$.tags[0]` |
| `.slice(...)` | Shorthand for `.select(x.slice(...))`. | `x.path.tags.slice(0, 10)` | `$.tags[0:10]` |
| `.where(predicate)` | Shorthand for `.select(x.filter(predicate))`. | `x.path.items.where(x.this.kind == "text")` | `$.items[?(@.kind == "text")]` |
| `.desc(name)` | Shorthand for `.desc(x.key(name))`. | `x.path.desc("field_id")` | `$..field_id` |
