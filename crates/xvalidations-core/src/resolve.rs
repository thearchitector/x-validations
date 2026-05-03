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
    if reference == "#" {
        return Ok(document.clone());
    }

    let mut current = document;
    for raw_token in reference.trim_start_matches("#/").split('/') {
        let token = unescape_json_pointer_token(raw_token);
        current = match current {
            Value::Object(object) => {
                object
                    .get(&token)
                    .ok_or_else(|| XValidationFailure::Resolve {
                        message: format!("missing JSON Pointer token {token:?} in {reference:?}"),
                    })?
            }
            Value::Array(values) => {
                if !is_json_pointer_array_index(&token) {
                    return Err(XValidationFailure::Resolve {
                        message: format!("invalid JSON Pointer array token {token:?}"),
                    });
                }
                let index = token
                    .parse::<usize>()
                    .map_err(|_| XValidationFailure::Resolve {
                        message: format!("invalid JSON Pointer array token {token:?}"),
                    })?;
                values
                    .get(index)
                    .ok_or_else(|| XValidationFailure::Resolve {
                        message: format!("missing JSON Pointer index {index} in {reference:?}"),
                    })?
            }
            _ => {
                return Err(XValidationFailure::Resolve {
                    message: format!("cannot traverse scalar while resolving {reference:?}"),
                });
            }
        };
    }
    Ok(current.clone())
}

fn is_json_pointer_array_index(token: &str) -> bool {
    token == "0"
        || (token.starts_with(['1', '2', '3', '4', '5', '6', '7', '8', '9'])
            && token.chars().all(|character| character.is_ascii_digit()))
}

fn unescape_json_pointer_token(token: &str) -> String {
    token.replace("~1", "/").replace("~0", "~")
}
