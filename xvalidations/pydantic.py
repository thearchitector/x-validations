"""Pydantic integration."""

import copy
import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import UnionType
from typing import ClassVar, Literal, TypeIs, Union, Unpack, cast, get_args, get_origin

from pydantic import BaseModel, ConfigDict, ValidationError, validate_call
from pydantic.aliases import AliasChoices
from pydantic.fields import FieldInfo
from pydantic.json_schema import (
    DEFAULT_REF_TEMPLATE,
    GenerateJsonSchema,
    JsonSchemaMode,
)

from xvalidations._validation import STRICT_CALL_CONFIG
from xvalidations.authoring import (
    AuthoredValue,
    KeySelector,
    Path,
    ResolveMarker,
    Segment,
    Selector,
    XValidationContext,
    XValidationDeclaration,
)
from xvalidations.errors import InvalidRuleError
from xvalidations.models import JsonObject, JsonValue, XValidationRule

type LiteralUnionFormat = Literal["any_of", "primitive_type_array"]
type ExportMode = Literal["validation", "serialization"]
type DefsMap = dict[str, JsonValue]

DEFAULT_SCHEMA_MODE: ExportMode = "validation"
DEFS_FIELD = "$defs"
XVALIDATIONS_SCHEMA_URI = (
    "https://thearchitector.dev/xvalidations/meta/x-validations.schema.json"
)


@dataclass(frozen=True)
class _ExportContext:
    defs: DefsMap
    by_alias: bool
    mode: ExportMode


class XValidatedModel(BaseModel):
    """BaseModel subclass that exports x-validation rules into JSON Schema."""

    __xvalidation_declarations__: ClassVar[tuple[XValidationDeclaration, ...]] = ()

    def __init_subclass__(cls, **kwargs: Unpack[ConfigDict]) -> None:
        super().__init_subclass__(**kwargs)
        inherited = [
            declaration
            for base in cls.__bases__
            for declaration in getattr(base, "__xvalidation_declarations__", ())
        ]
        declared = [
            declaration
            for value in cls.__dict__.values()
            if (declaration := getattr(value, "__xvalidation_declaration__", None))
            is not None
        ]
        cls.__xvalidation_declarations__ = (*inherited, *declared)

    @classmethod
    @validate_call(config=STRICT_CALL_CONFIG)
    def model_json_schema(
        cls,
        by_alias: bool = True,  # skylos: ignore[SKY-L029]
        ref_template: str = DEFAULT_REF_TEMPLATE,
        schema_generator: type[GenerateJsonSchema] = GenerateJsonSchema,
        mode: JsonSchemaMode = DEFAULT_SCHEMA_MODE,
        union_format: LiteralUnionFormat = "any_of",
    ) -> JsonObject:
        """Generate JSON Schema with root x-validation metadata."""
        base_schema = cast(
            JsonObject,
            super().model_json_schema(
                by_alias=by_alias,
                ref_template=ref_template,
                schema_generator=schema_generator,
                mode=mode,
                union_format=union_format,
            ),
        )
        return _export_owned_schema(cls, base_schema, by_alias=by_alias, mode=mode)


@validate_call(config=STRICT_CALL_CONFIG)
def export_schema(
    model_cls: type[BaseModel],
    base_schema: Mapping[str, JsonValue] | None = None,
    *,
    by_alias: bool = True,
    mode: JsonSchemaMode = DEFAULT_SCHEMA_MODE,
) -> JsonObject:
    """Export a Pydantic schema with root x-validation rules."""
    owned_schema = (
        copy.deepcopy(dict(base_schema))
        if base_schema is not None
        else _fresh_schema_for(model_cls, by_alias=by_alias, mode=mode)
    )
    return _export_owned_schema(model_cls, owned_schema, by_alias=by_alias, mode=mode)


