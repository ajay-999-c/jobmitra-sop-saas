from typing import Literal

from pydantic import Field

from .candidate_profiles import Strict


class ResumeMetadata(Strict):
    uploaded_by: str | None = Field(default=None, min_length=1, max_length=120)
    preparation_source: Literal["ChatGPT", "Claude", "Manual", "Other"] | None = None
    source_original_id: int | None = Field(default=None, ge=1)
    upload_notes: str = Field(default="", max_length=2000)


class CurrentResume(Strict):
    expected_current_id: int | None = Field(ge=1)
    actor_name: str = Field(min_length=1, max_length=120)
