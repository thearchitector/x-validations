use pretty_assertions::assert_eq;
use serde_json::{json, Value};
use xvalidations_core::{xvalidate, XValidationFailure};

const XVALIDATIONS_SCHEMA_URI: &str = "https://thearchitector.dev/xvalidations/schema.json";

fn child_resource(assertion: &Value) -> Value {
    json!({
        "$id": "urn:test:child-resource",
        "$schema": XVALIDATIONS_SCHEMA_URI,
        "type": "object",
        "required": ["value"],
        "properties": {"value": {"type": "string"}},
        "x-validations": [{
            "id": "local-value",
            "target": "$.value",
            "assert": assertion
        }]
    })
}

fn validation_errors(payload: &Value, schema: &Value) -> Vec<xvalidations_core::ValidationError> {
    let XValidationFailure::Validation { errors } =
        xvalidate(payload, schema).expect_err("payload should fail")
    else {
        panic!("expected validation failure")
    };
    errors
}

#[test]
fn nested_resource_runs_at_properties_and_array_items_with_absolute_paths() {
    let schema = json!({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {"Child": child_resource(&json!({"const": "ok"}))},
        "type": "object",
        "properties": {
            "first": {"$ref": "#/$defs/Child"},
            "second": {"$ref": "#/$defs/Child"},
            "items": {"type": "array", "items": {"$ref": "#/$defs/Child"}}
        }
    });
    let errors = validation_errors(
        &json!({
            "first": {"value": "bad"},
            "second": {"value": "ok"},
            "items": [{"value": "bad"}]
        }),
        &schema,
    );

    assert_eq!(
        errors
            .iter()
            .map(|error| (error.path.as_str(), error.rule_id.as_deref()))
            .collect::<Vec<_>>(),
        [
            ("$.first.value", Some("local-value")),
            ("$.items[0].value", Some("local-value"))
        ]
    );
}

#[test]
fn refs_and_successful_applicator_branches_emit_resource_occurrences() {
    let schema = json!({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {"Child": child_resource(&json!({"const": "ok"}))},
        "type": "object",
        "properties": {
            "all": {"allOf": [{"$ref": "#/$defs/Child"}]},
            "any": {"anyOf": [{"type": "null"}, {"$ref": "#/$defs/Child"}]},
            "one": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/Child"}]},
            "conditional": {
                "if": {"type": "object"},
                "then": {"$ref": "#/$defs/Child"}
            }
        }
    });
    let errors = validation_errors(
        &json!({
            "all": {"value": "bad"},
            "any": {"value": "bad"},
            "one": {"value": "bad"},
            "conditional": {"value": "bad"}
        }),
        &schema,
    );

    assert_eq!(
        errors
            .iter()
            .map(|error| error.path.as_str())
            .collect::<Vec<_>>(),
        [
            "$.all.value",
            "$.any.value",
            "$.conditional.value",
            "$.one.value"
        ]
    );
}

#[test]
fn local_constant_and_schema_pointer_resolution_stay_in_the_resource() {
    let mut resource = child_resource(&json!({
        "allOf": [
            {"enum": {"$resolve": "#/x-constants/xv-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}},
            {"$resolve": "#/$defs/StringValue"}
        ]
    }));
    resource["x-constants"] = json!({
        "xv-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": ["ok"]
    });
    resource["$defs"] = json!({"StringValue": {"type": "string"}});

    assert_eq!(xvalidate(&json!({"value": "ok"}), &resource), Ok(()));
    let errors = validation_errors(&json!({"value": "bad"}), &resource);
    assert!(errors.iter().all(|error| error.rule_id.is_some()));
}

#[test]
fn base_schema_failure_short_circuits_payload_dependent_rule_compilation() {
    let resource = child_resource(&json!({
        "enum": {"$resolve": "$.missing["}
    }));
    let failure = xvalidate(&json!({}), &resource).expect_err("required should fail first");
    let XValidationFailure::Validation { errors } = failure else {
        panic!("expected base validation failure")
    };
    assert!(errors.iter().all(|error| error.rule_id.is_none()));
}

#[test]
fn duplicate_resource_ids_are_rejected_during_preparation() {
    let schema = json!({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {
            "First": child_resource(&json!({"const": "ok"})),
            "Second": child_resource(&json!({"const": "ok"}))
        }
    });
    assert!(matches!(
        xvalidate(&json!({}), &schema),
        Err(XValidationFailure::InvalidSchema { .. })
    ));
}

#[test]
fn embedded_xvalidation_resource_requires_an_id() {
    let mut child = child_resource(&json!({"const": "ok"}));
    child
        .as_object_mut()
        .expect("child is an object")
        .remove("$id");
    let schema = json!({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {"Child": child},
        "$ref": "#/$defs/Child"
    });

    assert!(matches!(
        xvalidate(&json!({"value": "ok"}), &schema),
        Err(XValidationFailure::InvalidSchema { .. })
    ));
}

#[test]
fn assertions_can_reference_another_prepared_resource() {
    let mut validating = child_resource(&json!({"$ref": "urn:test:constraints#allowed"}));
    validating["$id"] = json!("urn:test:validating");
    let schema = json!({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {
            "Validating": validating,
            "Constraints": {
                "$id": "urn:test:constraints",
                "$anchor": "allowed",
                "const": "ok"
            }
        },
        "$ref": "#/$defs/Validating"
    });

    assert_eq!(xvalidate(&json!({"value": "ok"}), &schema), Ok(()));
    let errors = validation_errors(&json!({"value": "bad"}), &schema);
    assert_eq!(errors[0].path, "$.value");
    assert_eq!(errors[0].rule_id.as_deref(), Some("local-value"));
}

#[test]
fn repeated_references_preserve_repeated_resource_occurrences() {
    let schema = json!({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {"Child": child_resource(&json!({"const": "ok"}))},
        "allOf": [
            {"$ref": "#/$defs/Child"},
            {"$ref": "#/$defs/Child"}
        ]
    });
    let errors = validation_errors(&json!({"value": "bad"}), &schema);

    assert_eq!(errors.len(), 2);
    assert!(errors.iter().all(|error| {
        error.path == "$.value" && error.rule_id.as_deref() == Some("local-value")
    }));
}
