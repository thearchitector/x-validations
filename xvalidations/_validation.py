"""Shared runtime validation policy for public Python APIs."""

from pydantic import ConfigDict

STRICT_CALL_CONFIG = ConfigDict(
    arbitrary_types_allowed=True, defer_build=True, strict=True
)
