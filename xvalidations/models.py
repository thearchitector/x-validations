from dataclasses import dataclass

from .path import Path
from .types import JsonScalar

type RuleAssertionValue = (
    JsonScalar | Path | list[RuleAssertionValue] | dict[str, RuleAssertionValue]
)
type RuleAssertion = dict[str, RuleAssertionValue]


@dataclass(frozen=True, slots=True)
class ValidationRule:
    """A typed target path and the JSON Schema assertion applied to it."""

    target: Path
    assertion: RuleAssertion
