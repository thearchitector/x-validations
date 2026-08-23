use std::collections::HashSet;

use jsonschema::{Registry, Uri};
use serde::Deserialize;
use serde_json::Value;

use crate::meta::{DRAFT202012_SCHEMA_URI, XVALIDATIONS_META_VALIDATOR, XVALIDATIONS_SCHEMA_URI};
use crate::pointer::{is_ancestor, join};
use crate::types::XValidationFailure;

const SYNTHETIC_DOCUMENT_URI: &str = "xvalidations:///document";

const SINGLE_SCHEMA_KEYWORDS: &[&str] = &[
    "additionalProperties",
    "contains",
    "contentSchema",
    "else",
    "if",
    "items",
    "not",
    "propertyNames",
    "then",
    "unevaluatedItems",
    "unevaluatedProperties",
];
const ARRAY_SCHEMA_KEYWORDS: &[&str] = &["allOf", "anyOf", "oneOf", "prefixItems"];
const OBJECT_SCHEMA_KEYWORDS: &[&str] = &[
    "$defs",
    "dependentSchemas",
    "patternProperties",
    "properties",
];

#[derive(Debug, Clone, PartialEq, Deserialize)]
pub(crate) struct ValidationRule {
    pub(crate) id: String,
    pub(crate) target: String,
    #[serde(rename = "assert")]
    pub(crate) assertion: Value,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ResourceId(Uri<String>);

impl ResourceId {
    fn parse_absolute_fragment_free(value: &str) -> Result<Self, XValidationFailure> {
        let uri = Uri::parse(value)
            .map(|uri| uri.to_owned())
            .map_err(|error| XValidationFailure::InvalidSchema {
                message: format!("invalid Schema Resource $id {value:?}: {error}"),
            })?;
        if uri.fragment().is_some() {
            return Err(XValidationFailure::InvalidSchema {
                message: format!("Schema Resource $id must be fragment-free: {value:?}"),
            });
        }
        Ok(Self(uri))
    }

    fn resolve_id(
        &self,
        registry: &Registry<'_>,
        reference: &str,
    ) -> Result<Self, XValidationFailure> {
        let resolved = registry
            .resolve_uri(&self.0.borrow(), reference)
            .map_err(|error| XValidationFailure::InvalidSchema {
                message: format!(
                    "could not resolve Schema Resource $id {reference:?} against {:?}: {error}",
                    self.as_str()
                ),
            })?;
        if resolved.fragment().is_some() {
            return Err(XValidationFailure::InvalidSchema {
                message: format!("Schema Resource $id must be fragment-free: {reference:?}"),
            });
        }
        Ok(Self((*resolved).clone()))
    }

    fn resolve_reference(
        &self,
        registry: &Registry<'_>,
        reference: &str,
    ) -> Result<String, XValidationFailure> {
        registry
            .resolve_uri(&self.0.borrow(), reference)
            .map(|uri| uri.as_str().to_string())
            .map_err(|error| XValidationFailure::InvalidSchema {
                message: format!(
                    "could not resolve reference {reference:?} against {:?}: {error}",
                    self.as_str()
                ),
            })
    }

    pub(crate) fn as_str(&self) -> &str {
        self.0.as_str()
    }
}

#[derive(Debug, Clone)]
pub(crate) struct PreparedResource {
    pub(crate) id: ResourceId,
    pub(crate) source: Value,
    pub(crate) rules: Vec<ValidationRule>,
}

#[derive(Debug, Clone)]
pub(crate) struct ResourceLocation {
    pub(crate) id: ResourceId,
    pub(crate) schema_pointer: String,
}

pub(crate) struct PreparedSchema {
    pub(crate) base_schema: Value,
    pub(crate) registry: Registry<'static>,
    pub(crate) resource_locations: Vec<ResourceLocation>,
    pub(crate) resources: Vec<PreparedResource>,
}

impl PreparedSchema {
    pub(crate) fn resource(&self, id: &str) -> Option<&PreparedResource> {
        self.resources
            .iter()
            .find(|resource| resource.id.as_str() == id)
    }

