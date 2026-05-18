# Privacy Review Execution Report — 166-Ticket Replay Batch

**Status:** Sanitized aggregate governance report (metrics and decisions only)  
**Replay reference:** [166-ticket larger replay execution report](larger_replay_166_ticket_execution_report.md)  
**Planning reference:** [Pilot corpus planning](pilot_corpus_planning.md)  
**Workflow:** `scripts/build_privacy_review_report.py`, `app/privacy_review/`

---

## Purpose

This report documents the **executed privacy-warning review phase** for the calibrated **166-ticket** replay batch. It records governance observations, corpus readiness implications, and operator review outcomes **before** any pilot corpus consideration, embedding generation, pgvector indexing, or production retrieval integration.

**Official workflow (current):** **redact first, review residual risk** — run `redact_ticket_export.py` before validate, replay, and privacy review. Scan **redacted** JSONL for **residual** warnings; do not treat pre-redaction warning counts as the final gate.

**Post-redaction execution:** [Redacted replay execution report — 166-ticket batch](redacted_replay_166_ticket_execution_report.md) — residual warnings **0/166**; replay stable; ready for reviewer sign-off (not corpus auto-approved).

This step is **governance reporting only** — it does not modify replay logic, privacy detection, or approve any corpus build.

---

## Source Safety

| Artifact | In git? | Notes |
|----------|---------|--------|
| Raw JSON export | **No** | Local/private only |
| Normalized JSONL | **No** | Local/private only (intermediate; do not use for corpus) |
| Redacted JSONL | **No** | Local/private only — use for validate / replay / privacy review |
| Replay report JSONL | **No** | `reports/` gitignored |
| Privacy review Markdown/JSON | **No** | `reports/` gitignored |

- All raw exports remain **local/private**.
- **No raw transcripts** are committed in this repository.
- **No extracted** phone numbers, card numbers, IBAN values, or message bodies appear below.
- Reports referenced here are **aggregate-only** (counts, categories, governance status).
- **No production indexing**, embeddings, or vector store writes were performed.

---

## Replay Context

The privacy review phase follows successful offline replay of the larger batch:

| Metric | Value |
|--------|------:|
| Replay scope | **166** tickets |
| `failed_replays` | **0** |
| `label_vs_department_mismatch_count` | **0** |
| `qa_attention_rate` | **≈ 30.7%** (51/166) |

Privacy review occurs **after** redaction, validation, and replay on **redacted** JSONL, and **before** corpus eligibility or pilot corpus build. Replay stability (zero failures, zero mismatches) confirms the operational harness is sound; privacy review addresses **residual data-handling risk** separately from routing correctness.

Full replay metrics: [166-ticket larger replay execution report](larger_replay_166_ticket_execution_report.md).

---

## Warning Summary

### Pre-redaction baseline (historical)

Initial validation on **normalized** JSONL (before redact-first policy) reported:

| Warning type | Count |
|--------------|------:|
| `card_like_long_digits` | 14 |
| `iban_like` | 7 |
| `phone_like` | 7 |

### Residual warnings (official gate)

After `redact_ticket_export.py`, re-run `validate_ticket_export.py` and `build_privacy_review_report.py` on **`*.redacted.jsonl`**. Counts should be **lower**; any remaining warnings are **residual risk** and still require human triage.

**Interpretation:** Pattern-match warnings are **observation signals**, not confirmed leaks. Redaction **reduces** volume but **does not replace** human review or reviewer sign-off. Redaction **does not** equal corpus approval.

Per governance rule (`app/privacy_review/`):

- Any warning on a ticket → `requires_manual_review=True`
- Any warning on a ticket → `corpus_eligible=False` until manually cleared

---

## Governance Interpretation

| Principle | Application |
|-----------|-------------|
| Warning-bearing records | Require **manual review**; not auto-approved for corpus |
| Warning-free records | May proceed to **future** corpus consideration after operator sign-off |
| No automatic approval | Privacy review does not promote tickets to corpus |
| No automatic rejection/removal | Redaction masks patterns; humans still approve corpus scope |
| Redact-first | Privacy review targets **redacted** exports for **residual** warnings |
| Mandatory before retrieval/indexing | Privacy review is a **hard gate** before pilot corpus or vector work |

Operator review outcomes for this execution:

- Privacy review workflow **executed** against the 166-ticket batch (local artifacts).
- Aggregate warnings **documented** and triage **pending** for flagged `room_id`s (local privacy review report — not committed).
- **No** batch-wide corpus approval granted.

