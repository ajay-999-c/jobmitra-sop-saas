"""PDF workflow: synthetic V3 stores, real PDFs, private files and immutable history."""

import base64
import hashlib
import io
import os
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from pypdf import PdfReader, PdfWriter
from sqlalchemy.exc import IntegrityError
from test_approved_v12 import client as client
from test_unified_v12 import HEADERS
from test_unified_v12 import store as store
from test_unified_v12 import v2 as v2

from jobmitra.modules.ats_v2 import proposal, proposal_pdf, unified
from jobmitra.modules.ats_v2 import proposal_documents as docs
from jobmitra.modules.ats_v2.database import transaction, validate
from jobmitra.modules.ats_v2.master_import import local_state
from jobmitra.modules.ats_v2.proposal_store import install


@pytest.fixture
def pdf_client(client, store):
    install(store[0])
    settings = client.app.state.settings
    settings.unified_v12_proposals_enabled = True
    settings.unified_v12_proposal_storage_root = store[-1] / "private-proposals"
    return client


def body(**changes):
    return {
        "idempotency_key": str(uuid4()),
        "actor_name": "Synthetic reviewer",
        "issue_date": unified.office_today().isoformat(),
        "fee_percent": "6",
        **changes,
    }


def route(store):
    return f"/api/v12/approved/companies/{store[1]}/proposals"


def post(client, path, data):
    return client.post(path, json=data, headers={"Idempotency-Key": data["idempotency_key"]})


def generated(client, store, **changes):
    response = post(client, route(store), body(**changes))
    assert response.status_code == 201, response.text
    return response.json()


def compact(text):
    return " ".join(text.split())


def test_very_long_company_wraps_without_losing_terms_or_signature():
    snapshot = {
        "company_name": "Long Fictional Company " + "Example " * 33,
        "consultant": proposal_pdf.CONSULTANT,
        "reference": "X" * 80,
        "issue_date": "2026-11-20",
        "fee_percent": "8.33",
        "clauses": proposal_pdf.clauses("8.33"),
    }
    reader = PdfReader(io.BytesIO(proposal_pdf.render(snapshot)))
    assert len(reader.pages) <= 2
    text = compact(" ".join(page.extract_text() for page in reader.pages))
    assert compact(snapshot["company_name"]) in text
    assert "Accepted by" in reader.pages[-1].extract_text()
    assert "The Client shall inform the Consultant" in reader.pages[-1].extract_text()
    for clause in snapshot["clauses"]:
        assert compact(unescape(re.sub(r"<[^>]+>", "", clause))) in text


