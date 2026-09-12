"""Pydantic lifecycle hooks delegate validation and schema generation to rules."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from inspect import cleandoc, getattr_static
from typing import Protocol, cast, overload

from pydantic import BaseModel, GetJsonSchemaHandler, model_validator
from pydantic._internal._decorators import (
    ModelValidatorDecoratorInfo,
    PydanticDescriptorProxy,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema, PydanticCustomError

from .expressions import Rule, RuleModel
from .references import RuleDefinitionError


@dataclass(frozen=True)
class Declaration:
    factory: Callable[[type[BaseModel], RuleModel], object]
    name: str
    id: str
    description: str | None
    error: str | None

    def construct(self, model: type[BaseModel]) -> Rule:
        expression = self.factory(model, RuleModel.for_model(model))
        if not isinstance(expression, Rule):
            raise RuleDefinitionError(f"Rule {self.id!r} must return a Rule")
        return replace(
            expression, id=self.id, description=self.description, error=self.error
        )

    def validate(self, instance: BaseModel) -> BaseModel:
        cls = type(instance)
        if cls.__pydantic_generic_metadata__["parameters"]:
            raise RuleDefinitionError(
                "Specialize generic models before validating rules"
            )
        rules = ModelState.of(cls).rules
        assert rules is not None, "Model rules must be built by the completion hook"
        rule = rules[self.name]
        if not rule.resolve(instance):
            raise PydanticCustomError(
                "xrule",
                "{message}",
                {
                    "message": rule.error
                    if rule.error is not None
                    else f"Rule '{rule.id}' failed",
                    "rule_id": rule.id,
                },
            )
        return instance


class ModelNamespace(Protocol):
    """Writable integration attributes on a model class, not a model instance."""

    __pydantic_ajv_state__: ModelState
    __pydantic_on_complete__: classmethod[BaseModel, [], None]
    __get_pydantic_json_schema__: classmethod[
        BaseModel, [CoreSchema, GetJsonSchemaHandler], JsonSchemaValue
    ]


@dataclass
class ModelState:
    installed: bool = False
    rules: dict[str, Rule] | None = None

    @classmethod
    def of(cls, model: type[BaseModel]) -> ModelState:
        # Subclasses construct their own references for inherited declarations.
        namespace = cast(ModelNamespace, model)
        if "__pydantic_ajv_state__" not in model.__dict__:
            namespace.__pydantic_ajv_state__ = cls()
        return namespace.__pydantic_ajv_state__

    def complete(self, model: type[BaseModel]) -> None:
        if self.rules is not None or model.__pydantic_generic_metadata__["parameters"]:
            return
        rules = {}
        ids = set()
        for name, decorator in model.__pydantic_decorators__.model_validators.items():
            declaration = decorator.func.__dict__.get("__rule_declaration__")
            if declaration is None:
                continue
            assert isinstance(declaration, Declaration)
            if declaration.id in ids:
                raise RuleDefinitionError(f"Duplicate rule id: {declaration.id!r}")
            ids.add(declaration.id)
            rules[name] = declaration.construct(model)
        self.rules = rules

    def export(self, handler: GetJsonSchemaHandler, schema: JsonSchemaValue) -> None:
        assert self.rules is not None, (
            "Model rules must be built by the completion hook"
        )
        for rule in self.rules.values():
            fragment = rule.dump(handler, schema)
            # Cooperative inherited hooks may have already attached this fragment.
            existing = schema.setdefault("allOf", [])
            if fragment not in existing:
                existing.append(fragment)

    def install(self, owner: type[BaseModel]) -> None:
        if self.installed:
            return
        self.installed = True
        # Descriptor introspection erases signatures; these are Pydantic's hook contracts.
        previous_complete = cast(
            classmethod[BaseModel, [], None],
            getattr_static(owner, "__pydantic_on_complete__"),
        ).__func__
        previous_schema = cast(
            classmethod[BaseModel, [CoreSchema, GetJsonSchemaHandler], JsonSchemaValue],
            getattr_static(owner, "__get_pydantic_json_schema__"),
        ).__func__

        def on_complete(cls: type[BaseModel]) -> None:
            previous_complete(cls)
            ModelState.of(cls).complete(cls)

        def json_schema(
            cls: type[BaseModel], core: CoreSchema, handler: GetJsonSchemaHandler
        ) -> JsonSchemaValue:
            schema = previous_schema(cls, core, handler)
            if handler.mode == "validation":
                if cls.__pydantic_generic_metadata__["parameters"]:
                    raise RuleDefinitionError(
                        "Specialize generic models before exporting rules"
                    )
                ModelState.of(cls).export(handler, handler.resolve_ref_schema(schema))
            return schema

        namespace = cast(ModelNamespace, owner)
        namespace.__pydantic_on_complete__ = classmethod(on_complete)
        namespace.__get_pydantic_json_schema__ = classmethod(json_schema)


class RuleProxy(PydanticDescriptorProxy[ModelValidatorDecoratorInfo]):
    def __set_name__(self, owner: type[BaseModel], name: str) -> None:
        ModelState.of(owner).install(owner)
        super().__set_name__(owner, name)


class RuleDecorator(Protocol):
    def __call__[Factory: Callable[..., Rule]](self, method: Factory, /) -> Factory: ...


@overload
def rule[Factory: Callable[..., Rule]](
    method: Factory,
    *,
    id: str | None = None,
    description: str | None = None,
    error: str | None = None,
) -> Factory: ...


@overload
def rule(
    method: None = None,
    *,
    id: str | None = None,
    description: str | None = None,
    error: str | None = None,
) -> RuleDecorator: ...


def rule(
    method: object = None,
    *,
    id: str | None = None,
    description: str | None = None,
    error: str | None = None,
) -> object:
    """Register a classmethod rule factory as a native after-validator."""

    def decorate(factory: object) -> RuleProxy:
        if not isinstance(factory, classmethod):
            raise RuleDefinitionError("Place @rule above @classmethod")
        function = factory.__func__
        doc = cleandoc(function.__doc__ or "") or None
        declaration = Declaration(
            function,
            function.__name__,
            id if id is not None else function.__name__,
            description if description is not None else doc,
            error,
        )

        def validate(self: BaseModel) -> BaseModel:
            return declaration.validate(self)

        validate.__name__ = function.__name__
        validate.__dict__["__rule_declaration__"] = declaration
        proxy = model_validator(mode="after")(validate)
        return RuleProxy(proxy.wrapped, proxy.decorator_info, proxy.shim)

    return decorate if method is None else decorate(method)
