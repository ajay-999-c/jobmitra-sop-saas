"""Read-only probe of this terminal's effective settings; no database connection."""

import json

from pydantic import ValidationError

from jobmitra.core.config import Settings
from jobmitra.core.workflow import WorkflowError
from jobmitra.modules.candidates.storage import LocalDocumentStorage
from jobmitra.modules.candidates.storage_diagnostics import storage_report


def main():
    try:
        settings = Settings()
        report = storage_report(settings)
        report["context"] = "terminal_probe_not_the_running_NSSM_process"
        try:
            LocalDocumentStorage(settings.document_storage_root, settings.document_max_bytes)
            report["initialization"] = "passed"
        except (WorkflowError, OSError, ValueError) as error:
            report["initialization"] = "failed"
            report["exception_type"] = type(error).__name__
        print(json.dumps(report, indent=2))
        return int(report["initialization"] != "passed")
    except ValidationError as error:
        print(
            json.dumps(
                {
                    "settings_invalid": [
                        {"field": item["loc"], "type": item["type"]}
                        for item in error.errors(
                            include_input=False, include_context=False, include_url=False
                        )
                    ]
                }
            )
        )
        return 1
    except Exception as error:
        print(json.dumps({"probe_failed": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
