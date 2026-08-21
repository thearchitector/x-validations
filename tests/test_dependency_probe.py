import tomllib
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


def test_package_declares_inline_types() -> None:
    assert Path("xvalidations/py.typed").is_file()


def test_build_backend_excludes_local_tool_artifacts() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    build_backend = pyproject["tool"]["uv"]["build-backend"]

    assert {
        "xvalidations/.coverage*",
        "xvalidations/.skylos*",
        "xvalidations/.skylos*/**",
        "xvalidations/__pycache__/**",
        "xvalidations/**/*.pyc",
    }.issubset(build_backend["source-exclude"])
