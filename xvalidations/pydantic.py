import hashlib
import inspect
import json
from typing import Any, cast
from urllib.parse import quote

from pydantic import BaseModel
from pydantic.json_schema import JsonSchemaValue

from .authoring import _Declaration, _XValidationDescriptor
from .models import ValidationRule
from .path import Path, path_to_jsonpath

XVALIDATIONS_SCHEMA_URI = "https://thearchitector.dev/xvalidations/schema.json"
_HOOK_WRAPPER_TAG = "__xvalidations_installed_hook__"
_PYDANTIC_SCHEMA_EXPORT = "model_json_schema"


def _install_model_hooks(owner: type[object]) -> None:
    local = owner.__dict__.get(_PYDANTIC_SCHEMA_EXPORT)
    if local is not None and _is_installed_wrapper(local):
        return
    prior = local
    if prior is None:
        prior = inspect.getattr_static(owner, _PYDANTIC_SCHEMA_EXPORT)
        if _is_installed_wrapper(prior):
            return
    wrapper = cast(Any, _schema_wrapper(prior))
    setattr(wrapper, _HOOK_WRAPPER_TAG, True)
    setattr(owner, _PYDANTIC_SCHEMA_EXPORT, classmethod(wrapper))


def _is_installed_wrapper(hook: object) -> bool:
    function = hook.__func__ if isinstance(hook, classmethod) else hook
    return bool(getattr(function, _HOOK_WRAPPER_TAG, False))


def _schema_wrapper(prior: object) -> object:
    def model_json_schema(
        model_cls: type[BaseModel], *args: object, **kwargs: object
    ) -> JsonSchemaValue:
        schema = cast(JsonSchemaValue, _invoke_hook(prior, model_cls, *args, **kwargs))
        if kwargs.get("mode", "validation") == "serialization":
            return schema
        declarations = _collect_declarations(model_cls)
        if not declarations:
            return schema
        return _render_root_resource(model_cls, schema, declarations)

    return model_json_schema


def _invoke_hook(
    hook: object, model_cls: type[BaseModel], *args: object, **kwargs: object
) -> object:
    getter = getattr(hook, "__get__", None)
    bound = getter(None, model_cls) if getter is not None else hook
    return cast(Any, bound)(*args, **kwargs)


def _collect_declarations(model_cls: type[BaseModel]) -> tuple[_Declaration, ...]:
    declarations: dict[str, _Declaration] = {}
    for base in reversed(model_cls.__mro__):
        if not issubclass(base, BaseModel):
            continue
        for name, value in base.__dict__.items():
            if isinstance(value, _XValidationDescriptor):
                declarations[name] = value.declaration
            elif name in declarations:
                del declarations[name]
    return tuple(declarations.values())


def _render_root_resource(
    model_cls: type[BaseModel],
    schema: JsonSchemaValue,
    declarations: tuple[_Declaration, ...],
) -> JsonSchemaValue:
    rules = [_render_rule(model_cls, declaration) for declaration in declarations]
    schema["$schema"] = XVALIDATIONS_SCHEMA_URI
    schema["x-validations"] = rules
    digest = hashlib.sha256(
        json.dumps(
            schema, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode()
    ).hexdigest()
    qualified_name = quote(f"{model_cls.__module__}.{model_cls.__qualname__}", safe="")
    schema["$id"] = f"urn:xvalidations:{qualified_name}:{digest}"
    return schema


def _render_rule(
    model_cls: type[BaseModel], declaration: _Declaration
) -> dict[str, object]:
    rule = cast(ValidationRule, declaration.descriptor.invoke(model_cls))
    rendered: dict[str, object] = {
        "id": declaration.id,
        "target": path_to_jsonpath(rule.target),
        "assert": _serialize_assertion(rule.assertion),
    }
    if declaration.description is not None:
        rendered["description"] = declaration.description
    return rendered


def _serialize_assertion(value: object) -> object:
    if isinstance(value, Path):
        return {"$path": path_to_jsonpath(value)}
    if isinstance(value, dict):
        return {key: _serialize_assertion(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_assertion(item) for item in value]
    return value
