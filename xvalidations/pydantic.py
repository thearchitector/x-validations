"""Pydantic integration."""

import copy
import hashlib
import json
from types import UnionType
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Literal,
    Union,
    cast,
    get_args,
    get_origin,
)

from pydantic import BaseModel
from pydantic.aliases import AliasChoices, AliasPath
from pydantic.json_schema import DEFAULT_REF_TEMPLATE, GenerateJsonSchema

from xvalidations.authoring import (
    AuthoredRule,
    KeySelector,
    Path,
    ResolveMarker,
    Segment,
    XValidationContext,
    XValidationDeclaration,
    key,
)
from xvalidations.errors import InvalidRuleError
from xvalidations.models import XValidationRule

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from pydantic.json_schema import JsonSchemaMode

    from xvalidations.authoring import Selector
    from xvalidations.models import JsonValue


type LiteralUnionFormat = Literal["any_of", "primitive_type_array"]
type ExportMode = Literal["validation", "serialization"]


class XValidatedModel(BaseModel):
    """BaseModel subclass that exports x-validation rules into JSON Schema."""

    __xvalidation_declarations__: ClassVar[tuple[XValidationDeclaration, ...]] = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
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
        cls.__xvalidation_declarations__ = tuple([*inherited, *declared])

    @classmethod
    def model_json_schema(
        cls,
        by_alias: bool = True,
        ref_template: str = DEFAULT_REF_TEMPLATE,
        schema_generator: type[GenerateJsonSchema] = GenerateJsonSchema,
        mode: "JsonSchemaMode" = "validation",
        union_format: LiteralUnionFormat = "any_of",
    ) -> dict[str, Any]:
        """Generate JSON Schema with root x-validation metadata."""
        base_schema = cast("Any", BaseModel.model_json_schema).__func__(
            cls,
            by_alias=by_alias,
            ref_template=ref_template,
            schema_generator=schema_generator,
            mode=mode,
            union_format=union_format,
        )
        return export_schema(cls, base_schema=base_schema, by_alias=by_alias, mode=mode)


def export_schema(
    model_cls: type[BaseModel],
    base_schema: "Mapping[str, Any] | None" = None,
    by_alias: bool = True,
    mode: "JsonSchemaMode" = "validation",
) -> dict[str, Any]:
    """Export a Pydantic schema with root x-validation rules."""
    copied: dict[str, Any]
    if base_schema is None:
        copied = cast("Any", BaseModel.model_json_schema).__func__(
            model_cls, by_alias=by_alias, mode=mode
        )
    else:
        copied = copy.deepcopy(dict(base_schema))

    defs: "dict[str, JsonValue]" = _copy_defs(copied)
    rules: list[XValidationRule] = []
    seen_rule_ids: set[str] = set()

    export_mode: ExportMode = mode
    for prefix, visited_model in iter_xvalidated_models(
        model_cls, by_alias=by_alias, mode=export_mode
    ):
        for declaration in visited_model.__xvalidation_declarations__:
            rule = _compile_declaration(
                declaration, prefix, visited_model, by_alias, export_mode, defs
            )
            if rule.id in seen_rule_ids:
                msg = f"duplicate x-validation rule id: {rule.id}"
                raise InvalidRuleError(msg)
            seen_rule_ids.add(rule.id)
            rules.append(rule)

    if defs:
        copied["$defs"] = defs
    elif "$defs" in copied:
        copied.pop("$defs")

    if rules:
        copied["x-validations"] = [
            rule.model_dump(by_alias=True, exclude_none=False) for rule in rules
        ]
    else:
        copied.pop("x-validations", None)

    return copied


def definition_name(value: "JsonValue") -> str:
    """Return a deterministic generated definition name for a JSON value."""
    dumped = _stable_json(value)
    digest = hashlib.sha256(dumped.encode()).hexdigest()[:12]
    return f"xv_{digest}"


def replace_markers(
    node: Any, prefix: Path, defs: "dict[str, JsonValue]"
) -> "JsonValue":
    """Replace resolve markers with exported resolve objects."""
    return _replace_markers(node, prefix, defs, None, True, "validation")


