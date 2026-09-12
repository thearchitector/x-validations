"""Public authoring arguments must match their static contracts."""

from pydantic_ajv import RuleModel


def ordering_string(x: RuleModel) -> None:
    _ = x < "1"


def ordering_collection(x: RuleModel) -> None:
    _ = x >= [1]


def membership_scalar(x: RuleModel) -> None:
    x.in_(1)


def membership_set(x: RuleModel) -> None:
    x.in_({1, 2})


def membership_nested(x: RuleModel) -> None:
    x.in_([[1]])


def property_number(x: RuleModel) -> None:
    x.unique_by(1)


def path_float(x: RuleModel) -> None:
    x[1.5]


def logical_non_rule(x: RuleModel) -> None:
    (x == 1) & x
