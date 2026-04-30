"""Stable exported data contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

type JsonValue = (
    None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
)
type InstanceLocation = tuple[str | int, ...]


class XValidationRule(BaseModel):
    """Exported x-validation rule."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    description: str
    target: str
    assert_: JsonValue = Field(alias="assert")


class XValidationBundle(BaseModel):
    """Generated definitions and exported rules."""

    defs: dict[str, JsonValue]
    rules: list[XValidationRule]


class ValidationIssue(BaseModel):
    """Normalized validation failure details."""

    path: str
    message: str
    keyword: str | None
    source: Literal["base", "x-validation"]
    rule_id: str | None
