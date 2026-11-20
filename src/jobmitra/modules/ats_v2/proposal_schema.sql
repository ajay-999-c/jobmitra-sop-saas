-- Optional, explicitly installed V3 proposal extension v1. Core version remains 3.
CREATE TABLE company_proposals (
 id TEXT PRIMARY KEY,
 company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
 contact_id TEXT,
 reference TEXT NOT NULL UNIQUE,
 issue_date TEXT NOT NULL,
 fee_basis_points INTEGER NOT NULL CHECK(fee_basis_points IN (600,833)),
 snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)),
 pdf_key TEXT NOT NULL UNIQUE,
 pdf_sha256 TEXT NOT NULL CHECK(length(pdf_sha256)=64),
 pdf_size INTEGER NOT NULL CHECK(pdf_size>0),
 created_at TEXT NOT NULL,
 prepared_by TEXT NOT NULL,
 actor_role TEXT NOT NULL,
 request_key TEXT NOT NULL UNIQUE,
 request_hash TEXT NOT NULL
);
CREATE INDEX ix_company_proposals_company ON company_proposals(company_id,created_at);
CREATE TABLE company_proposal_signed_documents (
 id TEXT PRIMARY KEY,
 proposal_id TEXT NOT NULL REFERENCES company_proposals(id) ON DELETE RESTRICT,
 storage_key TEXT NOT NULL UNIQUE,
 sha256 TEXT NOT NULL CHECK(length(sha256)=64),
 size INTEGER NOT NULL CHECK(size>0),
 original_filename TEXT NOT NULL,
 uploaded_at TEXT NOT NULL,
 uploaded_by TEXT NOT NULL,
 actor_role TEXT NOT NULL,
 request_key TEXT NOT NULL UNIQUE,
 request_hash TEXT NOT NULL
);
CREATE INDEX ix_proposal_signed_parent ON company_proposal_signed_documents(proposal_id,uploaded_at);
CREATE TABLE company_proposal_status_events (
 id TEXT PRIMARY KEY,
 proposal_id TEXT NOT NULL REFERENCES company_proposals(id) ON DELETE RESTRICT,
 status TEXT NOT NULL CHECK(status IN ('SENT','ACCEPTED','DECLINED')),
 evidence TEXT NOT NULL,
 effective_date TEXT NOT NULL,
 authorized_signatory TEXT,
 signed_document_id TEXT REFERENCES company_proposal_signed_documents(id) ON DELETE RESTRICT,
 created_at TEXT NOT NULL,
 recorded_by TEXT NOT NULL,
 actor_role TEXT NOT NULL,
 request_key TEXT NOT NULL UNIQUE,
 request_hash TEXT NOT NULL
);
CREATE INDEX ix_proposal_events_parent ON company_proposal_status_events(proposal_id,created_at);
CREATE TRIGGER proposal_immutable_update BEFORE UPDATE ON company_proposals BEGIN SELECT RAISE(ABORT,'Proposal versions are immutable'); END;
CREATE TRIGGER proposal_immutable_delete BEFORE DELETE ON company_proposals BEGIN SELECT RAISE(ABORT,'Proposal versions are immutable'); END;
CREATE TRIGGER proposal_signed_immutable_update BEFORE UPDATE ON company_proposal_signed_documents BEGIN SELECT RAISE(ABORT,'Signed versions are immutable'); END;
CREATE TRIGGER proposal_signed_immutable_delete BEFORE DELETE ON company_proposal_signed_documents BEGIN SELECT RAISE(ABORT,'Signed versions are immutable'); END;
CREATE TRIGGER proposal_event_immutable_update BEFORE UPDATE ON company_proposal_status_events BEGIN SELECT RAISE(ABORT,'Proposal history is immutable'); END;
CREATE TRIGGER proposal_event_immutable_delete BEFORE DELETE ON company_proposal_status_events BEGIN SELECT RAISE(ABORT,'Proposal history is immutable'); END;
