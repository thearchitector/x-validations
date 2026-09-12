"""Negative fixtures must fail for the documented reasons, without suppressions."""

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("source", "diagnostics"),
    [
        ("invalid_nodes.py", "expected.json"),
        ("invalid_authoring.py", "expected_authoring.json"),
    ],
)
def test_invalid_construction_diagnostics(source: str, diagnostics: str) -> None:
    directory = Path(__file__).parent / "fixtures" / "typing"
    fixture = directory / source
    expected = json.loads((directory / diagnostics).read_text())
    functions = [
        node
        for node in ast.parse(fixture.read_text()).body
        if isinstance(node, ast.FunctionDef)
    ]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--no-incremental",
            "--no-error-summary",
            "--show-error-codes",
            str(fixture),
        ],
        cwd=directory.parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    actual: dict[str, list[str]] = {}
    errors = [line for line in result.stdout.splitlines() if ": error:" in line]
    assert errors, result.stdout + result.stderr
    for error in errors:
        diagnostic = re.search(r":(\d+): error: .*\[([\w-]+)\]$", error)
        assert diagnostic is not None, error
        line = int(diagnostic[1])
        function = next(
            (
                node.name
                for node in functions
                if node.lineno <= line <= (node.end_lineno or node.lineno)
            ),
            None,
        )
        assert function is not None, error
        actual.setdefault(function, []).append(diagnostic[2])
    assert actual == expected, result.stdout
