use jsonpath_rust::JsonPath;
use serde_json::Value;

use crate::types::XValidationFailure;

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum LocationSegment {
    Property(String),
    Index(usize),
}

#[derive(Debug, Clone, PartialEq)]
pub struct JsonPathMatch {
    pub value: Value,
    pub location: Vec<LocationSegment>,
    pub normalized_path: String,
}

pub fn evaluate_jsonpath(
    query: &str,
    value: &Value,
) -> Result<Vec<JsonPathMatch>, XValidationFailure> {
    let normalized_query = normalize_bracket_string_selectors(query)?;
    let raw_matches =
        value
            .query_with_path(&normalized_query)
            .map_err(|error| XValidationFailure::JsonPath {
                message: format!("invalid JSONPath query {query:?}: {error}"),
            })?;
    if raw_matches.is_empty() && query.contains("[\"") {
        if let Some(matches) = evaluate_simple_jsonpath_with_bracket_strings(query, value)? {
            return Ok(matches);
        }
    }

    let mut matches = Vec::new();
    let mut seen = Vec::new();
    for raw_match in raw_matches {
        let normalized_path = raw_match.clone().path();
        let location = parse_normalized_path(&normalized_path)?;
        if seen.contains(&location) {
            continue;
        }
        seen.push(location.clone());
        matches.push(JsonPathMatch {
            value: raw_match.val().clone(),
            location,
            normalized_path,
        });
    }
    Ok(matches)
}

#[derive(Debug)]
enum SimpleStep {
    Properties(Vec<String>),
    Index(usize),
    Wildcard,
}

fn evaluate_simple_jsonpath_with_bracket_strings(
    query: &str,
    value: &Value,
) -> Result<Option<Vec<JsonPathMatch>>, XValidationFailure> {
    let Some(steps) = parse_simple_steps(query)? else {
        return Ok(None);
    };

    let mut current = vec![(value, Vec::new())];
    for step in steps {
        let mut next = Vec::new();
        for (node, location) in current {
            match &step {
                SimpleStep::Properties(properties) => {
                    if let Value::Object(object) = node {
                        for property in properties {
                            if let Some(value) = object.get(property) {
                                let mut child_location = location.clone();
                                child_location.push(LocationSegment::Property(property.clone()));
                                next.push((value, child_location));
                            }
                        }
                    }
                }
                SimpleStep::Index(index) => {
                    if let Value::Array(values) = node {
                        if let Some(value) = values.get(*index) {
                            let mut child_location = location.clone();
                            child_location.push(LocationSegment::Index(*index));
                            next.push((value, child_location));
                        }
                    }
                }
                SimpleStep::Wildcard => match node {
                    Value::Array(values) => {
                        for (index, value) in values.iter().enumerate() {
                            let mut child_location = location.clone();
                            child_location.push(LocationSegment::Index(index));
                            next.push((value, child_location));
                        }
                    }
                    Value::Object(object) => {
                        for (property, value) in object {
                            let mut child_location = location.clone();
                            child_location.push(LocationSegment::Property(property.clone()));
                            next.push((value, child_location));
                        }
                    }
                    _ => {}
                },
            }
        }
        current = next;
    }

    let mut matches = Vec::new();
    let mut seen = Vec::new();
    for (value, location) in current {
        if seen.contains(&location) {
            continue;
        }
        seen.push(location.clone());
        matches.push(JsonPathMatch {
            value: value.clone(),
            normalized_path: location_to_normalized_path(&location),
            location,
        });
    }
    Ok(Some(matches))
}

fn parse_simple_steps(query: &str) -> Result<Option<Vec<SimpleStep>>, XValidationFailure> {
    let chars = query.chars().collect::<Vec<_>>();
    if chars.first() != Some(&'$') {
        return Ok(None);
    }
    let mut steps = Vec::new();
    let mut index = 1;
    while index < chars.len() {
        match chars[index] {
            '.' => {
                index += 1;
                if chars.get(index) == Some(&'.') {
                    return Ok(None);
                }
                let start = index;
                while index < chars.len() && chars[index] != '.' && chars[index] != '[' {
                    index += 1;
                }
                if start == index {
                    return Err(jsonpath_query_error(query));
                }
                steps.push(SimpleStep::Properties(vec![chars[start..index]
                    .iter()
                    .collect()]));
            }
            '[' => {
                let Some((step, next_index)) = parse_simple_bracket_step(query, &chars, index)?
                else {
                    return Ok(None);
                };
                steps.push(step);
                index = next_index;
            }
            _ => return Ok(None),
        }
    }
    Ok(Some(steps))
}

