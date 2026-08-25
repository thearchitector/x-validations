from pydantic import ConfigDict, validate_call

type JsonScalar = None | bool | int | float | str


checkcall = validate_call(
    config=ConfigDict(arbitrary_types_allowed=True, defer_build=True, strict=True)
)
