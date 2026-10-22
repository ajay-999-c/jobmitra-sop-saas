"""Candidate Desk business actions, each committed as one explicit transaction."""

from datetime import UTC, datetime

from pydantic import ValidationError

from jobmitra.core.workflow import WorkflowError, office_today
from jobmitra.modules.staff.service import require_active

from . import repository as repo
from .models import (
    Candidate,
    CandidateDocument,
    CandidateVisit,
    JobSearchRequest,
    ResumeParseResult,
    WorkDomain,
    WorkSubdomain,
)
from .schemas import (
    CandidateProfile,
    CandidateRead,
    DomainRead,
    JobSearchRequestCreate,
    JobSearchRequestRead,
    ResumeParseRead,
    SubdomainRead,
    VisitRead,
    mobile_key,
    normalized_name,
)


def required(session, model, identity, lock=False):
    row = repo.find(session, model, identity, lock)
    if row is None:
        raise WorkflowError("Record not found.", 404)
    return row


def validate_staff(session, identity):
    if identity:
        require_active(session, [identity])


def version_check(row, expected):
    if row.version != expected:
        raise WorkflowError("This record changed on another device. Reload before saving.", 409)


def validated(schema, values):
    try:
        return schema.model_validate(values)
    except ValidationError:
        raise WorkflowError(
            "Check required fields, field values and nullable selections."
        ) from None


def profile_catalog(session, data, old=None):
    for model, field in ((WorkDomain, "domain_id"), (WorkSubdomain, "subdomain_id")):
        identity = getattr(data, field)
        if identity:
            row = required(session, model, identity, lock=True)
            if not row.is_active and (old is None or identity != getattr(old, field)):
                raise WorkflowError("Choose an active domain/subdomain for new assignments.")
            if model is WorkSubdomain and row.domain_id != data.domain_id:
                raise WorkflowError("Sub-domain must belong to the selected domain.")
    if data.subdomain_id and not data.domain_id:
        raise WorkflowError("Choose the parent domain first.")


class CandidateService:
    def __init__(self, session):
        self.session = session

    def create_candidate(self, data, *, strict_contacts=False):
        with self.session.begin():
            key = mobile_key(data.mobile)
            repo.lock_contacts(self.session, key, data.email)
            if repo.contact_matches(self.session, key, data.email) and (
                strict_contacts or not data.confirm_duplicate
            ):
                raise WorkflowError(
                    (
                        "Possible existing mobile/email. Open the profile or explicitly confirm "
                        "a separate person."
                    ),
                    409,
                )
            validate_staff(self.session, data.recorded_by_staff_id)
            profile_catalog(self.session, data)
            values = {name: getattr(data, name) for name in CandidateProfile.model_fields}
            candidate = Candidate(**values, mobile_normalized=key)
            self.session.add(candidate)
            self.session.flush()
            if data.source == "Walk-in":
                self.session.add(
                    CandidateVisit(
                        candidate_id=candidate.id,
                        visited_at=datetime.now(UTC),
                        purpose="Initial walk-in registration",
                        recorded_by_staff_id=data.recorded_by_staff_id,
                        authority_status="Not recorded",
                    )
                )
            if data.initial_job_search is not None:
                JobSearchService(self.session)._add(candidate.id, data.initial_job_search)
            self.session.flush()
            return CandidateRead.model_validate(candidate)

    def update_candidate(self, identity, data, *, strict_contacts=False, actor=None):
        with self.session.begin():
            # Mobile lock first, matching create lock order.
            repo.lock_contacts(
                self.session, mobile_key(data.mobile) if data.mobile else None, data.email
            )
            validate_staff(self.session, actor)
            row = required(self.session, Candidate, identity, True)
            version_check(row, data.version)
            fields = data.model_fields_set - {"version", "confirm_duplicate"}
            values = {key: getattr(row, key) for key in CandidateProfile.model_fields}
            values.update({key: getattr(data, key) for key in fields})
            profile = validated(CandidateProfile, values)
            key = mobile_key(profile.mobile)
            if (
                (strict_contacts or key != row.mobile_normalized or profile.email != row.email)
                and repo.contact_matches(self.session, key, profile.email, row.id)
                and (strict_contacts or not data.confirm_duplicate)
            ):
                raise WorkflowError(
                    "Possible existing mobile/email. Review matching profiles before saving.", 409
                )
            profile_catalog(self.session, profile, row)
            if any(getattr(row, field) != getattr(profile, field) for field in fields):
                for field in fields:
                    setattr(row, field, getattr(profile, field))
                row.mobile_normalized = key
                row.version += 1
            self.session.flush()
            return CandidateRead.model_validate(row)

    def search_candidates(self, query=None):
        return [CandidateRead.model_validate(row) for row in repo.candidates(self.session, query)]

    def find_possible_duplicates(self, mobile=None, exclude_id=None, email=None):
        try:
            key = mobile_key(mobile) if mobile else None
        except ValueError:
            key = None
        return [
            CandidateRead.model_validate(row)
            for row in repo.contact_matches(self.session, key, email, exclude_id)
        ]

    def get_candidate_detail(self, identity):
        return CandidateRead.model_validate(required(self.session, Candidate, identity))


class VisitService:
    def __init__(self, session, timezone="Asia/Kolkata"):
        self.session, self.timezone = session, timezone

    def register_walkin(self, data):
        return CandidateService(self.session).create_candidate(
            data.model_copy(update={"source": "Walk-in"})
        )

    def record_visit(self, candidate_id, data):
        with self.session.begin():
            required(self.session, Candidate, candidate_id)
            validate_staff(self.session, data.recorded_by_staff_id)
            row = CandidateVisit(candidate_id=candidate_id, **data.model_dump())
            self.session.add(row)
            self.session.flush()
            return VisitRead.model_validate(row)

    def list_visits_for_day(self, day=None, candidate_id=None):
        return [
            VisitRead.model_validate(row)
            for row in repo.visits(self.session, candidate_id, day, self.timezone)
        ]