fn parse_simple_bracket_step(
    query: &str,
    chars: &[char],
    mut index: usize,
) -> Result<Option<(SimpleStep, usize)>, XValidationFailure> {
    index += 1;
    index = skip_jsonpath_whitespace(chars, index);
    if chars.get(index) == Some(&'*') {
        let closing_index = skip_jsonpath_whitespace(chars, index + 1);
        if chars.get(closing_index) != Some(&']') {
            return Err(jsonpath_query_error(query));
        }
        return Ok(Some((SimpleStep::Wildcard, closing_index + 1)));
    }
    if chars
        .get(index)
        .is_some_and(|character| character.is_ascii_digit())
    {
        let start = index;
        while chars
            .get(index)
            .is_some_and(|character| character.is_ascii_digit())
        {
            index += 1;
        }
        let closing_index = skip_jsonpath_whitespace(chars, index);
        if chars.get(closing_index) != Some(&']') {
            return Err(jsonpath_query_error(query));
        }
        let token = chars[start..index].iter().collect::<String>();
        if !is_json_pointer_array_index(&token) {
            return Err(jsonpath_query_error(query));
        }
        let parsed = token
            .parse::<usize>()
            .map_err(|_| jsonpath_query_error(query))?;
        return Ok(Some((SimpleStep::Index(parsed), closing_index + 1)));
    }
    if chars.get(index) != Some(&'"') && chars.get(index) != Some(&'\'') {
        return Ok(None);
    }

    let mut properties = Vec::new();
    loop {
        let Some((property, next_index)) = parse_selector_property(chars, index)? else {
            return Err(jsonpath_query_error(query));
        };
        properties.push(property);
        index = skip_jsonpath_whitespace(chars, next_index);
        match chars.get(index) {
            Some(',') => index = skip_jsonpath_whitespace(chars, index + 1),
            Some(']') => return Ok(Some((SimpleStep::Properties(properties), index + 1))),
            _ => return Err(jsonpath_query_error(query)),
        }
    }
}

fn parse_selector_property(
    chars: &[char],
    index: usize,
) -> Result<Option<(String, usize)>, XValidationFailure> {
    match chars.get(index) {
        Some('"') => parse_double_quoted_selector_property(chars, index),
        Some('\'') => parse_single_quoted_selector_property(chars, index),
        _ => Ok(None),
    }
}

fn parse_single_quoted_selector_property(
    chars: &[char],
    mut index: usize,
) -> Result<Option<(String, usize)>, XValidationFailure> {
    if chars.get(index) != Some(&'\'') {
        return Ok(None);
    }
    index += 1;
    let mut property = String::new();
    while let Some(character) = chars.get(index).copied() {
        if character == '\\' {
            let Some(escaped) = chars.get(index + 1).copied() else {
                return Err(XValidationFailure::JsonPath {
                    message: "unterminated escape in JSONPath bracket selector".to_string(),
                });
            };
            property.push(escaped);
            index += 2;
        } else if character == '\'' {
            return Ok(Some((property, index + 1)));
        } else {
            property.push(character);
            index += 1;
        }
    }
    Err(XValidationFailure::JsonPath {
        message: "unterminated JSONPath bracket selector".to_string(),
    })
}

fn location_to_normalized_path(location: &[LocationSegment]) -> String {
    let mut path = "$".to_string();
    for segment in location {
        match segment {
            LocationSegment::Property(property) if is_identifier(property) => {
                path.push('.');
                path.push_str(property);
            }
            LocationSegment::Property(property) => {
                let quoted = serde_json::to_string(property)
                    .expect("serializing a JSONPath property string cannot fail");
                path.push_str(&format!("[{quoted}]"));
            }
            LocationSegment::Index(index) => path.push_str(&format!("[{index}]")),
        }
    }
    path
}

fn is_identifier(token: &str) -> bool {
    let mut chars = token.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    (first == '_' || first.is_ascii_alphabetic())
        && chars.all(|character| character == '_' || character.is_ascii_alphanumeric())
}