def _export_owned_schema(
    model_cls: type[BaseModel],
    schema: JsonObject,
    *,
    by_alias: bool,
    mode: JsonSchemaMode,
) -> JsonObject:
    schema["$schema"] = XVALIDATIONS_SCHEMA_URI

    raw_defs = schema.pop(DEFS_FIELD, {})
    defs = raw_defs if isinstance(raw_defs, dict) else {}
    rules: list[XValidationRule] = []
    seen_rule_ids: set[str] = set()

    export_mode: ExportMode = mode
    context = _ExportContext(defs=defs, by_alias=by_alias, mode=export_mode)
    for prefix, visited_model, declaration in _declarations_depth_first(
        model_cls, Path(), context, set()
    ):
        rule = _compile_declaration(declaration, prefix, visited_model, context)
        if rule.id in seen_rule_ids:
            msg = f"duplicate x-validation rule id: {rule.id}"
            raise InvalidRuleError(msg)
        seen_rule_ids.add(rule.id)
        rules.append(rule)

    if defs:
        schema[DEFS_FIELD] = defs

    if rules:
        schema["x-validations"] = [
            cast(JsonObject, rule.model_dump(by_alias=True, exclude_none=True))
            for rule in rules
        ]
    else:
        schema.pop("x-validations", None)

    return schema


def _fresh_schema_for(
    model_cls: type[BaseModel], *, by_alias: bool, mode: JsonSchemaMode
) -> JsonObject:
    generated = (
        super(XValidatedModel, model_cls).model_json_schema(
            by_alias=by_alias, mode=mode
        )
        if issubclass(model_cls, XValidatedModel)
        else model_cls.model_json_schema(by_alias=by_alias, mode=mode)
    )
    return cast(JsonObject, generated)


def _definition_name(value: JsonValue) -> str:
    """Return a deterministic generated definition name for a JSON value."""
    dumped = _stable_json(value)
    digest = hashlib.sha256(dumped.encode()).hexdigest()[:12]
    return f"xv_{digest}"


def _replace_resolve_marker(
    marker: ResolveMarker,
    prefix: Path,
    model_cls: type[BaseModel] | None,
    context: _ExportContext,
) -> JsonValue:
    value = marker.value
    if isinstance(value, Path):
        local_path = (
            _alias_path_for_model(
                value, model_cls, by_alias=context.by_alias, mode=context.mode
            )
            if model_cls is not None
            else value
        )
        return {"$resolve": _join_paths(prefix, local_path).to_jsonpath()}

    name = _definition_name(value)
    context.defs.setdefault(name, value)
    return {"$resolve": f"#/$defs/{_escape_json_pointer_token(name)}"}


def _replace_markers(
    node: AuthoredValue,
    prefix: Path,
    model_cls: type[BaseModel] | None,
    context: _ExportContext,
) -> JsonValue:
    if isinstance(node, ResolveMarker):
        return _replace_resolve_marker(node, prefix, model_cls, context)
    if isinstance(node, dict):
        return {
            str(key): _replace_markers(value, prefix, model_cls, context)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_replace_markers(value, prefix, model_cls, context) for value in node]
    return cast("JsonValue", node)


def _compile_declaration(
    declaration: XValidationDeclaration,
    prefix: Path,
    model_cls: type[BaseModel],
    context: _ExportContext,
) -> XValidationRule:
    try:
        authored = declaration.factory(XValidationContext())
    except ValidationError as error:
        msg = f"x-validation rule {declaration.id!r} did not return authored rule data"
        raise InvalidRuleError(msg) from error

    target = _alias_path_for_model(
        authored.target, model_cls, by_alias=context.by_alias, mode=context.mode
    )
    rule_data: dict[str, JsonValue] = {
        "id": declaration.id,
        "target": _join_paths(prefix, target).to_jsonpath(),
        "assert": _replace_markers(authored.assert_, prefix, model_cls, context),
    }
    if declaration.description is not None:
        rule_data["description"] = declaration.description
    return XValidationRule.model_validate(rule_data)


