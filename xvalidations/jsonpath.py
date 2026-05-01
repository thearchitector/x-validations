"""JSONPath helpers."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from jsonpath_rfc9535 import find

from xvalidations.errors import JsonPathError

if TYPE_CHECKING:
    from xvalidations.models import InstanceLocation, JsonValue


@dataclass(frozen=True)
class JsonPathMatch:
    """A normalized JSONPath match."""

    value: "JsonValue"
    location: "InstanceLocation"
    normalized_path: str


def evaluate_jsonpath(query: str, value: "JsonValue") -> list[JsonPathMatch]:
    """Evaluate a JSONPath query and dedupe locations in first-seen order."""
    try:
        raw_matches = list(find(query, value))
    except Exception as exc:
        msg = f"invalid JSONPath query: {query}"
        raise JsonPathError(msg) from exc

    matches: list[JsonPathMatch] = []
    seen: "set[InstanceLocation]" = set()
    for raw_match in raw_matches:
        location = cast("InstanceLocation", tuple(raw_match.location))
        if location in seen:
            continue
        seen.add(location)
        matches.append(
            JsonPathMatch(
                value=cast("JsonValue", raw_match.value),
                location=location,
                normalized_path=raw_match.path(),
            )
        )
    return matches
