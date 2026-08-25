use serde_json::Value;

use crate::artifact::{PreparedResource, PreparedSchema};
use crate::interpolate::interpolate_paths;
use crate::jsonpath::{evaluate_jsonpath, JsonPathMatch};
use crate::pointer::{location_from_pointer, location_to_jsonpath, LocationSegment};
use crate::types::{ValidationError, XValidationFailure};

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ResourceOccurrence {
    pub(crate) resource_id: String,
    pub(crate) instance_pointer: String,
}

pub(crate) fn validate_occurrences(
    prepared: &PreparedSchema,
    payload: &Value,
    occurrences: &[ResourceOccurrence],
) -> Result<Vec<ValidationError>, XValidationFailure> {
    let mut errors = Vec::new();
    for occurrence in occurrences {
        let resource = prepared.resource(&occurrence.resource_id).ok_or_else(|| {
            XValidationFailure::InvalidSchema {
                message: format!(
                    "base evaluation selected unknown Schema Resource {:?}",
                    occurrence.resource_id
                ),
            }
        })?;
        let local_payload = payload
            .pointer(&occurrence.instance_pointer)
            .ok_or_else(|| XValidationFailure::InvalidSchema {
                message: format!(
                    "base evaluation selected missing payload location {:?}",
                    occurrence.instance_pointer
                ),
            })?;
        let occurrence_location = location_from_pointer(&occurrence.instance_pointer, payload);
        validate_resource_occurrence(
            prepared,
            resource,
            local_payload,
            &occurrence_location,
            &mut errors,
        )?;
    }
    Ok(errors)
}

fn validate_resource_occurrence(
    prepared: &PreparedSchema,
    resource: &PreparedResource,
    local_payload: &Value,
    occurrence_location: &[LocationSegment],
    errors: &mut Vec<ValidationError>,
) -> Result<(), XValidationFailure> {
    for rule in &resource.rules {
        let target_matches = evaluate_jsonpath(&rule.target, local_payload)?;
        if target_matches.is_empty() {
            continue;
        }

        if let Some(projection_path) = unique_by_projection_path(&rule.assertion)? {
            validate_unique_by(
                &target_matches,
                projection_path,
                occurrence_location,
                &rule.id,
                errors,
            )?;
            continue;
        }

        let assertion = match interpolate_paths(&rule.assertion, local_payload) {
            Ok(assertion) => assertion,
            Err(XValidationFailure::InvalidRule { message }) => {
                push_assertion_construction_errors(
                    &target_matches,
                    occurrence_location,
                    &rule.id,
                    &message,
                    errors,
                );
                continue;
            }
            Err(error) => return Err(error),
        };
        let validator = match jsonschema::options()
            .with_draft(jsonschema::Draft::Draft202012)
            .with_registry(&prepared.registry)
            .build(&assertion)
        {
            Ok(validator) => validator,
            Err(error) => {
                push_assertion_construction_errors(
                    &target_matches,
                    occurrence_location,
                    &rule.id,
                    &format!("interpolated assertion is not valid Draft 2020-12: {error}"),
                    errors,
                );
                continue;
            }
        };

        for target_match in &target_matches {
            for error in validator.iter_errors(&target_match.value) {
                let mut absolute_location = occurrence_location.to_vec();
                absolute_location.extend(target_match.location.iter().cloned());
                absolute_location.extend(location_from_pointer(
                    &error.instance_path().to_string(),
                    &target_match.value,
                ));
                errors.push(ValidationError {
                    path: location_to_jsonpath(&absolute_location),
                    message: error.to_string(),
                    rule_id: Some(rule.id.clone()),
                });
            }
        }
    }
    Ok(())
}

fn push_assertion_construction_errors(
    target_matches: &[JsonPathMatch],
    occurrence_location: &[LocationSegment],
    rule_id: &str,
    message: &str,
    errors: &mut Vec<ValidationError>,
) {
    for target_match in target_matches {
        let mut absolute_location = occurrence_location.to_vec();
        absolute_location.extend(target_match.location.iter().cloned());
        errors.push(ValidationError {
            path: location_to_jsonpath(&absolute_location),
            message: message.to_string(),
            rule_id: Some(rule_id.to_string()),
        });
    }
}

fn unique_by_projection_path(assertion: &Value) -> Result<Option<&str>, XValidationFailure> {
    let Some(object) = assertion.as_object() else {
        return Ok(None);
    };
    if object.len() == 1 {
        return match object.get("x-uniqueBy") {
            Some(Value::String(path)) => Ok(Some(path.as_str())),
            Some(_) => Err(XValidationFailure::InvalidRule {
                message: "x-uniqueBy value must be a JSONPath string".to_string(),
            }),
            None => Ok(None),
        };
    }
    Ok(None)
}

fn validate_unique_by(
    target_matches: &[JsonPathMatch],
    projection_path: &str,
    occurrence_location: &[LocationSegment],
    rule_id: &str,
    errors: &mut Vec<ValidationError>,
) -> Result<(), XValidationFailure> {
    for target_match in target_matches {
        let Some(items) = target_match.value.as_array() else {
            return Err(XValidationFailure::InvalidRule {
                message: format!(
                    "x-uniqueBy target must be an array at {}",
                    target_match.normalized_path
                ),
            });
        };
        let mut groups: Vec<(Value, Vec<usize>)> = Vec::new();
        for (index, item) in items.iter().enumerate() {
            let projection_matches = evaluate_jsonpath(projection_path, item)?;
            if projection_matches.len() != 1 {
                return Err(XValidationFailure::InvalidRule {
                    message: format!(
                        "x-uniqueBy projection must return exactly one value for {}[{index}]",
                        target_match.normalized_path
                    ),
                });
            }
            let projected = projection_matches[0].value.clone();
            if let Some((_, matches)) = groups
                .iter_mut()
                .find(|(group_value, _)| *group_value == projected)
            {
                matches.push(index);
            } else {
                groups.push((projected, vec![index]));
            }
        }

        for (value, matches) in groups {
            if matches.len() < 2 {
                continue;
            }
            let message = format!(
                "x-uniqueBy projection {projection_path:?} produced duplicate value {value}"
            );
            for index in matches {
                let mut absolute_location = occurrence_location.to_vec();
                absolute_location.extend(target_match.location.iter().cloned());
                absolute_location.push(LocationSegment::Index(index));
                errors.push(ValidationError {
                    path: location_to_jsonpath(&absolute_location),
                    message: message.clone(),
                    rule_id: Some(rule_id.to_string()),
                });
            }
        }
    }
    Ok(())
}
