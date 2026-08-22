"""Stable exported data contracts."""

from pydantic import BaseModel, ConfigDict, Field, JsonValue

type JsonScalar = None | bool | int | float | str
type JsonObject = dict[str, JsonValue]

__all__ = ["JsonObject", "JsonScalar", "JsonValue", "XValidationRule"]


class XValidationRule(BaseModel):
    """Exported x-validation rule."""

    model_config = ConfigDict(populate_by_name=True, strict=True)

    id: str
    description: str | None = None
    target: str
    assert_: JsonValue = Field(alias="assert")
