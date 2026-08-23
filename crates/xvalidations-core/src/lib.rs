mod artifact;
mod compiler;
mod jsonpath;
mod meta;
mod pointer;
mod resolve;
mod types;

use serde_json::Value;

pub use types::{ValidationError, XValidationBindingFailure, XValidationFailure};

use crate::artifact::{prepare_schema, PreparedSchema};
use crate::compiler::{validate_occurrences, ResourceOccurrence};
use crate::pointer::pointer_to_jsonpath;

/// Validate an instance against its base schema and all matched X-Validation rules.
///
/// # Errors
///
/// Returns schema, rule, `JSONPath`, binding-resolution, or validation failures.
pub fn xvalidate(payload: &Value, schema: &Value) -> Result<(), XValidationFailure> {
    let prepared = prepare_schema(schema)?;
    let base_validator = jsonschema::options()
        .with_draft(jsonschema::Draft::Draft202012)
        .with_registry(&prepared.registry)
        .build(&prepared.base_schema)
        .map_err(|error| XValidationFailure::InvalidSchema {
            message: format!("normalized base schema is not valid Draft 2020-12: {error}"),
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

    let evaluation = base_validator.evaluate(payload);
    let occurrences = resource_occurrences(&evaluation, &prepared)?;
    let errors = validate_occurrences(&prepared, payload, &occurrences)?;
    if errors.is_empty() {
        Ok(())
    } else {
        Err(XValidationFailure::Validation {
            errors: sorted_errors(errors),
        })
    }
}

fn resource_occurrences(
    evaluation: &jsonschema::Evaluation,
    prepared: &PreparedSchema,
) -> Result<Vec<ResourceOccurrence>, XValidationFailure> {
    let mut occurrences = Vec::new();
    for annotation in evaluation.iter_annotations() {
        let Some(object) = annotation.annotations.value().as_object() else {
            continue;
        };
        if !object.contains_key("x-validations") {
            continue;
        }

        let resource_id = annotation
            .absolute_keyword_location
            .as_ref()
            .and_then(|location| prepared.resource_id_for_absolute_location(location.as_str()))
            .or_else(|| prepared.resource_id_for_schema_location(annotation.schema_location))
            .ok_or_else(|| XValidationFailure::InvalidSchema {
                message: format!(
                    "X-Validations annotation at {} does not identify a prepared resource",
                    annotation.schema_location
                ),
            })?;
        occurrences.push(ResourceOccurrence {
            resource_id: resource_id.to_string(),
            instance_pointer: annotation.instance_location.as_str().to_string(),
        });
    }
    Ok(occurrences)
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