@pytest.mark.parametrize("fee,amount,days", [("6", "36000.00", 21), ("8.33", "49980.00", 30)])
def test_pdf_exact_terms_and_decimal_amounts_no_master_changes(
    pdf_client, store, fee, amount, days
):
    with store[0].connect() as conn:
        before = local_state(conn)
    record = generated(pdf_client, store, fee_percent=fee, annual_ctc="600000.00")
    response = pdf_client.get(route(store) + f"/{record['id']}/pdf?download=true")
    assert response.status_code == 200 and response.content.startswith(b"%PDF-")
    assert response.headers["content-type"] == "application/pdf"
    assert hashlib.sha256(response.content).hexdigest() == record["pdf_sha256"]
    reader = PdfReader(io.BytesIO(response.content))
    assert len(reader.pages) == 1
    assert tuple(round(float(n)) for n in reader.pages[0].mediabox[2:]) == (595, 842)
    extracted = compact(reader.pages[0].extract_text())
    assert "Synthetic Client Company" in extracted
    assert record["snapshot"]["fee_amount"] == amount
    assert f"{days} days’ salary" in extracted
    assert f"{fee}% of the candidate’s annual CTC" in extracted
    assert "Terms & Conditions" in extracted and record["reference"] in extracted
    for i, clause in enumerate(proposal_pdf.clauses(fee), 1):
        plain = unescape(re.sub(r"<[^>]+>", "", clause))
        assert compact(plain) in extracted, i
    for label in [
        "Authorized Person Name",
        "Designation",
        "Signature",
        "With regards,",
        "Vishal Agrawal",
        "CEO",
        "Accepted by Synthetic Client Company",
    ]:
        assert label in extracted
    for removed in [
        "Recruitment Services Proposal",
        "Commercial summary",
        "Company acknowledgement",
        "Company seal",
        "Authorized representative name",
        "Chief Executive Officer",
        "Please review these terms",
        "Payment terms Within",
        "Page 1 of",
    ]:
        assert removed not in extracted
    fragments = []
    reader.pages[0].extract_text(
        visitor_text=lambda text, cm, tm, font, size: fragments.append(
            (
                text.strip(),
                tm[4] * cm[0] + tm[5] * cm[2] + cm[4],
                tm[4] * cm[1] + tm[5] * cm[3] + cm[5],
                str((font or {}).get("/BaseFont", "")),
                size,
            )
        )
    )
    for bold in [
        fee + "%",
        "annual CTC",
        str(days) + " days’",
        "7 days",
        "12 months",
        "3 months",
        "free replacement",
        "5 working days",
    ]:
        assert any(bold in value and "Bold" in font for value, _, _, font, _ in fragments), bold
    regards = next(row for row in fragments if row[0] == "With regards,")
    accepted = next(row for row in fragments if row[0].startswith("Accepted by"))
    vishal = next(row for row in fragments if row[0] == "Vishal Agrawal")
    assert abs(regards[2] - accepted[2]) < 0.1
    assert abs(regards[2] - vishal[2] - 15) < 0.1
    assert record["snapshot"]["pdf_renderer"] == 3
    assert record["snapshot"]["layout_source_sha256"] == proposal_pdf.TERMS["layout_source_sha256"]
    assert record["status"] == "PREPARED" and record["events"] == []
    root = pdf_client.app.state.settings.unified_v12_proposal_storage_root
    if os.name == "posix":
        assert root.stat().st_mode & 0o077 == 0
        assert all(p.stat().st_mode & 0o077 == 0 for p in root.iterdir())
    else:
        from jobmitra.modules.ats_v2.proposal_windows import WindowsStore

        with WindowsStore().root(root):
            pass
    with store[0].connect() as conn:
        assert local_state(conn) == before
    validate(store[0])


