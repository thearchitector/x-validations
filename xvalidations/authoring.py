"""Authoring DSL for x-validation rules."""

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import wraps
from typing import Protocol, cast

from pydantic import validate_call

from xvalidations._path import (
    Comparison,
    Expr,
    FilterSelector,
    IndexSelector,
    KeySelector,
    Path,
    Segment,
    Selector,
    SliceSelector,
    WildcardSelector,
    filter_selector,
    index_selector,
    key,
    path_to_jsonpath,
    predicate_to_jsonpath,
    slice_selector,
    wildcard,
)
from xvalidations._validation import STRICT_CALL_CONFIG
from xvalidations.models import JsonValue


@dataclass(frozen=True)
class ResolveMarker:
    """Placeholder for values resolved at validation time."""

    value: Path | JsonValue


type AuthoredValue = (
    JsonValue | ResolveMarker | list[AuthoredValue] | dict[str, AuthoredValue]
)


@dataclass(frozen=True)
class AuthoredRule:
    """Rule data returned by an authoring factory."""

    target: Path
    assert_: AuthoredValue


@dataclass(frozen=True)
class XValidationDeclaration:
    """Metadata attached by the xvalidation decorator."""

    id: str
    description: str | None
    factory: Callable[[XValidationContext], AuthoredRule]


class _DeclaredFactory(Protocol):
    __xvalidation_declaration__: XValidationDeclaration

    def __call__(self, context: XValidationContext) -> AuthoredRule: ...


@dataclass(frozen=True)
class RuleBuilder:
    """Build authored rule data for a target path."""

    target_path: Path

    @validate_call(config=STRICT_CALL_CONFIG)
    def assert_schema(self, schema_json: AuthoredValue) -> AuthoredRule:
        """Attach an assertion schema to this rule target."""
        return AuthoredRule(target=self.target_path, assert_=schema_json)


@dataclass(frozen=True)
class XValidationContext:
    """Context passed to x-validation authoring factories."""

    path: Path = field(default_factory=Path)
    this: Expr = field(default_factory=Expr)

    @staticmethod
    @validate_call(config=STRICT_CALL_CONFIG)
    def key(name: str) -> KeySelector:
        """Create a key selector."""
        return KeySelector(name)

    @staticmethod
    def wildcard() -> WildcardSelector:
        """Create a wildcard selector."""
        return WildcardSelector()

    @staticmethod
    @validate_call(config=STRICT_CALL_CONFIG)
    def index(index: int) -> IndexSelector:
        """Create an index selector."""
        return IndexSelector(index)

    @staticmethod
    @validate_call(config=STRICT_CALL_CONFIG)
    def slice(
        start: int | None = None, stop: int | None = None, step: int | None = None
    ) -> SliceSelector:
        """Create a slice selector."""
        return SliceSelector(start, stop, step)

    @staticmethod
    @validate_call(config=STRICT_CALL_CONFIG)
    def filter(predicate: Comparison) -> FilterSelector:
        """Create a filter selector."""
        return FilterSelector(predicate)

    @validate_call(config=STRICT_CALL_CONFIG)
    def target(self, path_object: Path) -> RuleBuilder:
        """Start building a rule for a target path."""
        return RuleBuilder(path_object)

    @validate_call(config=STRICT_CALL_CONFIG)
    def resolve(self, path_object_or_json_constant: Path | JsonValue) -> ResolveMarker:
        """Create a resolve marker for a path or JSON constant."""
        if isinstance(
            path_object_or_json_constant, str
        ) and path_object_or_json_constant.startswith("$"):
            msg = "resolve() requires a Path for JSONPath values"
            raise TypeError(msg)
        return ResolveMarker(path_object_or_json_constant)


@validate_call(config=STRICT_CALL_CONFIG)
def xvalidation(
    id: str, description: str | None = None
) -> Callable[
    [Callable[[XValidationContext], AuthoredRule]],
    Callable[[XValidationContext], AuthoredRule],
]:
    """Declare an x-validation rule and enforce its factory contract."""

    def decorator(
        factory: Callable[[XValidationContext], AuthoredRule],
    ) -> Callable[[XValidationContext], AuthoredRule]:
        @wraps(factory)
        @validate_call(config=STRICT_CALL_CONFIG, validate_return=True)
        def validated_factory(context: XValidationContext) -> AuthoredRule:
            return factory(context)

        declaration = XValidationDeclaration(
            id=id, description=description, factory=validated_factory
        )
        declared_factory = cast(_DeclaredFactory, validated_factory)
        declared_factory.__xvalidation_declaration__ = declaration
        return declared_factory

    return decorator


__all__ = [
    "AuthoredRule",
    "AuthoredValue",
    "Comparison",
    "Expr",
    "FilterSelector",
    "IndexSelector",
    "KeySelector",
    "Path",
    "ResolveMarker",
    "RuleBuilder",
    "Segment",
    "Selector",
    "SliceSelector",
    "WildcardSelector",
    "XValidationContext",
    "XValidationDeclaration",
    "filter_selector",
    "index_selector",
    "key",
    "path_to_jsonpath",
    "predicate_to_jsonpath",
    "slice_selector",
    "wildcard",
    "xvalidation",
]