---

## Corpus Readiness Outcome

| Field | Current value |
|-------|----------------|
| Pilot corpus planning status | **`review_required`** |
| Pilot corpus build approved | **No** |
| `embedding_status` (planned manifest) | **`not_started`** |
| `indexing_status` (planned manifest) | **`not_started`** |

The 166-ticket batch is **not** approved for pilot corpus build. Planning metadata (`app/corpus_planning/`) should remain `review_required` until privacy triage, anonymization verification, and explicit operator sign-off are complete.

**Potential future paths** (require separate approval steps):

1. **Reviewed clean subset** — 10–25 tickets with no unresolved warnings and documented sign-off ([pilot corpus planning](pilot_corpus_planning.md) Phase 1).
2. **Stronger anonymization / export sanitation** — re-export or re-normalize before any git-safe derivatives.
3. **Additional replay batches** — true 300–500 ticket sample for statistical confidence before corpus investment.

---

## Operational Learnings

- Official pipeline: normalize → **redact** → validate → replay → **residual** privacy review → sign-off → corpus builder.
- Privacy review is **integrated before** retrieval/corpus planning; premature corpus creation was prevented.
- Routing calibration remained **stable** on the larger replay (mismatch **0**, failures **0**).
- Governance gates (`corpus_eligible=False` on warnings) blocked automatic progression to corpus build.
- Real operational exports **commonly** trigger suspicious numeric-pattern warnings; aggregate counts are expected, not exceptional.

---

## Risk Review

| Risk | Status / mitigation |
|------|------------------------|
| Privacy leakage | Warnings triaged locally; no raw text in git-safe docs |
| Incomplete anonymization | Manual verification required before corpus candidacy |
| Retrieval contamination | Separate namespace planned; no bootstrap corpus mix yet |
| Operator trust erosion | No auto-send / auto-approve; explicit sign-off required |
| Governance drift | Documented status `review_required`; manifest fields planned |

---

## Decision

The **166-ticket replay batch is NOT approved** for pilot corpus build at this time.

Additional **manual review** and/or **anonymization verification** is required before any corpus implementation step. No embeddings, pgvector indexing, retrieval pipelines, or `corpus/vendor_ticket_real_pilot/` directories are authorized by this report.

---

## Governance (this step)

| Item | Status |
|------|--------|
| Corpus directories created | **No** |
| Embeddings generated | **No** |
| pgvector indexing | **No** |
| Retrieval execution | **No** |
| Production moderation system | **No** |
| Scope | Documentation / governance conclusions only |

---

## Redact-first command sequence (166-ticket)

```bash
PYTHONPATH=. python3.11 scripts/normalize_ticket_export.py \
  data/private/vendor_tickets_400.json \
  --output data/private/vendor_tickets_400.normalized.jsonl \
  --skip-empty-messages

PYTHONPATH=. python3.11 scripts/redact_ticket_export.py \
  data/private/vendor_tickets_400.normalized.jsonl \
  --output data/private/vendor_tickets_400.redacted.jsonl \
  --overwrite

PYTHONPATH=. python3.11 scripts/validate_ticket_export.py \
  data/private/vendor_tickets_400.redacted.jsonl

PYTHONPATH=. python3.11 scripts/replay_ticket_export.py \
  data/private/vendor_tickets_400.redacted.jsonl \
  --output reports/vendor_tickets_400_redacted_replay.jsonl

PYTHONPATH=. python3.11 scripts/build_privacy_review_report.py \
  reports/vendor_tickets_400_redacted_replay.jsonl \
  --export-path data/private/vendor_tickets_400.redacted.jsonl \
  --output reports/privacy_review_166_redacted.md \
  --json-output reports/privacy_review_166_redacted.json
```

- Module: `app/privacy_review/redaction.py`
- **No** embeddings, pgvector indexing, or corpus build in this step

---

## Recommended Next Steps

1. Run the **redact-first** sequence above; triage **residual** warnings from `privacy_review_166_redacted` output.
2. **Verify** whether warnings reflect true sensitive values or acceptable anonymized placeholders.
3. **Define reviewer sign-off checklist** (roles, dates, exclusion log — aggregate-safe).
4. **Select a tiny reviewed subset** (10–25 tickets) from cleared records only.
5. **Only then** consider a controlled pilot corpus builder — separate implementation step; not authorized here.
