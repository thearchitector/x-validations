use pretty_assertions::assert_eq;
use serde_json::{json, Value};
use xvalidations_core::{xvalidate, XValidationFailure};

const XVALIDATIONS_SCHEMA_URI: &str = "https://thearchitector.dev/xvalidations/schema.json";

fn article_schema() -> Value {
    json!({
        "$id": "urn:test:article",
        "$schema": XVALIDATIONS_SCHEMA_URI,
        "type": "object",
        "required": ["tags", "primary_tag"],
        "properties": {
            "tags": {"type": "array", "items": {"type": "string"}},
            "primary_tag": {"type": "string"}
        },
        "x-validations": [
            {
                "id": "primary-tag-exists",
                "description": "Primary tag must be present in tags.",
                "target": "$.primary_tag",
                "assert": {"enum": {"$resolve": "$.tags[*]"}}
            }
        ]
    })
}

fn assert_invalid_schema(schema: &Value) {
    assert!(matches!(
        xvalidate(&json!({}), schema),
        Err(XValidationFailure::InvalidSchema { .. })
    ));
}

#[test]
fn phase1_rejects_base_schema_failure_and_skips_xvalidation() {
    let failure = xvalidate(&json!({"primary_tag": "rust"}), &article_schema())
        .expect_err("base schema failure should raise validation failure");

    let XValidationFailure::Validation { errors } = failure else {
        panic!("expected validation failure");
    };
    assert!(!errors.is_empty());
    assert!(errors.iter().all(|error| error.rule_id.is_none()));
}

#[test]
fn standard_compound_schema_root_is_allowed() {
    assert_eq!(xvalidate(&json!({}), &json!({"type": "object"})), Ok(()));
}

#[test]
fn root_xvalidation_schema_does_not_require_an_id() {
    let schema = json!({
        "$schema": XVALIDATIONS_SCHEMA_URI,
        "type": "object",
        "x-validations": [{
            "id": "value-is-ok",
            "target": "$.value",
            "assert": {"const": "ok"}
        }]
    });

    assert_eq!(xvalidate(&json!({"value": "ok"}), &schema), Ok(()));
    let XValidationFailure::Validation { errors } =
        xvalidate(&json!({"value": "bad"}), &schema).expect_err("rule should fail")
    else {
        panic!("expected validation failure")
    };
    assert_eq!(errors[0].rule_id.as_deref(), Some("value-is-ok"));
}

#[test]
fn xvalidation_dialect_requires_xvalidations() {
    assert_invalid_schema(&json!({
        "$schema": XVALIDATIONS_SCHEMA_URI,
        "type": "object"
    }));
}

#[test]
fn boolean_root_schemas_are_supported() {
    assert_eq!(xvalidate(&json!({"anything": true}), &json!(true)), Ok(()));

    let XValidationFailure::Validation { errors } =
        xvalidate(&json!({"anything": true}), &json!(false))
            .expect_err("false schema should reject every instance")
    else {
        panic!("expected validation failure")
    };
    assert_eq!(errors.len(), 1);
    assert_eq!(errors[0].path, "$");
    assert_eq!(errors[0].rule_id, None);
}

#[test]
fn base_validation_returns_all_authoritative_errors() {
    let schema = json!({
        "type": "object",
        "properties": {
            "first": {"type": "string"},
            "second": {"type": "integer"}
        }
    });
    let XValidationFailure::Validation { errors } =
        xvalidate(&json!({"first": 1, "second": "no"}), &schema)
            .expect_err("both properties should fail")
    else {
        panic!("expected validation failure")
    };
    assert_eq!(
        errors
            .iter()
            .map(|error| error.path.as_str())
            .collect::<Vec<_>>(),
        ["$.first", "$.second"]
    );
    assert!(errors.iter().all(|error| error.rule_id.is_none()));
}

#[test]
fn relative_base_resource_ids_and_refs_use_the_synthetic_document_base() {
    let schema = json!({
        "$defs": {
            "Value": {"$id": "value", "type": "string"}
        },
        "$ref": "value"
    });
    assert_eq!(xvalidate(&json!("ok"), &schema), Ok(()));
    assert!(matches!(
        xvalidate(&json!(42), &schema),
        Err(XValidationFailure::Validation { .. })
    ));
}

