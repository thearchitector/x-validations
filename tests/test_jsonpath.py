import pytest

from xvalidations.errors import JsonPathError
from xvalidations.jsonpath import JsonPathMatch, evaluate_jsonpath


def test_evaluate_jsonpath_returns_deduped_locations_in_order() -> None:
    data = {"items": [{"kind": "field", "id": "a"}, {"kind": "field", "id": "b"}]}

    matches = evaluate_jsonpath('$.items[?(@.kind == "field")].id', data)

    assert matches == [
        JsonPathMatch(
            value="a",
            location=("items", 0, "id"),
            normalized_path="$['items'][0]['id']",
        ),
        JsonPathMatch(
            value="b",
            location=("items", 1, "id"),
            normalized_path="$['items'][1]['id']",
        ),
    ]


def test_evaluate_jsonpath_dedupes_duplicate_locations() -> None:
    data = {"items": [{"id": "a"}]}

    matches = evaluate_jsonpath("$.items[0,0].id", data)

    assert matches == [
        JsonPathMatch(
            value="a",
            location=("items", 0, "id"),
            normalized_path="$['items'][0]['id']",
        )
    ]


def test_evaluate_jsonpath_invalid_syntax_raises_jsonpath_error() -> None:
    with pytest.raises(JsonPathError):
        evaluate_jsonpath("$[", {})
