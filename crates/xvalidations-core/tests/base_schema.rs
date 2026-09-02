use serde_json::json;
use xvalidations_core::{xvalidate, XValidationFailure};

#[test]
fn ordinary_draft_2020_12_schema_accepts_a_valid_payload() {
    let schema = json!({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}}
    });

    assert_eq!(xvalidate(&json!({"name": "Ada"}), &schema), Ok(()));
}

#[test]
fn ordinary_schema_reports_payload_errors() {
    let schema = json!({
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}}
    });

    let XValidationFailure::Validation { errors } =
        xvalidate(&json!({"name": 1}), &schema).expect_err("payload should fail")
    else {
        panic!("expected a validation failure");
    };
    assert_eq!(errors.len(), 1);
    assert_eq!(errors[0].path, "$.name");
    assert_eq!(errors[0].rule_id, None);
}

#[test]
fn base_payload_failure_stops_before_root_rules() {
    let schema = json!({
        "$schema": "https://thearchitector.dev/xvalidations/schema.json",
        "type": "object",
        "required": ["value"],
        "properties": {"value": {"type": "integer"}},
        "x-validations": [{
            "id": "small",
            "target": "$.value",
            "assert": {"maximum": 3}
        }]
    });

    let XValidationFailure::Validation { errors } =
        xvalidate(&json!({}), &schema).expect_err("payload should fail")
    else {
        panic!("expected a validation failure");
    };
    assert!(errors.iter().all(|error| error.rule_id.is_none()));
}
