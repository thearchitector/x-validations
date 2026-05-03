from pathlib import Path

import xvalidations


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
