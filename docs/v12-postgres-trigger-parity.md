# V12 PostgreSQL trigger responsibility audit

All 58 triggers in the verified source were reviewed by responsibility. The PostgreSQL development schema consolidates them into row guards and audit functions, with typed constraints and unique indexes. The original SQLite SQL and sealed staging guards are unchanged.

`guard_record()` implements identities, ownership, outcome dates/evidence, eligibility, retirement and append-only protections. `audit_record()` preserves event types and field-level snapshots. `emit_event()` inserts scoped history. Existing transactional services retain progression, stale-update and idempotency checks.

The development schema has 37 user triggers: 15 row guards, 15 truncate guards and seven audit triggers. Original JSON/text and timestamps remain raw TEXT; JSONB is used only to construct new audit objects, never to rewrite source evidence.

Concurrency uses a development-schema advisory transaction lock for short writes, candidate/JD row locks and a partial unique index for unresolved global allocations. Request receipts and stale checks run after acquiring the write lock. This conservatively preserves SQLite writer ordering; it is not a production throughput benchmark.

Physical deletes of retained entities are rejected in development. Existing archive/deactivate/retire workflows remain available. This is deliberately stricter than the source nonreferenced-company delete trigger; no approved UI delete operation was removed.

| Original SQLite trigger | Responsibility | PostgreSQL implementation |
|---|---|---|
| `profile_version_no_delete` | Append-only history and retained entities | `guard_record()` + constraints/services |
| `profile_version_no_update` | Append-only history and retained entities | `guard_record()` + constraints/services |
| `proposal_event_immutable_delete` | Append-only history and retained entities | `guard_record()` + constraints/services |
| `proposal_event_immutable_update` | Append-only history and retained entities | `guard_record()` + constraints/services |
| `proposal_immutable_delete` | Append-only history and retained entities | `guard_record()` + constraints/services |
| `proposal_immutable_update` | Append-only history and retained entities | `guard_record()` + constraints/services |
| `proposal_signed_immutable_delete` | Append-only history and retained entities | `guard_record()` + constraints/services |
| `proposal_signed_immutable_update` | Append-only history and retained entities | `guard_record()` + constraints/services |
| `trg_activity_candidate_immutable` | Immutable identity, provenance and rejected snapshots | `guard_record()` + constraints/services |
| `trg_activity_created` | Canonical creation/change audit payloads | `audit_record()` / `emit_event()` |
| `trg_activity_no_delete` | Append-only history and retained entities | `guard_record()` + constraints/services |
| `trg_activity_updated` | Canonical creation/change audit payloads | `audit_record()` / `emit_event()` |
| `trg_candidate_created` | Canonical creation/change audit payloads | `audit_record()` / `emit_event()` |
| `trg_candidate_identity_immutable` | Immutable identity, provenance and rejected snapshots | `guard_record()` + constraints/services |
| `trg_candidate_legacy_identity_immutable` | Immutable identity, provenance and rejected snapshots | `guard_record()` + constraints/services |
| `trg_candidate_updated` | Canonical creation/change audit payloads | `audit_record()` / `emit_event()` |
| `trg_company_audit_no_delete` | Append-only history and retained entities | `guard_record()` + constraints/services |
| `trg_company_audit_no_update` | Append-only history and retained entities | `guard_record()` + constraints/services |
| `trg_company_v3_created` | Canonical creation/change audit payloads | `audit_record()` / `emit_event()` |
| `trg_company_v3_updated` | Canonical creation/change audit payloads | `audit_record()` / `emit_event()` |
| `trg_event_scope_valid` | Event parent/ownership validation | `guard_record()` + constraints/services |
| `trg_events_block_delete` | Append-only history and retained entities | `guard_record()` + constraints/services |
| `trg_events_block_update` | Append-only history and retained entities | `guard_record()` + constraints/services |
| `trg_jd_candidate_identity_immutable` | Immutable identity, provenance and rejected snapshots | `guard_record()` + constraints/services |
| `trg_jd_created` | Canonical creation/change audit payloads | `audit_record()` / `emit_event()` |
| `trg_jd_identity_immutable` | Immutable identity, provenance and rejected snapshots | `guard_record()` + constraints/services |
| `trg_jd_local_company_change_valid` | Active company/contact ownership and placement-company retention | `guard_record()` + constraints/services |
| `trg_jd_local_company_valid` | Active company/contact ownership and placement-company retention | `guard_record()` + constraints/services |
| `trg_jd_updated` | Canonical creation/change audit payloads | `audit_record()` / `emit_event()` |
| `trg_jd_version_no_decrease` | Workflow versions, round ownership/retirement and terminal stages | `guard_record()` + constraints/services |
| `trg_jd_workflow_updated` | Canonical creation/change audit payloads | `audit_record()` / `emit_event()` |
| `trg_local_company_identity_immutable` | Immutable identity, provenance and rejected snapshots | `guard_record()` + constraints/services |
| `trg_local_company_no_referenced_delete` | Append-only history and retained entities | `guard_record()` + constraints/services |
| `trg_pool_added` | Canonical creation/change audit payloads | `audit_record()` / `emit_event()` |
| `trg_pool_insert_active` | Pool/selection eligibility and explicit outcome facts | `guard_record()` + constraints/services |
| `trg_pool_moved` | Canonical creation/change audit payloads | `audit_record()` / `emit_event()` |
| `trg_pool_note_changed` | Canonical creation/change audit payloads | `audit_record()` / `emit_event()` |
| `trg_rejection_snapshot_immutable` | Immutable identity, provenance and rejected snapshots | `guard_record()` + constraints/services |
| `trg_resume_added` | Canonical creation/change audit payloads | `audit_record()` / `emit_event()` |
| `trg_resume_current_changed` | Canonical creation/change audit payloads | `audit_record()` / `emit_event()` |
| `trg_resume_legacy_identity_immutable` | Immutable identity, provenance and rejected snapshots | `guard_record()` + constraints/services |
| `trg_resume_no_delete` | Append-only history and retained entities | `guard_record()` + constraints/services |
| `trg_resume_no_mutation` | Immutable identity, provenance and rejected snapshots | `guard_record()` + constraints/services |
| `trg_round_added` | Canonical creation/change audit payloads | `audit_record()` / `emit_event()` |
| `trg_round_identity_immutable` | Immutable identity, provenance and rejected snapshots | `guard_record()` + constraints/services |
| `trg_round_no_delete` | Append-only history and retained entities | `guard_record()` + constraints/services |
| `trg_round_retire_with_candidate` | Workflow versions, round ownership/retirement and terminal stages | `guard_record()` + constraints/services |
| `trg_round_stage_valid` | Workflow versions, round ownership/retirement and terminal stages | `guard_record()` + constraints/services |
| `trg_round_updated` | Canonical creation/change audit payloads | `audit_record()` / `emit_event()` |
| `trg_terminal_stage_lock` | Workflow versions, round ownership/retirement and terminal stages | `guard_record()` + constraints/services |
| `trg_v3_contact_audit` | Canonical creation/change audit payloads | `audit_record()` / `emit_event()` |
| `trg_v3_jd_contact_insert` | Active company/contact ownership and placement-company retention | `guard_record()` + constraints/services |
| `trg_v3_jd_contact_update` | Active company/contact ownership and placement-company retention | `guard_record()` + constraints/services |
| `trg_v3_outcome_audit` | Canonical creation/change audit payloads | `audit_record()` / `emit_event()` |
| `trg_v3_outcome_valid` | Pool/selection eligibility and explicit outcome facts | `guard_record()` + constraints/services |
| `trg_v3_placement_company_immutable` | Active company/contact ownership and placement-company retention | `guard_record()` + constraints/services |
| `trg_v3_pool_eligibility` | Pool/selection eligibility and explicit outcome facts | `guard_record()` + constraints/services |
| `trg_v3_selection_exclusivity` | Pool/selection eligibility and explicit outcome facts | `guard_record()` + constraints/services |

Verification covers master editing/audits, profile history, original/altered/parsed resumes, rejection snapshots, round retirement, selection/joining/closure/reactivation, ownership failures, concurrent selections/registration, atomic feedback, immutable proposal versions, signed evidence and stale proposal statuses.

Cloning uses PostgreSQL INSERT SELECT before installing development audit triggers, reconciles all 664 rows and copies 779 source identity/classification entries. It emits no synthetic import events. Sequence positions advance only inside the new development schema. New verification fixtures are non-production.

Production activation remains a separate decision: provision a least-privilege role, verify Windows filesystem behavior and storage mappings, review data eligibility, load-test concurrency and approve the cutover/rollback plan.
