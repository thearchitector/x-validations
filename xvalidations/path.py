import json
import re
from dataclasses import dataclass
from typing import Literal

from .types import JsonScalar

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class KeySelector:
    """Select an object member by name."""

    name: str


@dataclass(frozen=True, slots=True)
class WildcardSelector:
    """Select all child values."""


@dataclass(frozen=True, slots=True)
class IndexSelector:
    """Select an array item by index."""

    index: int


@dataclass(frozen=True, slots=True)
class SliceSelector:
    """Select an array slice."""

    start: int | None = None
    stop: int | None = None
    step: int | None = None


@dataclass(frozen=True, slots=True)
class Comparison:
    """Predicate comparison between a relative path and JSON scalar."""

    expr: Expr
    operator: Literal["==", "!="]
    value: JsonScalar


@dataclass(frozen=True, slots=True, eq=False)
class Expr:
    """Relative predicate expression rooted at the current filter item."""

    segments: tuple[KeySelector, ...] = ()

    def __getattr__(self, name: str) -> Expr:
        if name.startswith("__"):
            raise AttributeError(name)
        return Expr((*self.segments, KeySelector(name)))

    def __getitem__(self, name: str) -> Expr:
        return Expr((*self.segments, KeySelector(name)))

    def __eq__(self, other: JsonScalar) -> Comparison:  # type: ignore[override]
        return Comparison(self, "==", other)

    def __ne__(self, other: JsonScalar) -> Comparison:  # type: ignore[override]
        return Comparison(self, "!=", other)

    def __hash__(self) -> int:
        return hash(self.segments)


@dataclass(frozen=True, slots=True)
class FilterSelector:
    """Select array items matching a predicate."""

    predicate: Comparison


type Selector = (
    KeySelector | WildcardSelector | IndexSelector | SliceSelector | FilterSelector
)


@dataclass(frozen=True, slots=True)
class Segment:
    """A child or recursive JSONPath segment."""

    selectors: tuple[Selector, ...]
    recursive: bool = False


@dataclass(frozen=True, slots=True)
class Path:
    """Immutable JSONPath AST rooted at the current model."""

    segments: tuple[Segment, ...] = ()

    def select(self, selector: Selector, *selectors: Selector) -> Path:
        """Append a child segment."""
        return Path((*self.segments, Segment((selector, *selectors))))

    def desc(
        self, selector_or_name: Selector | str, *selectors_or_names: Selector | str
    ) -> Path:
        """Append a recursive descent segment."""
        selectors = tuple(
            KeySelector(selector) if isinstance(selector, str) else selector
            for selector in (selector_or_name, *selectors_or_names)
        )
        return Path((*self.segments, Segment(selectors, recursive=True)))

    def each(self) -> Path:
        """Append a wildcard child selector."""
        return Path((*self.segments, Segment((WildcardSelector(),))))

    def at(self, index: int) -> Path:
        """Append an array index selector."""
        return Path((*self.segments, Segment((IndexSelector(index),))))

    def slice(
        self, start: int | None = None, stop: int | None = None, step: int | None = None
    ) -> Path:
        """Append an array slice selector."""
        return Path((*self.segments, Segment((SliceSelector(start, stop, step),))))

    def where(self, predicate: Comparison) -> Path:
        """Append a filter selector."""
        return Path((*self.segments, Segment((FilterSelector(predicate),))))

    def to_jsonpath(self) -> str:
        """Serialize this path as RFC 9535 JSONPath."""
        return path_to_jsonpath(self)

    def __getattr__(self, name: str) -> Path:
        if name.startswith("__"):
            raise AttributeError(name)
        return Path((*self.segments, Segment((KeySelector(name),))))

    def __getitem__(self, name: str) -> Path:
        return Path((*self.segments, Segment((KeySelector(name),))))


def path_to_jsonpath(path: Path) -> str:
    """Serialize a path AST as RFC 9535 JSONPath."""
    return "$" + "".join(_serialize_segment(segment) for segment in path.segments)


def predicate_to_jsonpath(predicate: Comparison) -> str:
    """Serialize a predicate AST as RFC 9535 JSONPath."""
    expr_path = _serialize_expr(predicate.expr)
    value = json.dumps(predicate.value, separators=(",", ":"))
    return f"{expr_path} {predicate.operator} {value}"


def _serialize_segment(segment: Segment) -> str:
    if segment.recursive:
        return _serialize_recursive_segment(segment.selectors)
    return _serialize_child_segment(segment.selectors)


def _serialize_child_segment(selectors: tuple[Selector, ...]) -> str:
    if len(selectors) == 1:
        selector = selectors[0]
        if isinstance(selector, KeySelector) and _IDENTIFIER.fullmatch(selector.name):
            return f".{selector.name}"
        return _serialize_selector(selector)
    return (
        "["
        + ",".join(_serialize_union_selector(selector) for selector in selectors)
        + "]"
    )


def _serialize_recursive_segment(selectors: tuple[Selector, ...]) -> str:
    if len(selectors) == 1:
        selector = selectors[0]
        if isinstance(selector, KeySelector) and _IDENTIFIER.fullmatch(selector.name):
            return f"..{selector.name}"
    return ".." + _serialize_child_segment(selectors)


def _serialize_selector(selector: Selector) -> str:
    if isinstance(selector, KeySelector):
        serialized = f"[{json.dumps(selector.name)}]"
    elif isinstance(selector, WildcardSelector):
        serialized = "[*]"
    elif isinstance(selector, IndexSelector):
        serialized = f"[{selector.index}]"
    elif isinstance(selector, SliceSelector):
        serialized = f"[{_serialize_slice(selector)}]"
    else:
        serialized = f"[?({predicate_to_jsonpath(selector.predicate)})]"
    return serialized


def _serialize_union_selector(selector: Selector) -> str:
    if isinstance(selector, KeySelector):
        return json.dumps(selector.name)
    if isinstance(selector, IndexSelector):
        return str(selector.index)
    msg = "selector cannot be used in a union"
    raise TypeError(msg)


def _serialize_slice(selector: SliceSelector) -> str:
    parts = [
        "" if selector.start is None else str(selector.start),
        "" if selector.stop is None else str(selector.stop),
    ]
    if selector.step is not None:
        parts.append(str(selector.step))
    return ":".join(parts)


def _serialize_expr(expr: Expr) -> str:
    parts = ["@"]
    for selector in expr.segments:
        if _IDENTIFIER.fullmatch(selector.name):
            parts.append(f".{selector.name}")
        else:
            parts.append(f"[{json.dumps(selector.name)}]")
    return "".join(parts)
