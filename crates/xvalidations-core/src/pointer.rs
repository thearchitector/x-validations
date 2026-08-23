use std::fmt::Write;

use serde_json::Value;

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub(crate) enum LocationSegment {
    Property(String),
    Index(usize),
}

pub(crate) fn tokens(pointer: &str) -> Vec<String> {
    if pointer.is_empty() {
        return Vec::new();
    }
    pointer
        .trim_start_matches('/')
        .split('/')
        .map(decode_token)
        .collect()
}

pub(crate) fn decode_token(token: &str) -> String {
    token.replace("~1", "/").replace("~0", "~")
}

pub(crate) fn is_array_index(token: &str) -> bool {
    token == "0"
        || (token.starts_with(['1', '2', '3', '4', '5', '6', '7', '8', '9'])
            && token.chars().all(|character| character.is_ascii_digit()))
}

pub(crate) fn join(pointer: &str, token: &str) -> String {
    format!("{pointer}/{}", token.replace('~', "~0").replace('/', "~1"))
}

pub(crate) fn is_ancestor(ancestor: &str, descendant: &str) -> bool {
    ancestor.is_empty()
        || descendant == ancestor
        || descendant
            .strip_prefix(ancestor)
            .is_some_and(|suffix| suffix.starts_with('/'))
}

pub(crate) fn location_from_pointer(pointer: &str, root: &Value) -> Vec<LocationSegment> {
    let mut location = Vec::new();
    let mut current = Some(root);
    for token in tokens(pointer) {
        match current {
            Some(Value::Array(values)) if is_array_index(&token) => {
                let index = token
                    .parse::<usize>()
                    .expect("array-index token was checked before parsing");
                location.push(LocationSegment::Index(index));
                current = values.get(index);
            }
            Some(Value::Object(object)) => {
                location.push(LocationSegment::Property(token.clone()));
                current = object.get(&token);
            }
            _ => {
                location.push(LocationSegment::Property(token));
                current = None;
            }
        }
    }
    location
}

pub(crate) fn location_to_jsonpath(location: &[LocationSegment]) -> String {
    let mut path = "$".to_string();
    for segment in location {
        match segment {
            LocationSegment::Index(index) => {
                write!(path, "[{index}]").expect("writing to a String cannot fail");
            }
            LocationSegment::Property(property) if is_identifier(property) => {
                path.push('.');
                path.push_str(property);
            }
            LocationSegment::Property(property) => {
                let quoted = serde_json::to_string(property)
                    .expect("serializing a JSON pointer token string cannot fail");
                path.push('[');
                path.push_str(&quoted);
                path.push(']');
            }
        }
    }
    path
}

pub(crate) fn pointer_to_jsonpath(pointer: &str, root: &Value) -> String {
    location_to_jsonpath(&location_from_pointer(pointer, root))
}

fn is_identifier(token: &str) -> bool {
    let mut chars = token.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    (first == '_' || first.is_ascii_alphabetic())
        && chars.all(|character| character == '_' || character.is_ascii_alphanumeric())
}
