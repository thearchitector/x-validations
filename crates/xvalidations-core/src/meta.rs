use std::sync::LazyLock;

use serde_json::Value;

pub(crate) const DRAFT202012_SCHEMA_URI: &str = "https://json-schema.org/draft/2020-12/schema";

pub(crate) static XVALIDATIONS_META_SCHEMA: LazyLock<Value> = LazyLock::new(|| {
    serde_json::from_str(include_str!("meta/x-validations.schema.json"))
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

    use super::{XVALIDATIONS_META_SCHEMA, XVALIDATIONS_META_VALIDATOR};

    #[test]
    fn bundled_meta_schema_cache_is_a_repository_invariant() {
        assert_eq!(
            XVALIDATIONS_META_SCHEMA["$id"],
            "https://thearchitector.dev/xvalidations/meta/x-validations.schema.json"
        );
        assert!(XVALIDATIONS_META_VALIDATOR.is_valid(&json!({
            "$schema": "https://thearchitector.dev/xvalidations/meta/x-validations.schema.json",
            "type": "object"
        })));
    }
}
