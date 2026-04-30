from xvalidations.errors import XValidationError
from xvalidations.models import ValidationIssue


def test_xvalidation_error_exposes_errors_list() -> None:
    issue = ValidationIssue(
        path="$.primary_tag",
        message="'python' is not one of ['pydantic']",
        keyword="enum",
        source="x-validation",
        rule_id="primary-tag-exists",
    )

    error = XValidationError([issue])

    assert error.errors == [issue]
    assert str(error) == "1 validation issue(s)"