def test_terms_and_bold_runs_match_authoritative_word_source():
    source = Path(__file__).parents[1] / proposal_pdf.TERMS["layout_source_file"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == proposal_pdf.TERMS["source_sha256"]
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(source) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
    paragraphs = []
    for paragraph in document.findall("./w:body/w:p", ns):
        runs = []
        for run in paragraph.findall("w:r", ns):
            value = "".join(t.text or "" for t in run.findall("w:t", ns))
            bold = run.find("w:rPr/w:b", ns)
            if value:
                runs.append(
                    "<b>" + value + "</b>"
                    if bold is not None and bold.get("{" + ns["w"] + "}val") != "0"
                    else value
                )
        paragraphs.append("".join(runs))
    assert [re.sub(r"^\d+\.", "", p) for p in paragraphs[2:12]] == proposal_pdf.clauses("6")
    assert paragraphs[1] == proposal_pdf.TERMS["introduction"].format(
        consultant=proposal_pdf.CONSULTANT, company_name="Kedia Traders"
    )
    # Original standalone Email content remains unchanged despite new PDF terms.
    assert (
        hashlib.sha256(proposal.STUDIO_FILE.read_bytes()).hexdigest()
        == "cb3f47308cb7dac56c48fef38be958a145e9db5faa96575226668767b4b56d40"
    )


def test_approved_reference_logo_and_font_assets_are_retained():
    root = Path(__file__).parents[1]
    for key, digest in [
        ("layout_source_file", "layout_source_sha256"),
        ("visual_source_file", "visual_source_sha256"),
    ]:
        assert (
            hashlib.sha256((root / proposal_pdf.TERMS[key]).read_bytes()).hexdigest()
            == proposal_pdf.TERMS[digest]
        )
    with zipfile.ZipFile(root / proposal_pdf.TERMS["layout_source_file"]) as archive:
        assert archive.read("word/media/image1.png") == proposal_pdf.LOGO.read_bytes()
    assert len(PdfReader(root / proposal_pdf.TERMS["visual_source_file"]).pages) == 1
    assert (proposal_pdf.ASSETS / "OFL-Liberation.txt").is_file()


def test_heading_and_signoff_geometry_match_the_approved_pdf():
    def positions(reader):
        result = {}

        def visit(value, cm, tm, font, size):
            result[value.strip()] = (
                tm[4] * cm[0] + tm[5] * cm[2] + cm[4],
                tm[4] * cm[1] + tm[5] * cm[3] + cm[5],
                size,
            )

        reader.pages[0].extract_text(visitor_text=visit)
        return result

    source = Path(__file__).parents[1] / proposal_pdf.TERMS["visual_source_file"]
    expected = positions(PdfReader(source))
    blob = proposal_pdf.render(
        {
            "company_name": "Kedia Traders",
            "consultant": proposal_pdf.CONSULTANT,
            "reference": "JM-20261125-0FC1BF6B",
            "issue_date": "2026-11-25",
            "fee_percent": "6",
            "clauses": proposal_pdf.clauses("6"),
        }
    )
    actual = positions(PdfReader(io.BytesIO(blob)))
    for label in [
        "Terms & Conditions",
        "With regards,",
        "Vishal Agrawal",
        "Accepted by Kedia Traders",
        "Authorized Person Name:",
        "Designation:",
        "Signature",
    ]:
        assert actual[label] == pytest.approx(expected[label], abs=0.25), label


def test_new_template_preserves_existing_pdf_bytes_metadata_and_retry(pdf_client, store):
    writer = PdfWriter()
    writer.add_blank_page(width=595.28, height=841.89)
    writer.add_blank_page(width=595.28, height=841.89)
    out = io.BytesIO()
    writer.write(out)
    legacy = out.getvalue()
    old_body = body(reference="Retained historical version")
    with (
        patch.object(proposal_pdf, "render", return_value=legacy),
        patch.object(proposal_pdf, "RENDERER_VERSION", 2),
    ):
        old = post(pdf_client, route(store), old_body).json()
    new = generated(pdf_client, store, fee_percent="8.33")
    assert new["snapshot"]["pdf_renderer"] == 3
    path = route(store) + f"/{old['id']}/pdf?download=true"
    assert pdf_client.get(path).content == legacy
    with patch.object(
        proposal_pdf, "render", side_effect=AssertionError("History must not rerender")
    ):
        assert post(pdf_client, route(store), old_body).json() == old
    history = pdf_client.get(route(store)).json()["items"]
    assert next(row for row in history if row["id"] == old["id"]) == old


def test_extension_explicit_optional_atomic_and_v2_refused(client, store, v2):
    before_path = store[-1] / "isolated.sqlite3"
    with store[0].connect() as conn:
        before = local_state(conn)
    assert client.get(route(store)).status_code == 503
    install(store[0])
    install(store[0])
    validate(store[0])
    with store[0].connect() as conn:
        assert local_state(conn) == before
        assert conn.exec_driver_sql("PRAGMA user_version").scalar_one() == 3
    # Separate V2 store; explicit installer must not upgrade it.
    from jobmitra.modules.ats_v2.database import build_ats_engine, initialize

    other = build_ats_engine(store[-1] / "untouched-v2.sqlite3")
    initialize(other)
    with pytest.raises(RuntimeError, match="V3"):
        install(other)
    with other.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA user_version").scalar_one() == 2
        assert not conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE name='company_proposals'"
        ).first()
    other.dispose()
    assert before_path.is_file()


def test_private_access_and_cross_company_every_resource(pdf_client, store):
    record = generated(pdf_client, store)
    own = route(store) + "/" + record["id"]
    other = f"/api/v12/approved/companies/{uuid4()}/proposals/{record['id']}"
    for suffix in ["/pdf", "/email"]:
        assert pdf_client.get(other + suffix).status_code == 404
    wrong_contact = post(pdf_client, route(store), body(company_contact_id=str(uuid4())))
    assert wrong_contact.status_code == 422
    pdf_client.cookies.clear()
    for path in [route(store), own + "/pdf", own + "/email"]:
        assert pdf_client.get(path).status_code == 403
    assert post(pdf_client, route(store), body()).status_code == 403
    assert pdf_client.get("/static/ats-v2/" + record["id"] + ".pdf").status_code == 404


