use serde_json::Value;

use crate::meta::DRAFT202012_SCHEMA_URI;
use crate::pointer::{referenced_defs, resolved_defs};
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
    let mut schema_object =
        schema
            .as_object()
            .cloned()
            .ok_or_else(|| XValidationFailure::InvalidSchema {
                message: "exported schema must be an object".to_string(),
            })?;
    schema_object.remove("x-validations");
    schema_object.insert(
        "$schema".to_string(),
        Value::String(DRAFT202012_SCHEMA_URI.to_string()),
    );
    let mut derived = Value::Object(schema_object);

    let base_referenced_defs = referenced_defs(&derived);
    let owned_defs = rules
        .iter()
        .flat_map(|rule| resolved_defs(&rule.assertion))
        .collect::<std::collections::HashSet<_>>();
    let schema_object = derived
        .as_object_mut()
        .expect("derived schema is an object");
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
