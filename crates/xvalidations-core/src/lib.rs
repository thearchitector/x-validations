mod artifact;
mod compiler;
mod jsonpath;
mod meta;
mod pointer;
mod resolve;
mod target;
mod types;

use serde_json::Value;

pub use types::{
    ErrorSource, ValidationError, XValidationBindingFailure, XValidationFailure, XValidationRule,
};

use crate::artifact::prepare_schema;
use crate::compiler::generate_compiled_schema;
use crate::meta::XVALIDATIONS_META_VALIDATOR;
use crate::pointer::{is_array_index, tokens};

pub fn xvalidate(payload: &Value, schema: &Value) -> Result<(), XValidationFailure> {
    validate_exported_schema(schema)?;

    let prepared = prepare_schema(schema)?;
    let base_validator = jsonschema::validator_for(&prepared.base_schema).map_err(|error| {
        XValidationFailure::InvalidSchema {
            message: format!("derived base schema is not valid Draft 2020-12: {error}"),
        }
    })?;
    validate_payload(payload, &base_validator, ErrorSource::Base, None)?;

    let compiled = generate_compiled_schema(schema, payload, &prepared.rules)?;
    let compiled_validator = jsonschema::validator_for(&compiled.schema).map_err(|error| {
        XValidationFailure::InvalidSchema {
            message: format!("compiled x-validation schema is not valid Draft 2020-12: {error}"),
        }
    })?;
    validate_payload(
        payload,
        &compiled_validator,
        ErrorSource::XValidation,
        Some(&compiled.branch_rule_ids),
    )?;
    Ok(())
}

fn validate_exported_schema(schema: &Value) -> Result<(), XValidationFailure> {
    XVALIDATIONS_META_VALIDATOR
        .validate(schema)
        .map_err(|error| XValidationFailure::InvalidSchema {
            message: format!("exported schema failed x-validations preflight: {error}"),
        })
}

fn validate_payload(
    payload: &Value,
    validator: &jsonschema::Validator,
    source: ErrorSource,
    branch_rule_ids: Option<&[String]>,
) -> Result<(), XValidationFailure> {
    let validation_errors = validator.iter_errors(payload).collect::<Vec<_>>();
    if validation_errors.is_empty() {
        return Ok(());
    }

    let mut errors = validation_errors
        .iter()
        .map(|error| ValidationError {
            path: json_pointer_to_jsonpath(&error.instance_path().to_string(), payload),
            message: error.to_string(),
            keyword: keyword_from_schema_path(&error.schema_path().to_string()),
            source: source.clone(),
            rule_id: match source {
                ErrorSource::Base => None,
                ErrorSource::XValidation => {
                    rule_id_from_schema_path(&error.evaluation_path().to_string(), branch_rule_ids)
                }
            },
        })
        .collect::<Vec<_>>();
    errors.sort_by(|left, right| {
        (
            left.path.as_str(),
            left.rule_id.as_deref().unwrap_or(""),
            left.keyword.as_deref().unwrap_or(""),
            left.message.as_str(),
        )
            .cmp(&(
                right.path.as_str(),
                right.rule_id.as_deref().unwrap_or(""),
                right.keyword.as_deref().unwrap_or(""),
                right.message.as_str(),
            ))
    });

    Err(XValidationFailure::Validation { errors })
}

fn rule_id_from_schema_path(
    schema_path: &str,
    branch_rule_ids: Option<&[String]>,
) -> Option<String> {
    let branch_rule_ids = branch_rule_ids?;
    let tokens = tokens(schema_path);
    for window in tokens.windows(2) {
        if window[0] == "allOf" {
            let Ok(index) = window[1].parse::<usize>() else {
                continue;
            };
            return branch_rule_ids.get(index).cloned();
        }
    }
    None
}

fn keyword_from_schema_path(schema_path: &str) -> Option<String> {
    tokens(schema_path).pop()
}

fn json_pointer_to_jsonpath(pointer: &str, root: &Value) -> String {
    if pointer.is_empty() {
        return "$".to_string();
    }

    let mut path = "$".to_string();
    let mut current = Some(root);
    for token in tokens(pointer) {
        let next = match current {
            Some(Value::Array(values)) if is_array_index(&token) => {
                path.push_str(&format!("[{token}]"));
                token
                    .parse::<usize>()
                    .ok()
                    .and_then(|index| values.get(index))
            }
            Some(Value::Object(object)) => {
                append_property_path(&mut path, &token);
                object.get(&token)
            }
            _ => {
                append_property_path(&mut path, &token);
                None
            }
        };
        current = next;
    }
    path
}

fn append_property_path(path: &mut String, property: &str) {
    if is_identifier(property) {
        path.push('.');
        path.push_str(property);
    } else {
        let quoted = serde_json::to_string(property)
            .expect("serializing a JSON pointer token string cannot fail");
        path.push_str(&format!("[{quoted}]"));
    }
}

fn is_identifier(token: &str) -> bool {
    let mut chars = token.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    (first == '_' || first.is_ascii_alphabetic())
        && chars.all(|character| character == '_' || character.is_ascii_alphanumeric())
}
