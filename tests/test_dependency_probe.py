from pathlib import Path

import xvalid

import xvalidations


def test_project_imports_public_symbols() -> None:
    assert set(xvalidations.__all__) == {
        "InvalidRuleError",
        "XValidatedModel",
        "XValidationContext",
        "XValidationAuthoringError",
        "XValidationRule",
        "export_schema",
        "xvalidation",
    }


def test_xvalid_dependency_is_available_without_reexport() -> None:
    assert hasattr(xvalid, "xvalidate")
    assert not hasattr(xvalidations, "xvalidate")
    assert not hasattr(xvalidations, "XValidationError")


def test_package_layout_has_no_src_directory() -> None:
    assert not Path("src").exists()
