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


def test_xvalidation_error_parses_native_failure_dict() -> None:
    error = XValidationError({
        "kind": "validation",
        "issues": [
            {
                "path": "$.primary_tag",
                "message": "'pydantic' is not one of ['python']",
                "keyword": "enum",
                "source": "x-validation",
                "rule_id": "primary-tag-exists",
            }
        ],
    })

    assert error.failure is not None
    assert error.kind == "validation"
    assert error.errors[0].source == "x-validation"
    assert error.errors[0].rule_id == "primary-tag-exists"
