use pretty_assertions::assert_eq;
use serde_json::{json, Map, Value};
use xvalidations_core::{xvalidate, ErrorSource, XValidationFailure};

const XVALIDATIONS_SCHEMA_URI: &str =
    "https://thearchitector.dev/xvalidations/meta/x-validations.schema.json";

fn article_schema() -> Value {
    json!({
        "$schema": XVALIDATIONS_SCHEMA_URI,
        "type": "object",
        "required": ["tags", "primary_tag"],
        "properties": {
            "tags": {"type": "array", "items": {"type": "string"}},
            "primary_tag": {"type": "string"}
        },
        "x-validations": [
            {
                "id": "primary-tag-exists",
                "description": "Primary tag must be present in tags.",
                "target": "$.primary_tag",
                "assert": {"enum": {"$resolve": "$.tags[*]"}}
            }
        ]
    })
}

fn special_property_schema(property: &str, target: &str) -> Value {
    let mut properties = Map::new();
    properties.insert(property.to_string(), json!({"type": "string"}));
    json!({
        "$schema": XVALIDATIONS_SCHEMA_URI,
        "type": "object",
        "properties": properties,
        "x-validations": [
            {
                "id": "special-property-python",
                "target": target,
                "assert": {"const": "python"}
            }
        ]
    })
}

#[test]
fn xvalidation_failure_has_rule_id_and_path() {
    let failure = xvalidate(
        &json!({"tags": ["python"], "primary_tag": "rust"}),
        &article_schema(),
    )
    .expect_err("x-validation should fail");

    let XValidationFailure::Validation { errors } = failure else {
        panic!("expected validation failure");
    };
    assert_eq!(errors[0].source, ErrorSource::XValidation);
    assert_eq!(errors[0].rule_id.as_deref(), Some("primary-tag-exists"));
    assert_eq!(errors[0].path, "$.primary_tag");
}

#[test]
fn unique_by_compiles_duplicate_targets_to_false_overlays() {
    let schema = json!({
        "$schema": XVALIDATIONS_SCHEMA_URI,
        "type": "object",
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"field_id": {"type": "string"}}
                }
            }
        },
        "x-validations": [
            {
                "id": "unique-field-ids",
                "target": "$.fields[*]",
                "assert": {"x-uniqueBy": "$.field_id"}
            }
        ]
    });

    let failure = xvalidate(
        &json!({
            "fields": [
                {"field_id": "title"},
                {"field_id": "summary"},
                {"field_id": "title"}
            ]
        }),
        &schema,
    )
    .expect_err("duplicate field ids should fail");

    let XValidationFailure::Validation { errors } = failure else {
        panic!("expected validation failure");
    };
    assert_eq!(
        errors
            .iter()
            .map(|error| (
                error.path.as_str(),
                error.source.clone(),
                error.rule_id.as_deref()
            ))
            .collect::<Vec<_>>(),
        [
            (
                "$.fields[0]",
                ErrorSource::XValidation,
                Some("unique-field-ids")
            ),
            (
                "$.fields[2]",
                ErrorSource::XValidation,
                Some("unique-field-ids")
            )
        ]
    );
}

#[test]
fn compiled_schema_validation_rejects_invalid_json_schema_keyword_shape_inside_assertion() {
    let mut schema = article_schema();
    schema["x-validations"][0]["assert"] = json!({"type": 42});

    assert!(matches!(
        xvalidate(
            &json!({"tags": ["python"], "primary_tag": "python"}),
            &schema,
        ),
        Err(XValidationFailure::InvalidSchema { .. })
    ));
}

#[test]
fn resolve_rejects_non_exact_marker_object() {
    let mut schema = article_schema();
    schema["x-validations"][0]["assert"] =
        json!({"enum": {"$resolve": "$.tags[*]", "fallback": []}});

    assert!(matches!(
        xvalidate(
            &json!({"tags": ["python"], "primary_tag": "python"}),
            &schema,
        ),
        Err(XValidationFailure::Resolve { .. })
    ));
}

#[test]
fn bad_resolve_pointer_reports_resolve() {
    let mut schema = article_schema();
    schema["x-validations"][0]["assert"] = json!({"enum": {"$resolve": "#/$defs/Missing"}});

    assert!(matches!(
        xvalidate(
            &json!({"tags": ["python"], "primary_tag": "python"}),
            &schema,
        ),
        Err(XValidationFailure::Resolve { .. })
    ));
}

#[test]
fn jsonpath_syntax_error_reports_jsonpath() {
    let mut schema = article_schema();
    schema["x-validations"][0]["target"] = json!("$[");

    assert!(matches!(
        xvalidate(
            &json!({"tags": ["python"], "primary_tag": "python"}),
            &schema,
        ),
        Err(XValidationFailure::JsonPath { .. })
    ));
}

#[test]
fn unique_by_non_singleton_projection_reports_invalid_rule() {
    let schema = json!({
        "$schema": XVALIDATIONS_SCHEMA_URI,
        "type": "object",
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"field_id": {"type": "string"}}
                }
            }
        },
        "x-validations": [
            {
                "id": "unique-field-ids",
                "target": "$.fields[*]",
                "assert": {"x-uniqueBy": "$.missing"}
            }
        ]
    });

    assert!(matches!(
        xvalidate(&json!({"fields": [{"field_id": "title"}]}), &schema),
        Err(XValidationFailure::InvalidRule { .. })
    ));
}