    pub(crate) fn resource_id_for_absolute_location(&self, location: &str) -> Option<&str> {
        self.resources
            .iter()
            .filter(|resource| {
                location == resource.id.as_str()
                    || location
                        .strip_prefix(resource.id.as_str())
                        .is_some_and(|suffix| suffix.starts_with('#'))
            })
            .max_by_key(|resource| resource.id.as_str().len())
            .map(|resource| resource.id.as_str())
    }

    pub(crate) fn resource_id_for_schema_location(&self, location: &str) -> Option<&str> {
        let pointer = location
            .split_once('#')
            .map_or(location, |(_, fragment)| fragment);
        let owning_id = self
            .resource_locations
            .iter()
            .filter(|resource| is_ancestor(&resource.schema_pointer, pointer))
            .max_by_key(|resource| resource.schema_pointer.len())
            .map(|resource| resource.id.as_str())?;
        self.resource(owning_id)
            .map(|resource| resource.id.as_str())
    }
}

pub(crate) fn prepare_schema(schema: &Value) -> Result<PreparedSchema, XValidationFailure> {
    if !schema.is_object() && !schema.is_boolean() {
        return Err(XValidationFailure::InvalidSchema {
            message: "schema must be a JSON object or boolean".to_string(),
        });
    }

    let uri_registry = Registry::new()
        .prepare()
        .expect("an empty JSON Schema registry must prepare");
    let synthetic_id = ResourceId::parse_absolute_fragment_free(SYNTHETIC_DOCUMENT_URI)
        .expect("the synthetic document URI is an internal invariant");
    let mut base_schema = schema.clone();
    let mut resource_locations = Vec::new();
    let mut resources = Vec::new();
    walk_schema(
        schema,
        &mut base_schema,
        "",
        &synthetic_id,
        true,
        &uri_registry,
        &mut resource_locations,
        &mut resources,
    )?;

    let registry_resources = resource_locations
        .iter()
        .filter_map(|resource| {
            base_schema
                .pointer(&resource.schema_pointer)
                .cloned()
                .map(|schema| (resource.id.as_str().to_string(), schema))
        })
        .collect::<Vec<_>>();
    let registry = Registry::new()
        .extend(registry_resources)
        .map_err(|error| XValidationFailure::InvalidSchema {
            message: format!("could not add normalized Schema Resources to registry: {error}"),
        })?
        .prepare()
        .map_err(|error| XValidationFailure::InvalidSchema {
            message: format!("could not prepare normalized Schema Resource registry: {error}"),
        })?;

    Ok(PreparedSchema {
        base_schema,
        registry,
        resource_locations,
        resources,
    })
}

#[allow(clippy::too_many_arguments)]
fn walk_schema(
    original: &Value,
    normalized: &mut Value,
    pointer: &str,
    parent_id: &ResourceId,
    is_root: bool,
    uri_registry: &Registry<'_>,
    resource_locations: &mut Vec<ResourceLocation>,
    resources: &mut Vec<PreparedResource>,
) -> Result<(), XValidationFailure> {
    let (Value::Object(original_object), Value::Object(normalized_object)) = (original, normalized)
    else {
        if is_root {
            resource_locations.push(ResourceLocation {
                id: parent_id.clone(),
                schema_pointer: pointer.to_string(),
            });
        }
        return Ok(());
    };

    let declared_id = original_object.get("$id").and_then(Value::as_str);
    let effective_id = match declared_id {
        Some(id) => parent_id.resolve_id(uri_registry, id)?,
        None => parent_id.clone(),
    };
    if declared_id.is_some() || (is_root && !original_object.contains_key("$id")) {
        normalized_object.insert(
            "$id".to_string(),
            Value::String(effective_id.as_str().to_string()),
        );
    }

    if is_root || declared_id.is_some() {
        if resource_locations
            .iter()
            .any(|resource| resource.id == effective_id)
        {
            return Err(XValidationFailure::InvalidSchema {
                message: format!("duplicate Schema Resource ID {:?}", effective_id.as_str()),
            });
        }
        resource_locations.push(ResourceLocation {
            id: effective_id.clone(),
            schema_pointer: pointer.to_string(),
        });
    }

    let has_extensions = original_object.contains_key("x-validations")
        || original_object.contains_key("x-constants");
    let is_x_resource =
        original_object.get("$schema").and_then(Value::as_str) == Some(XVALIDATIONS_SCHEMA_URI);
    if has_extensions && !is_x_resource {
        return Err(XValidationFailure::InvalidSchema {
            message: "X-Validations extension fields require the X-Validations dialect".to_string(),
        });
    }
    if is_x_resource {
        if let Some(declared_id) = declared_id {
            let absolute_id =
                ResourceId::parse_absolute_fragment_free(declared_id).map_err(|_| {
                    XValidationFailure::InvalidSchema {
                        message: "X-Validations $id must be absolute and fragment-free".to_string(),
                    }
                })?;
            if absolute_id != effective_id {
                return Err(XValidationFailure::InvalidSchema {
                    message: "X-Validations $id must be absolute and fragment-free".to_string(),
                });
            }
        } else if !is_root {
            return Err(XValidationFailure::InvalidSchema {
                message:
                    "embedded X-Validations Schema Resource requires an absolute fragment-free $id"
                        .to_string(),
            });
        }
        validate_resource(original)?;
        let rules = parse_rules(original)?;
        validate_rule_ids(&rules)?;
        normalized_object.insert(
            "$schema".to_string(),
            Value::String(DRAFT202012_SCHEMA_URI.to_string()),
        );
        resources.push(PreparedResource {
            id: effective_id.clone(),
            source: original.clone(),
            rules,
        });
    }

    for keyword in SINGLE_SCHEMA_KEYWORDS {
        if let (Some(child), Some(normalized_child)) = (
            original_object.get(*keyword),
            normalized_object.get_mut(*keyword),
        ) {
            walk_schema(
                child,
                normalized_child,
                &join(pointer, keyword),
                &effective_id,
                false,
                uri_registry,
                resource_locations,
                resources,
            )?;
        }
    }
    for keyword in ARRAY_SCHEMA_KEYWORDS {
        let (Some(Value::Array(children)), Some(Value::Array(normalized_children))) = (
            original_object.get(*keyword),
            normalized_object.get_mut(*keyword),
        ) else {
            continue;
        };
        for (index, (child, normalized_child)) in children
            .iter()
            .zip(normalized_children.iter_mut())
            .enumerate()
        {
            walk_schema(
                child,
                normalized_child,
                &join(&join(pointer, keyword), &index.to_string()),
                &effective_id,
                false,
                uri_registry,
                resource_locations,
                resources,
            )?;
        }
    }
    for keyword in OBJECT_SCHEMA_KEYWORDS {
        let (Some(Value::Object(children)), Some(Value::Object(normalized_children))) = (
            original_object.get(*keyword),
            normalized_object.get_mut(*keyword),
        ) else {
            continue;
        };
        for (name, child) in children {
            let Some(normalized_child) = normalized_children.get_mut(name) else {
                continue;
            };
            walk_schema(
                child,
                normalized_child,
                &join(&join(pointer, keyword), name),
                &effective_id,
                false,
                uri_registry,
                resource_locations,
                resources,
            )?;
        }
    }
    Ok(())
}

pub(crate) fn normalize_assertion_uris(
    assertion: &mut Value,
    containing_resource: &ResourceId,
    registry: &Registry<'_>,
) -> Result<(), XValidationFailure> {
    normalize_schema_node(assertion, containing_resource, registry)
}

fn normalize_schema_node(
    node: &mut Value,
    parent_id: &ResourceId,
    registry: &Registry<'_>,
) -> Result<(), XValidationFailure> {
    let Value::Object(object) = node else {
        return Ok(());
    };
    let effective_id = match object.get("$id").and_then(Value::as_str) {
        Some(id) => parent_id.resolve_id(registry, id)?,
        None => parent_id.clone(),
    };
    if object.get("$id").is_some_and(Value::is_string) {
        object.insert(
            "$id".to_string(),
            Value::String(effective_id.as_str().to_string()),
        );
    }
    for keyword in ["$ref", "$dynamicRef"] {
        if let Some(Value::String(reference)) = object.get_mut(keyword) {
            *reference = effective_id.resolve_reference(registry, reference)?;
        }
    }
    for keyword in SINGLE_SCHEMA_KEYWORDS {
        if let Some(child) = object.get_mut(*keyword) {
            normalize_schema_node(child, &effective_id, registry)?;
        }
    }
    for keyword in ARRAY_SCHEMA_KEYWORDS {
        if let Some(Value::Array(children)) = object.get_mut(*keyword) {
            for child in children {
                normalize_schema_node(child, &effective_id, registry)?;
            }
        }
    }
    for keyword in OBJECT_SCHEMA_KEYWORDS {
        if let Some(Value::Object(children)) = object.get_mut(*keyword) {
            for child in children.values_mut() {
                normalize_schema_node(child, &effective_id, registry)?;
            }
        }
    }
    Ok(())
}

fn validate_resource(resource: &Value) -> Result<(), XValidationFailure> {
    XVALIDATIONS_META_VALIDATOR
        .validate(resource)
        .map_err(|error| XValidationFailure::InvalidSchema {
            message: format!("X-Validations resource failed preflight: {error}"),
        })
}

fn parse_rules(resource: &Value) -> Result<Vec<ValidationRule>, XValidationFailure> {
    let Some(raw_rules) = resource.get("x-validations") else {
        return Ok(Vec::new());
    };
    raw_rules
        .as_array()
        .ok_or_else(|| XValidationFailure::InvalidRule {
            message: "x-validations must be an array".to_string(),
        })?
        .iter()
        .cloned()
        .map(|rule| {
            serde_json::from_value(rule).map_err(|error| XValidationFailure::InvalidRule {
                message: format!("invalid x-validation rule: {error}"),
            })
        })
        .collect()
}

fn validate_rule_ids(rules: &[ValidationRule]) -> Result<(), XValidationFailure> {
    let mut seen = HashSet::new();
    for rule in rules {
        if !seen.insert(rule.id.as_str()) {
            return Err(XValidationFailure::InvalidRule {
                message: format!("duplicate local validation rule ID {:?}", rule.id),
            });
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::prepare_schema;
    use crate::meta::XVALIDATIONS_SCHEMA_URI;

    #[test]
    fn prepared_dialect_resource_keeps_base_keywords() {
        let prepared = prepare_schema(&json!({
            "$id": "urn:test:base-keywords",
            "$schema": XVALIDATIONS_SCHEMA_URI,
            "type": "object",
            "required": ["value"],
            "x-validations": [{
                "id": "value-rule",
                "target": "$.value",
                "assert": {"const": "ok"}
            }]
        }))
        .expect("resource should prepare");
        let validator = jsonschema::options()
            .with_registry(&prepared.registry)
            .build(&prepared.base_schema)
            .expect("base schema should compile");
        assert_eq!(validator.iter_errors(&json!({})).count(), 1);
    }

    #[test]
    fn only_schema_positions_are_walked() {
        let prepared = prepare_schema(&json!({
            "const": {
                "$schema": XVALIDATIONS_SCHEMA_URI,
                "$id": "urn:not-a-resource",
                "$ref": "urn:not-a-reference",
                "x-validations": [{
                    "id": "not-a-rule",
                    "target": "$.anything",
                    "assert": false
                }]
            }
        }))
        .expect("literal data should not be interpreted as a schema");
        assert!(prepared.resources.is_empty());
    }
}
