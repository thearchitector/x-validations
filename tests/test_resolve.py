import pytest

from xvalidations.errors import ResolveError
from xvalidations.resolve import resolve_placeholders, resolve_ref


def test_resolve_instance_jsonpath_returns_values_list() -> None:
    instance = {"tags": ["python", "pydantic"]}

    assert resolve_ref("$.tags[*]", instance, {}) == ["python", "pydantic"]


def test_resolve_schema_pointer_returns_def_value() -> None:
    schema = {"$defs": {"TagEnum": ["python", "pydantic"]}}

    assert resolve_ref("#/$defs/TagEnum", {}, schema) == ["python", "pydantic"]


def test_resolve_missing_schema_pointer_raises_resolve_error() -> None:
    with pytest.raises(ResolveError):
        resolve_ref("#/$defs/Missing", {}, {"$defs": {}})


@pytest.mark.parametrize("ref", ["#/-1", "#/01"], ids=["negative", "leading-zero"])
def test_resolve_invalid_array_pointer_token_raises_resolve_error(ref: str) -> None:
    with pytest.raises(ResolveError):
        resolve_ref(ref, {}, ["python"])


def test_resolve_invalid_prefix_raises_resolve_error() -> None:
    with pytest.raises(ResolveError):
        resolve_ref("tags", {}, {})


def test_resolve_non_string_resolve_value_raises_resolve_error() -> None:
    with pytest.raises(ResolveError):
        resolve_placeholders({"$resolve": 1}, {}, {})


def test_resolve_placeholders_replaces_nested_nodes() -> None:
    instance = {"tags": ["python"]}

    assert resolve_placeholders({"enum": {"$resolve": "$.tags[*]"}}, instance, {}) == {
        "enum": ["python"]
    }
