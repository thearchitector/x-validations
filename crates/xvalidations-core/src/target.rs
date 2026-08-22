use serde_json::{json, Value};

use crate::jsonpath::LocationSegment;

pub fn location_to_schema_overlay(location: &[LocationSegment], assertion: &Value) -> Value {
    let mut child = assertion.clone();
    for segment in location.iter().rev() {
        child = match segment {
            LocationSegment::Property(property) => json!({
                "type": "object",
                "properties": {
                    property: child
                }
            }),
            LocationSegment::Index(index) => {
                let mut prefix_items = vec![Value::Bool(true); *index];
                prefix_items.push(child);
                json!({
                    "type": "array",
                    "minItems": index + 1,
                    "prefixItems": prefix_items
                })
            }
        };
    }
    child
}
