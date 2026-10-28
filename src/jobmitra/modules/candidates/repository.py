"""Read/lock queries only; transactions belong to services."""

import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import case, false, func, or_, select, text

from .models import (
    Candidate,
    CandidateDocument,
    CandidateVisit,
    JobSearchRequest,
    ResumeParseResult,
    WorkDomain,
    WorkSubdomain,
)


def find(session, model, identity, lock=False):
    query = select(model).where(model.id == identity)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return session.scalar(query)


def candidates(session, query=None, *, limit=None, offset=0):
    stmt = select(Candidate)
    order = []
    query = (query or "").strip()
    if query:
        # Phone-like input only: letters must not turn a name into a phone search.
        if re.fullmatch(r"[+0-9\s().-]+", query):
            digits = re.sub(r"[^0-9]", "", query)
            if query.startswith("+91"):
                digits = digits[2:]
            elif digits.startswith("0091"):
                digits = digits[4:]
            elif len(digits) == 12 and digits.startswith("91"):
                digits = digits[2:]
            if len(digits) < 4:
                stmt = stmt.where(false())
            else:
                variants = {digits}
                if len(digits) == 10:
                    variants.update({"91" + digits, "0091" + digits})
                exact = Candidate.mobile_normalized.in_(variants)
                stmt = stmt.where(Candidate.mobile_normalized.contains(digits))
                order.append(case((exact, 0), else_=1))
        else:
            # Literal substring search; SQLAlchemy binds values, including wildcards.
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            stmt = stmt.where(
                or_(
                    Candidate.full_name.ilike(pattern, escape="\\"),
                    Candidate.email.ilike(pattern, escape="\\"),
                    Candidate.role_title.ilike(pattern, escape="\\"),
                )
            )
    stmt = stmt.order_by(*order, func.lower(Candidate.full_name), Candidate.id)
    if limit is not None:
        stmt = stmt.limit(limit).offset(offset)
    return session.scalars(stmt).all()


def candidate_count(session):
    return session.scalar(select(func.count()).select_from(Candidate))


def duplicates(session, mobile, exclude_id=None):
    stmt = select(Candidate).where(Candidate.mobile_normalized == mobile)
    if exclude_id:
        stmt = stmt.where(Candidate.id != exclude_id)
    return session.scalars(stmt.order_by(Candidate.full_name)).all()


def lock_mobile(session, key):
    # Serialize matching-mobile registrations without forbidding shared family numbers.
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": "candidate-mobile:" + key},
    )


def catalog(session, model, active=False):
    stmt = select(model)
    if active:
        stmt = stmt.where(model.is_active.is_(True))
        if model is WorkSubdomain:
            stmt = stmt.join(WorkDomain).where(WorkDomain.is_active.is_(True))
    return session.scalars(stmt.order_by(model.normalized_name)).all()


def roles(session):
    return session.scalars(
        select(Candidate.role_title)
        .where(Candidate.role_title.is_not(None))
        .distinct()
        .order_by(Candidate.role_title)
    ).all()


def visits(session, candidate_id=None, day=None, timezone="Asia/Kolkata"):
    stmt = select(CandidateVisit)
    if candidate_id:
        stmt = stmt.where(CandidateVisit.candidate_id == candidate_id)
    if day:
        start = datetime.combine(day, time.min, ZoneInfo(timezone))
        stmt = stmt.where(
            CandidateVisit.visited_at >= start,
            CandidateVisit.visited_at < start + timedelta(days=1),
        )
    return session.scalars(stmt.order_by(CandidateVisit.visited_at.desc(), CandidateVisit.id)).all()


def requests(session, candidate_id=None, staff_id=None, due=None):
    stmt = select(JobSearchRequest)
    if candidate_id:
        stmt = stmt.where(JobSearchRequest.candidate_id == candidate_id)
    if staff_id:
        stmt = stmt.where(JobSearchRequest.assigned_staff_id == staff_id)
    if due:
        stmt = stmt.where(
            JobSearchRequest.follow_up_date <= due,
            JobSearchRequest.status.not_in(["Placed", "Closed"]),
        )
    return session.scalars(
        stmt.order_by(
            JobSearchRequest.follow_up_date.asc().nullslast(), JobSearchRequest.opened_at.desc()
        )
    ).all()


def documents(session, candidate_id):
    return session.scalars(
        select(CandidateDocument)
        .where(CandidateDocument.candidate_id == candidate_id)
        .order_by(CandidateDocument.kind, CandidateDocument.version.desc())
    ).all()


def next_document_version(session, candidate_id, kind):
    return (
        session.scalar(
            select(func.max(CandidateDocument.version)).where(
                CandidateDocument.candidate_id == candidate_id, CandidateDocument.kind == kind
            )
        )
        or 0
    ) + 1


def parses(session, candidate_id):
    return session.scalars(
        select(ResumeParseResult)
        .join(CandidateDocument, ResumeParseResult.document_id == CandidateDocument.id)
        .where(CandidateDocument.candidate_id == candidate_id)
        .order_by(ResumeParseResult.created_at.desc(), ResumeParseResult.id)
    ).all()


def contact_mobile_key(value):
    # Existing stored keys remain untouched. Compare common Indian dial-code variants.
    if value.startswith("0091") and len(value) == 14:
        value = value[4:]
    elif value.startswith("91") and len(value) == 12:
        value = value[2:]
    return value


def contact_matches(session, mobile=None, email=None, exclude_id=None):
    clauses = []
    if mobile:
        canonical = contact_mobile_key(mobile)
        variants = {mobile, canonical}
        if len(canonical) == 10 and canonical[0] in "6789":
            variants.update({"91" + canonical, "0091" + canonical})
        clauses.append(Candidate.mobile_normalized.in_(variants))
    if email:
        clauses.append(func.lower(func.btrim(Candidate.email)) == email.strip().lower())
    if not clauses:
        return []
    stmt = select(Candidate).where(or_(*clauses))
    if exclude_id:
        stmt = stmt.where(Candidate.id != exclude_id)
    return session.scalars(stmt.order_by(Candidate.full_name, Candidate.id)).all()


def lock_contacts(session, mobile=None, email=None):
    keys = []
    if mobile:
        keys.append("candidate-mobile:" + contact_mobile_key(mobile))
    if email:
        keys.append("candidate-email:" + email.strip().lower())
    for key in sorted(keys):
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key}
        )