fn normalize_bracket_string_selectors(query: &str) -> Result<String, XValidationFailure> {
    let mut normalized = String::new();
    let chars = query.chars().collect::<Vec<_>>();
    let mut index = 0;
    while index < chars.len() {
        let selector_index = skip_jsonpath_whitespace(&chars, index + 1);
        if chars[index] == '[' && chars.get(selector_index) == Some(&'"') {
            let (selector, next_index) = normalize_double_quoted_selector(query, &chars, index)?;
            normalized.push_str(&selector);
            index = next_index;
        } else {
            normalized.push(chars[index]);
            index += 1;
        }
    }
    Ok(normalized)
}

fn normalize_double_quoted_selector(
    query: &str,
    chars: &[char],
    mut index: usize,
) -> Result<(String, usize), XValidationFailure> {
    let mut selector = String::from("[");
    index += 1;
    index = skip_jsonpath_whitespace(chars, index);
    loop {
        let Some((property, next_index)) = parse_double_quoted_selector_property(chars, index)?
        else {
            return Err(jsonpath_query_error(query));
        };
        selector.push('\'');
        selector.push_str(&escape_single_quoted_selector_property(&property));
        selector.push('\'');
        index = skip_jsonpath_whitespace(chars, next_index);
        match chars.get(index) {
            Some(',') => {
                selector.push(',');
                index = skip_jsonpath_whitespace(chars, index + 1);
            }
            Some(']') => {
                selector.push(']');
                return Ok((selector, index + 1));
            }
            _ => return Err(jsonpath_query_error(query)),
        }
    }
}

fn parse_double_quoted_selector_property(
    chars: &[char],
    mut index: usize,
) -> Result<Option<(String, usize)>, XValidationFailure> {
    if chars.get(index) != Some(&'"') {
        return Ok(None);
    }
    let start = index;
    index += 1;
    while let Some(character) = chars.get(index).copied() {
        if character == '\\' {
            if chars.get(index + 1).is_none() {
                return Err(XValidationFailure::JsonPath {
                    message: "unterminated escape in JSONPath bracket selector".to_string(),
                });
            }
            index += 2;
        } else if character == '"' {
            let raw_json_string = chars[start..=index].iter().collect::<String>();
            let property = serde_json::from_str(&raw_json_string).map_err(|error| {
                XValidationFailure::JsonPath {
                    message: format!("invalid JSONPath bracket selector string: {error}"),
                }
            })?;
            return Ok(Some((property, index + 1)));
        } else {
            index += 1;
        }
    }
    Err(XValidationFailure::JsonPath {
        message: "unterminated JSONPath bracket selector".to_string(),
    })
}

fn escape_single_quoted_selector_property(property: &str) -> String {
    let mut escaped = String::new();
    for character in property.chars() {
        match character {
            '\\' => escaped.push_str("\\\\"),
            '\'' => escaped.push_str("\\'"),
            '\n' => escaped.push_str("\\n"),
            '\r' => escaped.push_str("\\r"),
            '\t' => escaped.push_str("\\t"),
            character if character.is_control() => {
                escaped.push_str(&format!("\\u{:04x}", character as u32));
            }
            character => escaped.push(character),
        }
    }
    escaped
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
            property.push(escaped);
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
    if chars.next().map(|(_, character)| character) != Some(']')
        || !is_json_pointer_array_index(&index)
    {
        return Err(jsonpath_location_error(path));
    }
    let index = index
        .parse::<usize>()
        .map_err(|_| jsonpath_location_error(path))?;
    Ok(LocationSegment::Index(index))
}

fn skip_jsonpath_whitespace(chars: &[char], mut index: usize) -> usize {
    while chars
        .get(index)
        .is_some_and(|character| character.is_ascii_whitespace())
    {
        index += 1;
    }
    index
}

fn is_json_pointer_array_index(token: &str) -> bool {
    token == "0"
        || (token.starts_with(['1', '2', '3', '4', '5', '6', '7', '8', '9'])
            && token.chars().all(|character| character.is_ascii_digit()))
}

fn jsonpath_location_error(path: &str) -> XValidationFailure {
    XValidationFailure::JsonPath {
        message: format!("unsupported normalized JSONPath location: {path}"),
    }
}

fn jsonpath_query_error(query: &str) -> XValidationFailure {
    XValidationFailure::JsonPath {
        message: format!("invalid JSONPath bracket selector: {query}"),
    }
}
