# 50-Ticket Real Replay Baseline

**Status:** Sanitized operational snapshot (metrics only)  
**Related:** [Real replay calibration report](real_replay_calibration_report.md), [Real ticket export format](../data_governance/real_ticket_export_format.md)

---

## Purpose

This document records the **first calibrated baseline** after the full offline pipeline on a real anonymized 50-ticket export:

1. Real export normalization (`--skip-empty-messages`)
2. JSONL validation
3. Mock workflow replay
4. Static metrics dashboard
5. Routing calibration (Step 90) verified on re-replay

It is a **sanitized snapshot** for operators and reviewers—aggregate counts only, no ticket bodies or room-level message content.

---

## Source Safety

| Artifact | In git? | Notes |
|----------|---------|--------|
| Raw JSON export (`data/private/*.json`) | **No** | Local/private only |
| Normalized JSONL (`data/private/*.normalized.jsonl`) | **No** | Local/private only |
| Replay report JSONL (`reports/*_replay.jsonl`) | **No** | `reports/` gitignored |
| Dashboard Markdown/JSON (`reports/*_dashboard.*`) | **No** | `reports/` gitignored |

- **No raw ticket text** is committed in this repository.
- **No transcripts**, draft responses, final responses, or retrieval payloads appear in this document.
- Metrics below are **aggregate distributions** suitable for documentation.

---

## Pipeline

```text
raw JSON export (50 rooms, JSON array)
  → normalize_ticket_export.py --skip-empty-messages
  → validate_ticket_export.py
  → replay_ticket_export.py (mock LLM/RAG)
  → build_replay_metrics_dashboard.py
  → this sanitized baseline snapshot
```

Commands (local paths illustrative):

```bash
PYTHONPATH=. python3.11 scripts/normalize_ticket_export.py \
  data/private/vendor_tickets_50.json \
  --output data/private/vendor_tickets_50.normalized.jsonl \
  --skip-empty-messages

PYTHONPATH=. python3.11 scripts/validate_ticket_export.py \
  data/private/vendor_tickets_50.normalized.jsonl

PYTHONPATH=. python3.11 scripts/replay_ticket_export.py \
  data/private/vendor_tickets_50.normalized.jsonl \
  --output reports/vendor_tickets_50_replay.jsonl \
  --summary-json

PYTHONPATH=. python3.11 scripts/build_replay_metrics_dashboard.py \
  reports/vendor_tickets_50_replay.jsonl \
  --output reports/vendor_tickets_50_dashboard.md \
  --json-output reports/vendor_tickets_50_dashboard.json
```

---

## Normalization Summary

| Metric | Value |
|--------|------:|
| `input_records` | 50 |
| `normalized_records` | 50 |
| `invalid_records` | 0 |
| `skipped_empty_messages` | 6 |

**Category counts** (mapped to `ticket_label`):

| Label | Count |
|-------|------:|
| support | 34 |
| complaint | 11 |
| fund | 5 |

Per-ticket message counts are available in the local normalization summary only (not duplicated here).

---

## Replay / Dashboard Summary

Calibrated replay on normalized JSONL (mock workflow, no failures):

| Metric | Value |
|--------|------:|
| `total_rows` | 50 |
| `workflow_success_count` | 50 |
| `failed_replays` | 0 |
| `human_approval_required_count` | 50 |
| `label_vs_department_mismatch_count` | **0** |
| `mismatch_rate` | 0% |
| `qa_attention_count` | **13** |
| `qa_attention_rate` | **26%** |
| `qa_passed_count` | 50 |
| `qa_failed_count` | 0 |
| `total_qa_issue_count` | 0 |
| `total_qa_warning_count` | 13 |

### Assigned departments

| Department | Count |
|------------|------:|
| support | 34 |
| complaint | 11 |
| finance | 5 |

### Review priorities

| Priority | Count |
|----------|------:|
| LOW | 48 |
| MEDIUM | 2 |
| HIGH | 0 |

### Route labels

| Route | Count |
|-------|------:|
| general_vendor_support | 35 |
| billing_review | 13 |
| escalation_review | 2 |

### Detected intents

| Intent | Count |
|--------|------:|
| general_vendor_support | 35 |
| billing_discrepancy | 13 |
| escalation_sla | 2 |

### Department × priority matrix

| Department | HIGH | MEDIUM | LOW |
|------------|-----:|-------:|----:|
| support | 0 | 2 | 32 |
| finance | 0 | 0 | 5 |
| complaint | 0 | 0 | 11 |

---

## Interpretation

- **Department routing is aligned** after calibration: support (34), complaint (11), and fund→finance (5) match label counts; **zero** label-vs-department mismatches.
- **Support / fund / complaint labels** map to the expected departments; billing routes (13) concentrate on finance-related tickets rather than the whole cohort.
- **QA attention rate (26%)** is plausible for pilot review—warnings without hard QA failures (`qa_failed_count=0`).
- **No workflow replay failures** on the 50-ticket sample (100% workflow success).
- This baseline supports proceeding to a **larger replay sample** before any pilot corpus work.

---

## Governance

| Item | Status |
|------|--------|
| Pilot corpus | **Not created** |
| Embeddings | **Not generated** |
| pgvector indexing | **Not performed** |
| Production ingestion | **Not performed** |
| Auto-send / auto-approve | **Not enabled** |

Use this snapshot for **operational observation and metric comparison only**.

---

## Comparison with larger replay

The [166-ticket larger replay execution report](larger_replay_166_ticket_execution_report.md) compared against this baseline:

| Signal | 50-ticket | 166-ticket |
|--------|----------:|-----------:|
| Mismatches | 0 | 0 |
| QA attention rate | 26.0% | 30.7% |
| Failed replays | 0 | 0 |

Routing calibration generalized; see the larger report for privacy-warning notes before corpus work.

## Next Step Recommendation

1. **Privacy review** — triage suspicious-pattern warnings from the 166-ticket validation summary.
2. **Optional larger export** — true 300–500 ticket replay per [Larger Replay Batch Plan](larger_replay_batch_plan.md).
3. **Pilot corpus builder** — only after operator sign-off (separate manifest/lockfile; still no raw exports in git).
