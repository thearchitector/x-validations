use serde_json::Value;

use crate::meta::DRAFT202012_SCHEMA_URI;
use crate::types::{XValidationFailure, XValidationRule};

pub(crate) struct PreparedSchema {
    pub(crate) base_schema: Value,
    pub(crate) rules: Vec<XValidationRule>,
}

pub(crate) fn prepare_schema(schema: &Value) -> Result<PreparedSchema, XValidationFailure> {
    let rules = extract_xvalidations(schema)?;
    let base_schema = derive_base_schema(schema, &rules)?;
    Ok(PreparedSchema { base_schema, rules })
}

pub(crate) fn extract_xvalidations(
    schema: &Value,
) -> Result<Vec<XValidationRule>, XValidationFailure> {
    let Some(raw_rules) = schema.get("x-validations") else {
        return Ok(Vec::new());
    };
    if raw_rules.is_null() {
        return Ok(Vec::new());
    }
    let Some(raw_rules) = raw_rules.as_array() else {
        return Err(XValidationFailure::InvalidRule {
            message: "x-validations must be an array or null".to_string(),
        });
    };

    raw_rules
        .iter()
        .cloned()
        .map(|rule| {
            serde_json::from_value(rule).map_err(|error| XValidationFailure::InvalidRule {
                message: format!("invalid x-validation rule: {error}"),
            })
        })
        .collect()
}

fn derive_base_schema(
    schema: &Value,
    rules: &[XValidationRule],
) -> Result<Value, XValidationFailure> {
    let mut derived = schema.clone();
    {
        let Some(schema_object) = derived.as_object_mut() else {
            return Err(XValidationFailure::InvalidSchema {
                message: "exported schema must be an object".to_string(),
            });
        };

        schema_object.remove("x-validations");
        schema_object.insert(
            "$schema".to_string(),
            Value::String(DRAFT202012_SCHEMA_URI.to_string()),
        );
    }

    let base_referenced_defs = schema_referenced_defs(&derived);
    let owned_defs = xvalidation_owned_defs(rules);
    let Some(schema_object) = derived.as_object_mut() else {
        return Err(XValidationFailure::InvalidSchema {
            message: "exported schema must be an object".to_string(),
        });
    };
    if let Some(Value::Object(defs)) = schema_object.get_mut("$defs") {
        for def_name in owned_defs {
            if !base_referenced_defs.contains(&def_name) {
                defs.remove(&def_name);
            }
        }
        if defs.is_empty() {
            schema_object.remove("$defs");
        }
    }

    Ok(derived)
}

fn xvalidation_owned_defs(rules: &[XValidationRule]) -> Vec<String> {
    let mut owned = Vec::new();
    for rule in rules {
        collect_owned_defs(&rule.assertion, &mut owned);
    }
    owned
}

fn schema_referenced_defs(schema: &Value) -> Vec<String> {
    let mut referenced = Vec::new();
    collect_schema_refs(schema, &mut referenced);
    referenced
}

fn collect_schema_refs(node: &Value, referenced: &mut Vec<String>) {
    match node {
        Value::Object(object) => {
            for key in ["$ref", "$dynamicRef"] {
                if let Some(Value::String(reference)) = object.get(key) {
                    if let Some(def_name) = def_name_from_ref(reference) {
                        if !referenced.contains(&def_name) {
                            referenced.push(def_name);
                        }
                    }
                }
            }
            for value in object.values() {
                collect_schema_refs(value, referenced);
            }
        }
        Value::Array(values) => {
            for value in values {
                collect_schema_refs(value, referenced);
            }
        }
        _ => {}
    }
}

fn collect_owned_defs(node: &Value, owned: &mut Vec<String>) {
    match node {
        Value::Object(object) => {
            if object.len() == 1 {
                if let Some(Value::String(reference)) = object.get("$resolve") {
                    if let Some(def_name) = def_name_from_ref(reference) {
                        if !owned.contains(&def_name) {
                            owned.push(def_name);
                        }
                    }
                }
            }
            for value in object.values() {
                collect_owned_defs(value, owned);
            }
        }
        Value::Array(values) => {
            for value in values {
                collect_owned_defs(value, owned);
            }
        }
        _ => {}
    }
}

fn def_name_from_ref(reference: &str) -> Option<String> {
    let escaped_name = reference.strip_prefix("#/$defs/")?.split('/').next()?;
    Some(unescape_json_pointer_token(escaped_name))
}

fn unescape_json_pointer_token(token: &str) -> String {
    token.replace("~1", "/").replace("~0", "~")
}
