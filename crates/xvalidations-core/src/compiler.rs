use std::collections::{HashSet, VecDeque};

use serde_json::{json, Map, Value};

use crate::jsonpath::{evaluate_jsonpath, JsonPathMatch, LocationSegment};
use crate::meta::DRAFT202012_SCHEMA_URI;
use crate::pointer::referenced_defs;
use crate::resolve::resolve_placeholders;
use crate::target::location_to_schema_overlay;
use crate::types::{XValidationFailure, XValidationRule};

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct CompiledSchema {
    pub schema: Value,
    pub branch_rule_ids: Vec<String>,
}

pub(crate) fn generate_compiled_schema(
    schema: &Value,
    payload: &Value,
    rules: &[XValidationRule],
) -> Result<CompiledSchema, XValidationFailure> {
    let mut overlays = Vec::new();
    let mut branch_rule_ids = Vec::new();

    for rule in rules {
        let target_matches = evaluate_jsonpath(&rule.target, payload)?;
        let rule_overlays = if let Some(path) = unique_by_projection_path(&rule.assertion)? {
            compile_unique_by(&target_matches, path)?
        } else {
            let assertion = resolve_placeholders(&rule.assertion, payload, schema)?;
            target_matches
                .iter()
                .map(|target_match| location_to_schema_overlay(&target_match.location, &assertion))
                .collect()
        };

        for overlay in rule_overlays {
            overlays.push(overlay);
            branch_rule_ids.push(rule.id.clone());
        }
    }

    let mut compiled = json!({
        "$schema": DRAFT202012_SCHEMA_URI
    });
    if !overlays.is_empty() {
        let copied_defs = copy_referenced_defs(schema, &overlays)?;
        if !copied_defs.is_empty() {
            compiled["$defs"] = Value::Object(copied_defs);
        }
        compiled["allOf"] = Value::Array(overlays);
    }
    Ok(CompiledSchema {
        schema: compiled,
        branch_rule_ids,
    })
}

fn copy_referenced_defs(
    schema: &Value,
    overlays: &[Value],
) -> Result<Map<String, Value>, XValidationFailure> {
    let mut names = overlays
        .iter()
        .flat_map(referenced_defs)
        .collect::<VecDeque<_>>();
    let mut discovered = names.iter().cloned().collect::<HashSet<_>>();

    let source_defs = schema.get("$defs").and_then(Value::as_object);
    let mut copied = Map::new();
    while let Some(name) = names.pop_front() {
        let Some(definition) = source_defs.and_then(|defs| defs.get(&name)) else {
            return Err(XValidationFailure::InvalidSchema {
                message: format!("compiled assertion references missing $defs entry {name:?}"),
            });
        };
        for referenced_name in referenced_defs(definition) {
            if discovered.insert(referenced_name.clone()) {
                names.push_back(referenced_name);
            }
        }
        copied.insert(name, definition.clone());
    }
    Ok(copied)
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

fn compile_unique_by(
    target_matches: &[JsonPathMatch],
    projection_path: &str,
) -> Result<Vec<Value>, XValidationFailure> {
    let mut groups: Vec<(Value, Vec<Vec<LocationSegment>>)> = Vec::new();
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
        if let Some((_, locations)) = groups
            .iter_mut()
            .find(|(group_value, _)| *group_value == projected)
        {
            locations.push(target_match.location.clone());
        } else {
            groups.push((projected, vec![target_match.location.clone()]));
        }
    }

    let mut overlays = Vec::new();
    for (_, locations) in groups {
        if locations.len() > 1 {
            for location in locations {
                overlays.push(location_to_schema_overlay(&location, &Value::Bool(false)));
            }
        }
    }
    Ok(overlays)
}
