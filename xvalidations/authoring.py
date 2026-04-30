"""Authoring DSL for x-validation rules."""

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Literal, cast

if TYPE_CHECKING:
    from xvalidations.models import JsonValue

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_JSON_SCALAR_TYPES = (str, int, float, bool, type(None))


@dataclass(frozen=True)
class KeySelector:
    """Select an object member by name."""

    name: str


@dataclass(frozen=True)
class WildcardSelector:
    """Select all child values."""


@dataclass(frozen=True)
class IndexSelector:
    """Select an array item by index."""

    index: int


@dataclass(frozen=True)
class SliceSelector:
    """Select an array slice."""

    start: int | None = None
    stop: int | None = None
    step: int | None = None


@dataclass(frozen=True)
class FilterSelector:
    """Select array items matching a predicate."""

    predicate: "Comparison"


type Selector = (
    KeySelector | WildcardSelector | IndexSelector | SliceSelector | FilterSelector
)


@dataclass(frozen=True)
class Segment:
    """A child or recursive JSONPath segment."""

    selectors: tuple[Selector, ...]
    recursive: bool = False


@dataclass(frozen=True)
class Path:
    """Immutable JSONPath AST rooted at the current model."""

    segments: tuple[Segment, ...] = ()

    def select(self, *selectors: Selector) -> "Path":
        """Append a child segment."""
        if not selectors:
            msg = "select() requires at least one selector"
            raise TypeError(msg)
        return Path((*self.segments, Segment(tuple(selectors))))

    def desc(self, *selectors_or_names: Selector | str) -> "Path":
        """Append a recursive descent segment."""
        if not selectors_or_names:
            msg = "desc() requires at least one selector"
            raise TypeError(msg)
        selectors = tuple(
            key(selector) if isinstance(selector, str) else selector
            for selector in selectors_or_names
        )
        return Path((*self.segments, Segment(selectors, recursive=True)))

    def each(self) -> "Path":
        """Append a wildcard child selector."""
        return self.select(wildcard())

    def at(self, index: int) -> "Path":
        """Append an array index selector."""
        return self.select(index_selector(index))

    def slice(
        self, start: int | None = None, stop: int | None = None, step: int | None = None
    ) -> "Path":
        """Append an array slice selector."""
        return self.select(slice_selector(start, stop, step))

    def where(self, predicate: "Comparison") -> "Path":
        """Append a filter selector."""
        return self.select(filter_selector(predicate))

    def to_jsonpath(self) -> str:
        """Serialize this path as RFC 9535 JSONPath."""
        return path_to_jsonpath(self)

    def __getattr__(self, name: str) -> "Path":
        if name.startswith("__"):
            raise AttributeError(name)
        return self.select(key(name))

    def __getitem__(self, name: str) -> "Path":
        return self.select(key(name))


@dataclass(frozen=True, eq=False)
class Expr:
    """Relative predicate expression rooted at the current filter item."""

    segments: tuple[KeySelector, ...] = ()

    def __getattr__(self, name: str) -> "Expr":
        if name.startswith("__"):
            raise AttributeError(name)
        return Expr((*self.segments, key(name)))

    def __getitem__(self, name: str) -> "Expr":
        return Expr((*self.segments, key(name)))

    def __eq__(self, other: object) -> Any:
        _ensure_json_scalar(other)
        return Comparison(self, "==", other)

    def __ne__(self, other: object) -> Any:
        _ensure_json_scalar(other)
        return Comparison(self, "!=", other)

    def __hash__(self) -> int:
        return hash(self.segments)


@dataclass(frozen=True)
class Comparison:
    """Predicate comparison between a relative path and JSON scalar."""

    expr: Expr
    operator: Literal["==", "!="]
    value: object


@dataclass(frozen=True)
class ResolveMarker:
    """Placeholder for values resolved at validation time."""

    value: "Path | JsonValue"


@dataclass(frozen=True)
class AuthoredRule:
    """Rule data returned by an authoring factory."""

    target: Path
    assert_: Any


@dataclass(frozen=True)
class XValidationDeclaration:
    """Metadata attached by the xvalidation decorator."""

    id: str
    description: str
    factory: Callable[["XValidationContext"], AuthoredRule]


