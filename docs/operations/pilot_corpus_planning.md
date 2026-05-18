# Pilot Corpus Planning

**Status:** Planning only — no corpus directories, embeddings, indexing, or ingestion jobs  
**Audience:** Retrieval, data governance, AI operations, and operator reviewers

---

## Purpose

The future **pilot corpus** is intended for retrieval evaluation and operational AI experimentation using **privacy-reviewed, anonymized, replay-approved** vendor ticket records.

This document defines **governance boundaries, eligibility rules, manifest planning, and rollout phases** only. It does **not** authorize automatic corpus generation, vector indexing, or production RAG.

Related governance artifacts:

- [50-ticket real replay baseline](real_replay_50_ticket_baseline.md)
- [166-ticket larger replay execution report](larger_replay_166_ticket_execution_report.md)
- [Privacy review execution report — 166-ticket batch](privacy_review_166_ticket_execution_report.md)
- [Real data pilot plan (retrieval)](../data_governance/real_data_pilot_plan.md)
- Privacy review workflow: `app/privacy_review/`, `scripts/build_privacy_review_report.py`
- Planning contracts: `app/corpus_planning/`
- [Reviewer sign-off workflow](reviewer_signoff_workflow.md) — human approval checklist and `corpus_ready_after_signoff()` gates
- [Redacted replay execution report — 166-ticket batch](redacted_replay_166_ticket_execution_report.md)
- [Pilot corpus repository policy](pilot_corpus_repository_policy.md) — **local-only**; do not commit `corpus/vendor_ticket_real_pilot/` by default

**Current corpus status (166-ticket batch):** First **25-record** pilot corpus built locally at `corpus/vendor_ticket_real_pilot/` (`approved_record_count=25`, `source_batch_id=replay_166_redacted_v1`, `reviewer_signoff_id=signoff_replay_166_redacted_v1`). **`embedding_status`** and **`indexing_status`** remain **`not_started`**. Integrity verification: `scripts/check_pilot_corpus_integrity.py` — see [Pilot corpus 25 build report](pilot_corpus_25_build_report.md).

---

## Scope

### In scope

- Reviewed / anonymized replay-approved tickets (human sign-off required)
- Offline / local corpus preparation **planning**
- Manifest and lockfile structure (design only)
- Namespace isolation from synthetic / dev bootstrap corpus
- Retrieval evaluation **planning** (benchmarks, gates, sign-off checkpoints)

### Out of scope

- Production ingestion or live ticket sync
- pgvector indexing or Postgres vector tables
- Semantic retrieval execution in production
- Embedding generation or OpenAI calls in CI
- Production RAG wiring (FastAPI, LangGraph runtime changes)
- Auto-sync with operational exports
- Automatic approval or auto-ingestion systems

---

## Preconditions

All of the following must be true **before** any pilot corpus directory is created or populated:

| Precondition | Current evidence (operations) |
|--------------|-------------------------------|
| Replay calibration stable | 50-ticket and 166-ticket replays completed |
| Routing mismatch acceptable | **0** mismatches on 50- and 166-ticket baselines |
| Replay failures acceptable | **0** failed replays on baselines |
| Privacy review completed | Executed for 166-ticket batch — [execution report](privacy_review_166_ticket_execution_report.md) |
| Suspicious warnings triaged | **Residual 0/166** on redacted run — [redacted replay report](redacted_replay_166_ticket_execution_report.md); pre-redaction 14/7/7 superseded |
| Operator / business sign-off | **Pending** — ready for sign-off; corpus build still blocked until approved |

Until sign-off, pilot corpus status remains **`review_required`** (current state for the 166-ticket batch) or **`blocked`** in planning metadata (`app/corpus_planning/models.py`).

---

## Candidate corpus inputs

Potential source pipeline (offline, local-only):

```
raw export (private)
  → normalize (--skip-empty-messages)
  → redact PII (scripts/redact_ticket_export.py)
  → validate redacted JSONL (residual suspicious-pattern warnings)
  → replay redacted export (mock workflow, routing metrics)
  → privacy review (residual warnings on redacted export)
  → reviewer sign-off (human checklist)
  → manual approved room_id list
  → build_pilot_corpus.py (approved subset from **redacted** JSONL only)
```

