# xvalidate

WASM runtime bindings for x-validations schemas.

The npm package is named `xvalidate`:

```js
import { xvalidate } from "xvalidate";

try {
  xvalidate(payload, schema);
} catch (error) {
  console.log(error.errors[0].path, error.errors[0].rule_id);
}
```

Build the JavaScript package with:

```bash
wasm-pack build crates/xvalidate-js --target bundler
```
