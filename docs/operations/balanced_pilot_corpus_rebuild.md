# Balanced Pilot Corpus Rebuild (Step 121)

**Status:** Planning and operator guidance — **no automatic rebuild**  
**Audience:** Data operations, AI governance, retrieval evaluation

---

## Purpose

Rebuild the **small sandbox pilot corpus** (`vendor_ticket_real_pilot`) so offline retrieval evaluation covers **support**, **complaint**, and **fund/finance** categories. This step is **governance and tooling only** — it does not activate LangGraph retrieval, change production `RAG_PROFILE`, or commit private artifacts.

---

## Confirmed root cause (Step 120)

| Finding | Detail |
|---------|--------|
| Retrieval pipeline | **Functioning** after metadata-filter search-path fix |
| Sandbox pgvector inventory | `support=16`, `complaint=9`, **`fund=0`** |
| Metadata-filtered finance eval | Correctly returned **no results** — no fund rows in index |
| First corpus build | **support=16**, **complaint=9**, **fund=0** ([25 build report](pilot_corpus_25_build_report.md)) |

**Conclusion:** Fund failures are primarily a **corpus composition** gap, not a broken filter implementation. Rebuild the approved room list and downstream artifacts with a **balanced label mix** before claiming fund retrieval readiness.

---

## Target composition (~25 records)

Keep the pilot **small and governed**. Do not expand beyond sandbox scope.

| `ticket_label` | Target count | Notes |
|----------------|--------------|--------|
| `support` | **≈ 10** | General vendor support / account flows |
| `complaint` | **≈ 7** | Escalation and service-quality complaints |
| `fund` | **≈ 5–8** | Settlement, billing, payout, reconciliation |

**Default balanced selection (25 total):** support **10**, complaint **7**, fund **8**.

Adjust only with **human reviewer** approval (e.g. fund **6** if replay pool is thin — document shortfall in sign-off notes).

---

## Governance requirements (unchanged)

| Requirement | Status |
|-------------|--------|
| Redacted export only | `data/private/vendor_tickets_400.redacted.jsonl` |
| Replay report as selection input | Post-redaction replay JSONL |
| Reviewer sign-off | **Required** — `decision=approved`, full checklist |
| Human confirms `approved_room_ids.txt` | **Required** — selection is a **candidate** list |
| No automatic approval | AI/tools cannot bypass sign-off |
| Corpus local-only | [Repository policy](pilot_corpus_repository_policy.md) |
| Embeddings / pgvector | Separate governed steps; not implied by this doc |

**Principle:** Balanced selection **suggests** rooms; humans **approve** scope before `build_pilot_corpus.py`.

---

## Room selection — balanced helper

**Script:** `scripts/select_approved_room_ids.py`

**Default balanced pilot (~25 rooms):**

```bash
PYTHONPATH=. python3.11 scripts/select_approved_room_ids.py \
  reports/replay_166_redacted.jsonl \
  -o data/private/approved_room_ids.txt \
  --balance-pilot \
  --exclude-qa-attention \
  --overwrite
```

**Custom per-label quotas** (must sum to intended corpus size):

```bash
PYTHONPATH=. python3.11 scripts/select_approved_room_ids.py \
  reports/replay_166_redacted.jsonl \
  -o data/private/approved_room_ids.txt \
  --balance-label support=10 \
  --balance-label complaint=7 \
  --balance-label fund=6 \
  --exclude-qa-attention \
  --overwrite
```

**Behavior:**

- Scans replay rows in **file order**; first eligible `room_id` per label fills each quota.
- Output file ordering: **deterministic** — `complaint`, then `fund`, then `support` (alphabetical by label).
- Prints `label_support=10/10`, `label_fund=6/8`, etc.; **`label_shortfall`** on stderr if replay pool cannot fill a quota.
- Header reminds: *Human reviewer must confirm this list before build_pilot_corpus.py*.

**Validate** against redacted export before build:

```bash
PYTHONPATH=. python3.11 scripts/validate_approved_room_ids.py \
  data/private/vendor_tickets_400.redacted.jsonl \
  --approved-room-ids data/private/approved_room_ids.txt
```

