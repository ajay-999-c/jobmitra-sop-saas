-- Optional V3 candidate profile extension v1. No original columns or rows change.
CREATE TABLE candidate_profile_versions (
 id INTEGER PRIMARY KEY,
 candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE RESTRICT,
 profile_json TEXT NOT NULL CHECK(json_valid(profile_json)),
 before_json TEXT NOT NULL CHECK(json_valid(before_json)),
 after_json TEXT NOT NULL CHECK(json_valid(after_json)),
 provenance_json TEXT NOT NULL CHECK(json_valid(provenance_json)),
 actor_name TEXT NOT NULL,
 actor_role TEXT NOT NULL,
 created_at TEXT NOT NULL,
 request_key TEXT NOT NULL UNIQUE,
 request_hash TEXT NOT NULL
);
CREATE INDEX ix_candidate_profile_versions ON candidate_profile_versions(candidate_id,id DESC);
CREATE TRIGGER profile_version_no_update BEFORE UPDATE ON candidate_profile_versions BEGIN SELECT RAISE(ABORT,'Profile versions are immutable'); END;
CREATE TRIGGER profile_version_no_delete BEFORE DELETE ON candidate_profile_versions BEGIN SELECT RAISE(ABORT,'Profile history cannot be deleted'); END;
