use serde_json::Value;
use wasm_bindgen::JsValue;
use wasm_bindgen_test::*;
use xvalidations_js::xvalidate;

fn article_contract() -> Value {
    serde_json::from_str(include_str!(
        "../../../tests/fixtures/contracts/article.json"
    ))
    .expect("article contract fixture should parse")
}

fn to_js(value: &Value) -> JsValue {
    serde_wasm_bindgen::to_value(value).expect("fixture should convert to JsValue")
}

fn from_js(value: JsValue) -> Value {
    serde_wasm_bindgen::from_value(value).expect("failure should convert from JsValue")
}

#[wasm_bindgen_test]
fn valid_article_fixture_returns_ok() {
    let contract = article_contract();

    assert!(xvalidate(
        to_js(&contract["valid_payload"]),
        to_js(&contract["schema"])
    )
    .is_ok());
}

#[wasm_bindgen_test]
fn invalid_article_fixture_returns_structured_validation_failure() {
    let contract = article_contract();

    let failure = xvalidate(
        to_js(&contract["x_invalid_payload"]),
        to_js(&contract["schema"]),
    )
    .expect_err("invalid article payload should throw structured failure");
    let failure = from_js(failure);

    assert_eq!(failure["kind"], "validation");
    assert_eq!(failure["issues"][0]["path"], "$.primary_tag");
    assert_eq!(failure["issues"][0]["source"], "x-validation");
    assert_eq!(failure["issues"][0]["rule_id"], "primary-tag-exists");
}

#[wasm_bindgen_test]
fn invalid_payload_conversion_returns_machine_readable_kind() {
    let contract = article_contract();

    let failure = xvalidate(JsValue::UNDEFINED, to_js(&contract["schema"]))
        .expect_err("undefined payload should throw conversion failure");
    let failure = from_js(failure);

    assert_eq!(failure["kind"], "invalid_payload");
}

#[wasm_bindgen_test]
fn invalid_schema_conversion_returns_machine_readable_kind() {
    let contract = article_contract();

    let failure = xvalidate(to_js(&contract["valid_payload"]), JsValue::UNDEFINED)
        .expect_err("undefined schema should throw conversion failure");
    let failure = from_js(failure);

    assert_eq!(failure["kind"], "invalid_schema_input");
}