**Redact-first semantics:**

- Redaction **reduces** warning volume; post-redaction warnings are **residual risk**.
- Human review is still required for residual warnings.
- Redaction **does not** equal corpus approval; reviewer sign-off is **mandatory**.
- **Do not** run `build_pilot_corpus.py` on unredacted `*.normalized.jsonl`.
- **No** embeddings or indexing in the redaction step.

Only tickets that pass **replay**, **privacy review**, and **operator approval** may enter the candidate set. No step auto-promotes tickets to corpus eligibility.

---

## Corpus governance rules

| Rule | Rationale |
|------|-----------|
| No raw production dumps in git | Prevent PII/secrets leakage |
| No unreviewed tickets | Warnings are observation signals, not approval |
| No automatic export ingestion | Human gate on every batch |
| No direct production synchronization | Offline pilot only |
| Reviewed / anonymized records only | Placeholders (`SELLER_ID_001`, etc.) |
| Separate namespace from `corpus/vendor_ticket/` | Avoid bootstrap contamination |
| Local / offline first | No production DB or vector store in planning phase |

---

## Proposed directory structure

**Documented only — directories are not created in this planning step.**

```
corpus/
  vendor_ticket_real_pilot/
    manifest.json
    lockfile.json
    documents/
    metadata/
    governance/
```

- **`documents/`** — short, approved snippets (policies, patterns, style notes), not full raw threads
- **`metadata/`** — per-document retrieval metadata (no raw transcripts)
- **`governance/`** — sign-off records, exclusion logs, review notes (aggregate-safe)

---

## Manifest planning

Future `manifest.json` fields (illustrative):

| Field | Purpose |
|-------|---------|
| `corpus_id` | Stable pilot corpus identifier |
| `created_at` | UTC timestamp of manifest creation |
| `source_batch_id` | e.g. `replay_166_2026-05` (aggregate label, not raw export path) |
| `reviewed_record_count` | Tickets approved for corpus inclusion |
| `excluded_record_count` | Tickets blocked (warnings, replay failure, operator reject) |
| `warning_summary` | Aggregate warning type counts only |
| `reviewer_signoff` | Named roles / dates (no secrets) |
| `embedding_status` | Initially **`not_started`** |
| `indexing_status` | Initially **`not_started`** |

`embedding_status` and `indexing_status` must remain **`not_started`** until a separate, explicitly approved implementation step authorizes embedding/index work.

---

## Candidate metadata fields

Potential per-document retrieval metadata (no raw transcript storage):

| Field | Use |
|-------|-----|
| `room_id` | Traceability to approved export row (local only) |
| `ticket_label` | support / complaint / fund |
| `ticket_subtype` | Finer routing context |
| `department` | Assigned department from replay |
| `route_label` | Workflow route observation |
| `qa_attention` | Whether QA flagged the replay row |
| `review_priority` | LOW / MEDIUM / HIGH |
| `replay_batch_id` | Links to 50- or 166-ticket (or future) batch |

**Do not** store full message bodies, `draft_response`, `final_response`, or `conversation_transcript` in git-safe corpus files.

---

## Corpus eligibility guidance

A record is **eligible** for pilot corpus candidacy only if:

- No **unresolved** privacy warnings for that `room_id`
- Replay **successful** (no workflow errors in replay report)
- Anonymization **verified** by data/operator review
- Explicit **approval** by operators and data team

Records with any privacy warning remain **blocked** until manual review clears them (`corpus_eligible=False` in privacy review contracts).

---

## Rollout strategy

| Phase | Scope | Gate |
|-------|--------|------|
| **Phase 1** | Tiny reviewed subset (**10–25** tickets) | Privacy + replay sign-off; manifest draft |
| **Phase 2** | Evaluation-only retrieval experiments | Phase 1 complete; no production traffic |
| **Phase 3** | Offline retrieval benchmarking vs golden snapshot | Phase 2 metrics reviewed |
| **Phase 4** | Optional future pgvector evaluation | Explicit infra + governance approval |

Each phase requires **explicit sign-off** before the next phase. Planning metadata uses `PilotCorpusStatus` (`app/corpus_planning/models.py`).

---

## Risk areas

