# Redacted Replay Execution Report — 166-Ticket Batch

**Status:** Sanitized aggregate report (metrics only)  
**Principle:** Redact first, review residual risk  
**Baseline (unredacted):** [166-ticket larger replay execution report](larger_replay_166_ticket_execution_report.md)  
**Privacy (pre-redaction):** [Privacy review execution report — 166-ticket batch](privacy_review_166_ticket_execution_report.md)

---

## Purpose

This report documents the **executed redact-first pipeline** on the calibrated **166-ticket** batch: automatic PII redaction, validation of redacted JSONL, offline replay, and privacy review of **residual** warnings.

It validates that redaction reduces privacy-pattern signals while preserving operational replay behavior, **before** reviewer sign-off or pilot corpus build.

This step is **reporting and validation only** — no corpus creation, embeddings, pgvector indexing, or retrieval activation.

---

## Source Safety

| Artifact | In git? | Notes |
|----------|---------|--------|
| Raw JSON export | **No** | Local/private only |
| Normalized JSONL | **No** | Intermediate; not used for replay/privacy gate after redaction |
| Redacted JSONL | **No** | Local/private only |
| Replay / dashboard / privacy reports | **No** | `reports/` gitignored |

- **No raw ticket text** or **redacted transcripts** appear in this document.
- All figures are **aggregate counts and rates** only.
- Local artifacts: `data/private/vendor_tickets_400.*`, `reports/vendor_tickets_400_redacted_*`, `reports/privacy_review_166_redacted.*`

---

## Pipeline

Official redact-first sequence executed locally:

```text
normalize (--skip-empty-messages)
  → redact_ticket_export.py
  → validate_ticket_export.py (redacted JSONL)
  → replay_ticket_export.py (redacted JSONL)
  → build_replay_metrics_dashboard.py
  → build_privacy_review_report.py (residual warnings)
  → [pending] reviewer sign-off → approved subset → build_pilot_corpus.py
```

---

## Redaction Summary

Command: `scripts/redact_ticket_export.py` on `vendor_tickets_400.normalized.jsonl` → `vendor_tickets_400.redacted.jsonl`

| Metric | Value |
|--------|------:|
| `input_records` | 166 |
| `output_records` | 166 |
| `invalid_records` | 0 |
| `records_changed` | 28 |

**Redaction replacements by type** (pattern matches masked; not per-ticket):

| Type | Count |
|------|------:|
| `card_number` | 33 |
| `iban` | 17 |
| `phone_number` | 35 |
| `email` | 0 |

28 of 166 tickets had at least one message text change. Placeholders (`[CARD_NUMBER]`, `[IBAN]`, `[PHONE_NUMBER]`) replace matched patterns only; source normalized file was not modified.

---

## Validation After Redaction

Command: `scripts/validate_ticket_export.py` on redacted JSONL

| Metric | Value |
|--------|------:|
| `valid_tickets` | 166 |
| `invalid_lines` | 0 |

**Residual suspicious-pattern warnings:**

| Warning type | Count |
|--------------|------:|
| `card_like_long_digits` | **0** |
| `iban_like` | **0** |
| `phone_like` | **0** |

**Interpretation:** After redaction, the validator reported **no** residual pattern warnings. Any future privacy triage should use **redacted** exports; pre-redaction counts (14 / 7 / 7) are superseded for gating purposes. Human review and reviewer sign-off remain required before corpus work.

---

## Replay After Redaction

Command: `scripts/replay_ticket_export.py` on redacted JSONL (mock LLM/RAG)

| Metric | Value |
|--------|------:|
| `replayed_tickets` | 166 |
| `failed_replays` | 0 |
| `label_vs_department_mismatch_count` | 0 |
| `qa_attention_count` | 51 |
| `qa_attention_rate` | **30.7%** |

### Route labels

| Route | Count |
|-------|------:|
| general_vendor_support | 109 |
| billing_review | 51 |
| escalation_review | 6 |

### Assigned departments

| Department | Count |
|------------|------:|
| support | 109 |
| finance | 20 |
| complaint | 37 |

### Review priorities

| Priority | Count |
|----------|------:|
| LOW | 160 |
| MEDIUM | 6 |

Replay behavior matches the [unredacted 166-ticket replay](larger_replay_166_ticket_execution_report.md): routing calibration remained stable (zero failures, zero mismatches, identical QA attention rate).

---

## Comparison With Unredacted Replay

| Metric | Before redaction | After redaction | Interpretation |
|--------|-----------------:|----------------:|----------------|
| `failed_replays` | 0 | 0 | Replay harness stable |
| `label_vs_department_mismatch_count` | 0 | 0 | Routing unchanged |
| `qa_attention_count` | 51 | 51 | QA signals unchanged |
| `qa_attention_rate` | 30.7% | 30.7% | No operational drift |
| `card_like_long_digits` (validation warnings) | 14 | **0** | Redaction cleared card-like patterns |
| `iban_like` | 7 | **0** | Redaction cleared IBAN-like patterns |
| `phone_like` | 7 | **0** | Redaction cleared phone-like patterns |
| support / complaint / finance dept | 109 / 37 / 20 | 109 / 37 / 20 | Department mix unchanged |

**Summary:** Redaction **reduced privacy-pattern warnings to zero** on this batch while **preserving** replay routing and QA metrics. Redaction placeholders in message text did not alter department assignment or route labels.

---

## Privacy Governance Outcome

Privacy review on redacted export + redacted replay report:

| Metric | Value |
|--------|------:|
| `total_tickets_reviewed` | 166 |
| `tickets_with_warnings` | **0** |
| `manual_review_required_count` | 0 |
| `corpus_blocked_count` (warning-driven) | 0 |
| `corpus_eligible_count` (pattern gate) | 166 |

**Governance notes:**

- Redaction **reduces risk** but **does not equal** corpus approval.
- `corpus_eligible_count` in tooling means **no residual pattern warnings** — not automatic pilot corpus authorization.
- **Reviewer sign-off** ([reviewer sign-off workflow](reviewer_signoff_workflow.md)) is still **mandatory** before `build_pilot_corpus.py`.
- Pilot corpus remains **blocked** until explicit human approval.

---

## Decision

**Status: ready for reviewer sign-off** (not auto-approved for corpus build).

- **Residual privacy warnings:** none detected on redacted JSONL after this run.
- **Corpus build:** still **not authorized** until `ReviewerSignoffRecord` with `decision=approved` and a manual **10–25** `room_id` approved list.
- **Embeddings / pgvector:** remain **not started**.

---

## Governance (this step)

| Item | Status |
|------|--------|
| Corpus directories created | **No** |
| Embeddings generated | **No** |
| pgvector indexing | **No** |
| Retrieval activation | **No** |
| Auto-approval | **No** |
| Scope | Local execution + sanitized aggregate documentation |

---

## Recommended Next Steps

1. **Create reviewer sign-off** — `scripts/create_reviewer_signoff.py` → `data/private/reviewer_signoff_replay_166_redacted.json` ([workflow](reviewer_signoff_workflow.md)).
2. **Select 10–25 approved `room_id`s** — `scripts/select_approved_room_ids.py` → `data/private/approved_room_ids.txt`; human confirms list.
3. **Validate approved IDs** — `scripts/validate_approved_room_ids.py` against `vendor_tickets_400.redacted.jsonl`.
4. **Run controlled pilot corpus builder** (separate step) — `build_pilot_corpus.py` with **redacted** JSONL only after steps 1–3.
5. **Later** — embedding generation and pgvector evaluation only with explicit governance approval.
