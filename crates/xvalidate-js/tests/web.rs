wasm_bindgen_test::wasm_bindgen_test_configure!(run_in_browser);

use js_sys::Reflect;
use serde_json::Value;
use wasm_bindgen::JsValue;
use wasm_bindgen_test::*;
use xvalidate::xvalidate;

const CONTRACTS: &[(&str, &str)] = &[
    (
        "article.json",
        include_str!("../../../tests/fixtures/contracts/article.json"),
    ),
    (
        "jsonpath_nested.json",
        include_str!("../../../tests/fixtures/contracts/jsonpath_nested.json"),
    ),
    (
        "unique_by.json",
        include_str!("../../../tests/fixtures/contracts/unique_by.json"),
    ),
];

fn contract_values() -> Vec<(&'static str, Value)> {
    CONTRACTS
        .iter()
        .map(|(name, source)| {
            (
                *name,
                serde_json::from_str(source).expect("contract fixture should parse"),
            )
        })
        .collect()
}

fn to_js(value: &Value) -> JsValue {
    serde_wasm_bindgen::to_value(value).expect("fixture should convert to JsValue")
}

fn from_js(value: JsValue) -> Value {
    serde_wasm_bindgen::from_value(value).expect("failure should convert from JsValue")
}

fn error_property(error: &JsValue, name: &str) -> JsValue {
    Reflect::get(error, &JsValue::from_str(name)).expect("error property should be readable")
}

fn error_property_string(error: &JsValue, name: &str) -> String {
    error_property(error, name)
        .as_string()
        .expect("error property should be a string")
}

fn error_failure(error: &JsValue) -> Value {
    from_js(error_property(error, "failure"))
}

#[wasm_bindgen_test]
fn contract_valid_payloads_return_ok() {
    for (name, contract) in contract_values() {
        if let Some(valid_payload) = contract.get("valid_payload") {
            assert!(
                xvalidate(to_js(valid_payload), to_js(&contract["schema"])).is_ok(),
                "{name}"
            );
        }
    }
}

#[wasm_bindgen_test]
fn contract_base_invalid_payloads_have_only_base_errors() {
    for (name, contract) in contract_values() {
        if let Some(base_invalid_payload) = contract.get("base_invalid_payload") {
            let failure = xvalidate(to_js(base_invalid_payload), to_js(&contract["schema"]))
                .expect_err("base-invalid payload should throw structured failure");
            assert_eq!(error_property_string(&failure, "name"), "XValidationError");
            assert_eq!(error_property_string(&failure, "kind"), "validation");
            let failure = error_failure(&failure);
            let errors = failure["errors"]
                .as_array()
                .expect("validation failure should contain error array");

            assert!(!errors.is_empty(), "{name}");
            assert!(errors.iter().all(|error| error["rule_id"].is_null()));
            assert_eq!(
                errors[0]
                    .as_object()
                    .expect("validation error should be an object")
                    .len(),
                3,
                "{name}"
            );
            assert!(errors[0].get("keyword").is_none(), "{name}");
            assert!(errors[0].get("source").is_none(), "{name}");
            assert_eq!(
                errors[0]["path"], contract["expected_base_error"]["path"],
                "{name}"
            );
        }
    }
}

#[wasm_bindgen_test]
fn contract_x_invalid_payloads_match_expected_error() {
    for (name, contract) in contract_values() {
        let payload = contract.get("x_invalid_payload");
        let expected_error = contract.get("expected_x_error");
        if let (Some(payload), Some(expected_error)) = (payload, expected_error) {
            let failure = xvalidate(to_js(payload), to_js(&contract["schema"]))
                .expect_err("x-invalid payload should throw structured failure");
            assert_eq!(error_property_string(&failure, "name"), "XValidationError");
            assert_eq!(error_property_string(&failure, "kind"), "validation");
            let errors = from_js(error_property(&failure, "errors"));
            let failure = error_failure(&failure);

            assert_eq!(failure["kind"], "validation", "{name}");
            assert!(!errors
                .as_array()
                .expect("errors should be an array")
                .is_empty());
            assert_eq!(
                failure["errors"][0]["path"], expected_error["path"],
                "{name}"
            );
            assert_eq!(
                failure["errors"][0]["rule_id"], expected_error["rule_id"],
                "{name}"
            );
            assert!(failure["errors"][0].get("keyword").is_none(), "{name}");
            assert!(failure["errors"][0].get("source").is_none(), "{name}");
        }
    }
}

#[wasm_bindgen_test]
fn invalid_payload_conversion_returns_machine_readable_kind() {
    let (_, contract) = contract_values()
        .into_iter()
        .next()
        .expect("at least one contract should exist");

    let failure = xvalidate(JsValue::UNDEFINED, to_js(&contract["schema"]))
        .expect_err("undefined payload should throw conversion failure");
    assert_eq!(
        error_property_string(&failure, "name"),
        "XValidationTypeError"
    );
    assert_eq!(error_property_string(&failure, "kind"), "invalid_payload");
    let failure = error_failure(&failure);

    assert_eq!(failure["kind"], "invalid_payload");
    assert!(failure["message"].is_string());
}

#[wasm_bindgen_test]
fn invalid_schema_conversion_returns_machine_readable_kind() {
    let (_, contract) = contract_values()
        .into_iter()
        .next()
        .expect("at least one contract should exist");

    let failure = xvalidate(to_js(&contract["valid_payload"]), JsValue::UNDEFINED)
        .expect_err("undefined schema should throw conversion failure");
    assert_eq!(
        error_property_string(&failure, "name"),
        "XValidationTypeError"
    );
    assert_eq!(
        error_property_string(&failure, "kind"),
        "invalid_schema_input"
    );
    let failure = error_failure(&failure);

    assert_eq!(failure["kind"], "invalid_schema_input");
    assert!(failure["message"].is_string());
}

#[wasm_bindgen_test]
fn boolean_schemas_are_supported() {
    let payload = serde_json::json!({"value": 1});

    xvalidate(to_js(&payload), to_js(&Value::Bool(true)))
        .expect("true schema should accept every payload");

    let failure = xvalidate(to_js(&payload), to_js(&Value::Bool(false)))
        .expect_err("false schema should reject every payload");
    let failure = error_failure(&failure);

    assert!(failure["errors"]
        .as_array()
        .is_some_and(|errors| !errors.is_empty()));
    assert!(failure["errors"][0]["rule_id"].is_null());
}
