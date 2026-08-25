use serde::{Deserialize, Serialize};
use serde_json::Value;
use thiserror::Error;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ValidationError {
    pub path: String,
    pub message: String,
    pub rule_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Error, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum XValidationFailure {
    #[error("invalid schema: {message}")]
    InvalidSchema { message: String },
    #[error("invalid rule: {message}")]
    InvalidRule { message: String },
    #[error("jsonpath error: {message}")]
    JsonPath { message: String },
    #[error("{count} validation error(s)", count = errors.len())]
    Validation { errors: Vec<ValidationError> },
}

impl XValidationFailure {
    #[must_use]
    pub const fn kind(&self) -> &'static str {
        match self {
            Self::InvalidSchema { .. } => "invalid_schema",
            Self::InvalidRule { .. } => "invalid_rule",
            Self::JsonPath { .. } => "json_path",
            Self::Validation { .. } => "validation",
        }
    }

    #[must_use]
    pub const fn exception_name(&self) -> &'static str {
        match self {
            Self::InvalidSchema { .. } => "ExportedSchemaError",
            Self::InvalidRule { .. } => "InvalidRuleError",
            Self::JsonPath { .. } => "JsonPathError",
            Self::Validation { .. } => "XValidationError",
        }
    }

    #[must_use]
    pub fn errors(&self) -> Option<&[ValidationError]> {
        match self {
            Self::Validation { errors } => Some(errors),
            Self::InvalidSchema { .. } | Self::InvalidRule { .. } | Self::JsonPath { .. } => None,
        }
    }

    /// Serialize this core failure for a language binding.
    ///
    /// # Errors
    ///
    /// Returns an error if serialization fails.
    pub fn to_json_value(&self) -> Result<Value, serde_json::Error> {
        serde_json::to_value(self)
    }
}
