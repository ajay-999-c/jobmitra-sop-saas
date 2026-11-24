"""Request-scoped document failures: metadata only, never exception values or payloads."""

import ctypes
import json
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from uuid import uuid4

CURRENT = ContextVar("jobmitra_document_diagnostics", default=None)
LOGGER = logging.getLogger("uvicorn.error")


def begin(request, route):
    if "/proposals" in route:
        family, field = "proposal", "unified_v12_proposal_storage_root"
    elif "/resumes" in route or "/parsed-" in route:
        family, field = "resume", "ats_v2_resume_storage_root"
    else:
        return None
    root = getattr(request.app.state.settings, field, None)
    root = str(root) if root is not None else None
    if root and ("://" in root or re.match(r"^[A-Za-z][A-Za-z0-9+.-]+:/", root)):
        root = "[invalid URI root redacted]"
    return CURRENT.set(
        {
            "event_id": str(uuid4()),
            "operation": family + "." + request.method.lower(),
            "route": route,  # APIRoute template, never the actual candidate/company URL.
            "storage_root": root,
            "storage_step": "before_filesystem",
            "process_sid": None,
            "acl_protected": None,
            "owner_sid": None,
            "owner_valid": None,
            "acl_target": None,
            "validation_reason": None,
            "native_failure": None,
            "failure": None,
        }
    )


def end(token):
    if token is not None:
        CURRENT.reset(token)


def note(**values):
    state = CURRENT.get()
    if state is not None:
        state.update(values)


def native_failure(api, code):
    note(native_failure={"native_api": api, "windows_error_code": code})


def sanitized_trace(error):
    result, seen = [], set()
    while error is not None and id(error) not in seen and len(result) < 8:
        seen.add(id(error))
        frames, tb = [], error.__traceback__
        while tb is not None:
            frames.append(
                {
                    "file": Path(tb.tb_frame.f_code.co_filename).name,
                    "function": tb.tb_frame.f_code.co_name,
                    "line": tb.tb_lineno,
                }
            )
            tb = tb.tb_next
        result.append({"exception_type": type(error).__name__, "frames": frames[-24:]})
        # Include from-None contexts, but never their messages, args, source lines or locals.
        error = error.__cause__ or error.__context__
    return result


def capture(stage, error):
    state = CURRENT.get()
    if state is not None and state["failure"] is None:
        trace = sanitized_trace(error)
        frames = trace[0]["frames"] if trace else []
        state["failure"] = {
            **{k: v for k, v in state.items() if k not in {"failure", "native_failure"}},
            "validation_stage": stage,
            "failing_function": (state["native_failure"] or {}).get("native_api")
            or (frames[-1]["function"] if frames else stage),
            "original_exception_type": type(error).__name__,
            "errno": getattr(error, "errno", None),
            "windows_error_code": getattr(error, "winerror", None),
            **(state["native_failure"] or {}),
            "sanitized_traceback": trace,
        }


def stage(label):
    def decorate(function):
        @wraps(function)
        def traced(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except Exception as error:
                capture(label, error)
                raise

        return traced

    return decorate


def context_stage(label):
    def decorate(function):
        @contextmanager
        @wraps(function)
        def traced(*args, **kwargs):
            try:
                with function(*args, **kwargs) as value:
                    yield value
            except Exception as error:
                capture(label, error)
                raise

        return traced

    return decorate


def emit(error):
    """Logging must not change the original HTTP result, even if a log sink fails."""
    try:
        state = CURRENT.get()
        if state is None:
            return
        trace = sanitized_trace(error)
        frames = trace[0]["frames"] if trace else []
        capture(frames[-1]["function"] if frames else "request", error)
        payload = {
            **state["failure"],
            "http_status": 503,
            "response_exception_type": type(error).__name__,
        }
        code = payload["windows_error_code"]
        if isinstance(code, int) and hasattr(ctypes, "FormatError"):
            payload["windows_error_description"] = ctypes.FormatError(code).strip()
        LOGGER.error("document_storage_failure %s", json.dumps(payload, ensure_ascii=True))
    except Exception:
        pass  # Never replace a storage failure with a logging failure or raw fallback dump.
