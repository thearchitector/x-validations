use js_sys::{Error, Reflect};
use serde_json::Value;
use wasm_bindgen::prelude::*;
use xvalidations_core::{xvalidate as core_xvalidate, XValidationFailure};

#[wasm_bindgen(typescript_custom_section)]
const TYPESCRIPT_TYPES: &str = r#"
export interface ValidationError {
  path: string;
  message: string;
  rule_id: string | null;
}

export interface ValidationFailure {
  kind: "validation";
  errors: ValidationError[];
}

export interface XValidationError extends Error {
  name: "XValidationError";
  kind: "validation";
  failure: ValidationFailure;
  errors: ValidationError[];
}
"#;

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

fn failure_to_js(failure: XValidationFailure) -> JsValue {
    core_failure_to_js_error(&failure).unwrap_or_else(|error| error)
}

fn conversion_failure(kind: &'static str, message: &str) -> JsValue {
    binding_failure_to_js_error("XValidationTypeError", kind, message)
        .unwrap_or_else(|_| JsValue::from_str(message))
}

fn core_failure_to_js_error(failure: &XValidationFailure) -> Result<JsValue, JsValue> {
    let failure_value = serde_wasm_bindgen::to_value(failure).map_err(|error| {
        conversion_failure(
            "failure_serialization",
            &format!("failed to serialize validation failure: {error}"),
        )
    })?;
    let error = Error::new(&failure.to_string());
    let error = JsValue::from(error);

    set_property(&error, "name", &JsValue::from_str(failure.exception_name()))?;
    set_property(&error, "kind", &JsValue::from_str(failure.kind()))?;
    set_property(&error, "failure", &failure_value)?;

    if let Some(errors) = failure.errors() {
        let errors = serde_wasm_bindgen::to_value(errors).map_err(|error| {
            conversion_failure(
                "failure_serialization",
                &format!("failed to serialize validation errors: {error}"),
            )
        })?;
        set_property(&error, "errors", &errors)?;
    }

    Ok(error)
}

fn binding_failure_to_js_error(
    name: &'static str,
    kind: &str,
    message: &str,
) -> Result<JsValue, JsValue> {
    let failure = serde_json::json!({"kind": kind, "message": message});
    let failure_value = serde_wasm_bindgen::to_value(&failure)?;
    let error = JsValue::from(Error::new(message));
    set_property(&error, "name", &JsValue::from_str(name))?;
    set_property(&error, "kind", &JsValue::from_str(kind))?;
    set_property(&error, "failure", &failure_value)?;
    Ok(error)
}

fn set_property(target: &JsValue, name: &str, value: &JsValue) -> Result<(), JsValue> {
    match Reflect::set(target, &JsValue::from_str(name), value) {
        Ok(true) => Ok(()),
        Ok(false) => Err(JsValue::from_str(&format!(
            "failed to set error property: {name}"
        ))),
        Err(error) => Err(error),
    }
}
