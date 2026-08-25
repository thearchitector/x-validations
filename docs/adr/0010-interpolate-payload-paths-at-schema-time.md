# Replace resolve with schema-checked path interpolation

`$path` supersedes `$resolve` as the X-Validations Contract primitive. A `$path` marker is an exact singleton object containing an RFC 9535 JSONPath evaluated from the current Schema Resource instance. Singular syntax yields its selected value; non-singular syntax yields an array of all matches, including an empty array. Independent paths have set semantics and are never implicitly paired. Values returned from the payload are opaque and are not scanned again for markers.

The Authoring Library accepts `Path` recursively inside Rule Assertions, validates generated-schema compatibility during each validation-mode export, and renders the marker. JSON literals remain inline. The Contract and Validation Engine hard-reject legacy `$resolve` and `x-constants`, do not resolve schema pointers, and preserve `x-uniqueBy`.

## Consequences

For every matched rule, the Validation Engine interpolates operands and compiles the concrete assertion with ordinary Draft 2020-12 behavior. Invalid concrete assertions become rule failures attributed to selected targets; unmatched targets skip assertion construction. Valid keywords retain native applicability, so a numeric keyword remains inapplicable to a string target. This is a pre-1.0 hard cutover with no compatibility reader.
