mod compiler;
mod interpolate;
mod jsonpath;
mod pointer;
mod types;

use serde_json::Value;

pub use types::{ValidationError, XValidationFailure};

use crate::compiler::{validate_rules, ValidationRule};
use crate::pointer::pointer_to_jsonpath;

const DRAFT202012_SCHEMA_URI: &str = "https://json-schema.org/draft/2020-12/schema";
const XVALIDATIONS_SCHEMA_URI: &str = "https://thearchitector.dev/xvalidations/schema.json";

struct RuntimeSchema {
    base_schema: Value,
    rules: Vec<ValidationRule>,
}

/// Validate an instance against its base schema and root X-Validation rules.
///
/// # Errors
///
/// Returns schema, rule, JSONPath, or validation failures.
pub fn xvalidate(payload: &Value, schema: &Value) -> Result<(), XValidationFailure> {
    let runtime = split_root_schema(schema)?;
    let base_validator = jsonschema::options()
        .with_draft(jsonschema::Draft::Draft202012)
        .build(&runtime.base_schema)
        .map_err(|error| XValidationFailure::InvalidSchema {
            message: error.to_string(),
        })?;

    let base_errors = base_validator
        .iter_errors(payload)
        .map(|error| ValidationError {
            path: pointer_to_jsonpath(&error.instance_path().to_string(), payload),
            message: error.to_string(),
            rule_id: None,
        })
        .collect::<Vec<_>>();
    if !base_errors.is_empty() {
        return Err(XValidationFailure::Validation {
            errors: sorted_errors(base_errors),
        });
    }

    let errors = validate_rules(&runtime.rules, payload)?;
    if errors.is_empty() {
        Ok(())
    } else {
        Err(XValidationFailure::Validation {
            errors: sorted_errors(errors),
        })
    }
}

fn split_root_schema(schema: &Value) -> Result<RuntimeSchema, XValidationFailure> {
    if schema.get("$schema").and_then(Value::as_str) != Some(XVALIDATIONS_SCHEMA_URI) {
        return Ok(RuntimeSchema {
            base_schema: schema.clone(),
            rules: Vec::new(),
        });
    }

    let mut base_schema = schema.clone();
    let object = base_schema
        .as_object_mut()
        .expect("an x-validations root schema is an object");
    object.insert(
        "$schema".to_string(),
        Value::String(DRAFT202012_SCHEMA_URI.to_string()),
    );
    let rules = object
        .remove("x-validations")
        .expect("an x-validations root schema declares rules");
    let rules = serde_json::from_value(rules).map_err(|error| XValidationFailure::InvalidRule {
        message: error.to_string(),
    })?;
    Ok(RuntimeSchema { base_schema, rules })
}

fn sorted_errors(mut errors: Vec<ValidationError>) -> Vec<ValidationError> {
    errors.sort_by(|left, right| {
        (
            left.path.as_str(),
            left.rule_id.as_deref().unwrap_or(""),
            left.message.as_str(),
        )
            .cmp(&(
                right.path.as_str(),
                right.rule_id.as_deref().unwrap_or(""),
                right.message.as_str(),
            ))
    });
    errors
}
