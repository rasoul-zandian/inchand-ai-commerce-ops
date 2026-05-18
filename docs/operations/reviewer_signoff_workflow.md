# Reviewer Sign-off Workflow

**Status:** Governance workflow only — no corpus build, embeddings, or indexing  
**Audience:** AI ops, privacy, business, and compliance reviewers  
**Contracts:** `app/corpus_planning/reviewer_models.py`, `app/corpus_planning/reviewer_builders.py`

---

## Purpose

This workflow defines **human-only** approval gates before any pilot corpus builder runs. It converts offline replay and privacy observations into **explicit reviewer decisions** with a deterministic checklist — not automatic corpus eligibility.

Related artifacts:

- [166-ticket replay execution report](larger_replay_166_ticket_execution_report.md)
- [Privacy review execution report — 166-ticket batch](privacy_review_166_ticket_execution_report.md) (residual warnings after redaction)
- [Pilot corpus planning](pilot_corpus_planning.md)
- Planning metadata: `app/corpus_planning/models.py`

---

## Principles

| Principle | Rule |
|-----------|------|
| Human approval only | **AI systems cannot self-approve** corpus eligibility |
| Advisory replay metrics | Routing/QA replay outputs inform review; they do not approve corpus |
| Explicit privacy triage | Privacy warnings require **named reviewer** clearance per batch/subset |
| No auto-ingestion | Sign-off does not copy exports or write vector indexes |
| Auditability | Sign-off records use stable IDs, roles, decisions, and checklist pass/fail |

---

## Reviewer responsibilities

| Role | `ReviewerRole` | Focus |
|------|----------------|--------|
| AI operations | `ai_ops_reviewer` | Replay stability, scope, retrieval safety |
| Privacy / data | `privacy_reviewer` | Anonymization, PII pattern triage |
| Business / operations | `business_reviewer` | Ticket mix, operator expectations |
| Compliance | `compliance_reviewer` | Policy alignment, escalation paths |

A single sign-off record represents **one reviewer’s** attestation. Multi-role approval may require **multiple records** before `corpus_ready_after_signoff()` is true for a batch (product policy outside this contract).

---

## Approval states (`ReviewerDecision`)

| Decision | Meaning | Corpus build |
|----------|---------|--------------|
| `approved` | Reviewer attests checklist passed for scoped records | May proceed **only if** all gates pass |
| `rejected` | Records unsuitable for pilot corpus | **Blocked** |
| `needs_redaction` | Export/anonymization must be fixed and re-reviewed | **Blocked** |
| `escalate` | Requires senior/compliance review | **Blocked** |

---

## Checklist semantics

Default checklist (`build_default_reviewer_checklist()`):

| Item | Intent |
|------|--------|
| `no_raw_pii_visible` | No raw PII in scoped export derivatives |
| `anonymization_verified` | Placeholders and sanitization verified manually |
| `retrieval_safe` | Snippets suitable for retrieval eval (no full threads) |
| `governance_approved` | Aligns with pilot plan and ops reports |
| `corpus_scope_validated` | Subset size/category mix explicitly bounded (e.g. 10–25) |

**Rules:**

- All five items are **required** on every `ReviewerSignoffRecord`.
- `approved` decision **requires** every item `passed=True`.
- Checklist `notes` are short, single-line governance comments (max 280 chars) — **not** ticket transcripts.

---

## Escalation handling

Set `decision=escalate` when:

- Privacy warnings cannot be cleared at the reviewer’s authority level
- Ambiguous anonymization (placeholder vs real identifier)
- Compliance policy conflict

Escalation **always** yields `corpus_ready_after_signoff() == False` until a new sign-off record with `approved` replaces it.

---

## Governance gates before corpus build

`corpus_ready_after_signoff(record)` is **True** only when **all** hold:

1. `replay_review_completed=True`
2. `privacy_review_completed=True`
3. `decision == approved`
4. Every checklist item `passed=True`
5. Decision is not `rejected`, `needs_redaction`, or `escalate`

This is **in addition to** `corpus_plan_ready_for_build()` on `PilotCorpusPlan` (planning status). Both gates must be satisfied before implementing a corpus builder.

**Current 166-ticket batch:** privacy execution report status remains **`review_required`**; **no** sign-off `approved` record exists in git.

---

## Phased rollout expectations

| Phase | Sign-off expectation |
|-------|----------------------|
| Phase 1 (10–25 tickets) | Privacy + AI ops sign-off on named subset |
| Phase 2 (retrieval eval) | Business validation of scope |
| Phase 3 (benchmarking) | Compliance aware of eval-only posture |
| Phase 4 (optional pgvector) | Separate infra + governance approval |

Each phase requires **explicit** sign-off; prior phase approval does not carry forward automatically.

---

## Auditability

Sign-off records should include:

- `signoff_id` — stable identifier (e.g. `signoff_replay166_privacy_001`)
- `source_batch_id` — aggregate batch label (e.g. `replay_166`)
- `reviewer_role` + `reviewer_id` — role enum + short reviewer handle (no customer PII)
- `signed_at_utc` — optional ISO-8601 timestamp
- `approved_record_count` — count of tickets in scope (aggregate only)

Store records in local governance logs or ticket systems — **not** in git if they reference operational identifiers beyond aggregate policy allows.

---

## Governance (this step)

| Item | Status |
|------|--------|
| Corpus directories | **Not created** |
| Embeddings / indexing | **Not performed** |
| Auto-approval | **Forbidden** |
| Scope | Contracts + documentation only |

---

## Local sign-off execution (Step 104)

After [redacted replay execution](redacted_replay_166_ticket_execution_report.md) shows **0 residual warnings**, run locally (outputs under `data/private/` only):

### 1. Create reviewer sign-off

```bash
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
  --approved-record-count 20 \
  --output data/private/reviewer_signoff_replay_166_redacted.json
```

`approved` requires **all** `--check` flags. JSON contains governance metadata only — no transcripts.

### 2. Select candidate approved room IDs

```bash
PYTHONPATH=. python3.11 scripts/select_approved_room_ids.py \
  reports/vendor_tickets_400_redacted_replay.jsonl \
  --output data/private/approved_room_ids.txt \
  --limit 25 \
  --include-label support \
  --include-label complaint \
  --include-label fund \
  --exclude-qa-attention
```

Human reviewer must **confirm or edit** the list before corpus build. Selection is deterministic (replay report order).

### 3. Validate approved IDs against redacted export

```bash
PYTHONPATH=. python3.11 scripts/validate_approved_room_ids.py \
  data/private/vendor_tickets_400.redacted.jsonl \
  --approved-room-ids data/private/approved_room_ids.txt
```

### 4. Next step (separate)

`build_pilot_corpus.py` with **redacted** JSONL — only after sign-off + validated approved list.

---

## Recommended next steps

1. Complete redact-first pipeline and confirm **0 residual warnings** on redacted JSONL.
2. Run `create_reviewer_signoff.py` with explicit checklist `--check` flags.
3. Run `select_approved_room_ids.py`, human-review the candidate list, then `validate_approved_room_ids.py`.
4. Run `build_pilot_corpus.py` in a **separate** step — not part of sign-off execution.
