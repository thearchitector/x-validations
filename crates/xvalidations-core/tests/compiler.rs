use pretty_assertions::assert_eq;
use serde_json::{json, Value};
use xvalidations_core::{xvalidate, ValidationError, XValidationFailure};

const XVALIDATIONS_SCHEMA_URI: &str = "https://thearchitector.dev/xvalidations/schema.json";

fn rule_schema(target: &str, assertion: Value) -> Value {
    json!({
        "$id": "urn:test:compiler",
        "$schema": XVALIDATIONS_SCHEMA_URI,
        "type": "object",
        "x-validations": [{
            "id": "runtime-rule",
            "target": target,
            "assert": assertion
        }]
    })
}

fn validation_errors(payload: &Value, schema: &Value) -> Vec<ValidationError> {
    let XValidationFailure::Validation { errors } =
        xvalidate(payload, schema).expect_err("payload should fail")
    else {
        panic!("expected validation failure")
    };
    errors
}

#[test]
fn singular_path_interpolation_uses_the_selected_value() {
    let schema = rule_schema("$.value", json!({"maximum": {"$path": "$.upper"}}));
    assert_eq!(xvalidate(&json!({"value": 2, "upper": 3}), &schema), Ok(()));
    let errors = validation_errors(&json!({"value": 4, "upper": 3}), &schema);
    assert_eq!(errors[0].path, "$.value");
    assert_eq!(errors[0].rule_id.as_deref(), Some("runtime-rule"));
}

#[test]
fn nonsingular_path_interpolation_uses_set_semantics() {
    let schema = rule_schema("$.value", json!({"enum": {"$path": "$.allowed[*]"}}));
    assert_eq!(
        xvalidate(&json!({"value": "a", "allowed": ["a", "b"]}), &schema),
        Ok(())
    );
    assert_eq!(
        validation_errors(&json!({"value": "c", "allowed": ["a", "b"]}), &schema)[0].path,
        "$.value"
    );
}

#[test]
fn missing_singular_and_empty_many_operands_fail_selected_targets() {
    let singular = rule_schema("$.value", json!({"maximum": {"$path": "$.missing"}}));
    let many = rule_schema("$.value", json!({"enum": {"$path": "$.missing[*]"}}));
    for schema in [singular, many] {
        let errors = validation_errors(&json!({"value": 1}), &schema);
        assert_eq!(errors[0].path, "$.value");
        assert_eq!(errors[0].rule_id.as_deref(), Some("runtime-rule"));
    }
}

#[test]
fn incompatible_runtime_operand_fails_selected_target() {
    let schema = rule_schema("$.value", json!({"maximum": {"$path": "$.upper"}}));
    let errors = validation_errors(&json!({"value": 1, "upper": "bad"}), &schema);
    assert!(errors[0].message.contains("not valid Draft 2020-12"));
}

#[test]
fn valid_but_target_inapplicable_keyword_keeps_json_schema_behavior() {
    let schema = rule_schema("$.value", json!({"maximum": {"$path": "$.upper"}}));
    assert_eq!(
        xvalidate(&json!({"value": "not numeric", "upper": 3}), &schema),
        Ok(())
    );
}

#[test]
fn independently_interpolated_paths_are_not_correlated() {
    let schema = rule_schema("$.values[*]", json!({"enum": {"$path": "$.allowed[*]"}}));
    assert_eq!(
        xvalidate(
            &json!({"values": ["a", "b"], "allowed": ["b", "a"]}),
            &schema
        ),
        Ok(())
    );
}

#[test]
fn marker_looking_payload_data_is_not_reinterpreted() {
    let schema = rule_schema("$.value", json!({"const": {"$path": "$.expected"}}));
    let marker = json!({"$path": "$.other"});
    assert_eq!(
        xvalidate(
            &json!({"value": marker, "expected": marker, "other": "different"}),
            &schema
        ),
        Ok(())
    );
}

#[test]
fn unmatched_targets_skip_assertion_construction() {
    let schema = rule_schema(
        "$.missing_target",
        json!({"enum": {"$path": "$.malformed["}}),
    );
    assert_eq!(xvalidate(&json!({}), &schema), Ok(()));
}

#[test]
fn malformed_target_jsonpath_is_reported() {
    let schema = rule_schema("$[", json!({"const": {"$path": "$.expected"}}));
    assert!(matches!(
        xvalidate(&json!({"value": "ok"}), &schema),
        Err(XValidationFailure::JsonPath { .. })
    ));
}

#[test]
fn legacy_resolve_and_non_singleton_path_markers_are_rejected() {
    for assertion in [
        json!({"enum": {"$resolve": "$.allowed[*]"}}),
        json!({"const": {"$resolve": "$.expected"}}),
        json!({"enum": {"$path": "$.allowed[*]", "fallback": []}}),
    ] {
        assert!(matches!(
            xvalidate(&json!({}), &rule_schema("$.value", assertion)),
            Err(XValidationFailure::InvalidSchema { .. })
        ));
    }
}

#[test]
fn static_rules_and_nested_unique_by_are_rejected() {
    for assertion in [
        json!({"const": "static"}),
        json!({"allOf": [{"x-uniqueBy": "$.id"}]}),
    ] {
        assert!(matches!(
            xvalidate(&json!({}), &rule_schema("$.value", assertion)),
            Err(XValidationFailure::InvalidSchema { .. })
        ));
    }
}

#[test]
fn unique_by_validates_each_target_array() {
    let schema = rule_schema("$.fields", json!({"x-uniqueBy": "$.id"}));
    let errors = validation_errors(
        &json!({"fields": [{"id": "same"}, {"id": "same"}]}),
        &schema,
    );
    assert_eq!(
        errors
            .iter()
            .map(|error| error.path.as_str())
            .collect::<Vec<_>>(),
        ["$.fields[0]", "$.fields[1]"]
    );
}

#[test]
fn unique_by_keeps_separate_target_arrays_independent() {
    let schema = rule_schema("$.groups[*]", json!({"x-uniqueBy": "$.id"}));
    assert_eq!(
        xvalidate(
            &json!({"groups": [[{"id": "same"}], [{"id": "same"}]]}),
            &schema,
        ),
        Ok(())
    );
}

#[test]
fn unique_by_rejects_non_array_runtime_targets() {
    let schema = rule_schema("$.field", json!({"x-uniqueBy": "$.id"}));
    assert!(matches!(
        xvalidate(&json!({"field": {"id": "same"}}), &schema),
        Err(XValidationFailure::InvalidRule { .. })
    ));
}
