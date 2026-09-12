"""Strict argument contracts shared by authoring and validated construction."""

from collections.abc import Callable
from functools import partial, wraps
from typing import Annotated

from pydantic import BeforeValidator, ConfigDict, Field, ValidationError, validate_call


class RuleDefinitionError(ValueError):
    """An expression is incompatible with its declared model structure."""


def definition[**P, R](message: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Preserve signatures and translate argument errors at construction boundaries."""

    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        @wraps(function)
        def bind(*args: P.args, **kwargs: P.kwargs) -> Callable[[], R]:
            return partial(function, *args, **kwargs)

        validated = validate_call(
            config=ConfigDict(
                strict=True,
                allow_inf_nan=False,
                arbitrary_types_allowed=True,
                defer_build=True,
            )
        )(bind)

        @wraps(function)
        def call(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                invoke = validated(*args, **kwargs)
            except ValidationError as error:
                details = error.errors(include_url=False)
                for detail in details:
                    cause = detail.get("ctx", {}).get("error")
                    if isinstance(cause, RuleDefinitionError):
                        raise cause from error
                value = details[0].get("input")
                raise RuleDefinitionError(message.format(value=value)) from error
            return invoke()

        return call

    return decorate


def _builtin(value: object) -> object:
    if type(value) not in (str, bool, int, float, type(None)):
        raise ValueError("Expected a builtin JSON primitive")
    return value


type Primitive = str | bool | int | float | None
type Number = int | float
type Builtin[T] = Annotated[T, BeforeValidator(_builtin)]
type JsonLiteral = Builtin[Primitive]
type JsonNumber = Builtin[Number]
type PathKey = Builtin[str | Annotated[int, Field(ge=0)]]
type PropertyName = Builtin[str]
type JsonCollection[T: Primitive] = list[Builtin[T]] | tuple[Builtin[T], ...]