| Risk | Mitigation |
|------|------------|
| Privacy leakage | Privacy review workflow; no raw text in git; warning triage |
| Overfitting to replay sample | Hold out tickets; cap pilot size; document batch bias |
| Poor anonymization | Manual review; placeholder policy; re-export sanitization |
| Retrieval contamination | Separate namespace; lockfile; no mix with bootstrap corpus |
| Operator trust erosion | Human approval; no auto-send / auto-approve |
| Governance drift | Manifest sign-off fields; status enum; blocked state |

---

## Controlled pilot corpus builder

**Script:** `scripts/build_pilot_corpus.py`  
**Library:** `app/corpus_planning/pilot_corpus_builder.py`

Builds `corpus/vendor_ticket_real_pilot/` **only** from a manually approved subset:

```bash
PYTHONPATH=. python3.11 scripts/build_pilot_corpus.py \
  data/private/vendor_tickets_400.redacted.jsonl \
  --approved-room-ids data/private/approved_room_ids.txt \
  --corpus-dir corpus/vendor_ticket_real_pilot \
  --source-batch-id replay_166_v1 \
  --reviewer-signoff-id SIGNOFF_001
```

**Requirements:**

- One `room_id` per line in the approved IDs file (`#` comments and blank lines allowed).
- Document order follows **approved list order** (not export file order).
- Fails if approved list is empty, any ID is missing, or export contains duplicate `room_id`s.
- Fails if corpus dir exists without `--overwrite`.
- **No** embeddings, **no** pgvector indexing, **no** OpenAI calls.

**Output layout:**

```text
corpus/vendor_ticket_real_pilot/
  manifest.json
  corpus.lock.json
  documents/<room_id>.json
  metadata/build_summary.json
  governance/reviewer_signoff_reference.json
```

Commit `corpus/vendor_ticket_real_pilot/` to git **only** after governance review confirms records are sanitized and sign-off is complete. `data/private/` and `reports/` remain **uncommitted**.

---

## Sign-off and approved room selection (local)

After [redacted replay report](redacted_replay_166_ticket_execution_report.md) (residual warnings **0**):

```bash
# Sign-off (all checklist --check flags required for approved)
PYTHONPATH=. python3.11 scripts/create_reviewer_signoff.py \
  --source-batch-id replay_166_redacted_v1 \
  --reviewer-role ai_ops_reviewer \
  --reviewer-id LOCAL_REVIEWER \
  --decision approved \
  --check no_raw_pii_visible \
  --check anonymization_verified \
  --check retrieval_safe \
  --check governance_approved \
  --check corpus_scope_validated \
  --output data/private/reviewer_signoff_replay_166_redacted.json

# Candidate approved room IDs (human must confirm)
PYTHONPATH=. python3.11 scripts/select_approved_room_ids.py \
  reports/vendor_tickets_400_redacted_replay.jsonl \
  --output data/private/approved_room_ids.txt \
  --limit 25 --exclude-qa-attention

# Validate IDs exist in redacted export
PYTHONPATH=. python3.11 scripts/validate_approved_room_ids.py \
  data/private/vendor_tickets_400.redacted.jsonl \
  --approved-room-ids data/private/approved_room_ids.txt
```

Then run `build_pilot_corpus.py` with **`vendor_tickets_400.redacted.jsonl`** — separate step.

---

## Recommended next steps

1. Execute local sign-off + approved room selection (above); outputs stay in `data/private/`.
2. Run `build_pilot_corpus.py` locally; review generated documents before any git commit.
3. Run **`check_pilot_corpus_integrity.py`** on `corpus/vendor_ticket_real_pilot/`; document results in [pilot corpus 25 build report](pilot_corpus_25_build_report.md).
4. **Later (separate step):** embedding generation and pgvector evaluation only after explicit approval.

---

## Governance

| Item | Default in repo |
|------|----------------|
| `corpus/vendor_ticket_real_pilot/` | Built **locally** (25 records); **gitignored** — see [repository policy](pilot_corpus_repository_policy.md) |
| Integrity checker | `scripts/check_pilot_corpus_integrity.py` |
| Embeddings generated | **No** (`not_started`) |
| pgvector indexing | **No** |
| Retrieval activation over pilot corpus | **No** |
| Production ingestion | **No** |
| Auto ticket selection | **Forbidden** |
