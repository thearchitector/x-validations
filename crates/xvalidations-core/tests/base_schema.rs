use pretty_assertions::assert_eq;
use serde_json::{json, Value};
use xvalidations_core::{xvalidate, IssueSource, XValidationFailure};

const XVALIDATIONS_SCHEMA_URI: &str =
    "https://thearchitector.dev/xvalidations/meta/x-validations.schema.json";

fn article_schema() -> Value {
    json!({
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

fn assert_invalid_schema(schema: Value) {
    assert!(matches!(
        xvalidate(&json!({}), &schema),
        Err(XValidationFailure::InvalidSchema { .. })
    ));
}

#[test]
fn phase1_rejects_base_schema_failure_and_skips_xvalidation() {
    let failure = xvalidate(&json!({"primary_tag": "rust"}), &article_schema())
        .expect_err("base schema failure should raise validation failure");

    let XValidationFailure::Validation { issues } = failure else {
        panic!("expected validation failure");
    };
    assert!(!issues.is_empty());
    assert!(issues
        .iter()
        .all(|issue| issue.source == IssueSource::Base && issue.rule_id.is_none()));
}

#[test]
fn schema_preflight_requires_schema_field() {
    assert_invalid_schema(json!({
        "type": "object"
    }));
}

#[test]
fn schema_preflight_requires_xvalidations_meta_schema_uri() {
    assert_invalid_schema(json!({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object"
    }));
}

#[test]
fn schema_preflight_rejects_invalid_xvalidation_rule_shape() {
    assert_invalid_schema(json!({
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
    assert_invalid_schema(json!({
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
                "assert": {"enum": {"$resolve": "$.allowed_tags"}}
            }
        ]
    });

    assert_eq!(
        xvalidate(
            &json!({"allowed_tags": ["python"], "primary_tag": "rust"}),
            &schema
        ),
        Ok(())
    );
}

#[test]
fn phase1_keeps_resolved_defs_that_base_schema_still_references() {
    let schema = json!({
        "$schema": XVALIDATIONS_SCHEMA_URI,
        "$defs": {
            "SharedTag": {"type": "string"}
        },
        "type": "object",
        "required": ["tag"],
        "properties": {
            "tag": {"$ref": "#/$defs/SharedTag"}
        },
        "x-validations": [
            {
                "id": "tag-in-shared-def",
                "target": "$.tag",
                "assert": {"enum": {"$resolve": "#/$defs/SharedTag"}}
            }
        ]
    });

    assert_eq!(xvalidate(&json!({"tag": "python"}), &schema), Ok(()));
}

#[test]
fn base_issue_path_preserves_numeric_object_properties() {
    let failure = xvalidate(
        &json!({"0": 1}),
        &json!({
            "$schema": XVALIDATIONS_SCHEMA_URI,
            "type": "object",
            "properties": {
                "0": {"type": "string"}
            }
        }),
    )
    .expect_err("numeric object property should fail string validation");

    let XValidationFailure::Validation { issues } = failure else {
        panic!("expected validation failure");
    };
    assert_eq!(issues[0].path, "$[\"0\"]");
}
