mod artifact;
pub mod compiler;
mod jsonpath;
mod meta;
mod resolve;
mod target;
pub mod types;

use serde_json::Value;

pub use types::{
    IssueSource, ValidationIssue, XValidationBindingFailure, XValidationFailure, XValidationRule,
};

use crate::artifact::prepare_schema;
use crate::compiler::generate_compiled_schema;
use crate::meta::xvalidations_meta_schema;

pub fn xvalidate(payload: &Value, schema: &Value) -> Result<(), XValidationFailure> {
    validate_xvalidations_meta_schema()?;
    validate_exported_schema(schema)?;

    let prepared = prepare_schema(schema)?;
    validate_draft202012_schema(&prepared.base_schema)?;
    validate_payload_against_schema(payload, &prepared.base_schema, IssueSource::Base, None)?;

    let compiled = generate_compiled_schema(schema, payload)?;
    validate_payload_against_schema(
        payload,
        &compiled.schema,
        IssueSource::XValidation,
        Some(&compiled.branch_rule_ids),
    )?;
    let _rules = prepared.rules;
    Ok(())
}

fn validate_xvalidations_meta_schema() -> Result<(), XValidationFailure> {
    let meta_schema = xvalidations_meta_schema()?;
    jsonschema::draft202012::meta::validate(&meta_schema).map_err(|error| {
        XValidationFailure::InvalidSchema {
            message: format!("bundled x-validations meta-schema is invalid: {error}"),
        }
    })
}

fn validate_exported_schema(schema: &Value) -> Result<(), XValidationFailure> {
    let meta_schema = xvalidations_meta_schema()?;
    let validator = jsonschema::draft202012::new(&meta_schema).map_err(|error| {
        XValidationFailure::InvalidSchema {
            message: format!("could not build x-validations meta-schema validator: {error}"),
        }
    })?;

    validator
        .validate(schema)
        .map_err(|error| XValidationFailure::InvalidSchema {
            message: format!("exported schema failed x-validations preflight: {error}"),
        })
}

fn validate_draft202012_schema(schema: &Value) -> Result<(), XValidationFailure> {
    jsonschema::draft202012::meta::validate(schema).map_err(|error| {
        XValidationFailure::InvalidSchema {
            message: format!("derived base schema is not valid Draft 2020-12: {error}"),
        }
    })
}

fn validate_payload_against_schema(
    payload: &Value,
    schema: &Value,
    source: IssueSource,
    branch_rule_ids: Option<&[String]>,
) -> Result<(), XValidationFailure> {
    let validator = jsonschema::draft202012::new(schema).map_err(|error| {
        XValidationFailure::InvalidSchema {
            message: format!("could not build Draft 2020-12 validator: {error}"),
        }
    })?;

    let mut errors = validator.iter_errors(payload).collect::<Vec<_>>();
    errors.sort_by_key(|error| error.instance_path().to_string());
    if errors.is_empty() {
        return Ok(());
    }

    let issues = errors
        .iter()
        .map(|error| ValidationIssue {
            path: json_pointer_to_jsonpath(&error.instance_path().to_string(), payload),
            message: error.to_string(),
            keyword: keyword_from_schema_path(&error.schema_path().to_string()),
            source: source.clone(),
            rule_id: match source {
                IssueSource::Base => None,
                IssueSource::XValidation => {
                    rule_id_from_schema_path(&error.evaluation_path().to_string(), branch_rule_ids)
                }
            },
        })
        .collect();

    Err(XValidationFailure::Validation { issues })
}

fn rule_id_from_schema_path(
    schema_path: &str,
    branch_rule_ids: Option<&[String]>,
) -> Option<String> {
    let branch_rule_ids = branch_rule_ids?;
    let tokens = json_pointer_tokens(schema_path);
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
    json_pointer_tokens(schema_path).pop()
}

fn json_pointer_to_jsonpath(pointer: &str, root: &Value) -> String {
    if pointer.is_empty() {
        return "$".to_string();
    }

    let mut path = "$".to_string();
    let mut current = Some(root);
    for raw_token in pointer.trim_start_matches('/').split('/') {
        let token = unescape_json_pointer_token(raw_token);
        let next = match current {
            Some(Value::Array(values)) if is_json_pointer_array_index(&token) => {
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

fn json_pointer_tokens(pointer: &str) -> Vec<String> {
    if pointer.is_empty() {
        return Vec::new();
    }
    pointer
        .trim_start_matches('/')
        .split('/')
        .map(unescape_json_pointer_token)
        .collect()
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

fn is_json_pointer_array_index(token: &str) -> bool {
    token == "0"
        || (token.starts_with(['1', '2', '3', '4', '5', '6', '7', '8', '9'])
            && token.chars().all(|character| character.is_ascii_digit()))
}

fn unescape_json_pointer_token(token: &str) -> String {
    token.replace("~1", "/").replace("~0", "~")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn xvalidation_schema_uri_constant_matches_meta_schema() {
        let meta_schema = xvalidations_meta_schema().expect("meta-schema JSON is valid");

        assert_eq!(
            meta_schema["$schema"],
            Value::String(crate::meta::DRAFT202012_SCHEMA_URI.to_string())
        );
    }
}
