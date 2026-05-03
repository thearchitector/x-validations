"""Runtime validation API."""

from typing import Any


def xvalidate(payload: Any, schema: dict[str, Any]) -> None:
    """Validate JSON-compatible payload against exported x-validations schema."""
    from xvalidations import _xvalidations  # noqa: PLC0415

    _xvalidations.xvalidate(payload, schema)
