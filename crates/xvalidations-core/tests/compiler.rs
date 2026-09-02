use serde_json::{json, Value};
use xvalidations_core::{xvalidate, ValidationError, XValidationFailure};

fn validation_errors(payload: &Value, rules: Value) -> Vec<ValidationError> {
    let schema = json!({
        "$schema": "https://thearchitector.dev/xvalidations/schema.json",
        "type": "object",
        "x-validations": rules
    });
    let XValidationFailure::Validation { errors } =
        xvalidate(payload, &schema).expect_err("rule should fail")
    else {
        panic!("expected a validation failure");
    };
    errors
}

#[test]
fn scalar_path_interpolation_uses_the_selected_value() {
    let errors = validation_errors(
        &json!({"limit": 3, "values": [2, 4]}),
        json!([{
            "id": "limit",
            "target": "$.values[*]",
            "assert": {"maximum": {"$path": "$.limit"}}
        }]),
    );

    assert_eq!(errors.len(), 1);
    assert_eq!(errors[0].path, "$.values[1]");
    assert_eq!(errors[0].rule_id.as_deref(), Some("limit"));
}

#[test]
fn collection_path_interpolation_has_set_semantics() {
    let errors = validation_errors(
        &json!({"allowed": ["a"], "values": ["a", "b"]}),
        json!([{
            "id": "allowed",
            "target": "$.values[*]",
            "assert": {"enum": {"$path": "$.allowed[*]"}}
        }]),
    );

    assert_eq!(errors.len(), 1);
    assert_eq!(errors[0].path, "$.values[1]");
}

#[test]
fn root_target_can_select_multiple_nested_values() {
    let errors = validation_errors(
        &json!({"groups": [{"values": [1, -1]}, {"values": [-2]}]}),
        json!([{
            "id": "positive",
            "target": "$.groups[*].values[*]",
            "assert": {"minimum": 0}
        }]),
    );

    assert_eq!(
        errors
            .iter()
            .map(|error| error.path.as_str())
            .collect::<Vec<_>>(),
        ["$.groups[0].values[1]", "$.groups[1].values[0]"]
    );
}
