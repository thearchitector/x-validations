use std::collections::HashSet;

use jsonpath_rust::JsonPath;
use serde_json::Value;

use crate::pointer::{is_array_index, LocationSegment};
use crate::types::XValidationFailure;

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct JsonPathMatch {
    pub value: Value,
    pub location: Vec<LocationSegment>,
    pub normalized_path: String,
}

pub(crate) fn evaluate_jsonpath(
    query: &str,
    value: &Value,
) -> Result<Vec<JsonPathMatch>, XValidationFailure> {
    let raw_matches =
        value
            .query_with_path(query)
            .map_err(|error| XValidationFailure::JsonPath {
                message: format!("invalid JSONPath query {query:?}: {error}"),
            })?;

    let mut matches = Vec::new();
    let mut seen = HashSet::new();
    for raw_match in raw_matches {
        let normalized_path = raw_match.clone().path();
        let location = parse_normalized_path(&normalized_path)?;
        if !seen.insert(location.clone()) {
            continue;
        }
        matches.push(JsonPathMatch {
            value: raw_match.val().clone(),
            location,
            normalized_path,
        });
    }
    Ok(matches)
}

fn parse_normalized_path(path: &str) -> Result<Vec<LocationSegment>, XValidationFailure> {
    if path == "$" {
        return Ok(Vec::new());
    }
    let mut chars = path.char_indices().peekable();
    if chars.next() != Some((0, '$')) {
        return Err(jsonpath_location_error(path));
    }

    let mut location = Vec::new();
    while let Some((_, character)) = chars.peek().copied() {
        match character {
            '.' => {
                chars.next();
                let mut property = String::new();
                while let Some((_, next)) = chars.peek().copied() {
                    if next == '.' || next == '[' {
                        break;
                    }
                    property.push(next);
                    chars.next();
                }
                if property.is_empty() {
                    return Err(jsonpath_location_error(path));
                }
                location.push(LocationSegment::Property(property));
            }
            '[' => {
                chars.next();
                location.push(parse_bracket_segment(path, &mut chars)?);
            }
            _ => return Err(jsonpath_location_error(path)),
        }
    }
    Ok(location)
}

fn parse_bracket_segment(
    path: &str,
    chars: &mut std::iter::Peekable<std::str::CharIndices<'_>>,
) -> Result<LocationSegment, XValidationFailure> {
    match chars.peek().copied() {
        Some((_, '\'' | '"')) => parse_quoted_property(path, chars),
        Some(_) => parse_index(path, chars),
        None => Err(jsonpath_location_error(path)),
    }
}

fn parse_quoted_property(
    path: &str,
    chars: &mut std::iter::Peekable<std::str::CharIndices<'_>>,
) -> Result<LocationSegment, XValidationFailure> {
    let Some((_, quote)) = chars.next() else {
        return Err(jsonpath_location_error(path));
    };
    let mut property = String::new();
    let mut closed = false;
    while let Some((_, character)) = chars.next() {
        if character == '\\' {
            let Some((_, escaped)) = chars.next() else {
                return Err(jsonpath_location_error(path));
            };
            let decoded = match escaped {
                'b' => '\u{0008}',
                'f' => '\u{000c}',
                'n' => '\n',
                'r' => '\r',
                't' => '\t',
                '\\' => '\\',
                '\'' => '\'',
                '"' => '"',
                'u' => parse_unicode_escape(path, chars)?,
                _ => return Err(jsonpath_location_error(path)),
            };
            property.push(decoded);
        } else if character == quote {
            closed = true;
            break;
        } else {
            property.push(character);
        }
    }
    if !closed || chars.next().map(|(_, character)| character) != Some(']') {
        return Err(jsonpath_location_error(path));
    }
    Ok(LocationSegment::Property(property))
}

fn parse_unicode_escape(
    path: &str,
    chars: &mut std::iter::Peekable<std::str::CharIndices<'_>>,
) -> Result<char, XValidationFailure> {
    let digits = (0..4)
        .map(|_| chars.next().map(|(_, character)| character))
        .collect::<Option<String>>()
        .ok_or_else(|| jsonpath_location_error(path))?;
    let codepoint = u32::from_str_radix(&digits, 16).map_err(|_| jsonpath_location_error(path))?;
    char::from_u32(codepoint).ok_or_else(|| jsonpath_location_error(path))
}

fn parse_index(
    path: &str,
    chars: &mut std::iter::Peekable<std::str::CharIndices<'_>>,
) -> Result<LocationSegment, XValidationFailure> {
    let mut index = String::new();
    while let Some((_, character)) = chars.peek().copied() {
        if character == ']' {
            break;
        }
        index.push(character);
        chars.next();
    }
    if chars.next().map(|(_, character)| character) != Some(']') || !is_array_index(&index) {
        return Err(jsonpath_location_error(path));
    }
    let index = index
        .parse::<usize>()
        .map_err(|_| jsonpath_location_error(path))?;
    Ok(LocationSegment::Index(index))
}

fn jsonpath_location_error(path: &str) -> XValidationFailure {
    XValidationFailure::JsonPath {
        message: format!("unsupported normalized JSONPath location: {path}"),
    }
}

#[cfg(test)]
mod tests {
    use serde_json::{json, Value};

    use super::evaluate_jsonpath;

    fn values(query: &str, value: &Value) -> Vec<Value> {
        evaluate_jsonpath(query, value)
            .expect("characterized RFC 9535 query should evaluate")
            .into_iter()
            .map(|matched| matched.value)
            .collect()
    }

    #[test]
    fn dependency_handles_escaped_quotes_and_unicode_escapes() {
        let value = json!({"a\"b": 1, "alpha": 2});

        assert_eq!(values(r#"$["a\"b"]"#, &value), [json!(1)]);
        assert_eq!(values(r#"$["\u0061lpha"]"#, &value), [json!(2)]);
    }

    #[test]
    fn dependency_handles_unions_recursive_descent_and_special_names() {
        let value = json!({"a": 1, "b": 2, "a.b": 3, "nested": {"id": 4}});

        assert_eq!(values(r#"$["a","b"]"#, &value), [json!(1), json!(2)]);
        assert_eq!(values("$..id", &value), [json!(4)]);
        assert_eq!(values(r#"$["a.b"]"#, &value), [json!(3)]);
    }

    #[test]
    fn dependency_handles_filters_slices_and_wildcards() {
        let value = json!({
            "items": [
                {"kind": "other", "id": 0},
                {"kind": "field", "id": 1},
                {"kind": "field", "id": 2}
            ]
        });

        assert_eq!(
            values(r#"$.items[?(@.kind == "field")].id"#, &value),
            [json!(1), json!(2)]
        );
        assert_eq!(values("$.items[1:3].id", &value), [json!(1), json!(2)]);
        assert_eq!(
            values("$.items[*].id", &value),
            [json!(0), json!(1), json!(2)]
        );
    }
}