@dataclass(frozen=True)
class RuleBuilder:
    """Build authored rule data for a target path."""

    target_path: Path

    def assert_schema(self, schema_json: Any) -> AuthoredRule:
        """Attach an assertion schema to this rule target."""
        return AuthoredRule(target=self.target_path, assert_=schema_json)


@dataclass(frozen=True)
class XValidationContext:
    """Context passed to x-validation authoring factories."""

    path: Path = field(default_factory=Path)
    this: Expr = field(default_factory=Expr)

    def key(self, name: str) -> KeySelector:
        """Create a key selector."""
        return key(name)

    def wildcard(self) -> WildcardSelector:
        """Create a wildcard selector."""
        return wildcard()

    def index(self, index: int) -> IndexSelector:
        """Create an index selector."""
        return index_selector(index)

    def slice(
        self, start: int | None = None, stop: int | None = None, step: int | None = None
    ) -> SliceSelector:
        """Create a slice selector."""
        return slice_selector(start, stop, step)

    def filter(self, predicate: Comparison) -> FilterSelector:
        """Create a filter selector."""
        return filter_selector(predicate)

    def target(self, path_object: Path) -> RuleBuilder:
        """Start building a rule for a target path."""
        if not isinstance(path_object, Path):
            msg = "target() requires a Path"
            raise TypeError(msg)
        return RuleBuilder(path_object)

    def resolve(
        self, path_object_or_json_constant: "Path | JsonValue"
    ) -> ResolveMarker:
        """Create a resolve marker for a path or JSON constant."""
        if isinstance(
            path_object_or_json_constant, str
        ) and path_object_or_json_constant.startswith("$"):
            msg = "resolve() requires a Path for JSONPath values"
            raise TypeError(msg)
        return ResolveMarker(path_object_or_json_constant)


def key(name: str) -> KeySelector:
    """Create an object key selector."""
    return KeySelector(name)


def wildcard() -> WildcardSelector:
    """Create a wildcard selector."""
    return WildcardSelector()


def index_selector(index: int) -> IndexSelector:
    """Create an array index selector."""
    return IndexSelector(index)


def slice_selector(
    start: int | None = None, stop: int | None = None, step: int | None = None
) -> SliceSelector:
    """Create an array slice selector."""
    return SliceSelector(start, stop, step)


def filter_selector(predicate: Comparison) -> FilterSelector:
    """Create a filter selector."""
    return FilterSelector(predicate)


def path_to_jsonpath(path: Path) -> str:
    """Serialize a path AST as RFC 9535 JSONPath."""
    return "$" + "".join(_serialize_segment(segment) for segment in path.segments)


def predicate_to_jsonpath(predicate: Comparison) -> str:
    """Serialize a predicate AST as RFC 9535 JSONPath."""
    expr_path = _serialize_expr(predicate.expr)
    value = json.dumps(predicate.value, separators=(",", ":"))
    return f"{expr_path} {predicate.operator} {value}"


def xvalidation(
    id: str, description: str
) -> Callable[
    [Callable[[XValidationContext], AuthoredRule]],
    Callable[[XValidationContext], AuthoredRule],
]:
    """Attach x-validation declaration metadata to an authoring factory."""

    def decorator(
        factory: Callable[[XValidationContext], AuthoredRule],
    ) -> Callable[[XValidationContext], AuthoredRule]:
        declaration = XValidationDeclaration(
            id=id, description=description, factory=factory
        )
        cast("Any", factory).__xvalidation_declaration__ = declaration
        return factory

    return decorator


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
        return f"[{json.dumps(selector.name)}]"
    if isinstance(selector, WildcardSelector):
        return "[*]"
    if isinstance(selector, IndexSelector):
        return f"[{selector.index}]"
    if isinstance(selector, SliceSelector):
        return f"[{_serialize_slice(selector)}]"
    if isinstance(selector, FilterSelector):
        return f"[?({predicate_to_jsonpath(selector.predicate)})]"
    msg = f"unsupported selector: {selector!r}"
    raise TypeError(msg)


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


def _ensure_json_scalar(value: object) -> None:
    if isinstance(value, _JSON_SCALAR_TYPES):
        return
    msg = "filter comparison value must be a JSON scalar"
    raise TypeError(msg)
