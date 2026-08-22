# xvalidate

Native Python runtime bindings for x-validations schemas.

Install this package directly when you only need runtime validation:

```bash
pip install xvalidate
```

The module exports `xvalidate.xvalidate` plus structured exception types such as
`xvalidate.XValidationError`.

```python
from xvalidate import XValidationError, xvalidate

try:
    xvalidate(payload, schema)
except XValidationError as error:
    first = error.errors[0]
    print(first.path, first.rule_id, first.keyword)
```

Each item in `error.errors` is a `ValidationError` propagated directly from the
Rust Validation Engine.
