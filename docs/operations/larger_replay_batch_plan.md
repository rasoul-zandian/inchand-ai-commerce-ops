# Larger Replay Batch Plan

**Status:** Planning / runbook (no execution required in CI)  
**Baseline reference:** [50-ticket real replay baseline](real_replay_50_ticket_baseline.md)  
**Related:** [Real replay calibration report](real_replay_calibration_report.md)

---

## Purpose

The calibrated **50-ticket** sample proved that normalization, replay, and department routing can align on real anonymized exports (`mismatch_count=0`, stable QA attention). Before building a **pilot corpus**, indexing embeddings, or touching pgvector, we run a **larger offline replay batch**—typically **100–500** closed vendor tickets—to confirm metrics scale and remain explainable.

This step validates operational behavior at modest volume **without** production ingestion, auto-send, or retrieval changes.

---

## Scope

### In scope (offline / local only)

| Step | Tool |
|------|------|
| Normalize | `scripts/normalize_ticket_export.py` |
| Redact | `scripts/redact_ticket_export.py` (**before** validate / privacy review) |
| Validate | `scripts/validate_ticket_export.py` (on **redacted** JSONL) |
| Replay | `scripts/replay_ticket_export.py` (mock LLM/RAG; **redacted** input) |
| Privacy review | `scripts/build_privacy_review_report.py` (**residual** warnings) |
| Dashboard | `scripts/build_replay_metrics_dashboard.py` |
| Compare | Manual or spreadsheet diff vs [50-ticket baseline](real_replay_50_ticket_baseline.md) |

### Explicitly out of scope

- Pilot corpus creation (`corpus/vendor_ticket_real_pilot/`)
- Embedding generation or OpenAI calls
- pgvector indexing or retrieval stack changes
- Production ingestion, queues, or operator UI
- Auto-send / auto-approve
- Committing `data/private/` or `reports/` artifacts

---

## Input requirements

| Requirement | Detail |
|-------------|--------|
| Volume | **100–500** anonymized closed vendor tickets (recommend starting at **100** if export quality is uncertain) |
| Format | Same operational JSON array as the first export when possible |
| Fields | `id`, `category`, `shop_id`, `messages[].type`, `messages[].content` |
| Anonymization | No raw PII, secrets, payment identifiers, or production credentials |
| Storage | `data/private/` only (gitignored) |
| Labels | Expect mix similar to baseline: `support`, `complaint`, `fund` (or equivalent categories) |

Review [real ticket export format](../data_governance/real_ticket_export_format.md) before requesting exports.

---

## Commands

Replace `500` with your batch size (e.g. `100`, `250`). All paths stay under `data/private/` and `reports/`.

### Normalize

```bash
PYTHONPATH=. python3.11 scripts/normalize_ticket_export.py \
  data/private/vendor_tickets_500.json \
  --output data/private/vendor_tickets_500.normalized.jsonl \
  --skip-empty-messages
```

Review summary: `input_records`, `invalid_records`, `skipped_empty_messages`, `category_counts`. Exit code **0** only if all records normalize.

### Redact (required before validate / privacy review)

```bash
PYTHONPATH=. python3.11 scripts/redact_ticket_export.py \
  data/private/vendor_tickets_500.normalized.jsonl \
  --output data/private/vendor_tickets_500.redacted.jsonl \
  --overwrite
```

Redaction reduces privacy-warning volume. Warnings on the **redacted** file are **residual risk** and still require human review. Redaction does **not** approve corpus build.

### Validate redacted

```bash
PYTHONPATH=. python3.11 scripts/validate_ticket_export.py \
  data/private/vendor_tickets_500.redacted.jsonl
```

Exit code **0** = all JSONL lines pass `ConversationTicketSnapshot` schema. Record `suspicious_pattern_warnings` as **residual** counts.

### Replay redacted

```bash
PYTHONPATH=. python3.11 scripts/replay_ticket_export.py \
  data/private/vendor_tickets_500.redacted.jsonl \
  --output reports/vendor_tickets_500_redacted_replay.jsonl \
  --summary-json
```

Uses mock LLM/RAG only (no OpenAI, no Postgres).

### Dashboard (redacted replay)

