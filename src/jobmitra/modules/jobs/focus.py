"""Manual JD work focus; never a candidate progression or completion state."""

from typing import Literal, get_args

WorkFocus = Literal[
    "CANDIDATE_POOL",
    "CANDIDATE_CONTACT",
    "JOBMITRA_SCREENING",
    "COMPANY_SUBMISSION",
    "INTERVIEWS",
    "SELECTION",
    "JOINING",
]
FOCUS_STAGES = tuple((code, code.replace("_", " ").title()) for code in get_args(WorkFocus))
FOCUS_LABELS = dict(FOCUS_STAGES)
FOCUS_CHECK = "current_work_focus IN (" + ",".join(repr(code) for code in get_args(WorkFocus)) + ")"
