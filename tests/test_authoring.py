import pytest

from xvalidations.authoring import (
    AuthoredRule,
    Path,
    ResolveMarker,
    XValidationContext,
    XValidationDeclaration,
    filter_selector,
    key,
    path_to_jsonpath,
    predicate_to_jsonpath,
    xvalidation,
)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param(lambda x: x.path.primary_tag, "$.primary_tag", id="attr"),
        pytest.param(lambda x: x.path["primary-tag"], '$["primary-tag"]', id="bracket"),
        pytest.param(lambda x: x.path.tags.each(), "$.tags[*]", id="each"),
        pytest.param(lambda x: x.path.tags.at(0), "$.tags[0]", id="index"),
        pytest.param(lambda x: x.path.tags.slice(0, 10, 2), "$.tags[0:10:2]", id="slice"),
        pytest.param(lambda x: x.path.desc("field_id"), "$..field_id", id="desc"),
    ],
)
def test_path_shortcuts_serialize_to_jsonpath(
    path: object, expected: str
) -> None:
    x = XValidationContext()

    assert path(x).to_jsonpath() == expected


def test_selector_union_serializes_as_bracket_list() -> None:
    path = XValidationContext().path.select(key("a"), key("b"))

    assert path_to_jsonpath(path) == '$["a","b"]'


def test_filter_equality_serializes_to_rfc9535() -> None:
    x = XValidationContext()
    predicate = x.this.kind == "field"
    path = x.path.items.where(predicate).id

    assert predicate_to_jsonpath(predicate) == '@.kind == "field"'
    assert path.to_jsonpath() == '$.items[?(@.kind == "field")].id'


def test_filter_inequality_serializes_to_rfc9535() -> None:
    x = XValidationContext()
    predicate = x.this.kind != "field"

    assert predicate_to_jsonpath(predicate) == '@.kind != "field"'


def test_filter_rejects_non_json_scalar_rhs() -> None:
    x = XValidationContext()

    with pytest.raises(TypeError):
        x.this.kind == {"kind": "field"}


def test_select_without_selectors_raises_type_error() -> None:
    with pytest.raises(TypeError):
        Path().select()


def test_desc_without_selectors_raises_type_error() -> None:
    with pytest.raises(TypeError):
        Path().desc()


def test_target_rejects_raw_jsonpath_string() -> None:
    with pytest.raises(TypeError):
        XValidationContext().target("$.primary_tag")


def test_resolve_rejects_raw_jsonpath_string() -> None:
    with pytest.raises(TypeError):
        XValidationContext().resolve("$.tags[*]")


def test_resolve_allows_plain_non_path_string_constant() -> None:
    marker = XValidationContext().resolve("python")

    assert marker == ResolveMarker("python")


def test_xvalidation_attaches_rule_declaration_to_function() -> None:
    @xvalidation(id="primary-tag-exists", description="Primary tag must be present in tags.")
    def primary_tag_exists(x: XValidationContext) -> AuthoredRule:
        return x.target(x.path.primary_tag).assert_schema(
            {"enum": x.resolve(x.path.tags.each())}
        )

    declaration = primary_tag_exists.__xvalidation_declaration__

    assert declaration == XValidationDeclaration(
        id="primary-tag-exists",
        description="Primary tag must be present in tags.",
        factory=primary_tag_exists,
    )


def test_paths_are_immutable_after_chaining() -> None:
    root = Path()
    tags = root.tags
    each_tag = tags.each()

    assert root.to_jsonpath() == "$"
    assert tags.to_jsonpath() == "$.tags"
    assert each_tag.to_jsonpath() == "$.tags[*]"


def test_filter_constructor_helper_serializes() -> None:
    x = XValidationContext()
    path = x.path.items.select(filter_selector(x.this.kind == "field"))

    assert path.to_jsonpath() == '$.items[?(@.kind == "field")]'
