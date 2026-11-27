"""Candidate master and evidence search for ATS V2's SQLite database."""

import json
import re

from sqlalchemy import bindparam, text

from jobmitra.modules.candidates.schemas import mobile_key

from . import request_receipts as receipts
from .candidate_schemas import CandidateCreate, CandidatePatch, SearchParams
from .common import AtsError, one
from .database import insert_result, transaction

JSON_FIELDS = {
    "skills": "skills_json",
    "preferred_cities": "preferred_cities_json",
    "links": "links_json",
}


def candidate_dict(row):
    result = dict(row)
    raw_source = result.pop("source_json", None)
    result.pop("source_fingerprint", None)
    result["source_legacy"] = "postgresql" if result.get("legacy_postgres_id") else None
    if result["source_legacy"]:
        source = json.loads(raw_source or "{}")
        source = source if isinstance(source, dict) else {}
        # Only useful profile facts cross this boundary. The full import snapshot
        # can contain private paths, extracted resumes and historical actor data.
        for field in ("notice_period_text", "hometown", "home_state"):
            value = source.get(field)
            result[field] = value if isinstance(value, str) else None
        for field, value_type in (("ready_to_relocate", bool), ("experience_months", int)):
            value = source.get(field)
            result[field] = value if type(value) is value_type else None
        value = source.get("source")
        result["source_original"] = value if isinstance(value, str) else None
    for field, column in JSON_FIELDS.items():
        result[field] = json.loads(result.pop(column, "{}" if field == "links" else "[]"))
    result.pop("phone_normalized", None)
    result.pop("email_normalized", None)
    result.pop("search_text", None)
    result["is_active"] = bool(result["is_active"])
    return result


def participation(conn, candidate_id):
    from .attachment_corrections import removed_sql

    return [
        dict(r)
        for r in conn.execute(
            text(
                "SELECT jc.*,"
                + removed_sql("jc")
                + " AS attachment_removed,j.jd_code,j.title,j.status "
                "FROM jd_candidates jc JOIN job_descriptions j ON j.id=jc.job_id "
                "WHERE jc.candidate_id=:id ORDER BY jc.added_at DESC,jc.id DESC"
            ),
            {"id": candidate_id},
        ).mappings()
    ]


def participation_many(conn, candidate_ids):
    from .attachment_corrections import removed_sql

    result = {}
    if not candidate_ids:
        return result
    query = text(
        "SELECT jc.*,"
        + removed_sql("jc")
        + " AS attachment_removed,j.jd_code,j.title,j.status FROM jd_candidates jc "
        "JOIN job_descriptions j ON j.id=jc.job_id WHERE jc.candidate_id IN :ids "
        "ORDER BY jc.added_at DESC,jc.id DESC"
    ).bindparams(bindparam("ids", expanding=True))
    for row in conn.execute(query, {"ids": candidate_ids}).mappings():
        result.setdefault(row["candidate_id"], []).append(dict(row))
    return result


def get_candidate(engine, candidate_id):
    with engine.connect() as conn:
        result = candidate_dict(one(conn, "candidates", candidate_id))
        result["participation"] = participation(conn, candidate_id)
        from .unified import eligibility, is_v3

        if is_v3(conn):
            result.update(eligibility(conn, candidate_id))
        return result


def normalized_phone(value):
    if not value:
        return None
    digits = mobile_key(value)
    return "91" + digits if len(digits) == 10 else digits


def _db_values(data):
    values = data.model_dump(exclude_unset=isinstance(data, CandidatePatch))
    for field, column in JSON_FIELDS.items():
        if field in values:
            values[column] = json.dumps(values.pop(field), ensure_ascii=False)
    if "phone" in values:
        values["phone_normalized"] = normalized_phone(values["phone"])
    if "email" in values:
        values["email_normalized"] = values["email"].casefold() if values["email"] else None
    return values


def _duplicates(conn, values, candidate_id=None):
    from .registration_store import ensure_source

    ensure_source(conn, values)
    clauses, params = [], {"candidate_id": candidate_id or -1}
    for field in ("phone_normalized", "email_normalized"):
        if values.get(field):
            clauses.append(f"{field}=:{field}")
            params[field] = values[field]
    if clauses:
        found = (
            conn.execute(
                text(
                    "SELECT id,phone_normalized,email_normalized FROM candidates "
                    "WHERE id<>:candidate_id AND ("
                    + " OR ".join(clauses)
                    + ") LIMIT 1"
                ),
                params,
            )
            .mappings()
            .first()
        )
        if found:
            phone_match = values.get("phone_normalized") and (
                values["phone_normalized"] == found["phone_normalized"]
            )
            raise AtsError(
                "Potential duplicate: a candidate with this "
                + ("mobile number" if phone_match else "email")
                + " already exists. Review the existing profile.",
                409,
                code="DUPLICATE_PHONE" if phone_match else "DUPLICATE_EMAIL",
            )


