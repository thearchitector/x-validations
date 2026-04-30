"""Resolve marker helpers."""

from typing import TYPE_CHECKING, Any, cast

from xvalidations.errors import ResolveError
from xvalidations.jsonpath import evaluate_jsonpath

if TYPE_CHECKING:
    from xvalidations.models import JsonValue


def resolve_placeholders(
    node: "JsonValue", instance_json: "JsonValue", base_schema: "JsonValue"
) -> "JsonValue":
    """Resolve all $resolve placeholders inside a JSON value."""
    if isinstance(node, dict):
        if set(node) == {"$resolve"}:
            ref = node["$resolve"]
            if not isinstance(ref, str):
                msg = "$resolve value must be a string"
                raise ResolveError(msg)
            return resolve_ref(ref, instance_json, base_schema)
        return {
            key: resolve_placeholders(value, instance_json, base_schema)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [
            resolve_placeholders(value, instance_json, base_schema) for value in node
        ]
    return node


def resolve_ref(
    ref: str, instance_json: "JsonValue", base_schema: "JsonValue"
) -> "JsonValue":
    """Resolve a JSONPath or JSON Pointer reference."""
    if ref.startswith("$"):
        return [match.value for match in evaluate_jsonpath(ref, instance_json)]
    if ref.startswith("#/") or ref == "#":
        return _resolve_json_pointer(ref, base_schema)
    msg = f"unsupported $resolve reference: {ref}"
    raise ResolveError(msg)


def _resolve_json_pointer(ref: str, document: "JsonValue") -> "JsonValue":
    if ref == "#":
        return document

    current: Any = document
    for raw_token in ref.removeprefix("#/").split("/"):
        token = _unescape_json_pointer_token(raw_token)
        if isinstance(current, dict):
            if token not in current:
                msg = f"missing JSON Pointer token: {token}"
                raise ResolveError(msg)
            current = current[token]
        elif isinstance(current, list):
            try:
                if not _is_json_pointer_array_index(token):
                    msg = f"invalid JSON Pointer array index: {token}"
                    raise ResolveError(msg)
                index = int(token)
                current = current[index]
            except (ValueError, IndexError) as exc:
                msg = f"missing JSON Pointer index: {token}"
                raise ResolveError(msg) from exc
        else:
            msg = f"cannot resolve through scalar token: {token}"
            raise ResolveError(msg)
    return cast("JsonValue", current)


def _unescape_json_pointer_token(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _is_json_pointer_array_index(token: str) -> bool:
    return token == "0" or (token[:1] in "123456789" and token.isdecimal())
