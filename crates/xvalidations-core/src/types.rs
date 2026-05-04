use serde::{Deserialize, Serialize};
use serde_json::Value;
use thiserror::Error;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum IssueSource {
    Base,
    XValidation,
}

impl IssueSource {
    pub fn as_str(&self) -> &'static str {
        match self {
            IssueSource::Base => "base",
            IssueSource::XValidation => "x-validation",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ValidationIssue {
    pub path: String,
    pub message: String,
    pub keyword: Option<String>,
    pub source: IssueSource,
    pub rule_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct XValidationRule {
    pub id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    pub target: String,
    #[serde(rename = "assert")]
    pub assertion: Value,
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
    #[error("resolve error: {message}")]
    Resolve { message: String },
    #[error("{count} validation issue(s)", count = issues.len())]
    Validation { issues: Vec<ValidationIssue> },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct XValidationBindingFailure {
    pub kind: String,
    pub message: String,
}

impl XValidationBindingFailure {
    pub fn new(kind: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            kind: kind.into(),
            message: message.into(),
        }
    }

    pub fn to_json_value(&self) -> Result<Value, serde_json::Error> {
        serde_json::to_value(self)
    }
}

impl XValidationFailure {
    pub fn kind(&self) -> &'static str {
        match self {
            XValidationFailure::InvalidSchema { .. } => "invalid_schema",
            XValidationFailure::InvalidRule { .. } => "invalid_rule",
            XValidationFailure::JsonPath { .. } => "json_path",
            XValidationFailure::Resolve { .. } => "resolve",
            XValidationFailure::Validation { .. } => "validation",
        }
    }

    pub fn issues(&self) -> Option<&[ValidationIssue]> {
        match self {
            XValidationFailure::Validation { issues } => Some(issues),
            XValidationFailure::InvalidSchema { .. }
            | XValidationFailure::InvalidRule { .. }
            | XValidationFailure::JsonPath { .. }
            | XValidationFailure::Resolve { .. } => None,
        }
    }

    pub fn to_json_value(&self) -> Result<Value, serde_json::Error> {
        serde_json::to_value(self)
    }
}