def rebuild_search(conn, candidate_id):
    row = one(conn, "candidates", candidate_id)
    professional = [
        row.get(k)
        for k in (
            "job_title",
            "current_employer",
            "qualification",
            "professional_summary",
            "skills_json",
        )
    ]
    # Only current, explicitly reviewed professional JSON participates in matching.
    professional.extend(
        json.dumps(json.loads(r[0]).get("profile", {}), ensure_ascii=False)
        for r in conn.execute(
            text(
                "SELECT parsed_json FROM candidate_resumes WHERE candidate_id=:id "
                "AND resume_kind='PARSED_TEXT' AND is_current=1 AND parsed_json IS NOT NULL"
            ),
            {"id": candidate_id},
        )
    )
    from .profile_store import installed

    if installed(conn):
        profile = conn.execute(
            text(
                "SELECT profile_json FROM candidate_profile_versions WHERE candidate_id=:id "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"id": candidate_id},
        ).scalar()
        extra = json.loads(profile or "{}")
        professional.extend(
            json.dumps(extra.get(k), ensure_ascii=False)
            for k in (
                "employment_history",
                "education_history",
                "certifications",
                "projects",
                "subdomain",
            )
            if extra.get(k)
        )
    projection = " ".join(str(value) for value in professional if value).casefold()
    conn.execute(
        text(
            "UPDATE candidates SET search_text=:value,"
            "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=:id"
        ),
        {"value": projection, "id": candidate_id},
    )


def create_candidate(engine, data: CandidateCreate):
    values = _db_values(data)
    with transaction(engine) as conn:
        prior = receipts.replay(conn, "candidate-create", data.model_dump(mode="json"))
        if prior is not None:
            return get_candidate(engine, prior)
        _duplicates(conn, values)
        # Generate the stable public code before INSERT so its initial audit is complete.
        import uuid

        values["candidate_code"] = "ATS-" + uuid.uuid4().hex[:16].upper()
        columns = ",".join(values)
        placeholders = ",".join(":" + key for key in values)
        candidate_id = insert_result(
            conn, text(f"INSERT INTO candidates({columns}) VALUES({placeholders})"), values
        ).lastrowid
        rebuild_search(conn, candidate_id)
        receipts.record(
            conn,
            "candidate-create",
            data.model_dump(mode="json"),
            candidate_id,
            candidate_id=candidate_id,
        )
    return get_candidate(engine, candidate_id)


def update_candidate(engine, candidate_id, data: CandidatePatch):
    values = _db_values(data)
    request_data = {
        "candidate_id": candidate_id,
        **data.model_dump(mode="json", exclude_unset=True),
    }
    with transaction(engine) as conn:
        if receipts.replay(conn, "candidate-update", request_data) is not None:
            return get_candidate(engine, candidate_id)
        one(conn, "candidates", candidate_id)
        _duplicates(conn, values, candidate_id)
        if values:
            conn.execute(
                text(
                    "UPDATE candidates SET "
                    + ",".join(f"{k}=:{k}" for k in values)
                    + " WHERE id=:candidate_id"
                ),
                {**values, "candidate_id": candidate_id},
            )
            rebuild_search(conn, candidate_id)
        receipts.record(
            conn, "candidate-update", request_data, candidate_id, candidate_id=candidate_id
        )
    return get_candidate(engine, candidate_id)


def _like(value):
    return (
        "%" + value.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    )


