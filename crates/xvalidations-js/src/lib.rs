use serde_json::{json, Value};
use wasm_bindgen::prelude::*;
use xvalidations_core::xvalidate as core_xvalidate;

#[wasm_bindgen]
pub fn xvalidate(payload: JsValue, schema: JsValue) -> Result<(), JsValue> {
    let payload = json_value_from_js(payload, "invalid_payload")?;
    let schema = json_value_from_js(schema, "invalid_schema_input")?;

    core_xvalidate(&payload, &schema).map_err(failure_to_js)
}

fn json_value_from_js(value: JsValue, kind: &'static str) -> Result<Value, JsValue> {
    if value.is_undefined() {
        return Err(conversion_failure(kind, "value must not be undefined"));
    }
    serde_wasm_bindgen::from_value(value)
        .map_err(|error| conversion_failure(kind, &error.to_string()))
}

fn failure_to_js(failure: xvalidations_core::XValidationFailure) -> JsValue {
    serde_wasm_bindgen::to_value(&failure).unwrap_or_else(|error| {
        conversion_failure(
            "failure_serialization",
            &format!("failed to serialize validation failure: {error}"),
        )
    })
}

fn conversion_failure(kind: &'static str, message: &str) -> JsValue {
    serde_wasm_bindgen::to_value(&json!({
        "kind": kind,
        "message": message,
    }))
    .unwrap_or_else(|_| JsValue::from_str(message))
}
