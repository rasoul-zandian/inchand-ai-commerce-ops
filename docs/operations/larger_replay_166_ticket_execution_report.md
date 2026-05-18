# 166-Ticket Larger Replay Execution Report

**Status:** Sanitized aggregate report (metrics only)  
**Baseline:** [50-ticket real replay baseline](real_replay_50_ticket_baseline.md)  
**Runbook:** [Larger replay batch plan](larger_replay_batch_plan.md)

---

## Purpose

This report documents the **first larger real-ticket replay** after the calibrated [50-ticket baseline](real_replay_50_ticket_baseline.md). It confirms that routing calibration and offline replay tooling generalize beyond the initial sample before any pilot corpus, embedding generation, pgvector indexing, or production integration.

**Naming note:** The source export file was named `vendor_tickets_400.json`, but the usable batch contained **166** normalized tickets. This report refers to the **166-ticket larger replay**, not a 400-ticket replay.

---

## Source Safety

| Artifact | In git? | Notes |
|----------|---------|--------|
| Raw JSON export (`data/private/vendor_tickets_400.json` or similar) | **No** | Local/private only |
| Normalized JSONL (`data/private/*.normalized.jsonl`) | **No** | Local/private only |
| Replay report JSONL (`reports/*_replay.jsonl`) | **No** | `reports/` gitignored |
| Dashboard Markdown/JSON (`reports/*_dashboard.*`) | **No** | `reports/` gitignored |

- **No raw ticket text** is committed in this repository.
- **No transcripts**, draft responses, final responses, or retrieval payloads are included below.
- All figures are **aggregate counts and rates** suitable for operational review.

---

## Pipeline

**Historical execution** (metrics below) used normalize → validate → replay on normalized JSONL.

**Official pipeline (redact first)** — use for all new runs and corpus prep:

```text
raw JSON export
  → normalize_ticket_export.py --skip-empty-messages
  → redact_ticket_export.py
  → validate_ticket_export.py (redacted JSONL)
  → replay_ticket_export.py (redacted JSONL)
  → build_replay_metrics_dashboard.py
  → build_privacy_review_report.py (residual warnings)
  → reviewer sign-off → approved subset → build_pilot_corpus.py (redacted JSONL)
```

Redaction reduces warning volume; **residual** warnings after redaction still require human review. Redaction does **not** equal corpus approval.

---

## Normalization Summary

| Metric | Value |
|--------|------:|
| `input_records` | 166 |
| `normalized_records` | 166 |
| `invalid_records` | 0 |
| `skipped_empty_messages` | 140 |

**Messages per ticket:** min=5, max=1154, avg=35.39

**Category counts** (mapped to `ticket_label`):

| Label | Count |
|-------|------:|
| support | 109 |
| complaint | 37 |
| fund | 20 |

**Sender type counts** (across all messages):

| Sender type | Count |
|-------------|------:|
| seller | 4208 |
| support_agent | 1667 |

Empty `messages[].content` rows are common in real exports; `--skip-empty-messages` removed **140** blank lines without failing tickets.

---

## Validation Summary

| Metric | Value |
|--------|------:|
| `valid_tickets` | 166 |
| `invalid_lines` | 0 |

**Suspicious-pattern warnings** (counts only—not validation failures):

| Warning type | Count |
|--------------|------:|
| card_like_long_digits | 14 |
| iban_like | 7 |
| phone_like | 7 |

These warnings indicate that **privacy and anonymization review** is required before any corpus indexing or git-safe derivative work. They do not block offline replay but must be triaged with the technical/data team.

---

## Replay Summary

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
| complaint | 37 |
| finance | 20 |

Label counts match assigned departments exactly (support 109, complaint 37, fund→finance 20).

### Review priorities

| Priority | Count |
|----------|------:|
| LOW | 160 |
| MEDIUM | 6 |
| HIGH | 0 |

---

## Comparison with 50-Ticket Baseline

