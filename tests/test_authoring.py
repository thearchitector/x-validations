from collections.abc import Callable
from operator import eq
from typing import cast

import pytest
from pydantic import ValidationError
from xvalidate import XValidationError, xvalidate

from xvalidations import XValidatedModel, XValidationContext, xvalidation
from xvalidations.authoring import AuthoredRule, Path


def _exported_target(path: Callable[[XValidationContext], Path]) -> str:
    class Probe(XValidatedModel):
        @xvalidation(id="probe", description="Probe path serialization.")
        def probe(x: XValidationContext) -> AuthoredRule:
            return x.target(path(x)).assert_schema({})

    return str(Probe.model_json_schema()["x-validations"][0]["target"])


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param(lambda x: x.path.primary_tag, "$.primary_tag", id="attr"),
        pytest.param(lambda x: x.path["primary-tag"], '$["primary-tag"]', id="bracket"),
        pytest.param(lambda x: x.path.tags.each(), "$.tags[*]", id="each"),
        pytest.param(lambda x: x.path.tags.at(0), "$.tags[0]", id="index"),
        pytest.param(
            lambda x: x.path.tags.slice(0, 10, 2), "$.tags[0:10:2]", id="slice"
        ),
        pytest.param(lambda x: x.path.desc("field_id"), "$..field_id", id="desc"),
    ],
)
def test_path_shortcuts_serialize_to_jsonpath(
    path: Callable[[XValidationContext], Path], expected: str
) -> None:
    assert _exported_target(path) == expected


def test_selector_union_serializes_as_bracket_list() -> None:
    assert (
        _exported_target(lambda x: x.path.select(x.key("a"), x.key("b")))
        == '$["a","b"]'
    )


def test_filter_equality_serializes_to_rfc9535() -> None:
    assert (
        _exported_target(lambda x: x.path.items.where(x.this.kind == "field").id)
        == '$.items[?(@.kind == "field")].id'
    )


def test_filter_inequality_serializes_to_rfc9535() -> None:
    assert (
        _exported_target(lambda x: x.path.items.where(x.this.kind != "field"))
        == '$.items[?(@.kind != "field")]'
    )


def test_filter_rejects_non_json_scalar_rhs() -> None:
    x = XValidationContext()

    with pytest.raises(ValidationError):
        eq(x.this.kind, {"kind": "field"})


def test_select_without_selectors_raises_type_error() -> None:
    with pytest.raises(ValidationError):
        XValidationContext().path.select()


def test_desc_without_selectors_raises_type_error() -> None:
    with pytest.raises(ValidationError):
        XValidationContext().path.desc()


def test_target_rejects_raw_jsonpath_string() -> None:
    with pytest.raises(ValidationError):
        XValidationContext().target("$.primary_tag")


def test_context_helpers_do_not_coerce_argument_types() -> None:
    with pytest.raises(ValidationError):
        XValidationContext.index(cast(int, "0"))


def test_resolve_rejects_raw_jsonpath_string() -> None:
    with pytest.raises(TypeError):
        XValidationContext().resolve("$.tags[*]")


def test_resolve_allows_plain_non_path_string_constant() -> None:
    class ConstantTag(XValidatedModel):
        tag: str

        @xvalidation(id="constant-tag", description="Tag must be python.")
        def constant_tag(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.tag).assert_schema({"const": x.resolve("python")})

    schema = ConstantTag.model_json_schema()

    assert xvalidate({"tag": "python"}, schema) is None
    with pytest.raises(XValidationError):
        xvalidate({"tag": "rust"}, schema)


def test_xvalidation_decorator_exports_declared_rule() -> None:
    class Article(XValidatedModel):
        tags: list[str]
        primary_tag: str

        @xvalidation(
            id="primary-tag-exists", description="Primary tag must be present in tags."
        )
        def primary_tag_exists(x: XValidationContext) -> AuthoredRule:
            return x.target(x.path.primary_tag).assert_schema({
                "enum": x.resolve(x.path.tags.each())
            })

    assert Article.model_json_schema()["x-validations"] == [
        {
            "id": "primary-tag-exists",
            "description": "Primary tag must be present in tags.",
            "target": "$.primary_tag",
            "assert": {"enum": {"$resolve": "$.tags[*]"}},
        }
    ]


def test_paths_are_immutable_after_chaining() -> None:
    root = XValidationContext().path
    tags = root.tags
    each_tag = tags.each()

    assert _exported_target(lambda _x: root) == "$"
    assert _exported_target(lambda _x: tags) == "$.tags"
    assert _exported_target(lambda _x: each_tag) == "$.tags[*]"


def test_filter_constructor_helper_serializes() -> None:
    assert (
        _exported_target(
            lambda x: x.path.items.select(x.filter(x.this.kind == "field"))
        )
        == '$.items[?(@.kind == "field")]'
    )
