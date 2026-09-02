use jsonpath_rust::parser::model::{Segment, Selector};
use jsonpath_rust::parser::parse_json_path;
use serde_json::{Map, Value};

use crate::jsonpath::evaluate_jsonpath;
use crate::types::XValidationFailure;

pub(crate) fn interpolate_paths(
    node: &Value,
    payload: &Value,
) -> Result<Value, XValidationFailure> {
    match node {
        Value::Object(object) => interpolate_object(object, payload),
        Value::Array(values) => values
            .iter()
            .map(|value| interpolate_paths(value, payload))
            .collect(),
        _ => Ok(node.clone()),
    }
}

fn interpolate_object(
    object: &Map<String, Value>,
    payload: &Value,
) -> Result<Value, XValidationFailure> {
    if object.len() == 1 {
        if let Some(path_value) = object.get("$path") {
            let path = path_value
                .as_str()
                .expect("a $path operand contains a JSONPath string");
            return interpolate_path(path, payload);
        }
    }

    object
        .iter()
        .map(|(key, value)| {
            interpolate_paths(value, payload).map(|interpolated| (key.clone(), interpolated))
        })
        .collect::<Result<Map<String, Value>, XValidationFailure>>()
        .map(Value::Object)
}

fn interpolate_path(path: &str, payload: &Value) -> Result<Value, XValidationFailure> {
    let matches = evaluate_jsonpath(path, payload)?;
    if is_singular(path)? {
        return Ok(matches
            .into_iter()
            .next()
            .expect("a singular $path operand selects one value")
            .value);
    }
    Ok(Value::Array(
        matches.into_iter().map(|selected| selected.value).collect(),
    ))
}

fn is_singular(path: &str) -> Result<bool, XValidationFailure> {
    let query = parse_json_path(path).map_err(|error| XValidationFailure::JsonPath {
        message: format!("invalid JSONPath query {path:?}: {error}"),
    })?;
    Ok(query.segments.iter().all(|segment| {
        matches!(
            segment,
            Segment::Selector(Selector::Name(_) | Selector::Index(_))
        )
    }))
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::interpolate_paths;

    #[test]
    fn singular_and_many_paths_have_contract_cardinality() {
        let payload = json!({"upper": 3, "values": [1, 2]});
        assert_eq!(
            interpolate_paths(&json!({"maximum": {"$path": "$.upper"}}), &payload)
                .expect("singular path should interpolate"),
            json!({"maximum": 3})
        );
        assert_eq!(
            interpolate_paths(&json!({"enum": {"$path": "$.values[*]"}}), &payload)
                .expect("many path should interpolate"),
            json!({"enum": [1, 2]})
        );
    }

    #[test]
    fn marker_looking_selected_data_is_opaque() {
        let payload = json!({"value": {"$path": "$.other"}, "other": "changed"});
        assert_eq!(
            interpolate_paths(&json!({"const": {"$path": "$.value"}}), &payload)
                .expect("selected data should be returned without reinterpretation"),
            json!({"const": {"$path": "$.other"}})
        );
    }
}
