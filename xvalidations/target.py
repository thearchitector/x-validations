"""Target overlay helpers."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xvalidations.models import InstanceLocation, JsonValue


def location_to_schema_overlay(
    location: "InstanceLocation", assertion: "JsonValue"
) -> "dict[str, JsonValue] | JsonValue":
    """Create a root JSON Schema overlay for a concrete instance location."""
    if not location:
        return assertion

    head, *tail = location
    child = location_to_schema_overlay(tuple(tail), assertion)
    if isinstance(head, str):
        return {"type": "object", "properties": {head: child}}

    prefix_items: "list[JsonValue]" = [True] * head
    prefix_items.append(child)
    return {"type": "array", "minItems": head + 1, "prefixItems": prefix_items}
