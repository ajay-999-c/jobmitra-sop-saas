-- Optional V3 registration extension v1: canonical EMAIL source support.
CREATE TABLE candidate_registration_extension (
 version INTEGER PRIMARY KEY CHECK(version=1)
);
CREATE TRIGGER registration_extension_no_update BEFORE UPDATE ON candidate_registration_extension BEGIN SELECT RAISE(ABORT,'Registration extension version is immutable'); END;
CREATE TRIGGER registration_extension_no_delete BEFORE DELETE ON candidate_registration_extension BEGIN SELECT RAISE(ABORT,'Registration extension version is immutable'); END;
