import copy
import hashlib
import inspect
import json
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path as FilePath
from typing import Any, cast, get_args
from urllib.parse import quote

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, GetJsonSchemaHandler
from pydantic.aliases import AliasChoices, AliasPath
from pydantic.fields import FieldInfo
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema

from .authoring import _Declaration, _XValidationDescriptor
from .errors import InvalidRuleError, InvalidSchemaError
from .models import ValidationRule
from .path import (
    Comparison,
    Expr,
    FilterSelector,
    IndexSelector,
    KeySelector,
    Path,
    Segment,
    SliceSelector,
    WildcardSelector,
    path_to_jsonpath,
)

XVALIDATIONS_SCHEMA_URI = "https://thearchitector.dev/xvalidations/schema.json"
_HOOK_WRAPPER_TAG = "__xvalidations_installed_hook__"
_PYDANTIC_SCHEMA_HOOK = "__get_pydantic_json_schema__"
_RESERVED_RESOURCE_KEYS = frozenset({"$schema", "$id", "x-validations", "x-constants"})
_BUNDLE_SINGLE_SCHEMA_KEYWORDS = frozenset({
    "additionalItems",
    "additionalProperties",
    "contains",
    "contentSchema",
    "else",
    "if",
    "items",
    "not",
    "propertyNames",
    "then",
    "unevaluatedItems",
    "unevaluatedProperties",
})
_BUNDLE_ARRAY_SCHEMA_KEYWORDS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
_BUNDLE_OBJECT_SCHEMA_KEYWORDS = frozenset({
    "$defs",
    "definitions",
    "dependentSchemas",
    "patternProperties",
    "properties",
})
_TRAVERSAL_OBJECT_SCHEMA_KEYWORDS = frozenset({
    "dependentSchemas",
    "patternProperties",
    "properties",
})
type _OwnedValue = (
    None | bool | int | float | str | Path | list[_OwnedValue] | dict[str, _OwnedValue]
)


@dataclass(frozen=True, slots=True)
class _EffectiveRule:
    declaration: _Declaration
    target: Path
    assertion: dict[str, _OwnedValue]


@dataclass(frozen=True, slots=True)
class _SelectedPath:
    path: Path
    fragments: tuple[object, ...]
    many: bool


_ASSERTION_META_SCHEMA = json.loads(
    FilePath(__file__).with_name("assertion-schema.json").read_text(encoding="utf-8")
)
Draft202012Validator.check_schema(_ASSERTION_META_SCHEMA)
_ASSERTION_META_VALIDATOR = Draft202012Validator(
    _ASSERTION_META_SCHEMA, format_checker=Draft202012Validator.FORMAT_CHECKER
)


def _install_model_hooks(owner: type[object]) -> None:
    local = owner.__dict__.get(_PYDANTIC_SCHEMA_HOOK)
    if local is not None and _is_installed_wrapper(local):
        return
    prior = local
    if prior is None:
        prior = inspect.getattr_static(owner, _PYDANTIC_SCHEMA_HOOK)
        if _is_installed_wrapper(prior):
            return
    wrapper = cast(Any, _schema_wrapper(prior))
    setattr(wrapper, _HOOK_WRAPPER_TAG, True)
    setattr(owner, _PYDANTIC_SCHEMA_HOOK, classmethod(wrapper))


def _is_installed_wrapper(hook: object) -> bool:
    function = hook.__func__ if isinstance(hook, classmethod) else hook
    return bool(getattr(function, _HOOK_WRAPPER_TAG, False))