---

## Local operator flow (end-to-end)

Run on a machine with **private data** already present. **Do not commit** `data/private/`, `corpus/vendor_ticket_real_pilot/`, `artifacts/embeddings/`, or `reports/`.

### 1. Prerequisites

- Redacted replay completed ([redacted replay report](redacted_replay_166_ticket_execution_report.md)).
- Privacy review and replay review complete.
- Reviewer sign-off record exists or will be updated for **new** `approved_record_count`.

### 2. Rebuild `approved_room_ids.txt`

Use `--balance-pilot` (or explicit `--balance-label` quotas). Manually review the file; edit if needed; confirm label mix in a spreadsheet or manifest preview (**no raw transcripts in tickets**).

### 3. Reviewer sign-off (if scope changed)

Update or create sign-off with new `approved_record_count` (e.g. 25) and checklist passes:

```bash
PYTHONPATH=. python3.11 scripts/create_reviewer_signoff.py \
  --output data/private/reviewer_signoff_replay_166_redacted_v2.json \
  --signoff-id signoff_replay_166_redacted_v2 \
  --source-batch-id replay_166_redacted_v1 \
  --approved-record-count 25 \
  --decision approved \
  --check no_raw_pii_visible \
  --check anonymization_verified \
  --check retrieval_safe \
  --check governance_approved \
  --check corpus_scope_validated \
  --overwrite
```

### 4. Rebuild pilot corpus

```bash
PYTHONPATH=. python3.11 scripts/build_pilot_corpus.py \
  data/private/vendor_tickets_400.redacted.jsonl \
  --approved-room-ids data/private/approved_room_ids.txt \
  --corpus-dir corpus/vendor_ticket_real_pilot \
  --source-batch-id replay_166_redacted_v1 \
  --reviewer-signoff-id signoff_replay_166_redacted_v2 \
  --overwrite
```

Verify integrity and **label counts** in manifest:

```bash
PYTHONPATH=. python3.11 scripts/check_pilot_corpus_integrity.py \
  corpus/vendor_ticket_real_pilot
```

**Gate:** `ticket_label_counts` must show **`fund` ≥ 5** before embeddings (target 5–8).

### 5. Regenerate embeddings

**Mock dry-run (optional sanity check):**

```bash
PYTHONPATH=. python3.11 scripts/build_pilot_corpus_embeddings.py \
  corpus/vendor_ticket_real_pilot \
  --output-dir artifacts/embeddings/vendor_ticket_real_pilot \
  --provider mock \
  --model mock-embedding-1536 \
  --dimensions 1536 \
  --overwrite
```

**Real OpenAI (local only):**

```bash
PYTHONPATH=. python3.11 scripts/build_pilot_corpus_embeddings.py \
  corpus/vendor_ticket_real_pilot \
  --output-dir artifacts/embeddings/vendor_ticket_real_pilot_openai \
  --provider openai \
  --model text-embedding-3-small \
  --dimensions 1536 \
  --confirm-real-openai \
  --overwrite
```

```bash
PYTHONPATH=. python3.11 scripts/check_embedding_artifact_integrity.py \
  artifacts/embeddings/vendor_ticket_real_pilot_openai
```

### 6. Re-index sandbox pgvector

Replace prior pilot rows for the same namespace/version or use a new `index_version` if you need side-by-side comparison.

```bash
PYTHONPATH=. python3.11 scripts/index_pilot_embeddings_pgvector.py \
  artifacts/embeddings/vendor_ticket_real_pilot_openai \
  --namespace vendor_ticket_real_pilot \
  --index-version pilot_v1 \
  --profile semantic_pgvector \
  --confirm-sandbox \
  --overwrite
```

**Inventory check (aggregate only):**

```bash
PYTHONPATH=. python3.11 scripts/inspect_pilot_pgvector_metadata.py \
  --namespace vendor_ticket_real_pilot \
  --index-version pilot_v1 \
  --profile semantic_pgvector \
  --output reports/pilot_pgvector_metadata_inventory_pilot_v1.json \
  --overwrite
```

