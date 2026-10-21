from jobmitra.core.workflow import WorkflowError

from . import repository as repo
from .models import Candidate, CandidateDocument
from .schemas import DocumentRead
from .service import required, validate_staff
from .storage import DocumentStorage


class CandidateDocumentService:
    def __init__(self, session, storage: DocumentStorage):
        self.session, self.storage = session, storage

    def upload_document(
        self,
        candidate_id,
        stream,
        filename,
        kind,
        staff_id=None,
        source_document_id=None,
        reviewed=False,
    ):
        stored = None
        try:
            with self.session.begin():
                required(self.session, Candidate, candidate_id, True)
                validate_staff(self.session, staff_id)
                if kind not in ("ORIGINAL_RESUME", "MODIFIED_RESUME", "AUTHORITY"):
                    raise WorkflowError("Invalid document kind.")
                if kind == "MODIFIED_RESUME":
                    if source_document_id is None or not reviewed:
                        raise WorkflowError(
                            "Select an original resume and confirm review/authorizatio"
                            "n for this modified copy."
                        )
                    source = required(self.session, CandidateDocument, source_document_id)
                    if source.candidate_id != candidate_id or source.kind != "ORIGINAL_RESUME":
                        raise WorkflowError("Source must be this candidate’s original resume.")
                elif source_document_id is not None:
                    raise WorkflowError("Source lineage belongs only to a modified resume.")
                version = repo.next_document_version(self.session, candidate_id, kind)
                stored = self.storage.save(stream, filename)
                row = CandidateDocument(
                    candidate_id=candidate_id,
                    kind=kind,
                    original_filename=filename,
                    storage_key=stored.storage_key,
                    content_type=stored.content_type,
                    size_bytes=stored.size_bytes,
                    sha256=stored.sha256,
                    version=version,
                    uploaded_by_staff_id=staff_id,
                    source_document_id=source_document_id,
                    approval_status=(
                        "Reviewed"
                        if kind == "MODIFIED_RESUME"
                        else "Unverified"
                        if kind == "AUTHORITY"
                        else None
                    ),
                )
                self.session.add(row)
                self.session.flush()
                result = DocumentRead.model_validate(row)
            return result
        except BaseException:
            if stored:
                self.storage.remove(stored.storage_key)
            raise

    def upload_original_resume(self, candidate_id, stream, filename, staff_id=None):
        return self.upload_document(candidate_id, stream, filename, "ORIGINAL_RESUME", staff_id)

    def upload_modified_resume(
        self, candidate_id, stream, filename, staff_id, source_document_id, reviewed
    ):
        return self.upload_document(
            candidate_id,
            stream,
            filename,
            "MODIFIED_RESUME",
            staff_id,
            source_document_id,
            reviewed,
        )

    def upload_authority(self, candidate_id, stream, filename, staff_id=None):
        return self.upload_document(candidate_id, stream, filename, "AUTHORITY", staff_id)

    def download_document(self, candidate_id, document_id):
        row = required(self.session, CandidateDocument, document_id)
        if row.candidate_id != candidate_id:
            raise WorkflowError("Document not found.", 404)
        path = self.storage.path(row.storage_key)
        if not path.is_file():
            raise WorkflowError(
                "The stored file is unavailable. Restore it from the private file backup.", 404
            )
        return DocumentRead.model_validate(row), path

    def list_document_versions(self, candidate_id):
        return [
            DocumentRead.model_validate(row) for row in repo.documents(self.session, candidate_id)
        ]
