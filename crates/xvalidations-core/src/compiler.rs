use serde_json::{json, Map, Value};

use crate::artifact::extract_xvalidations;
use crate::jsonpath::{evaluate_jsonpath, JsonPathMatch, LocationSegment};
use crate::meta::DRAFT202012_SCHEMA_URI;
use crate::resolve::resolve_placeholders;
use crate::target::location_to_schema_overlay;
use crate::types::XValidationFailure;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CompiledSchema {
    pub schema: Value,
    pub branch_rule_ids: Vec<String>,
}

pub fn generate_compiled_schema(
    schema: &Value,
    payload: &Value,
) -> Result<CompiledSchema, XValidationFailure> {
    let mut overlays = Vec::new();
    let mut branch_rule_ids = Vec::new();

    for rule in extract_xvalidations(schema)? {
        let target_matches = evaluate_jsonpath(&rule.target, payload)?;
        let rule_overlays = if let Some(path) = unique_by_projection_path(&rule.assertion)? {
            compile_unique_by(&target_matches, path)?
        } else {
            let assertion = resolve_placeholders(&rule.assertion, payload, schema)?;
            validate_assertion_schema(&assertion)?;
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
        let copied_defs = referenced_defs(schema, &Value::Array(overlays.clone()))?;
        if !copied_defs.is_empty() {
            compiled["$defs"] = Value::Object(copied_defs);
        }
        compiled["allOf"] = Value::Array(overlays);
    }
    validate_compiled_schema_document(&compiled)?;

    Ok(CompiledSchema {
        schema: compiled,
        branch_rule_ids,
    })
}

fn validate_assertion_schema(assertion: &Value) -> Result<(), XValidationFailure> {
    jsonschema::draft202012::meta::validate(assertion).map_err(|error| {
        XValidationFailure::InvalidSchema {
            message: format!("resolved assertion schema is not valid Draft 2020-12: {error}"),
        }
    })
}

fn validate_compiled_schema_document(compiled: &Value) -> Result<(), XValidationFailure> {
    jsonschema::draft202012::meta::validate(compiled).map_err(|error| {
        XValidationFailure::InvalidSchema {
            message: format!("compiled x-validation schema is not valid Draft 2020-12: {error}"),
        }
    })
}

fn referenced_defs(schema: &Value, node: &Value) -> Result<Map<String, Value>, XValidationFailure> {
    let mut names = Vec::new();
    collect_referenced_def_names(node, &mut names);

    let source_defs = schema.get("$defs").and_then(Value::as_object);
    let mut copied = Map::new();
    let mut index = 0;
    while index < names.len() {
        let name = names[index].clone();
        index += 1;
        if copied.contains_key(&name) {
            continue;
        }
        let Some(definition) = source_defs.and_then(|defs| defs.get(&name)) else {
            return Err(XValidationFailure::InvalidSchema {
                message: format!("compiled assertion references missing $defs entry {name:?}"),
            });
        };
        collect_referenced_def_names(definition, &mut names);
        copied.insert(name, definition.clone());
    }
    Ok(copied)
}

fn collect_referenced_def_names(node: &Value, names: &mut Vec<String>) {
    match node {
        Value::Object(object) => {
            for key in ["$ref", "$dynamicRef"] {
                if let Some(Value::String(reference)) = object.get(key) {
                    if let Some(def_name) = def_name_from_ref(reference) {
                        if !names.contains(&def_name) {
                            names.push(def_name);
                        }
                    }
                }
            }
            for value in object.values() {
                collect_referenced_def_names(value, names);
            }
        }
        Value::Array(values) => {
            for value in values {
                collect_referenced_def_names(value, names);
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
