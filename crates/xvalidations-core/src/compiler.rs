use serde_json::Value;

use crate::artifact::{normalize_assertion_uris, PreparedResource, PreparedSchema};
use crate::jsonpath::{evaluate_jsonpath, JsonPathMatch};
use crate::pointer::{location_from_pointer, location_to_jsonpath, LocationSegment};
use crate::resolve::resolve_placeholders;
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

        let mut assertion = resolve_placeholders(&rule.assertion, local_payload, &resource.source)?;
        normalize_assertion_uris(&mut assertion, &resource.id, &prepared.registry)?;
        let validator = jsonschema::options()
            .with_draft(jsonschema::Draft::Draft202012)
            .with_registry(&prepared.registry)
            .build(&assertion)
            .map_err(|error| XValidationFailure::InvalidSchema {
                message: format!(
                    "assertion for rule {:?} is not valid Draft 2020-12: {error}",
                    rule.id
                ),
            })?;

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
    let mut groups: Vec<(Value, Vec<&JsonPathMatch>)> = Vec::new();
    for target_match in target_matches {
        let projection_matches = evaluate_jsonpath(projection_path, &target_match.value)?;
        if projection_matches.len() != 1 {
            return Err(XValidationFailure::InvalidRule {
                message: format!(
                    "x-uniqueBy projection must return exactly one value for {}",
                    target_match.normalized_path
                ),
            });
        }
        let projected = projection_matches[0].value.clone();
        if let Some((_, matches)) = groups
            .iter_mut()
            .find(|(group_value, _)| *group_value == projected)
        {
            matches.push(target_match);
        } else {
            groups.push((projected, vec![target_match]));
        }
    }

    for (value, matches) in groups {
        if matches.len() < 2 {
            continue;
        }
        let message =
            format!("x-uniqueBy projection {projection_path:?} produced duplicate value {value}");
        for target_match in matches {
            let mut absolute_location = occurrence_location.to_vec();
            absolute_location.extend(target_match.location.iter().cloned());
            errors.push(ValidationError {
                path: location_to_jsonpath(&absolute_location),
                message: message.clone(),
                rule_id: Some(rule_id.to_string()),
            });
        }
    }
    Ok(())
}
