import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from xvalidations import XValidatedModel, XValidationContext, xvalidate, xvalidation
from xvalidations.authoring import AuthoredRule
from xvalidations.codegen import app, codegen_command, stripped_schema_text


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


def test_typer_cli_help_lists_input_and_output() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "--input" in result.output
    assert "--output" in result.output


def test_codegen_strips_xvalidations_before_invoking_datamodel_codegen() -> None:
    schema = Article.model_json_schema()

    stripped = stripped_schema_text(schema)

    assert "x-validations" not in stripped
    assert json.loads(stripped)["properties"]["tags"]["type"] == "array"


def test_codegen_invokes_datamodel_codegen_with_pydantic_v2_output(
    tmp_path: Path,
) -> None:
    command = codegen_command(tmp_path / "schema.json", tmp_path / "model.py")

    assert command == [
        "datamodel-codegen",
        "--input",
        str(tmp_path / "schema.json"),
        "--input-file-type",
        "jsonschema",
        "--output",
        str(tmp_path / "model.py"),
        "--output-model-type",
        "pydantic_v2.BaseModel",
    ]


def test_codegen_missing_datamodel_codegen_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    schema_path = tmp_path / "article.schema.json"
    schema_path.write_text(json.dumps(Article.model_json_schema()))

    def fake_run(command: list[str], check: bool) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = CliRunner().invoke(
        app, ["--input", str(schema_path), "--output", str(tmp_path / "model.py")]
    )

    assert result.exit_code == 127
    assert "datamodel-codegen executable not found" in result.output


def test_codegen_invalid_input_json_exits_nonzero(tmp_path: Path) -> None:
    schema_path = tmp_path / "bad.schema.json"
    schema_path.write_text("{")

    result = CliRunner().invoke(
        app, ["--input", str(schema_path), "--output", str(tmp_path / "model.py")]
    )

    assert result.exit_code == 1


def test_generated_plain_model_validates_with_xvalidate_external_schema(
    tmp_path: Path,
) -> None:
    schema = Article.model_json_schema()
    schema_path = tmp_path / "article.schema.json"
    output_path = tmp_path / "generated_article.py"
    schema_path.write_text(json.dumps(schema))

    result = CliRunner().invoke(
        app, ["--input", str(schema_path), "--output", str(output_path)]
    )

    assert result.exit_code == 0
    generated_text = output_path.read_text()
    assert "x-validations" not in generated_text

    generated_module = _load_module(output_path)
    generated_article = generated_module.Article.model_validate({
        "tags": ["python"],
        "primary_tag": "python",
    })

    assert xvalidate(generated_article, schema=schema) is None


def _load_module(path: Path) -> object:
    spec = importlib.util.spec_from_file_location("generated_article", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["generated_article"] = module
    if spec is None or spec.loader is None:
        msg = "could not load generated module"
        raise RuntimeError(msg)
    spec.loader.exec_module(module)
    return module