**Gate:** `ticket_label_counts.fund` must be **> 0** and align with corpus manifest.

### 7. Re-run retrieval eval

```bash
PYTHONPATH=. python3.11 scripts/eval_pilot_retrieval.py \
  --cases evals/pilot_retrieval/vendor_ticket_real_pilot_cases.json \
  --namespace vendor_ticket_real_pilot \
  --index-version pilot_v1 \
  --profile semantic_pgvector \
  --compare-modes \
  --output reports/pilot_retrieval_eval_pilot_v1.json \
  --overwrite
```

Copy **aggregate metrics only** into [pilot retrieval evaluation report](pilot_retrieval_evaluation_report.md). Update [failure analysis](pilot_retrieval_failure_analysis.md) if fund cases still fail.

---

## Explicit non-goals (this step)

| Non-goal | Reason |
|----------|--------|
| LangGraph / production retrieval activation | Out of sandbox scope |
| `RAG_PROFILE` changes | Governance gate |
| Rerankers, hybrid search, HNSW tuning | Over-engineering |
| New embedding providers | Not required for balance |
| Committing private artifacts | Policy violation |
| Exposing raw ticket content | Safety |

---

## Step 123 — eval calibration (v4)

After balanced index exists, calibrate eval cases only (no re-index):

- Remove `metadata_filter.namespace` / `index_version` from cases — scope via CLI.
- Re-run compare-modes against `vendor_ticket_real_pilot_balanced` / `pilot_balanced_v1`.

See [failure analysis](pilot_retrieval_failure_analysis.md) Step 123.

---

## Step 122 execution (completed locally)

Sanitized outcomes are recorded in [pilot balanced rebuild execution report](pilot_balanced_rebuild_execution_report.md).

| Checkpoint | Result |
|------------|--------|
| Corpus `fund` count | **8** |
| pgvector `ticket_label_counts.fund` | **8** |
| Compare-mode (pre–Step 123) | **0.90** both modes |
| After Step 123 calibration | metadata_filtered **1.00** (10/10); vector_only **0.90** |
| Step 124 decision | **`retrieval_ready_for_sandbox_tooling_review`** |

**Fund selection note:** `--exclude-qa-attention` alone yields **fund=0/8**; merged list documents QA-flagged fund rows (all fund replay tickets QA-flagged).

---

## Success criteria (fund eval progress)

| Check | Target | Step 122–123 result |
|-------|--------|---------------------|
| Corpus `fund` count | **≥ 5** (ideally 5–8) | **8** |
| pgvector `ticket_label_counts.fund` | **> 0**, matches corpus | **8** |
| `metadata_filtered` fund compare subset | pass_rate **1.0**, wrong_label **0**, empty **0** | **10/10** |
| Eval aggregates | Gitignored JSON + ops docs | Recorded |

---

## Step 124 — retrieval eval decision

```text
recommended_decision = retrieval_ready_for_sandbox_tooling_review
```

**Metadata-filtered fund routing gate:** **passed** after balanced rebuild and eval calibration (v4).

**Vector-only:** pass_rate **0.90** with one documented co-label edge on small pilot (`pilot-fund-wallet-fa-016`) — does not block sandbox tooling review.

**Not approved by this decision:** LangGraph integration, production `RAG_PROFILE`, customer-facing retrieval, runtime `retrieval_activated=true`.

See [pilot retrieval evaluation report](pilot_retrieval_evaluation_report.md) and [failure analysis](pilot_retrieval_failure_analysis.md) Step 124.

---

## Related documentation

- [Pilot retrieval failure analysis](pilot_retrieval_failure_analysis.md) — Step 120 root cause
- [Pilot corpus 25 build report](pilot_corpus_25_build_report.md) — prior imbalanced build
- [Reviewer sign-off workflow](reviewer_signoff_workflow.md)
- [Pilot corpus repository policy](pilot_corpus_repository_policy.md)
- [PgVector sandbox indexing plan](pgvector_sandbox_indexing_plan.md)