def _declarations_depth_first(
    model_cls: type[BaseModel],
    prefix: Path,
    context: _ExportContext,
    active: set[type[BaseModel]],
) -> Iterator[tuple[Path, type[XValidatedModel], XValidationDeclaration]]:
    if model_cls in active:
        return
    active.add(model_cls)

    try:
        if issubclass(model_cls, XValidatedModel):
            for declaration in model_cls.__xvalidation_declarations__:
                yield prefix, model_cls, declaration

        for field_name, field_info in model_cls.model_fields.items():
            export_name = _field_export_name(
                field_name, field_info, by_alias=context.by_alias, mode=context.mode
            )
            field_prefix = Path((
                *prefix.segments,
                Segment((KeySelector(export_name),)),
            ))
            for nested_model, nested_prefix in _model_types_from_annotation(
                field_info.annotation, field_prefix
            ):
                yield from _declarations_depth_first(
                    nested_model, nested_prefix, context, active
                )
    finally:
        active.remove(model_cls)


def _model_types_from_annotation(
    annotation: object, prefix: Path
) -> Iterator[tuple[type[BaseModel], Path]]:
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is None:
        yield from _model_type_from_plain_annotation(annotation, prefix)
        return

    if origin is Union or origin is UnionType:
        yield from _model_types_from_args(args, prefix)
        return

    if str(origin) == "<class 'typing.Annotated'>":
        if args:
            yield from _model_types_from_annotation(args[0], prefix)
        return

    if origin in {list, tuple, set, frozenset}:
        if args:
            yield from _model_types_from_annotation(args[0], prefix.each())
        return

    yield from _model_types_from_args(args, prefix)


def _model_type_from_plain_annotation(
    annotation: object, prefix: Path
) -> Iterator[tuple[type[BaseModel], Path]]:
    if _is_model_type(annotation):
        yield annotation, prefix


def _model_types_from_args(
    args: tuple[object, ...], prefix: Path
) -> Iterator[tuple[type[BaseModel], Path]]:
    for arg in args:
        yield from _model_types_from_annotation(arg, prefix)


def _field_export_name(
    field_name: str, field_info: FieldInfo, *, by_alias: bool, mode: ExportMode
) -> str:
    if not by_alias:
        return field_name
    if mode == "serialization":
        alias = getattr(field_info, "serialization_alias", None) or getattr(
            field_info, "alias", None
        )
    else:
        alias = getattr(field_info, "validation_alias", None) or getattr(
            field_info, "alias", None
        )
    if isinstance(alias, str):
        return alias
    if isinstance(alias, AliasChoices):
        return _field_export_name_from_alias_choices(alias, field_name)
    return field_name


def _alias_path_for_model(
    path: Path, model_cls: type[BaseModel], *, by_alias: bool, mode: ExportMode
) -> Path:
    if not by_alias:
        return path

    current_model: type[BaseModel] | None = model_cls
    aliased_segments: list[Segment] = []
    for segment in path.segments:
        selectors: list[Selector] = []
        next_model: type[BaseModel] | None = None
        segment_had_model_key = False
        for selector in segment.selectors:
            if isinstance(selector, KeySelector) and current_model is not None:
                field_info = current_model.model_fields.get(selector.name)
                if field_info is not None:
                    segment_had_model_key = True
                    selectors.append(
                        KeySelector(
                            _field_export_name(
                                selector.name, field_info, by_alias=True, mode=mode
                            )
                        )
                    )
                    next_model = _first_model_from_annotation(field_info.annotation)
                    continue
            selectors.append(selector)
        aliased_segments.append(Segment(tuple(selectors), recursive=segment.recursive))
        if segment_had_model_key:
            current_model = next_model
    return Path(tuple(aliased_segments))


def _is_model_type(annotation: object) -> TypeIs[type[BaseModel]]:
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def _field_export_name_from_alias_choices(alias: AliasChoices, fallback: str) -> str:
    for choice in alias.choices:
        if isinstance(choice, str):
            return choice
    return fallback


def _first_model_from_annotation(annotation: object) -> type[BaseModel] | None:
    for model_cls, _ in _model_types_from_annotation(annotation, Path()):
        return model_cls
    return None


def _join_paths(prefix: Path, path: Path) -> Path:
    return Path((*prefix.segments, *path.segments))


def _stable_json(value: JsonValue) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _escape_json_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")