def search_candidates(engine, params: SearchParams, *, include_names=False):
    clauses, bindings, scores = ["c.is_active=1"], {}, []
    evidence = "COALESCE(c.search_text,'')"
    if include_names:
        evidence = "(COALESCE(c.search_text,'') || ' ' || lower(c.full_name))"
        if params.identity_lookup:
            evidence = (
                "(COALESCE(c.search_text,'') || ' ' || lower(c.full_name) || ' ' || "
                "COALESCE(c.phone,'') || ' ' || COALESCE(c.phone_normalized,'') || ' ' || "
                "lower(COALESCE(c.email,'')) || ' ' || "
                "lower(COALESCE(c.current_city,'')) || ' ' || "
                "lower(COALESCE(c.preferred_cities_json,'')))"
            )
    keywords = params.keywords
    if include_names and params.identity_lookup and re.fullmatch(r"[+\d\s().-]+", keywords):
        digits = re.sub(r"\D", "", keywords)
        if len(digits) >= 3:
            keywords = digits
    terms = [a or b for a, b in re.findall(r'"([^"\n]+)"|([^\s,]+)', keywords)][:30]
    for index, term in enumerate(terms):
        key = f"term{index}"
        bindings[key] = _like(term)
        expression = f"{evidence} LIKE :{key} ESCAPE '\\'"
        scores.append(f"CASE WHEN {expression} THEN 1 ELSE 0 END")
    if terms:
        clauses.append(
            "("
            + (" AND " if params.match == "ALL" else " OR ").join(
                f"{evidence} LIKE :term{i} ESCAPE '\\'" for i in range(len(terms))
            )
            + ")"
        )
    if params.location:
        clauses.append(
            "(lower(COALESCE(c.current_city,'')) LIKE :location ESCAPE '\\' "
            "OR EXISTS (SELECT 1 FROM json_each(c.preferred_cities_json) "
            "WHERE lower(value) LIKE :location ESCAPE '\\'))"
        )
        bindings["location"] = _like(params.location)
    experience = []
    for field, operator in (("experience_min", ">="), ("experience_max", "<=")):
        value = getattr(params, field)
        if value is not None:
            experience.append(f"c.experience_years {operator} :{field}")
            bindings[field] = value
    if experience:
        expression = " AND ".join(experience)
        clauses.append(
            f"(({expression}) OR c.experience_years IS NULL)"
            if params.include_unknown_experience
            else f"({expression})"
        )
    elif not params.include_unknown_experience:
        clauses.append("c.experience_years IS NOT NULL")
    salary_bounds = (("salary_min", ">="), ("salary_max", "<="), ("budget", "<="))
    if any(getattr(params, field) is not None for field, _ in salary_bounds):
        bindings["basis"] = params.salary_basis
        comparable = (
            "c.expected_salary_inr IS NOT NULL AND "
            "c.expected_salary_period IS NOT NULL AND "
            "c.expected_salary_period IN ('MONTHLY','ANNUAL') AND "
            "c.expected_salary_basis IS NOT NULL AND "
            "c.expected_salary_basis<>'UNKNOWN' AND "
            "(:basis='INDICATIVE' OR c.expected_salary_basis=:basis)"
        )
        annual = (
            "c.expected_salary_inr * CASE WHEN c.expected_salary_period='MONTHLY' "
            "THEN 12 ELSE 1 END"
        )
        conditions = []
        for field, operator in salary_bounds:
            value = getattr(params, field)
            if value is not None:
                bindings[field] = value * (12 if params.salary_period == "MONTHLY" else 1)
                conditions.append(f"{annual} {operator} :{field}")
        expression = f"(({comparable}) AND {' AND '.join(conditions)})"
        clauses.append(
            f"({expression} OR NOT ({comparable}))" if params.include_unknown_salary else expression
        )
    elif not params.include_unknown_salary:
        clauses.append(
            "c.expected_salary_inr IS NOT NULL AND c.expected_salary_period IS NOT NULL "
            "AND c.expected_salary_basis IS NOT NULL AND c.expected_salary_basis<>'UNKNOWN'"
        )
    if params.max_notice_days is not None:
        bindings["notice"] = params.max_notice_days
        expression = "c.notice_days<=:notice"
        clauses.append(
            f"({expression} OR c.notice_days IS NULL)"
            if params.include_unknown_notice
            else expression
        )
    elif not params.include_unknown_notice:
        clauses.append("c.notice_days IS NOT NULL")
    if params.availability:
        clauses.append("c.availability=:availability")
        bindings["availability"] = params.availability
    where = " AND ".join(clauses)
    relevance = " + ".join(scores) or "0"
    ordering = {
        "relevance": "relevance DESC,c.updated_at DESC,c.id DESC",
        "recent": "c.updated_at DESC,c.id DESC",
        "experience": "c.experience_years DESC,c.updated_at DESC,c.id DESC",
    }[params.sort]
    with engine.connect() as conn:
        total = conn.scalar(text(f"SELECT count(*) FROM candidates c WHERE {where}"), bindings)
        rows = conn.execute(
            text(
                f"SELECT c.*,({relevance}) AS relevance FROM candidates c WHERE {where} "
                f"ORDER BY {ordering} LIMIT :limit OFFSET :offset"
            ),
            {**bindings, "limit": params.page_size, "offset": (params.page - 1) * params.page_size},
        ).mappings()
        items = [candidate_dict(row) for row in rows]
        ids = [row["id"] for row in items]
        from .unified import eligibility_many, is_v3

        participation_rows = participation_many(conn, ids)
        eligibility_rows = eligibility_many(conn, ids) if is_v3(conn) else {}
        for item in items:
            item["participation"] = participation_rows.get(item["id"], [])
            item.update(eligibility_rows.get(item["id"], {}))
    return {"items": items, "total": total, "page": params.page, "page_size": params.page_size}
