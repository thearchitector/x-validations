use std::fs;
use std::path::Path;

use serde_json::Value;
use xvalidations_core::{xvalidate, IssueSource, XValidationFailure};

#[test]
fn contract_fixtures_validate_in_rust_core() {
    let contracts_dir =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/contracts");
    let mut paths = fs::read_dir(contracts_dir)
        .expect("contract fixture directory should exist")
        .map(|entry| {
            entry
                .expect("contract fixture entry should be readable")
                .path()
        })
        .collect::<Vec<_>>();
    paths.sort();

    for path in paths {
        let contract = fs::read_to_string(&path).expect("contract should be readable");
        let contract: Value = serde_json::from_str(&contract).expect("contract should be JSON");
        let schema = &contract["schema"];

        if let Some(valid_payload) = contract.get("valid_payload") {
            assert_eq!(xvalidate(valid_payload, schema), Ok(()), "{path:?}");
        }

        if let Some(base_invalid_payload) = contract.get("base_invalid_payload") {
            let failure = xvalidate(base_invalid_payload, schema)
                .expect_err("base-invalid payload should fail");
            let XValidationFailure::Validation { issues } = failure else {
                panic!("expected validation failure for {path:?}");
            };
            assert!(
                !issues.is_empty(),
                "base-invalid payload should report issues"
            );
            assert!(issues
                .iter()
                .all(|issue| issue.source == IssueSource::Base && issue.rule_id.is_none()));
        }

        let x_invalid_payload = contract
            .get("x_invalid_payload")
            .or_else(|| contract.get("payload"));
        let expected_issue = contract
            .get("expected_x_issue")
            .or_else(|| contract.get("expected_issue"));
        if let (Some(payload), Some(expected_issue)) = (x_invalid_payload, expected_issue) {
            let failure = xvalidate(payload, schema).expect_err("x-invalid payload should fail");
            let XValidationFailure::Validation { issues } = failure else {
                panic!("expected validation failure for {path:?}");
            };
            assert_eq!(issues.len(), 1, "{path:?}");
            let issue = &issues[0];
            assert_eq!(issue.path, expected_issue["path"], "{path:?}");
            assert_eq!(
                issue_source_name(&issue.source),
                expected_issue["source"].as_str(),
                "{path:?}"
            );
            assert_eq!(
                issue.rule_id.as_deref(),
                expected_issue["rule_id"].as_str(),
                "{path:?}"
            );
        }
    }
}

fn issue_source_name(source: &IssueSource) -> Option<&'static str> {
    match source {
        IssueSource::Base => Some("base"),
        IssueSource::XValidation => Some("x-validation"),
    }
}