def _replace_markers(
    node: Any,
    prefix: Path,
    defs: "dict[str, JsonValue]",
    model_cls: type[BaseModel] | None,
    by_alias: bool,
    mode: ExportMode,
) -> "JsonValue":
    if isinstance(node, ResolveMarker):
        value = node.value
        if isinstance(value, Path):
            local_path = (
                _alias_path_for_model(value, model_cls, by_alias, mode)
                if model_cls is not None
                else value
            )
            return {"$resolve": _join_paths(prefix, local_path).to_jsonpath()}
        constant = value
        name = definition_name(constant)
        defs.setdefault(name, constant)
        return {"$resolve": f"#/$defs/{_escape_json_pointer_token(name)}"}
    if isinstance(node, dict):
        return {
            str(key): _replace_markers(value, prefix, defs, model_cls, by_alias, mode)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [
            _replace_markers(value, prefix, defs, model_cls, by_alias, mode)
            for value in node
        ]
    return cast("JsonValue", node)


def iter_xvalidated_models(
    root: type[BaseModel], by_alias: bool = True, mode: ExportMode = "validation"
) -> "Iterator[tuple[Path, type[XValidatedModel]]]":
    """Yield reachable x-validated model classes and their root prefixes."""
    active: set[type[BaseModel]] = set()
    yield from _iter_xvalidated_models(root, Path(), by_alias, mode, active)


def _compile_declaration(
    declaration: XValidationDeclaration,
    prefix: Path,
    model_cls: type[BaseModel],
    by_alias: bool,
    mode: ExportMode,
    defs: "dict[str, JsonValue]",
) -> XValidationRule:
    authored = declaration.factory(XValidationContext())
    if not isinstance(authored, AuthoredRule):
        msg = f"x-validation rule {declaration.id!r} did not return authored rule data"
        raise InvalidRuleError(msg)

    target = _alias_path_for_model(authored.target, model_cls, by_alias, mode)
    return XValidationRule.model_validate({
        "id": declaration.id,
        "description": declaration.description,
        "target": _join_paths(prefix, target).to_jsonpath(),
        "assert": _replace_markers(
            authored.assert_, prefix, defs, model_cls, by_alias, mode
        ),
    })


def _copy_defs(schema: dict[str, Any]) -> "dict[str, JsonValue]":
    raw_defs = schema.get("$defs")
    if isinstance(raw_defs, dict):
        return cast("dict[str, JsonValue]", copy.deepcopy(raw_defs))
    return {}


def _iter_xvalidated_models(
    model_cls: type[BaseModel],
    prefix: Path,
    by_alias: bool,
    mode: ExportMode,
    active: set[type[BaseModel]],
) -> "Iterator[tuple[Path, type[XValidatedModel]]]":
    if model_cls in active:
        return
    active.add(model_cls)

    try:
        if issubclass(model_cls, XValidatedModel):
            yield prefix, model_cls

        for field_name, field_info in model_cls.model_fields.items():
            export_name = _field_export_name(field_name, field_info, by_alias, mode)
            field_prefix = prefix.select(key(export_name))
            for nested_model, nested_prefix in _model_types_from_annotation(
                field_info.annotation, field_prefix
            ):
                yield from _iter_xvalidated_models(
                    nested_model, nested_prefix, by_alias, mode, active
                )
    finally:
        active.remove(model_cls)


def _model_types_from_annotation(
    annotation: Any, prefix: Path
) -> "Iterator[tuple[type[BaseModel], Path]]":
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is None:
        if _is_model_type(annotation):
            yield annotation, prefix
        return

    if origin is Union or origin is UnionType:
        for arg in args:
            yield from _model_types_from_annotation(arg, prefix)
        return

    if str(origin) == "<class 'typing.Annotated'>":
        if args:
            yield from _model_types_from_annotation(args[0], prefix)
        return

    if origin in {list, tuple, set, frozenset}:
        if args:
            yield from _model_types_from_annotation(args[0], prefix.each())
        return

    for arg in args:
        yield from _model_types_from_annotation(arg, prefix)


def _field_export_name(
    field_name: str, field_info: Any, by_alias: bool, mode: ExportMode
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
    if isinstance(alias, AliasPath):
        return field_name
    return field_name


def _alias_path_for_model(
    path: Path, model_cls: type[BaseModel], by_alias: bool, mode: ExportMode
) -> Path:
    if not by_alias:
        return path

    current_model: type[BaseModel] | None = model_cls
    aliased_segments: list[Segment] = []
    for segment in path.segments:
        selectors: "list[Selector]" = []
        next_model: type[BaseModel] | None = None
        segment_had_model_key = False
        for selector in segment.selectors:
            if isinstance(selector, KeySelector) and current_model is not None:
                field_info = current_model.model_fields.get(selector.name)
                if field_info is not None:
                    segment_had_model_key = True
                    selectors.append(
                        key(_field_export_name(selector.name, field_info, True, mode))
                    )
                    next_model = _first_model_from_annotation(field_info.annotation)
                    continue
            selectors.append(selector)
        aliased_segments.append(Segment(tuple(selectors), recursive=segment.recursive))
        if segment_had_model_key:
            current_model = next_model
    return Path(tuple(aliased_segments))


def _is_model_type(annotation: Any) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def _field_export_name_from_alias_choices(alias: AliasChoices, fallback: str) -> str:
    for choice in alias.choices:
        if isinstance(choice, str):
            return choice
    return fallback


def _first_model_from_annotation(annotation: Any) -> type[BaseModel] | None:
    for model_cls, _prefix in _model_types_from_annotation(annotation, Path()):
        return model_cls
    return None


def _join_paths(prefix: Path, path: Path) -> Path:
    return Path((*prefix.segments, *path.segments))


def _stable_json(value: "JsonValue") -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _escape_json_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")