#[test]
fn invalid_root_identifier_is_not_hidden_by_synthetic_normalization() {
    assert!(matches!(
        xvalidate(&json!(null), &json!({"$id": 42})),
        Err(XValidationFailure::InvalidSchema { .. })
    ));
}

#[test]
fn schema_preflight_requires_xvalidations_meta_schema_uri() {
    assert_invalid_schema(&json!({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "x-validations": []
    }));
}

#[test]
fn schema_preflight_rejects_invalid_xvalidation_rule_shape() {
    assert_invalid_schema(&json!({
        "$id": "urn:test:invalid-rule",
        "$schema": XVALIDATIONS_SCHEMA_URI,
        "type": "object",
        "x-validations": [
            {
                "id": "missing-assert",
                "target": "$.id"
            }
        ]
    }));
}

#[test]
fn schema_preflight_allows_optional_description_and_unique_by_primitive() {
    let schema = json!({
        "$id": "urn:test:unique-by",
        "$schema": XVALIDATIONS_SCHEMA_URI,
        "type": "object",
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field_id": {"type": "string"}
                    }
                }
            }
        },
        "x-validations": [
            {
                "id": "unique-field-ids",
                "target": "$.fields[*]",
                "assert": {"x-uniqueBy": "$.field_id"}
            }
        ]
    });

    assert_eq!(xvalidate(&json!({"fields": []}), &schema), Ok(()));
}

#[test]
fn schema_preflight_rejects_unknown_top_level_x_assertion_primitive() {
    assert_invalid_schema(&json!({
        "$id": "urn:test:unknown-assertion",
        "$schema": XVALIDATIONS_SCHEMA_URI,
        "type": "object",
        "x-validations": [
            {
                "id": "unsupported",
                "target": "$.id",
                "assert": {"x-notSupported": "$.id"}
            }
        ]
    }));
}

#[test]
fn schema_preflight_allows_resolve_hole_where_json_schema_expects_array() {
    let schema = json!({
        "$id": "urn:test:resolve-hole",
        "$schema": XVALIDATIONS_SCHEMA_URI,
        "type": "object",
        "required": ["allowed_tags", "primary_tag"],
        "properties": {
            "allowed_tags": {"type": "array", "items": {"type": "string"}},
            "primary_tag": {"type": "string"}
        },
        "x-validations": [
            {
                "id": "primary-tag-exists",
                "target": "$.primary_tag",
                "assert": {"enum": {"$resolve": "$.allowed_tags[*]"}}
            }
        ]
    });

    assert_eq!(
        xvalidate(
            &json!({"allowed_tags": ["python"], "primary_tag": "python"}),
            &schema
        ),
        Ok(())
    );
}

#[test]
fn phase1_keeps_resolved_defs_that_base_schema_still_references() {
    let schema = json!({
        "$id": "urn:test:resolved-defs",
        "$schema": XVALIDATIONS_SCHEMA_URI,
        "$defs": {
            "BaseTag": {"type": "string"}
        },
        "x-constants": {
            "xv-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": ["python"]
        },
        "type": "object",
        "required": ["tag"],
        "properties": {
            "tag": {"$ref": "#/$defs/BaseTag"}
        },
        "x-validations": [
            {
                "id": "tag-in-resource-def",
                "target": "$.tag",
                "assert": {"enum": {"$resolve": "#/x-constants/xv-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}
            }
        ]
    });

    assert_eq!(xvalidate(&json!({"tag": "python"}), &schema), Ok(()));
}

#[test]
fn base_error_path_preserves_numeric_object_properties() {
    let failure = xvalidate(
        &json!({"0": 1}),
        &json!({
            "$id": "urn:test:numeric-property",
            "$schema": XVALIDATIONS_SCHEMA_URI,
            "type": "object",
            "properties": {
                "0": {"type": "string"}
            },
            "x-validations": []
        }),
    )
    .expect_err("numeric object property should fail string validation");

    let XValidationFailure::Validation { errors } = failure else {
        panic!("expected validation failure");
    };
    assert_eq!(errors[0].path, "$[\"0\"]");
}
