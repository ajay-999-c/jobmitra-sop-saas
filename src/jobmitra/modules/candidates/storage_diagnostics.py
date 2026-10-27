"""Opt-in, server-local storage diagnostics. Never return this report through HTTP."""

import hashlib
import marshal
import os
import platform
import re
import sys
from pathlib import Path

from dotenv import dotenv_values

from .storage import LocalDocumentStorage

ROOT_VARIABLE = "jobmitra_document_storage_root"


def display_path(value):
    if value is None:
        return None
    value = str(value)
    # A misconfigured URL could include credentials; it is not a local storage path.
    # Path() can collapse URL double slashes; retain the redaction after coercion.
    url_shaped = "://" in value or re.search(r"\b[A-Za-z][A-Za-z0-9+.-]+:[\\/]", value)
    return "<URL-shaped value redacted>" if url_shaped else value


def inspect_root(root):
    """Observe native Path behaviour without normalizing or repairing the setting."""
    result = {"effective_root": display_path(root), "failed_conditions": []}
    if root is None:
        result["failed_conditions"].append("not_configured")
        return result
    path = Path(root)
    result.update(
        path_type=type(path).__name__,
        is_absolute=path.is_absolute(),
        forbidden_components=[p for p in path.parts if p.lower() in ("static", "templates")],
    )
    for name in ("is_dir", "is_symlink"):
        try:
            result[name] = getattr(path, name)()
        except (OSError, ValueError) as error:
            result[name] = None
            result[name + "_error"] = type(error).__name__
    if not result["is_absolute"]:
        result["failed_conditions"].append("not_absolute")
    if result["is_symlink"]:
        result["failed_conditions"].append("symlink")
    if result["forbidden_components"]:
        result["failed_conditions"].append("static_or_templates_component")
    # This is a separate, later validation branch in LocalDocumentStorage.
    if result["is_dir"] is False:
        result["failed_conditions"].append("directory_missing_or_not_directory")
    try:
        resolved = path.resolve()
        result["resolved_root"] = display_path(resolved)
        if any(p.lower() in ("static", "templates") for p in resolved.parts):
            result["failed_conditions"].append("resolved_inside_static_or_templates")
    except (OSError, ValueError, RuntimeError) as error:
        result["resolve_error"] = type(error).__name__
    return result


def storage_report(settings):
    """Allow-list only storage metadata; never serialize Settings or environment."""
    report = inspect_root(settings.document_storage_root)
    report.update(
        os_name=os.name,
        python_platform=sys.platform,
        python_version=platform.python_version(),
        executable=sys.executable,
        pid=os.getpid(),
        cwd=str(Path.cwd()),
    )
    effective = settings.document_storage_root
    environment = {k.lower(): v for k, v in os.environ.items()}
    env_root = environment.get(ROOT_VARIABLE)
    report["process_environment_root"] = display_path(env_root)
    report["process_environment_root_present"] = ROOT_VARIABLE in environment
    report["effective_matches_process_environment"] = (
        effective == Path(env_root) if env_root is not None else None
    )
    # The normal application constructs Settings() with the model's .env path.
    # Read ONLY the storage value for comparison; never print the dotenv mapping.
    env_file = Path(settings.model_config["env_file"])
    report["dotenv_path"] = str(env_file.absolute())
    report["dotenv_exists"] = env_file.is_file()
    try:
        values = dotenv_values(env_file) if env_file.is_file() else {}
        file_root = {k.lower(): v for k, v in values.items()}.get(ROOT_VARIABLE)
        report["dotenv_root_now"] = display_path(file_root)
        report["effective_matches_dotenv_now"] = (
            effective == Path(file_root) if file_root is not None else None
        )
    except (OSError, UnicodeError, ValueError) as error:
        report["dotenv_read_error"] = type(error).__name__
    report["precedence"] = "Settings arguments > process environment > project .env > defaults"
    report["source_caveat"] = (
        "Source comparison is current, not a startup provenance record. "
        "app.state.settings stays cached until process restart; "
        "a terminal probe is a separate process."
    )
    code = LocalDocumentStorage.__init__.__code__
    report["validator_file"] = code.co_filename
    report["validator_first_line"] = code.co_firstlineno
    report["loaded_validator_sha256"] = hashlib.sha256(marshal.dumps(code)).hexdigest()
    try:
        report["validator_file_sha256_now"] = hashlib.sha256(
            Path(code.co_filename).read_bytes()
        ).hexdigest()
    except OSError as error:
        report["validator_file_read_error"] = type(error).__name__
    return report
