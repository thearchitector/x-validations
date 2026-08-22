use serde_json::{Map, Value};

use crate::jsonpath::evaluate_jsonpath;
use crate::types::XValidationFailure;

pub fn resolve_placeholders(
    node: &Value,
    payload: &Value,
    schema: &Value,
) -> Result<Value, XValidationFailure> {
    match node {
        Value::Object(object) => resolve_object(object, payload, schema),
        Value::Array(values) => values
            .iter()
            .map(|value| resolve_placeholders(value, payload, schema))
            .collect(),
        _ => Ok(node.clone()),
    }
}

fn resolve_object(
    object: &Map<String, Value>,
    payload: &Value,
    schema: &Value,
) -> Result<Value, XValidationFailure> {
    if let Some(resolve_value) = object.get("$resolve") {
        if object.len() != 1 {
            return Err(XValidationFailure::Resolve {
                message: "$resolve marker object must not contain other keys".to_string(),
            });
        }
        let Some(reference) = resolve_value.as_str() else {
            return Err(XValidationFailure::Resolve {
                message: "$resolve value must be a string".to_string(),
            });
        };
        return resolve_ref(reference, payload, schema);
    }

    object
        .iter()
        .map(|(key, value)| {
            resolve_placeholders(value, payload, schema).map(|resolved| (key.clone(), resolved))
        })
        .collect::<Result<Map<String, Value>, XValidationFailure>>()
        .map(Value::Object)
}

pub fn resolve_ref(
    reference: &str,
    payload: &Value,
    schema: &Value,
) -> Result<Value, XValidationFailure> {
    if reference.starts_with('$') {
        return Ok(Value::Array(
            evaluate_jsonpath(reference, payload)?
                .into_iter()
                .map(|jsonpath_match| jsonpath_match.value)
                .collect(),
        ));
    }
    if reference == "#" || reference.starts_with("#/") {
        return resolve_json_pointer(reference, schema);
    }
    Err(XValidationFailure::Resolve {
        message: format!("unsupported $resolve reference: {reference}"),
    })
}

fn resolve_json_pointer(reference: &str, document: &Value) -> Result<Value, XValidationFailure> {
    let pointer = reference
        .strip_prefix('#')
        .expect("JSON Pointer references were checked by the caller");
    document
        .pointer(pointer)
        .cloned()
        .ok_or_else(|| XValidationFailure::Resolve {
            message: format!("JSON Pointer {reference:?} does not exist in the exported schema"),
        })
}