def _schema_wrapper(prior: object) -> object:
    def json_schema_hook(
        model_cls: type[BaseModel],
        core_schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        schema = cast(
            JsonSchemaValue, _invoke_hook(prior, model_cls, core_schema, handler)
        )
        if handler.mode == "serialization" or _is_ruled_resource(schema):
            return schema
        rules = _build_effective_rules(model_cls)
        if not rules:
            return schema
        return _render_model_resource(model_cls, schema, handler, rules)

    return json_schema_hook


def _invoke_hook(hook: object, model_cls: type[BaseModel], *args: object) -> object:
    getter = getattr(hook, "__get__", None)
    bound = getter(None, model_cls) if getter is not None else hook
    if not callable(bound):
        raise TypeError("Pydantic hook is not callable")
    return bound(*args)


def _build_effective_rules(model_cls: type[BaseModel]) -> tuple[_EffectiveRule, ...]:
    declarations = _collect_effective_declarations(model_cls)
    duplicate_ids = _duplicates(declaration.id for declaration in declarations.values())
    if duplicate_ids:
        joined = ", ".join(repr(rule_id) for rule_id in duplicate_ids)
        raise InvalidRuleError(f"duplicate final validation rule IDs: {joined}")
    rules = [
        _invoke_declaration(model_cls, declaration)
        for declaration in declarations.values()
    ]
    return tuple(sorted(rules, key=lambda rule: rule.declaration.id))


def _collect_effective_declarations(
    model_cls: type[BaseModel],
) -> dict[str, _Declaration]:
    inherited: dict[str, _Declaration] = {}
    sources: dict[str, _Declaration] = {}
    conflicts: set[str] = set()
    for base in model_cls.__bases__:
        if not isinstance(base, type) or not issubclass(base, BaseModel):
            continue
        for name, declaration in _collect_effective_declarations(base).items():
            previous = sources.get(name)
            if previous is None:
                inherited[name] = declaration
                sources[name] = declaration
            elif previous.descriptor is not declaration.descriptor:
                conflicts.add(name)

    local_descriptors = {
        name: value
        for name, value in model_cls.__dict__.items()
        if isinstance(value, _XValidationDescriptor)
    }
    for name in inherited:
        if name in model_cls.__dict__ and name not in local_descriptors:
            raise InvalidRuleError(
                f"inherited validation rule method {name!r} is shadowed without @xvalidation"
            )
    unresolved = conflicts.difference(local_descriptors)
    if unresolved:
        joined = ", ".join(repr(name) for name in sorted(unresolved))
        raise InvalidRuleError(f"ambiguous inherited validation rule methods: {joined}")
    for name, descriptor in local_descriptors.items():
        declaration = descriptor.declaration
        has_inherited = name in inherited
        if has_inherited and not declaration.override:
            raise InvalidRuleError(
                f"validation rule method {name!r} overrides an inherited rule without an override marker"
            )
        if not has_inherited and declaration.override:
            raise InvalidRuleError(
                f"validation rule method {name!r} is marked override but no inherited rule exists"
            )
        inherited[name] = declaration
    return inherited


def _invoke_declaration(
    model_cls: type[BaseModel], declaration: _Declaration
) -> _EffectiveRule:
    if not declaration.id:
        raise InvalidRuleError(
            f"validation rule method {declaration.name!r} produces an empty ID"
        )
    authored = declaration.descriptor.invoke(model_cls)
    if not isinstance(authored, ValidationRule):
        raise InvalidRuleError(
            f"validation rule factory {declaration.name!r} must return ValidationRule"
        )
    if not isinstance(authored.target, Path):
        raise InvalidRuleError(
            f"validation rule {declaration.id!r} has an invalid target path"
        )
    assertion = _own_object(authored.assertion, f"rule {declaration.id!r} assertion")
    if not _contains_path(assertion) and set(assertion) != {"x-uniqueBy"}:
        raise InvalidRuleError(
            f"validation rule {declaration.id!r} is static; use Pydantic field constraints instead"
        )
    _validate_path_literals(authored.target)
    return _EffectiveRule(declaration, authored.target, assertion)


def _own_object(value: object, context: str) -> dict[str, _OwnedValue]:
    owned = _own_value(value, context)
    if not isinstance(owned, dict):
        raise InvalidRuleError(f"{context} must be an object")
    return owned


def _own_value(value: object, context: str) -> _OwnedValue:
    if isinstance(value, Path):
        return value
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidRuleError(f"{context} contains a non-finite float")
        return value
    if isinstance(value, list | tuple):
        return [_own_value(item, f"{context} item") for item in value]
    if isinstance(value, dict):
        if set(value) == {"$path"}:
            raise InvalidRuleError(
                f"{context} uses the reserved singleton $path marker syntax"
            )
        if set(value) == {"$resolve"}:
            raise InvalidRuleError(
                f"{context} uses the removed singleton $resolve marker syntax"
            )
        owned: dict[str, _OwnedValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvalidRuleError(f"{context} contains a non-string object key")
            owned[key] = _own_value(item, f"{context}.{key}")
        return owned
    raise InvalidRuleError(
        f"{context} contains non-JSON value of type {type(value).__name__}"
    )


def _contains_path(value: _OwnedValue) -> bool:
    if isinstance(value, Path):
        return True
    if isinstance(value, list):
        return any(_contains_path(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_path(item) for item in value.values())
    return False


def _render_model_resource(
    model_cls: type[BaseModel],
    schema: JsonSchemaValue,
    handler: GetJsonSchemaHandler,
    rules: tuple[_EffectiveRule, ...],
) -> JsonSchemaValue:
    collisions = _RESERVED_RESOURCE_KEYS.intersection(schema)
    if collisions:
        joined = ", ".join(sorted(collisions))
        raise InvalidSchemaError(f"model JSON Schema overrides reserved keys: {joined}")

    rendered_rules: list[dict[str, object]] = []
    for rule in rules:
        selected_target = _select_path(rule.target, model_cls, schema, handler)
        target_schema = _combine_fragments(selected_target.fragments, handler)
        validation_assertion, rendered_assertion = _transform_assertion(
            rule.assertion, model_cls, schema, handler
        )
        private_document = {"target": target_schema, "assert": validation_assertion}
        try:
            _ASSERTION_META_VALIDATOR.validate(private_document)
        except JsonSchemaValidationError as error:
            raise InvalidRuleError(
                f"validation rule {rule.declaration.id!r} target/assertion is invalid: {error.message}"
            ) from error
        rendered: dict[str, object] = {
            "id": rule.declaration.id,
            "target": path_to_jsonpath(selected_target.path),
            "assert": rendered_assertion,
        }
        if rule.declaration.description is not None:
            rendered["description"] = rule.declaration.description
        rendered_rules.append(rendered)

    resource = _bundle_resource(schema, handler)
    resource["$schema"] = XVALIDATIONS_SCHEMA_URI
    resource["x-validations"] = rendered_rules
    digest = hashlib.sha256(_canonical_bytes(resource)).hexdigest()
    qualified_name = quote(f"{model_cls.__module__}.{model_cls.__qualname__}", safe="")
    resource["$id"] = f"urn:xvalidations:{qualified_name}:{digest}"
    return resource


def _transform_assertion(
    value: _OwnedValue,
    model_cls: type[BaseModel],
    root_schema: JsonSchemaValue,
    handler: GetJsonSchemaHandler,
) -> tuple[object, object]:
    if isinstance(value, Path):
        selected = _select_path(value, model_cls, root_schema, handler)
        fragment = _combine_fragments(selected.fragments, handler)
        validation: object = fragment
        if selected.many:
            validation = {"type": "array", "items": fragment}
        return validation, {"$path": path_to_jsonpath(selected.path)}
    if isinstance(value, list):
        pairs = [
            _transform_assertion(item, model_cls, root_schema, handler)
            for item in value
        ]
        return [pair[0] for pair in pairs], [pair[1] for pair in pairs]
    if isinstance(value, dict):
        transformed = {
            key: _transform_assertion(item, model_cls, root_schema, handler)
            for key, item in value.items()
        }
        return (
            {key: pair[0] for key, pair in transformed.items()},
            {key: pair[1] for key, pair in transformed.items()},
        )
    return copy.deepcopy(value), copy.deepcopy(value)


def _select_path(
    path: Path,
    model_cls: type[BaseModel],
    root_schema: JsonSchemaValue,
    handler: GetJsonSchemaHandler,
) -> _SelectedPath:
    _validate_path_literals(path)
    fragments: tuple[object, ...] = (root_schema,)
    model_types = tuple(_reachable_models(model_cls))
    rendered_segments: list[Segment] = []
    many = False
    for segment in path.segments:
        if segment.recursive or len(segment.selectors) > 1:
            many = True
        selected: list[object] = []
        rendered_selectors: list[object] = []
        next_model_types: list[type[BaseModel]] = []
        for selector in segment.selectors:
            if isinstance(selector, WildcardSelector | SliceSelector | FilterSelector):
                many = True
            rebound, selected_fragments, advanced = _select_schema_selector(
                selector, fragments, model_types, handler, recursive=segment.recursive
            )
            rendered_selectors.append(rebound)
            selected.extend(selected_fragments)
            next_model_types.extend(advanced)
        if not selected:
            raise InvalidRuleError(
                f"typed path {path_to_jsonpath(path)!r} cannot traverse generated schema for {model_cls.__name__}"
            )
        fragments = tuple(_unique_schemas(selected))
        model_types = tuple(
            cast(type[BaseModel], item) for item in _unique_objects(next_model_types)
        )
        rendered_segments.append(
            Segment(tuple(cast(Any, rendered_selectors)), segment.recursive)
        )
    return _SelectedPath(Path(tuple(rendered_segments)), fragments, many)


def _select_schema_selector(
    selector: object,
    fragments: tuple[object, ...],
    model_types: tuple[type[BaseModel], ...],
    handler: GetJsonSchemaHandler,
    *,
    recursive: bool,
) -> tuple[object, list[object], list[type[BaseModel]]]:
    source_fragments = (
        list(_descendant_schemas(fragments, handler)) if recursive else list(fragments)
    )
    if isinstance(selector, KeySelector):
        names = _exported_names(selector.name, model_types, source_fragments, handler)
        matches: dict[str, list[object]] = {}
        for name in names:
            values = _property_fragments(source_fragments, name, handler)
            if values:
                matches[name] = values
        if len(matches) > 1:
            raise InvalidRuleError(
                f"typed path key {selector.name!r} has ambiguous exported aliases"
            )
        if not matches:
            values = _mapping_value_fragments(source_fragments, handler)
            if values:
                return selector, values, list(model_types)
            return selector, [], []
        name, values = next(iter(matches.items()))
        return KeySelector(name), values, list(model_types)
    if isinstance(selector, WildcardSelector):
        return (
            selector,
            _wildcard_fragments(source_fragments, handler),
            list(model_types),
        )
    if isinstance(selector, IndexSelector | SliceSelector | FilterSelector):
        values = _item_fragments(source_fragments, selector, handler)
        advanced = list(model_types)
        if isinstance(selector, FilterSelector) and values:
            selector = _bind_predicate_aliases(
                selector, tuple(values), tuple(advanced), handler
            )
        return selector, values, advanced
    return selector, [], []


def _bind_predicate_aliases(
    selector: FilterSelector,
    fragments: tuple[object, ...],
    model_types: tuple[type[BaseModel], ...],
    handler: GetJsonSchemaHandler,
) -> FilterSelector:
    rendered: list[KeySelector] = []
    current_fragments = fragments
    current_model_types = model_types
    for key in selector.predicate.expr.segments:
        rebound, selected, advanced = _select_schema_selector(
            key, current_fragments, current_model_types, handler, recursive=False
        )
        if not isinstance(rebound, KeySelector) or not selected:
            raise InvalidRuleError(
                f"predicate path cannot traverse generated schema key {key.name!r}"
            )
        rendered.append(rebound)
        current_fragments = tuple(selected)
        current_model_types = tuple(advanced)
    return FilterSelector(
        Comparison(
            Expr(tuple(rendered)), selector.predicate.operator, selector.predicate.value
        )
    )


def _exported_names(
    raw_name: str,
    model_types: tuple[type[BaseModel], ...],
    fragments: list[object],
    handler: GetJsonSchemaHandler,
) -> tuple[str, ...]:
    candidates: list[str] = []
    for model_type in model_types:
        field = model_type.model_fields.get(raw_name)
        if field is not None:
            candidates.extend(_field_candidates(raw_name, field))
    candidates.append(raw_name)
    properties: set[str] = set()
    for fragment in fragments:
        for variant in _schema_variants(fragment, handler):
            raw_properties = variant.get("properties")
            if isinstance(raw_properties, dict):
                properties.update(raw_properties)
    present = tuple(
        candidate for candidate in dict.fromkeys(candidates) if candidate in properties
    )
    return present or (raw_name,)


def _field_candidates(name: str, field: FieldInfo) -> list[str]:
    candidates: list[str] = []
    alias = field.validation_alias
    if isinstance(alias, str):
        candidates.append(alias)
    elif isinstance(alias, AliasChoices):
        candidates.extend(choice for choice in alias.choices if isinstance(choice, str))
    elif isinstance(alias, AliasPath) and alias.path and isinstance(alias.path[0], str):
        candidates.append(alias.path[0])
    if isinstance(field.alias, str):
        candidates.append(field.alias)
    candidates.append(name)
    return candidates


def _reachable_models(model_cls: type[BaseModel]) -> Iterable[type[BaseModel]]:
    pending = [model_cls]
    seen: set[type[BaseModel]] = set()
    while pending:
        model_type = pending.pop()
        if model_type in seen:
            continue
        seen.add(model_type)
        yield model_type
        for field in model_type.model_fields.values():
            pending.extend(_models_in_annotation(field.annotation))


def _models_in_annotation(annotation: object) -> list[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    models: list[type[BaseModel]] = []
    for argument in get_args(annotation):
        models.extend(_models_in_annotation(argument))
    return models


def _schema_variants(
    schema: object, handler: GetJsonSchemaHandler
) -> Iterable[dict[str, object]]:
    resolved = _resolve_schema(schema, handler)
    if not isinstance(resolved, dict):
        return
    for keyword in ("anyOf", "oneOf"):
        branches = resolved.get(keyword)
        if isinstance(branches, list):
            for branch in branches:
                yield from _schema_variants(branch, handler)
            return
    yield resolved


def _resolve_schema(schema: object, handler: GetJsonSchemaHandler) -> object:
    if not isinstance(schema, dict) or "$ref" not in schema:
        return schema
    try:
        resolved = handler.resolve_ref_schema(cast(JsonSchemaValue, schema))
    except LookupError as error:
        raise InvalidRuleError(
            f"generated schema reference {schema.get('$ref')!r} cannot be resolved"
        ) from error
    siblings = {key: value for key, value in schema.items() if key != "$ref"}
    if siblings and isinstance(resolved, dict):
        return {**resolved, **siblings}
    return resolved


def _property_fragments(
    schemas: Iterable[object], name: str, handler: GetJsonSchemaHandler
) -> list[object]:
    selected: list[object] = []
    for schema in schemas:
        for variant in _schema_variants(schema, handler):
            properties = variant.get("properties")
            if isinstance(properties, dict) and name in properties:
                selected.append(properties[name])
    return selected


def _item_fragments(
    schemas: Iterable[object], selector: object, handler: GetJsonSchemaHandler
) -> list[object]:
    selected: list[object] = []
    for schema in schemas:
        for variant in _schema_variants(schema, handler):
            prefix = variant.get("prefixItems")
            if isinstance(selector, IndexSelector) and isinstance(prefix, list):
                index = (
                    selector.index
                    if selector.index >= 0
                    else len(prefix) + selector.index
                )
                if 0 <= index < len(prefix):
                    selected.append(prefix[index])
                    continue
            elif isinstance(prefix, list):
                selected.extend(prefix)
            items = variant.get("items")
            if isinstance(items, dict | bool):
                selected.append(items)
    return selected


def _mapping_value_fragments(
    schemas: Iterable[object], handler: GetJsonSchemaHandler
) -> list[object]:
    selected: list[object] = []
    for schema in schemas:
        for variant in _schema_variants(schema, handler):
            additional = variant.get("additionalProperties")
            if isinstance(additional, dict | bool):
                selected.append(additional)
    return selected


def _wildcard_fragments(
    schemas: Iterable[object], handler: GetJsonSchemaHandler
) -> list[object]:
    selected: list[object] = []
    for schema in schemas:
        for variant in _schema_variants(schema, handler):
            properties = variant.get("properties")
            if isinstance(properties, dict):
                selected.extend(properties.values())
            additional = variant.get("additionalProperties")
            if isinstance(additional, dict | bool):
                selected.append(additional)
            items = variant.get("items")
            if isinstance(items, dict | bool):
                selected.append(items)
            prefix = variant.get("prefixItems")
            if isinstance(prefix, list):
                selected.extend(prefix)
    return selected


def _descendant_schemas(
    roots: Iterable[object], handler: GetJsonSchemaHandler
) -> Iterable[object]:
    pending = list(roots)
    seen: set[bytes] = set()
    while pending:
        schema = pending.pop()
        resolved = _resolve_schema(schema, handler)
        try:
            identity = _canonical_bytes(resolved)
        except TypeError, ValueError:
            identity = repr(resolved).encode()
        if identity in seen:
            continue
        seen.add(identity)
        yield resolved
        if not isinstance(resolved, dict):
            continue
        for keyword in _BUNDLE_SINGLE_SCHEMA_KEYWORDS:
            child = resolved.get(keyword)
            if isinstance(child, dict | bool):
                pending.append(child)
        for keyword in _BUNDLE_ARRAY_SCHEMA_KEYWORDS:
            children = resolved.get(keyword)
            if isinstance(children, list):
                pending.extend(children)
        for keyword in _TRAVERSAL_OBJECT_SCHEMA_KEYWORDS:
            children = resolved.get(keyword)
            if isinstance(children, dict):
                pending.extend(children.values())


def _combine_fragments(
    fragments: Iterable[object], handler: GetJsonSchemaHandler
) -> object:
    resolved = [
        copy.deepcopy(_resolve_schema(fragment, handler)) for fragment in fragments
    ]
    unique = list(_unique_schemas(resolved))
    if not unique:
        raise InvalidRuleError("typed path selected no generated schema fragments")
    return unique[0] if len(unique) == 1 else {"anyOf": unique}


def _validate_path_literals(path: Path) -> None:
    for segment in path.segments:
        for selector in segment.selectors:
            if isinstance(selector, FilterSelector):
                _own_value(selector.predicate.value, "filter predicate")


def _bundle_resource(
    schema: JsonSchemaValue, handler: GetJsonSchemaHandler
) -> JsonSchemaValue:
    root = copy.deepcopy(schema)
    allocated: dict[str, str] = {}
    definitions: dict[str, object] = {}
    root_defs = root.get("$defs")
    occupied = set(root_defs) if isinstance(root_defs, dict) else set()

    def rewrite(node: object, *, is_root: bool = False) -> object:
        if isinstance(node, bool):
            return node
        if not isinstance(node, dict):
            return copy.deepcopy(node)
        if not is_root and _is_ruled_resource(node):
            return copy.deepcopy(node)
        rewritten = copy.deepcopy(node)
        reference = rewritten.pop("$ref", None)
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            key = allocated.get(reference)
            if key is None:
                try:
                    resolved = handler.resolve_ref_schema({"$ref": reference})
                except LookupError:
                    rewritten["$dynamicRef"] = "#"
                else:
                    if resolved == schema:
                        rewritten["$dynamicRef"] = "#"
                    else:
                        key = _definition_key(reference, occupied | set(definitions))
                        allocated[reference] = key
                        definitions[key] = {}
                        definitions[key] = rewrite(resolved)
                        rewritten["$dynamicRef"] = f"#/$defs/{key}"
            else:
                rewritten["$dynamicRef"] = f"#/$defs/{key}"
        elif reference is not None:
            rewritten["$ref"] = reference
        _rewrite_schema_children(rewritten, rewrite)
        return rewritten

    bundled = rewrite(root, is_root=True)
    if not isinstance(bundled, dict):
        raise InvalidSchemaError("Pydantic generated a non-object model schema")
    existing = bundled.get("$defs")
    if existing is not None and not isinstance(existing, dict):
        raise InvalidSchemaError("model $defs must be an object")
    if isinstance(existing, dict):
        definitions = {**existing, **definitions}
    if definitions:
        bundled["$defs"] = definitions
    return bundled


def _rewrite_schema_children(node: dict[str, object], rewrite: object) -> None:
    transform = cast(Any, rewrite)
    for key in _BUNDLE_SINGLE_SCHEMA_KEYWORDS:
        child = node.get(key)
        if isinstance(child, dict | bool):
            node[key] = transform(child)
        elif key == "items" and isinstance(child, list):
            node[key] = [transform(item) for item in child]
    for key in _BUNDLE_ARRAY_SCHEMA_KEYWORDS:
        children = node.get(key)
        if isinstance(children, list):
            node[key] = [transform(child) for child in children]
    for key in _BUNDLE_OBJECT_SCHEMA_KEYWORDS:
        children = node.get(key)
        if isinstance(children, dict):
            node[key] = {name: transform(child) for name, child in children.items()}


def _is_ruled_resource(node: object) -> bool:
    return (
        isinstance(node, dict)
        and node.get("$schema") == XVALIDATIONS_SCHEMA_URI
        and isinstance(node.get("x-validations"), list)
    )


def _definition_key(reference: str, occupied: set[str]) -> str:
    raw = reference.rsplit("/", 1)[-1]
    readable = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_") or "Model"
    digest = hashlib.sha256(reference.encode()).hexdigest()
    key = f"{readable}-{digest}"
    index = 2
    while key in occupied:
        key = f"{readable}-{digest}-{index}"
        index += 1
    return key


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _unique_schemas(values: Iterable[object]) -> Iterable[object]:
    seen: set[bytes] = set()
    for value in values:
        key = _canonical_bytes(value)
        if key not in seen:
            seen.add(key)
            yield value


def _unique_objects(values: Iterable[object]) -> Iterable[object]:
    seen: set[int] = set()
    for value in values:
        identity = id(value)
        if identity not in seen:
            seen.add(identity)
            yield value


def _duplicates(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)