```bash
PYTHONPATH=. python3.11 scripts/build_replay_metrics_dashboard.py \
  reports/vendor_tickets_500_redacted_replay.jsonl \
  --output reports/vendor_tickets_500_redacted_dashboard.md \
  --json-output reports/vendor_tickets_500_redacted_dashboard.json
```

### Privacy review (residual warnings)

```bash
PYTHONPATH=. python3.11 scripts/build_privacy_review_report.py \
  reports/vendor_tickets_500_redacted_replay.jsonl \
  --export-path data/private/vendor_tickets_500.redacted.jsonl \
  --output reports/privacy_review_500_redacted.md \
  --json-output reports/privacy_review_500_redacted.json
```

Keep Markdown/JSON under `reports/`; do not commit if derived from real private data.

---

## Metrics to compare with 50-ticket baseline

Record aggregates from dashboard JSON and replay summary. Compare against [50-ticket baseline](real_replay_50_ticket_baseline.md).

| Metric | 50-ticket baseline | Larger batch (fill in) |
|--------|-------------------:|------------------------|
| `total_rows` | 50 | |
| `failed_replays` | 0 | |
| `label_vs_department_mismatch_count` | 0 | |
| `mismatch_rate` | 0% | |
| `qa_attention_count` | 13 | |
| `qa_attention_rate` | 26% | |
| `skipped_empty_messages` (normalize) | 6 | |

**Distributions to compare:**

- `ticket_label_counts` (support / complaint / fund proportions)
- `assigned_department_counts` (should track labels)
- `route_label_counts` (watch for billing_review explosion)
- `review_priority_counts` (HIGH / MEDIUM / LOW)
- `department_priority_matrix`
- `detected_intent_counts` (optional)

**Optional (from normalize summary):**

- `unknown_source_type_counts` in normalizer output (sender mapping observation)
- `invalid_records` / `parse_errors` (must be zero before replay)

Proportions matter more than raw counts when batch size changes (e.g. mismatch **rate**, QA attention **rate**).

---

## Acceptance signals

Treat the larger batch as **passed** when:

- Normalization: `invalid_records = 0` (or documented, fixed export issues with re-run)
- Validation: exit code **0**
- Replay: `failed_replays = 0`
- Routing: `mismatch_rate` remains **near 0** (allow isolated edge cases only with documented room_id examples)
- QA: `qa_attention_rate` remains **explainable** (not an unexplained spike vs baseline)
- Departments: `assigned_department_counts` align with `ticket_label_counts` (support / complaint / finance for fund)
- Routes: no unexpected explosion of `billing_review` on support-labeled tickets
- Safety: replay report and dashboard contain **no** raw message text, drafts, or secrets

---

## Decision tree

```text
Normalization / validation failed?
  → Fix export or normalizer carefully; do not replay until clean.

failed_replays > 0?
  → Inspect replay errors (line numbers only); fix workflow bugs; re-run.

mismatch_rate rises materially?
  → Inspect label/routing calibration; do NOT build corpus yet.

qa_attention_rate spikes without clear cause?
  → Inspect QA rules / warning noise; do NOT loosen gates blindly.

All acceptance signals pass?
  → Document larger replay snapshot (Step 95 — execution report).
  → Consider pilot corpus builder only after operator sign-off.
```

---

## Governance

| Rule | Detail |
|------|--------|
| `data/private/` | Local only; never commit raw, normalized, or redacted exports |
| `reports/` | Local only; never commit replay/dashboard artifacts from real data |
| Git commits | Sanitized aggregate docs only (like the 50-ticket baseline) |
| Production | No workflow or routing code changes as part of this runbook |
| Corpus / RAG | No indexing until replay metrics are reviewed and approved |

---

## First larger replay completed

The first execution used a source file named `vendor_tickets_400.json` but yielded **166** usable tickets after normalization. Sanitized results and baseline comparison: [**166-ticket larger replay execution report**](larger_replay_166_ticket_execution_report.md) (`mismatch_count=0`, `failed_replays=0`, QA attention 51/166).

For a future true 300–500 ticket export, re-run this runbook and add a new sanitized report; do not commit `reports/` or `data/private/` artifacts.

A dedicated replay **comparison script** remains deferred.

## Recommended next step after execution

Document additional larger batches the same way as [Step 95 — 166-ticket execution report](larger_replay_166_ticket_execution_report.md) when new exports are available.
