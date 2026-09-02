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

fn error_property(error: &JsValue, name: &str) -> JsValue {
    Reflect::get(error, &JsValue::from_str(name)).expect("error property should be readable")
}

fn errors(error: &JsValue) -> Value {
    serde_wasm_bindgen::from_value(error_property(error, "errors"))
        .expect("errors should convert from JsValue")
}

#[wasm_bindgen_test]
fn contract_valid_payloads_return_ok() {
    for (name, contract) in contract_values() {
        assert!(
            xvalidate(
                to_js(&contract["valid_payload"]),
                to_js(&contract["schema"])
            )
            .is_ok(),
            "{name}"
        );
    }
}

#[wasm_bindgen_test]
fn contract_base_failures_have_no_rule_id() {
    for (name, contract) in contract_values() {
        let failure = xvalidate(
            to_js(&contract["base_invalid_payload"]),
            to_js(&contract["schema"]),
        )
        .expect_err("base-invalid payload should fail");
        let errors = errors(&failure);
        let errors = errors.as_array().expect("errors should be an array");

        assert!(!errors.is_empty(), "{name}");
        assert!(errors.iter().all(|error| error["rule_id"].is_null()));
        assert_eq!(
            errors[0]["path"], contract["expected_base_error"]["path"],
            "{name}"
        );
    }
}

#[wasm_bindgen_test]
fn contract_rule_failures_match_expected_error() {
    for (name, contract) in contract_values() {
        let failure = xvalidate(
            to_js(&contract["x_invalid_payload"]),
            to_js(&contract["schema"]),
        )
        .expect_err("x-invalid payload should fail");
        let errors = errors(&failure);
        let error = &errors[0];
        let expected = &contract["expected_x_error"];

        assert_eq!(error["path"], expected["path"], "{name}");
        assert_eq!(error["rule_id"], expected["rule_id"], "{name}");
    }
}
