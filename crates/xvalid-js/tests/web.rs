use js_sys::Reflect;
use serde_json::Value;
use wasm_bindgen::JsValue;
use wasm_bindgen_test::*;
use xvalid_js::xvalidate;

const CONTRACTS: &[(&str, &str)] = &[
    (
        "article.json",
        include_str!("../../../tests/fixtures/contracts/article.json"),
    ),
    (
        "jsonpath_nested.json",
        include_str!("../../../tests/fixtures/contracts/jsonpath_nested.json"),
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
fn contract_base_invalid_payloads_have_only_base_issues() {
    for (name, contract) in contract_values() {
        if let Some(base_invalid_payload) = contract.get("base_invalid_payload") {
            let failure = xvalidate(to_js(base_invalid_payload), to_js(&contract["schema"]))
                .expect_err("base-invalid payload should throw structured failure");
            assert_eq!(error_property_string(&failure, "name"), "XValidationError");
            assert_eq!(error_property_string(&failure, "kind"), "validation");
            let failure = error_failure(&failure);
            let issues = failure["issues"]
                .as_array()
                .expect("validation failure should contain issue array");

            assert!(!issues.is_empty(), "{name}");
            assert!(issues
                .iter()
                .all(|issue| { issue["source"] == "base" && issue["rule_id"].is_null() }));
        }
    }
}

#[wasm_bindgen_test]
fn contract_x_invalid_payloads_match_expected_issue() {
    for (name, contract) in contract_values() {
        let payload = contract
            .get("x_invalid_payload")
            .or_else(|| contract.get("payload"));
        let expected_issue = contract
            .get("expected_x_issue")
            .or_else(|| contract.get("expected_issue"));
        if let (Some(payload), Some(expected_issue)) = (payload, expected_issue) {
            let failure = xvalidate(to_js(payload), to_js(&contract["schema"]))
                .expect_err("x-invalid payload should throw structured failure");
            assert_eq!(error_property_string(&failure, "name"), "XValidationError");
            assert_eq!(error_property_string(&failure, "kind"), "validation");
            let errors = from_js(error_property(&failure, "errors"));
            let failure = error_failure(&failure);

            assert_eq!(failure["kind"], "validation", "{name}");
            assert_eq!(errors.as_array().map(Vec::len), Some(1), "{name}");
            assert_eq!(
                failure["issues"].as_array().map(Vec::len),
                Some(1),
                "{name}"
            );
            assert_eq!(
                failure["issues"][0]["path"], expected_issue["path"],
                "{name}"
            );
            assert_eq!(
                failure["issues"][0]["source"], expected_issue["source"],
                "{name}"
            );
            assert_eq!(
                failure["issues"][0]["rule_id"], expected_issue["rule_id"],
                "{name}"
            );
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
