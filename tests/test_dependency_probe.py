from pathlib import Path

from jsonpath_rfc9535 import find

import xvalidations


def test_jsonpath_rfc9535_returns_value_location_and_normalized_path() -> None:
    data = {"items": [{"kind": "field", "id": "a"}, {"kind": "note", "id": "b"}]}

    matches = list(find('$.items[?(@.kind == "field")].id', data))

    assert len(matches) == 1
    assert matches[0].value == "a"
    assert matches[0].location == ("items", 0, "id")
    assert matches[0].path() == "$['items'][0]['id']"


def test_project_imports_public_symbols() -> None:
    assert set(xvalidations.__all__) == {
        "ExportedSchemaError",
        "InvalidRuleError",
        "JsonPathError",
        "ResolveError",
        "ValidationIssue",
        "XValidatedModel",
        "XValidationContext",
        "XValidationError",
        "XValidationRule",
        "export_schema",
        "xvalidate",
        "xvalidation",
    }


def test_package_layout_has_no_src_directory() -> None:
    assert not Path("src").exists()
