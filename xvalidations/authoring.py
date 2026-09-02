from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, overload

from .models import RuleAssertion, ValidationRule
from .path import (
    Comparison,
    Expr,
    FilterSelector,
    IndexSelector,
    KeySelector,
    Path,
    SliceSelector,
    WildcardSelector,
)


@dataclass(frozen=True, slots=True)
class _RuleBuilder:
    target_path: Path

    def assert_schema(self, schema_json: RuleAssertion) -> ValidationRule:
        """Attach an object-form JSON Schema assertion to this target."""
        return ValidationRule(target=self.target_path, assertion=schema_json)


@dataclass(frozen=True, slots=True)
class XValidationContext:
    """Context passed to a decorated rule classmethod."""

    path: Path = field(default_factory=Path)
    this: Expr = field(default_factory=Expr)

    @staticmethod
    def key(name: str) -> KeySelector:
        return KeySelector(name)

    @staticmethod
    def wildcard() -> WildcardSelector:
        return WildcardSelector()

    @staticmethod
    def index(index: int) -> IndexSelector:
        return IndexSelector(index)

    @staticmethod
    def slice(
        start: int | None = None, stop: int | None = None, step: int | None = None
    ) -> SliceSelector:
        return SliceSelector(start, stop, step)

    @staticmethod
    def filter(predicate: Comparison) -> FilterSelector:
        return FilterSelector(predicate)

    def target(self, path_object: Path) -> _RuleBuilder:
        return _RuleBuilder(path_object)


@dataclass(frozen=True, slots=True)
class _Declaration:
    name: str
    id: str
    description: str | None
    override: bool
    descriptor: _XValidationDescriptor


class _XValidationDescriptor(classmethod):  # type: ignore[type-arg]
    """Descriptor installed by :func:`xvalidation`."""

    def __init__(
        self,
        method: classmethod[Any, Any, ValidationRule],
        *,
        id: str | None,
        description: str | None,
        override: bool,
    ) -> None:
        if not isinstance(method, classmethod):
            msg = "@xvalidation must decorate a classmethod"
            raise TypeError(msg)
        super().__init__(method.__func__)
        self._explicit_id = id
        self._description = description
        self._override = override
        self._name: str | None = None

    def __set_name__(self, owner: type[object], name: str) -> None:
        self._name = name
        from xvalidations.pydantic import _install_model_hooks

        _install_model_hooks(owner)

    @property
    def declaration(self) -> _Declaration:
        if self._name is None:
            msg = "x-validation descriptor has not been assigned to a model"
            raise TypeError(msg)
        rule_id = self._explicit_id
        if rule_id is None:
            rule_id = "-".join(
                part for part in self._name.strip("_").split("_") if part
            )
            rule_id = rule_id.lower()
        return _Declaration(
            name=self._name,
            id=rule_id,
            description=self._description,
            override=self._override
            or bool(getattr(self.__func__, "__override__", False)),
            descriptor=self,
        )

    def invoke(self, model_cls: type[object]) -> object:
        factory = super().__get__(None, model_cls)
        return factory(XValidationContext())


@overload
def xvalidation(
    method: classmethod[Any, Any, ValidationRule], /
) -> _XValidationDescriptor: ...


@overload
def xvalidation(
    *, id: str | None = None, description: str | None = None, override: bool = False
) -> Callable[[classmethod[Any, Any, ValidationRule]], _XValidationDescriptor]: ...


def xvalidation(
    method: classmethod[Any, Any, ValidationRule] | None = None,
    /,
    *,
    id: str | None = None,
    description: str | None = None,
    override: bool = False,
) -> (
    _XValidationDescriptor
    | Callable[[classmethod[Any, Any, ValidationRule]], _XValidationDescriptor]
):
    """Declare a model-scoped Validation Rule on a classmethod."""

    def decorate(
        decorated: classmethod[Any, Any, ValidationRule],
    ) -> _XValidationDescriptor:
        return _XValidationDescriptor(
            decorated, id=id, description=description, override=override
        )

    if method is not None:
        return decorate(method)
    return decorate
