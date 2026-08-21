import pytest
from xvalid import XValidationError, xvalidate

from tests.conftest import Article
from xvalidations import (
    InvalidRuleError,
    XValidatedModel,
    XValidationAuthoringError,
    XValidationContext,
    xvalidation,
)
from xvalidations.authoring import AuthoredRule


def test_validation_issue_exposes_schema_checking_fields() -> None:
    with pytest.raises(XValidationError) as exc_info:
        xvalidate(
            {"tags": ["pydantic"], "primary_tag": "python"}, Article.model_json_schema()
        )

    issue = exc_info.value.errors[0]
    assert issue.path == "$.primary_tag"
    assert issue.source == "x-validation"
    assert issue.rule_id == "primary-tag-exists"


def test_authoring_errors_live_in_xvalidations() -> None:
    class DuplicateRule(XValidatedModel):
        first: str
        second: str

        @xvalidation(id="duplicate", description="First rule.")
        def first_rule(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.first).assert_schema({"type": "string"})

        @xvalidation(id="duplicate", description="Second rule.")
        def second_rule(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.second).assert_schema({"type": "string"})

    with pytest.raises(XValidationAuthoringError) as exc_info:
        DuplicateRule.model_json_schema()

    assert isinstance(exc_info.value, InvalidRuleError)
    assert "duplicate" in str(exc_info.value)