| Metric | 50-ticket baseline | 166-ticket replay | Interpretation |
|--------|-------------------:|------------------:|----------------|
| `failed_replays` | 0 | 0 | Replay remained stable at larger volume |
| `label_vs_department_mismatch_count` | 0 | 0 | Routing calibration held; no label/department drift |
| `qa_attention_rate` | 26.0% (13/50) | 30.7% (51/166) | Slight increase; still explainable (warnings, not hard QA failures) |
| Support department | 34 | 109 | Scales with support-labeled tickets (34→109 labels) |
| Complaint department | 11 | 37 | Scales with complaint labels (11→37) |
| Finance department | 5 | 20 | Scales with fund labels (5→20) |
| `billing_review` routes | 13 | 51 | Proportional to finance/fund tickets, not support-wide bleed |
| `general_vendor_support` routes | 35 | 109 | Aligns with support label count |
| Review priority LOW | 48 | 160 | Dominant priority unchanged |
| Review priority MEDIUM | 2 | 6 | Small escalation/edge slice |
| `skipped_empty_messages` (normalize) | 6 | 140 | Real exports contain many empty content rows; skip flag is essential |

**Summary interpretation:**

- **Routing remains stable** — zero mismatches on 166 tickets after Step 90 calibration.
- **Department distribution tracks labels** — support / complaint / fund counts align with assigned departments.
- **QA attention increased slightly** (26.0% → 30.7%) but remains plausible for operator review; investigate warning drivers, do not loosen gates blindly.
- **No replay failures** — 100% workflow success on the larger batch.

---

## Operational Learnings

- Calibrated intent and department routing **generalized** beyond the 50-ticket sample.
- Support, fund, and complaint labels continued to map to support, finance, and complaint departments respectively.
- **Replay failure rate remained zero** at 166 tickets (mock workflow).
- **Empty messages are common** in real exports; `--skip-empty-messages` is required for practical normalization.
- **Suspicious token warnings** (card/IBAN/phone-like patterns) show that anonymization review must precede corpus work—even when schema validation passes.
- Long-tailed conversation length (max 1154 messages in one room) did not break replay; per-ticket aggregates only in reports.

---

## Decision

The larger replay **supports** moving toward pilot corpus planning **only after**:

1. **Privacy warning review** — triage card/IBAN/phone-like warnings with technical/data owners.
2. **Optional true 300–500 ticket export** — if stakeholders want more statistical confidence before corpus investment.
3. **Operator / business sign-off** — explicit approval of routing alignment and QA attention rates (~31%).

Do **not** create pilot corpus, generate embeddings, or index pgvector until the above are satisfied.

---

## Governance

| Item | Status |
|------|--------|
| Real ticket data in git | **No** |
| Embeddings generated | **No** |
| pgvector indexing | **No** |
| Pilot corpus created | **No** |
| Production ingestion | **No** |
| Auto-send / auto-approve | **No** |
| Scope | Offline/local observation only |

---

## Privacy Warning Review Workflow (redact-first)

Run privacy review on **redacted** exports for **residual** warnings only:

```bash
PYTHONPATH=. python3.11 scripts/redact_ticket_export.py \
  data/private/vendor_tickets_400.normalized.jsonl \
  --output data/private/vendor_tickets_400.redacted.jsonl \
  --overwrite

PYTHONPATH=. python3.11 scripts/build_privacy_review_report.py \
  reports/vendor_tickets_400_redacted_replay.jsonl \
  --export-path data/private/vendor_tickets_400.redacted.jsonl \
  --output reports/privacy_review_166_redacted.md \
  --json-output reports/privacy_review_166_redacted.json
```

- Do **not** build corpus from unredacted `*.normalized.jsonl`.
- Contracts: `app/privacy_review/models.py`, `app/privacy_review/redaction.py`, `app/privacy_review/review_builders.py`
- Residual warnings still require human triage; reviewer sign-off remains mandatory

---

## Pilot Corpus Planning

Governance-first planning for a future real-ticket pilot corpus (no build/indexing in this phase):

- [`pilot_corpus_planning.md`](pilot_corpus_planning.md) — preconditions, eligibility, manifest fields, phased rollout
- Planning contracts: `app/corpus_planning/models.py`, `app/corpus_planning/builders.py`

Pilot corpus creation requires privacy review completion, replay stability, and operator sign-off. `embedding_status` / `indexing_status` remain **`not_started`** until a separate approved implementation step.

---

## Recommended Next Steps

1. **Redact** normalized export, then **review residual warnings** with the data team using `build_privacy_review_report.py` on redacted JSONL.
2. **Follow pilot corpus planning** — [`pilot_corpus_planning.md`](pilot_corpus_planning.md); define reviewer sign-off and select a tiny reviewed subset (10–25 tickets).
3. **Decide sample size** — request a true 300–500 ticket export for another replay comparison, or proceed with the 166-ticket evidence after sign-off.
4. **Later** — implement corpus builder only after planning gates; compare pilot retrieval quality against operational replay baselines.
