"""Stable exported data contracts."""

from pydantic import BaseModel, ConfigDict, Field

type JsonValue = (
    None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
)
type InstanceLocation = tuple[str | int, ...]

__all__ = ["InstanceLocation", "JsonValue", "XValidationBundle", "XValidationRule"]


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