def test_read_only_email_preview_copy_and_missing_email(pdf_client, store):
    record = generated(pdf_client, store)
    own = route(store) + "/" + record["id"]
    first = pdf_client.get(own + "/pdf").content
    for _ in range(2):
        draft = pdf_client.get(own + "/email").json()
        assert draft["recipient_email"] == ""
        assert draft["subject"] == proposal_pdf.TITLE + " | Synthetic Client Company"
        assert "Dear Synthetic HR," in draft["body"]
        assert "please find attached our Recruitment Services Proposal" in draft["body"]
        assert "Terms & Conditions" in draft["body"]
        assert "Indore jurisdiction" not in draft["body"]
        assert not draft["attachment_attached"] and not draft["delivery_enabled"]
        assert "manually" in draft["instructions"]
    history = pdf_client.get(route(store)).json()["items"]
    assert len(history) == 1 and history[0]["events"] == [] and history[0]["status"] == "PREPARED"
    assert pdf_client.get(own + "/pdf").content == first
    manual = generated(pdf_client, store, recipient_email="manual@example.test")
    assert manual["snapshot"]["recipient_email"] == "manual@example.test"
    assert (
        pdf_client.get(f"/api/v12/approved/companies/{store[1]}/proposal-context").json()[
            "recipient_email"
        ]
        == ""
    )


def test_generation_retry_concurrency_and_failed_publish_roll_back(pdf_client, store):
    data = body()

    def prepare():
        return docs.generate(
            store[0],
            store[1],
            docs.Generate(**data),
            "OPERATOR_TOKEN",
            pdf_client.app.state.settings.unified_v12_proposal_storage_root,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(lambda _: prepare(), range(2)))
    assert a["id"] == b["id"]
    assert post(pdf_client, route(store), {**data, "fee_percent": "8.33"}).status_code == 409
    root = pdf_client.app.state.settings.unified_v12_proposal_storage_root
    before = set(root.iterdir())
    with patch.object(docs, "_insert", side_effect=RuntimeError("Forced rollback")):
        with pytest.raises(RuntimeError):
            docs.generate(store[0], store[1], docs.Generate(**body()), "OPERATOR_TOKEN", root)
    assert set(root.iterdir()) == before
    assert len(pdf_client.get(route(store)).json()["items"]) == 1


def test_signed_versions_and_explicit_acceptance_do_not_overwrite(pdf_client, store):
    record = generated(pdf_client, store)
    p = route(store) + "/" + record["id"]
    blob = pdf_client.get(p + "/pdf").content
    # A synthetic received-copy fixture; not a claim of a real signature.
    upload = body(filename="received-signed-copy.pdf", file_base64=base64.b64encode(blob).decode())
    upload.pop("issue_date")
    upload.pop("fee_percent")
    first = post(pdf_client, p + "/signed-documents", upload)
    assert first.status_code == 201, first.text
    first = first.json()
    sid = first["signed_documents"][0]["id"]
    assert first["status"] == "PREPARED" and first["events"] == []
    again = post(pdf_client, p + "/signed-documents", upload).json()
    assert len(again["signed_documents"]) == 1
    assert pdf_client.get(p + "/signed-documents/" + sid).content == blob
    second = post(
        pdf_client, p + "/signed-documents", {**upload, "idempotency_key": str(uuid4())}
    ).json()
    assert len(second["signed_documents"]) == 2
    event = body(
        status="ACCEPTED",
        evidence="Synthetic received-copy confirmation for isolated test",
        expected_event_id=None,
        confirmed=True,
        effective_date=unified.office_today().isoformat(),
        signed_document_id=sid,
        authorized_signatory="Synthetic client signatory",
    )
    event.pop("issue_date")
    event.pop("fee_percent")
    assert post(pdf_client, p + "/status", {**event, "signed_document_id": None}).status_code == 422
    accepted = post(pdf_client, p + "/status", event)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "ACCEPTED"
    assert (
        post(pdf_client, p + "/status", event).json()["latest_event_id"]
        == accepted.json()["latest_event_id"]
    )
    assert pdf_client.get(p + "/pdf").content == blob
    assert pdf_client.get(p + "/signed-documents/" + sid).content == blob
    for table in [
        "company_proposals",
        "company_proposal_signed_documents",
        "company_proposal_status_events",
    ]:
        with pytest.raises(IntegrityError), transaction(store[0]) as conn:
            conn.exec_driver_sql(f"DELETE FROM {table}")


