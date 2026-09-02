use serde::Deserialize;
use serde_json::Value;

use crate::interpolate::interpolate_paths;
use crate::jsonpath::{evaluate_jsonpath, JsonPathMatch};
use crate::pointer::{location_from_pointer, location_to_jsonpath, LocationSegment};
use crate::types::{ValidationError, XValidationFailure};

#[derive(Debug, Clone, PartialEq, Deserialize)]
pub(crate) struct ValidationRule {
    pub(crate) id: String,
    pub(crate) target: String,
    #[serde(rename = "assert")]
    pub(crate) assertion: Value,
}

pub(crate) fn validate_rules(
    rules: &[ValidationRule],
    payload: &Value,
) -> Result<Vec<ValidationError>, XValidationFailure> {
    let mut errors = Vec::new();
    for rule in rules {
        let target_matches = evaluate_jsonpath(&rule.target, payload)?;
        if let Some(projection_path) = rule.assertion.get("x-uniqueBy").and_then(Value::as_str) {
            validate_unique_by(&target_matches, projection_path, &rule.id, &mut errors)?;
            continue;
        }

        let assertion = interpolate_paths(&rule.assertion, payload)?;
        let validator = jsonschema::options()
            .with_draft(jsonschema::Draft::Draft202012)
            .build(&assertion)
            .map_err(|error| XValidationFailure::InvalidRule {
                message: error.to_string(),
            })?;

        for target_match in &target_matches {
            for error in validator.iter_errors(&target_match.value) {
                let mut location = target_match.location.clone();
                location.extend(location_from_pointer(
                    &error.instance_path().to_string(),
                    &target_match.value,
                ));
                errors.push(ValidationError {
                    path: location_to_jsonpath(&location),
                    message: error.to_string(),
                    rule_id: Some(rule.id.clone()),
                });
            }
        }
    }
    Ok(errors)
}

fn validate_unique_by(
    target_matches: &[JsonPathMatch],
    projection_path: &str,
    rule_id: &str,
    errors: &mut Vec<ValidationError>,
) -> Result<(), XValidationFailure> {
    for target_match in target_matches {
        let items = target_match
            .value
            .as_array()
            .expect("an x-uniqueBy target is an array");
        let mut groups: Vec<(Value, Vec<usize>)> = Vec::new();
        for (index, item) in items.iter().enumerate() {
            let projected = evaluate_jsonpath(projection_path, item)?
                .into_iter()
                .next()
                .expect("x-uniqueBy projects one value per item")
                .value;
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
                let mut location = target_match.location.clone();
                location.push(LocationSegment::Index(index));
                errors.push(ValidationError {
                    path: location_to_jsonpath(&location),
                    message: message.clone(),
                    rule_id: Some(rule_id.to_string()),
                });
            }
        }
    }
    Ok(())
}
