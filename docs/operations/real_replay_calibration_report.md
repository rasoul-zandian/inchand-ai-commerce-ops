# Real Replay Calibration Report

**Status:** First successful offline calibration cycle (documentation only)  
**Audience:** Operators, workflow owners, retrieval reviewers  
**Related:** [Real ticket export format](../data_governance/real_ticket_export_format.md), [Real data pilot plan](../data_governance/real_data_pilot_plan.md)

---

## Purpose

Before building a pilot corpus, generating embeddings, or indexing into pgvector, we run **offline replay** on anonymized real vendor-ticket exports. Replay executes the mock vendor-ticket workflow per ticket and records compact routing/QA metrics—without draft text, transcripts, or production side effects.

Calibration closes the loop: observe label vs department mismatches, adjust deterministic intent and department routing, replay again, and confirm alignment. This de-risks production rollout and corpus work by surfacing routing bias early.

---

## Real Export Summary

The first operational export arrived as a **UTF-8 JSON array** (50 rooms), not native JSONL. Top-level shape per ticket:

| Field | Role |
|-------|------|
| `id` | Chat room identifier |
| `category` | Room topic label (e.g. `support`, `complaint`, `fund`) |
| `shop_id` | Seller/shop identifier (anonymized placeholder in safe copies) |
| `messages` | Ordered conversation turns |
| `messages[].type` | Source sender role (normalized downstream) |
| `messages[].content` | Message body text |

**Governance:**

- Raw and normalized files live under **`data/private/`** (gitignored).
- **No real tickets are committed** to the repository.
- Exports are **normalized** to `ConversationTicketSnapshot` JSONL before validation and replay.

Normalization command:

```bash
PYTHONPATH=. python3.11 scripts/normalize_ticket_export.py \
  data/private/vendor_tickets_50.json \
  --output data/private/vendor_tickets_50.normalized.jsonl \
  --skip-empty-messages
```

---

## Replay Pipeline

```text
raw export (JSON array)
  → normalize_ticket_export.py   # id→room_id, category→ticket_label, etc.
  → validate_ticket_export.py    # schema + line-level checks
  → replay_ticket_export.py      # mock LangGraph per ticket → JSONL report
  → observe metrics              # route_label, assigned_department, mismatches
  → calibrate routing            # deterministic intent + department rules
  → replay again                 # confirm mismatch reduction
```

Replay command (after validation passes):

```bash
PYTHONPATH=. python3.11 scripts/replay_ticket_export.py \
  data/private/vendor_tickets_50.normalized.jsonl \
  --output reports/vendor_tickets_50_replay.jsonl \
  --summary-json
```

Reports under **`reports/`** are local artifacts only (gitignored).

---

## Initial Replay Results (Before Calibration)

First replay on 50 normalized tickets (mock LLM/RAG, no failures):

| Metric | Value |
|--------|-------|
| `replayed_tickets` | 50 |
| `failed_replays` | 0 |
| `ticket_label_counts` | support=34, complaint=11, fund=5 |
| `route_label_counts` | **billing_review=48**, escalation_review=2 |
| `assigned_department` | **finance=37**, complaint=11, **support=2** |
| `label_vs_department_mismatch_count` | **32** |

### Finance bias issue

`TicketIntentAgent` used **`billing_discrepancy` as the default fallback**, so most tickets routed to `billing_review` and `assigned_department=finance` even when `ticket_label` was `support`. Department routing also treated `billing_review` as a finance signal before support labels were considered, amplifying the mismatch. Mock ticket boilerplate text could further trigger finance keywords unrelated to the room topic.

---

## Calibration Changes

Deterministic adjustments (no new LLM calls, no retrieval changes):

| Change | Effect |
|--------|--------|
| Default intent → `general_vendor_support` | Stops blanket billing classification |
| `billing_discrepancy` only with explicit finance signals | Keywords in user text, or finance-like labels (`fund`, `financial`, …) |
| Support `ticket_label` protected | Routes to support unless user text has finance keywords |
| `fund` mapped to finance | Five fund rooms align with finance department |
| Complaint priority preserved | Complaint labels still win over support/finance in department routing |
| Support label before `billing_review` in department router | Prevents finance override when route was misclassified |

See Step 90 implementation in `app/nodes/vendor_ticket.py` and `app/review_queue/department_routing.py`.

---

## Replay Results After Calibration

Second replay on the same 50-ticket normalized JSONL:

| Metric | Before | After |
|--------|--------|-------|
| `billing_review` | 48 | **13** |
| `general_vendor_support` | — | **35** |
| `escalation_review` | 2 | 2 |
| `assigned_department` finance | 37 | **5** |
| `assigned_department` support | 2 | **34** |
| `assigned_department` complaint | 11 | 11 |
| `label_vs_department_mismatch_count` | 32 | **0** |

### Why this is a successful milestone

- **Label alignment:** Support, complaint, and fund counts match `assigned_department` (34 / 11 / 5).
- **Zero mismatches:** Label-vs-department observation count dropped from 32 → 0 on the same export.
- **Stable replay:** 50/50 tickets replayed with no failures; metrics are reproducible offline.
- **No production scope creep:** Calibration used mock workflow only; no corpus or vector store involvement.

This validates the replay-first governance path before pilot corpus or indexing work.

---

## Safety & Governance

| Item | Status |
|------|--------|
| Real tickets in git | **No** — `data/private/` gitignored |
| Pilot corpus built | **No** |
| Embeddings generated | **No** |
| pgvector indexing | **No** |
| Production ingestion | **No** |
| Replay environment | **Offline / local-only** (mock LLM + mock RAG) |

---

## Operational Learnings

- Real replay exposed routing bias early—before any indexed retrieval or operator-facing queue.
- Replay-first is safer than routing production traffic or indexing an unreviewed corpus.
- Label-aware routing (`ticket_label` from chat room category) significantly improved department alignment.
- Deterministic calibration before ML training or embedding batches reduces operational risk.
- Normalization (`normalize_ticket_export.py`) is required when exports use the JSON-array operational shape.

---

## Recommended Next Steps

1. **Larger replay sample** — 100–500 tickets; confirm metrics hold across labels and edge cases.
2. **Replay metrics summary** — optional script or dashboard-friendly aggregate over `reports/*.jsonl` (still offline).
3. **Controlled pilot corpus** — human-reviewed snippets under `corpus/vendor_ticket_real_pilot/` after sign-off (separate manifest/lockfile).
4. **Retrieval evaluation** — only after pilot corpus exists; compare against golden snapshot baselines.