class JobSearchService:
    def __init__(self, session, timezone="Asia/Kolkata"):
        self.session, self.timezone = session, timezone

    def read(self, row):
        overdue = (
            row.follow_up_date is not None
            and row.follow_up_date < office_today(self.timezone)
            and row.status not in ("Placed", "Closed")
        )
        return JobSearchRequestRead.model_validate(row).model_copy(update={"is_overdue": overdue})

    def _add(self, candidate_id, data):
        validate_staff(self.session, data.assigned_staff_id)
        row = JobSearchRequest(
            candidate_id=candidate_id,
            **data.model_dump(),
            closed_at=datetime.now(UTC) if data.status in ("Placed", "Closed") else None,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def create_request(self, candidate_id, data):
        with self.session.begin():
            required(self.session, Candidate, candidate_id)
            return self.read(self._add(candidate_id, data))

    def update_request(self, identity, data):
        with self.session.begin():
            row = required(self.session, JobSearchRequest, identity, True)
            version_check(row, data.version)
            fields = data.model_fields_set - {"version"}
            values = {key: getattr(row, key) for key in JobSearchRequestCreate.model_fields}
            values.update({key: getattr(data, key) for key in fields})
            change = validated(JobSearchRequestCreate, values)
            if change.assigned_staff_id != row.assigned_staff_id:
                validate_staff(self.session, change.assigned_staff_id)
            if any(getattr(row, key) != getattr(change, key) for key in fields):
                for key in fields:
                    setattr(row, key, getattr(change, key))
                row.closed_at = (
                    (row.closed_at or datetime.now(UTC))
                    if row.status in ("Placed", "Closed")
                    else None
                )
                row.version += 1
            self.session.flush()
            return self.read(row)

    def list_due_requests(self, staff_id=None, due_only=False, candidate_id=None):
        return [
            self.read(row)
            for row in repo.requests(
                self.session,
                candidate_id,
                staff_id,
                office_today(self.timezone) if due_only else None,
            )
        ]

    def list_candidate_requests(self, candidate_id):
        return self.list_due_requests(candidate_id=candidate_id)


class DomainCatalogService:
    def __init__(self, session):
        self.session = session

    def add_domain(self, data):
        return self._add(WorkDomain, data)

    def add_subdomain(self, data):
        return self._add(WorkSubdomain, data)

    def _add(self, model, data):
        with self.session.begin():
            values = data.model_dump()
            if (
                model is WorkSubdomain
                and not required(self.session, WorkDomain, data.domain_id, True).is_active
            ):
                raise WorkflowError("Parent domain must be active.")
            normalized = normalized_name(data.name)
            if not normalized:
                raise WorkflowError("Enter a nonblank name.")
            row = model(**values, normalized_name=normalized, key=normalized)
            self.session.add(row)
            self.session.flush()
            return (DomainRead if model is WorkDomain else SubdomainRead).model_validate(row)

    def update_category(self, model, identity, data):
        with self.session.begin():
            row = required(self.session, model, identity, True)
            for key in data.model_fields_set:
                value = getattr(data, key)
                if value is None:
                    raise WorkflowError("Name and active flag cannot be cleared.")
                setattr(row, key, value)
            row.normalized_name = normalized_name(row.name)
            if not row.normalized_name:
                raise WorkflowError("Enter a nonblank name.")
            self.session.flush()
            return (DomainRead if model is WorkDomain else SubdomainRead).model_validate(row)

    def list_active_catalog(self, active=True):
        return {
            "domains": [
                DomainRead.model_validate(row)
                for row in repo.catalog(self.session, WorkDomain, active)
            ],
            "subdomains": [
                SubdomainRead.model_validate(row)
                for row in repo.catalog(self.session, WorkSubdomain, active)
            ],
        }


class ResumeParseService:
    def __init__(self, session):
        self.session = session

    def add_parse_result(self, candidate_id, data):
        with self.session.begin():
            doc = required(self.session, CandidateDocument, data.document_id)
            if doc.candidate_id != candidate_id or doc.kind != "ORIGINAL_RESUME":
                raise WorkflowError(
                    "Choose a specific original resume belonging to this candidate."
                )
            validate_staff(self.session, data.pasted_by_staff_id)
            row = ResumeParseResult(**data.model_dump())
            self.session.add(row)
            self.session.flush()
            return ResumeParseRead.model_validate(row)

    def list_parse_results(self, candidate_id):
        return [
            ResumeParseRead.model_validate(row) for row in repo.parses(self.session, candidate_id)
        ]

    def review_parse_result(self, candidate_id, identity, data):
        with self.session.begin():
            row = required(self.session, ResumeParseResult, identity, True)
            doc = required(self.session, CandidateDocument, row.document_id)
            if doc.candidate_id != candidate_id:
                raise WorkflowError("Parse result not found.", 404)
            validate_staff(self.session, data.reviewed_by_staff_id)
            if row.review_status != "Unreviewed":
                raise WorkflowError(
                    (
                        "This review is already recorded; preserve it and paste a new resu"
                        "lt if needed."
                    ),
                    409,
                )
            row.review_status = data.review_status
            row.reviewed_by_staff_id = data.reviewed_by_staff_id
            row.reviewed_at = datetime.now(UTC)
            self.session.flush()
            return ResumeParseRead.model_validate(row)
