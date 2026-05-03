use serde_json::Value;

use crate::types::XValidationFailure;

pub(crate) const DRAFT202012_SCHEMA_URI: &str = "https://json-schema.org/draft/2020-12/schema";

pub(crate) fn xvalidations_meta_schema() -> Result<Value, XValidationFailure> {
    serde_json::from_str(include_str!("meta/x-validations.schema.json")).map_err(|error| {
        XValidationFailure::InvalidSchema {
            message: format!("bundled x-validations meta-schema is not JSON: {error}"),
        }
    })
}
