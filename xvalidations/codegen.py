"""Command-line helpers for generating plain Pydantic models."""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from xvalidations.artifact import strip_xvalidations

if TYPE_CHECKING:
    from xvalidations.models import JsonValue

app = typer.Typer(add_completion=False)


def stripped_schema_text(schema: "dict[str, JsonValue]") -> str:
    """Return deterministic JSON text for a stripped schema."""
    stripped = strip_xvalidations(schema)
    return json.dumps(stripped, sort_keys=True, separators=(",", ":"))


def codegen_command(schema_path: Path, output_path: Path) -> list[str]:
    """Build the datamodel-codegen command."""
    return [
        "datamodel-codegen",
        "--input",
        str(schema_path),
        "--input-file-type",
        "jsonschema",
        "--output",
        str(output_path),
        "--output-model-type",
        "pydantic_v2.BaseModel",
    ]


def command_function(
    input: Annotated[Path, typer.Option("--input", exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option("--output", dir_okay=False)],
) -> None:
    """Generate a plain Pydantic model from an exported schema."""
    try:
        schema = json.loads(input.read_text())
    except json.JSONDecodeError as exc:
        typer.echo(f"invalid JSON schema: {exc}", err=True)
        raise typer.Exit(1) from exc

    with tempfile.NamedTemporaryFile(
        suffix=".schema.json", delete=False
    ) as temp_schema:
        temp_schema_path = Path(temp_schema.name)
    try:
        temp_schema_path.write_text(stripped_schema_text(schema), encoding="utf-8")
        try:
            result = subprocess.run(
                codegen_command(temp_schema_path, output), check=False
            )
        except FileNotFoundError as exc:
            typer.echo("datamodel-codegen executable not found", err=True)
            raise typer.Exit(127) from exc
    finally:
        if temp_schema_path.exists():
            temp_schema_path.unlink()

    if result.returncode != 0:
        raise typer.Exit(result.returncode)


def main() -> None:
    """Run the CLI."""
    typer.run(command_function)


app.command()(command_function)
