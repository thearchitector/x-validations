use std::collections::HashSet;

use serde_json::Value;

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

pub(crate) fn def_name(reference: &str) -> Option<String> {
    let escaped_name = reference.strip_prefix("#/$defs/")?.split('/').next()?;
    Some(decode_token(escaped_name))
}

pub(crate) fn referenced_defs(node: &Value) -> HashSet<String> {
    let mut names = HashSet::new();
    walk(node, &mut |object| {
        for key in ["$ref", "$dynamicRef"] {
            if let Some(Value::String(reference)) = object.get(key) {
                if let Some(name) = def_name(reference) {
                    names.insert(name);
                }
            }
        }
    });
    names
}

pub(crate) fn resolved_defs(node: &Value) -> HashSet<String> {
    let mut names = HashSet::new();
    walk(node, &mut |object| {
        if object.len() == 1 {
            if let Some(Value::String(reference)) = object.get("$resolve") {
                if let Some(name) = def_name(reference) {
                    names.insert(name);
                }
            }
        }
    });
    names
}

fn walk(node: &Value, visit: &mut impl FnMut(&serde_json::Map<String, Value>)) {
    match node {
        Value::Object(object) => {
            visit(object);
            for value in object.values() {
                walk(value, visit);
            }
        }
        Value::Array(values) => {
            for value in values {
                walk(value, visit);
            }
        }
        _ => {}
    }
}
