# Publish Runtime Wrappers as xvalidate

Both the Python and JavaScript Runtime Wrappers are published as `xvalidate`, and the Python module is imported with the same name. PyPI and npm have separate namespaces, so a shared public name gives the same installation and import vocabulary in both ecosystems; internal Cargo package names remain distinct where the workspace requires uniqueness.

## Consequences

The abandoned `xvalidate` npm package was unpublished in 2023, so ownership or reuse of that unscoped name must be confirmed before the first JavaScript release. If npm will not release it, choosing a scoped package is a new naming decision rather than silently restoring a language suffix.
