"""Small shared input rules; no inferred recruitment values."""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_serializer

Nonnegative = Annotated[StrictInt, Field(ge=0)]
Positive = Annotated[StrictInt, Field(gt=0)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, str_strip_whitespace=True)


class ReadModel(InputModel):
    @field_serializer("*", when_used="json", check_fields=False)
    def consistent_timestamp(self, value):
        return value.astimezone(UTC) if isinstance(value, datetime) else value


def skills(values):
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ValueError("Skills must be a list of text values")
    result, seen = [], set()
    for value in values:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Skill values must be nonblank")
        if value.casefold() not in seen:
            seen.add(value.casefold())
            result.append(value)
    return result
