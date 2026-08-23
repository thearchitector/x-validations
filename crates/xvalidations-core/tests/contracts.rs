use std::fs;
use std::path::Path;

use serde_json::Value;
use xvalidations_core::{xvalidate, XValidationFailure};

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
            let XValidationFailure::Validation { errors } = failure else {
                panic!("expected validation failure for {path:?}");
            };
            assert!(
                !errors.is_empty(),
                "base-invalid payload should report errors"
            );
            assert!(errors.iter().all(|error| error.rule_id.is_none()));
            assert_error(&errors[0], &contract["expected_base_error"], &path);
        }

        if let (Some(payload), Some(expected_error)) = (
            contract.get("x_invalid_payload"),
            contract.get("expected_x_error"),
        ) {
            let failure = xvalidate(payload, schema).expect_err("x-invalid payload should fail");
            let XValidationFailure::Validation { errors } = failure else {
                panic!("expected validation failure for {path:?}");
            };
            assert!(!errors.is_empty(), "{path:?}");
            assert_error(&errors[0], expected_error, &path);
        }
    }
}

fn assert_error(error: &xvalidations_core::ValidationError, expected: &Value, path: &Path) {
    assert_eq!(error.path, expected["path"], "{}", path.display());
    assert_eq!(
        error.rule_id.as_deref(),
        expected["rule_id"].as_str(),
        "{}",
        path.display()
    );
}

#[test]
fn validation_error_serializes_only_the_public_contract_fields() {
    let value = serde_json::to_value(xvalidations_core::ValidationError {
        path: "$.value".to_string(),
        message: "failed".to_string(),
        rule_id: Some("rule".to_string()),
    })
    .expect("validation error should serialize");

    assert_eq!(
        value,
        serde_json::json!({
            "path": "$.value",
            "message": "failed",
            "rule_id": "rule"
        })
    );
}