#[test]
fn double_quoted_bracket_selector_validates() {
    let schema = json!({
        "$schema": XVALIDATIONS_SCHEMA_URI,
        "type": "object",
        "properties": {
            "primary-tag": {"type": "string"}
        },
        "x-validations": [
            {
                "id": "primary-tag-python",
                "target": "$[\"primary-tag\"]",
                "assert": {"const": "python"}
            }
        ]
    });

    let failure = xvalidate(&json!({"primary-tag": "rust"}), &schema)
        .expect_err("bracket selector should validate matched property");

    let XValidationFailure::Validation { errors } = failure else {
        panic!("expected validation failure");
    };
    assert_eq!(errors[0].path, "$[\"primary-tag\"]");
    assert_eq!(errors[0].rule_id.as_deref(), Some("primary-tag-python"));
}

#[test]
fn double_quoted_bracket_selector_with_single_quote_validates() {
    let schema = special_property_schema("a'b", "$[\"a'b\"]");

    let failure = xvalidate(&json!({"a'b": "rust"}), &schema)
        .expect_err("escaped bracket selector should validate matched property");

    let XValidationFailure::Validation { errors } = failure else {
        panic!("expected validation failure");
    };
    assert_eq!(errors[0].path, "$[\"a'b\"]");
    assert_eq!(
        errors[0].rule_id.as_deref(),
        Some("special-property-python")
    );
}

#[test]
fn double_quoted_bracket_selector_with_json_escape_validates() {
    let schema = special_property_schema("line\nfeed", "$[\"line\\nfeed\"]");

    let failure = xvalidate(&json!({"line\nfeed": "rust"}), &schema)
        .expect_err("JSON-escaped bracket selector should validate matched property");

    let XValidationFailure::Validation { errors } = failure else {
        panic!("expected validation failure");
    };
    assert_eq!(errors[0].path, "$[\"line\\nfeed\"]");
    assert_eq!(
        errors[0].rule_id.as_deref(),
        Some("special-property-python")
    );
}

#[test]
fn double_quoted_bracket_selector_with_whitespace_validates() {
    let schema = special_property_schema("a", "$[ \"a\"]");

    let failure = xvalidate(&json!({"a": "rust"}), &schema)
        .expect_err("whitespace bracket selector should validate matched property");

    let XValidationFailure::Validation { errors } = failure else {
        panic!("expected validation failure");
    };
    assert_eq!(errors[0].path, "$.a");
    assert_eq!(
        errors[0].rule_id.as_deref(),
        Some("special-property-python")
    );
}

#[test]
fn double_quoted_bracket_union_with_whitespace_validates_each_match() {
    let schema = json!({
        "$schema": XVALIDATIONS_SCHEMA_URI,
        "type": "object",
        "properties": {
            "a": {"type": "string"},
            "b": {"type": "string"}
        },
        "x-validations": [
            {
                "id": "letters-python",
                "target": "$[\"a\", \"b\"]",
                "assert": {"const": "python"}
            }
        ]
    });

    let failure = xvalidate(&json!({"a": "rust", "b": "rust"}), &schema)
        .expect_err("whitespace bracket union should validate every matched property");

    let XValidationFailure::Validation { errors } = failure else {
        panic!("expected validation failure");
    };
    let mut paths = errors
        .iter()
        .map(|error| error.path.as_str())
        .collect::<Vec<_>>();
    paths.sort();
    assert_eq!(paths, ["$.a", "$.b"]);
    assert!(errors
        .iter()
        .all(|error| error.rule_id.as_deref() == Some("letters-python")));
}

#[test]
fn assertion_refs_to_defs_are_enforced() {
    let schema = json!({
        "$schema": XVALIDATIONS_SCHEMA_URI,
        "$defs": {
            "AllowedTag": {"const": "python"}
        },
        "type": "object",
        "properties": {
            "primary_tag": {"type": "string"}
        },
        "x-validations": [
            {
                "id": "primary-tag-python",
                "target": "$.primary_tag",
                "assert": {"$ref": "#/$defs/AllowedTag"}
            }
        ]
    });
    assert_eq!(
        xvalidate(&json!({"primary_tag": "python"}), &schema),
        Ok(())
    );

    let failure = xvalidate(&json!({"primary_tag": "rust"}), &schema)
        .expect_err("assertion ref should validate payload");
    let XValidationFailure::Validation { errors } = failure else {
        panic!("expected validation failure");
    };
    assert_eq!(errors[0].rule_id.as_deref(), Some("primary-tag-python"));
}

#[test]
fn validation_errors_are_sorted_by_the_public_contract_key() {
    let schema = json!({
        "$schema": XVALIDATIONS_SCHEMA_URI,
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "x-validations": [
            {
                "id": "z-rule",
                "target": "$.value",
                "assert": {"const": "z"}
            },
            {
                "id": "a-rule",
                "target": "$.value",
                "assert": {"const": "a"}
            }
        ]
    });

    let failure =
        xvalidate(&json!({"value": "invalid"}), &schema).expect_err("both rules should fail");
    let XValidationFailure::Validation { errors } = failure else {
        panic!("expected validation failure");
    };

    assert_eq!(
        errors
            .iter()
            .map(|error| error.rule_id.as_deref())
            .collect::<Vec<_>>(),
        [Some("a-rule"), Some("z-rule")]
    );
}
