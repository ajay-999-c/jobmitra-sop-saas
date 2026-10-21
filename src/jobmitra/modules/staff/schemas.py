from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from jobmitra.core.validation import InputModel, ReadModel


class StaffCreate(InputModel):
    display_name: str = Field(min_length=1, max_length=200)


class StaffPatch(InputModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: Literal[False] | None = None


class StaffRead(ReadModel):
    id: UUID
    display_name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    duplicate_name_warning: bool = False
