use std::sync::LazyLock;

use serde_json::Value;

pub(crate) const DRAFT202012_SCHEMA_URI: &str = "https://json-schema.org/draft/2020-12/schema";
pub(crate) const XVALIDATIONS_SCHEMA_URI: &str =
    "https://thearchitector.dev/xvalidations/schema.json";

pub(crate) static XVALIDATIONS_META_SCHEMA: LazyLock<Value> = LazyLock::new(|| {
    serde_json::from_str(include_str!("meta-schema.json"))
        .expect("bundled x-validations meta-schema must be valid JSON")
});

pub(crate) static XVALIDATIONS_META_VALIDATOR: LazyLock<jsonschema::Validator> =
    LazyLock::new(|| {
        jsonschema::validator_for(&XVALIDATIONS_META_SCHEMA)
            .expect("bundled x-validations meta-schema must compile")
    });

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::{XVALIDATIONS_META_SCHEMA, XVALIDATIONS_META_VALIDATOR, XVALIDATIONS_SCHEMA_URI};

    #[test]
    fn bundled_meta_schema_cache_is_a_crate_invariant() {
        assert_eq!(XVALIDATIONS_META_SCHEMA["$id"], XVALIDATIONS_SCHEMA_URI);
        assert!(XVALIDATIONS_META_VALIDATOR.is_valid(&json!({
            "$schema": XVALIDATIONS_SCHEMA_URI,
            "type": "object",
            "x-validations": []
        })));
        assert!(!XVALIDATIONS_META_VALIDATOR.is_valid(&json!({
            "$schema": XVALIDATIONS_SCHEMA_URI,
            "x-validations": [],
            "x-constants": {}
        })));
        assert!(!XVALIDATIONS_META_VALIDATOR.is_valid(&json!({
            "$schema": XVALIDATIONS_SCHEMA_URI,
            "type": "object"
        })));
        assert!(!XVALIDATIONS_META_VALIDATOR.is_valid(&json!({
            "$id": "urn:test:invalid-resource",
            "$schema": XVALIDATIONS_SCHEMA_URI,
            "x-validations": [{"id": "missing-fields"}]
        })));
    }
}
