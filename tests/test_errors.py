from xvalid import ValidationIssue

from xvalidations.errors import InvalidRuleError, XValidationAuthoringError


def test_validation_issue_exposes_schema_checking_fields() -> None:
    issue = ValidationIssue(
        path="$.primary_tag",
        message="'python' is not one of ['pydantic']",
        keyword="enum",
        source="x-validation",
        rule_id="primary-tag-exists",
    )

    assert issue.path == "$.primary_tag"
    assert issue.source == "x-validation"
    assert issue.rule_id == "primary-tag-exists"


def test_authoring_errors_live_in_xvalidations() -> None:
    assert issubclass(InvalidRuleError, XValidationAuthoringError)
    assert str(InvalidRuleError("bad rule")) == "bad rule"