@pytest.mark.parametrize(
    "kind", ["renamed", "broken", "active", "encrypted", "filename", "oversize", "symlink"]
)
def test_invalid_or_unsafe_signed_uploads_refused(pdf_client, store, kind):
    record = generated(pdf_client, store)
    p = route(store) + "/" + record["id"]
    blob = pdf_client.get(p + "/pdf").content
    filename = "signed.pdf"
    if kind == "renamed":
        blob = b"not a pdf"
    if kind == "broken":
        blob = b"%PDF-1.4\ninvalid\n%%EOF"
    if kind == "active":
        writer = PdfWriter()
        writer.add_blank_page(100, 100)
        writer.add_js("alert(1)")
        out = io.BytesIO()
        writer.write(out)
        blob = out.getvalue()
    if kind == "encrypted":
        writer = PdfWriter()
        writer.add_blank_page(100, 100)
        writer.encrypt("test")
        out = io.BytesIO()
        writer.write(out)
        blob = out.getvalue()
    if kind == "filename":
        filename = "../signed.pdf"
    if kind == "oversize":
        blob = b"%PDF-" + b"0" * (10 * 1024 * 1024)
    if kind == "symlink":
        root = pdf_client.app.state.settings.unified_v12_proposal_storage_root
        alternate = store[-1] / "symlink"
        if os.name == "nt":
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(alternate), str(root)],
                check=True,
                capture_output=True,
            )
        else:
            alternate.symlink_to(root, target_is_directory=True)
        pdf_client.app.state.settings.unified_v12_proposal_storage_root = alternate
    data = {
        "actor_name": "Synthetic reviewer",
        "idempotency_key": str(uuid4()),
        "filename": filename,
        "file_base64": base64.b64encode(blob).decode(),
    }
    response = post(pdf_client, p + "/signed-documents", data)
    assert response.status_code in {413, 422, 503}, response.text
    assert pdf_client.get(route(store)).json()["items"][0]["signed_documents"] == []


def test_status_stale_cross_document_confirm_dates_and_integrity(pdf_client, store):
    a = generated(pdf_client, store)
    b = generated(pdf_client, store, fee_percent="8.33")
    p = route(store) + "/" + a["id"]
    q = route(store) + "/" + b["id"]
    other_signed = post(
        pdf_client,
        q + "/signed-documents",
        {
            "actor_name": "Tester",
            "idempotency_key": str(uuid4()),
            "filename": "received.pdf",
            "file_base64": base64.b64encode(pdf_client.get(q + "/pdf").content).decode(),
        },
    ).json()["signed_documents"][0]["id"]
    data = {
        "actor_name": "Tester",
        "idempotency_key": str(uuid4()),
        "status": "ACCEPTED",
        "expected_event_id": None,
        "evidence": "Synthetic confirmation",
        "effective_date": unified.office_today().isoformat(),
        "confirmed": True,
        "authorized_signatory": "Client",
        "signed_document_id": other_signed,
    }
    assert post(pdf_client, p + "/status", data).status_code == 422
    data.update(status="SENT", signed_document_id=None, authorized_signatory="")
    assert post(pdf_client, p + "/status", {**data, "confirmed": False}).status_code == 422
    assert (
        post(pdf_client, p + "/status", {**data, "effective_date": "2099-01-01"}).status_code == 422
    )
    sent = post(pdf_client, p + "/status", data)
    assert sent.status_code == 200, sent.text
    assert (
        post(
            pdf_client,
            p + "/status",
            {**data, "idempotency_key": str(uuid4()), "status": "DECLINED"},
        ).status_code
        == 409
    )
    with store[0].connect() as conn:
        if conn.dialect.name == "sqlite":
            assert conn.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"
            assert not conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        else:
            validate(store[0])
    root = pdf_client.app.state.settings.unified_v12_proposal_storage_root
    (root / (a["id"] + ".pdf")).write_bytes(b"corrupt")
    assert pdf_client.get(p + "/pdf").status_code == 503


def test_chunked_request_limit_and_html_injection(pdf_client, store):
    response = pdf_client.post(
        route(store),
        content=iter([b"x" * 8_000_000, b"y" * 8_000_000]),
        headers={**HEADERS, "Idempotency-Key": str(uuid4()), "Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert (
        post(pdf_client, route(store), body(consultant="<script>alert(1)</script>")).status_code
        == 422
    )
    pdf = proposal_pdf.render(
        {
            "company_name": "<script>alert(1)</script>",
            "consultant": proposal_pdf.CONSULTANT,
            "reference": "ESCAPE-TEST",
            "issue_date": "2026-11-20",
            "fee_percent": "6",
            "clauses": proposal_pdf.clauses("6"),
        }
    )
    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "<script>alert(1)</script>" in text
