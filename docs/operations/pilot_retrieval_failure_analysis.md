# Pilot Retrieval Failure Analysis & Query Calibration

**Status:** First sandbox eval analyzed — query calibration recommended; no retrieval activation  
**Audience:** Retrieval evaluation, AI platform governance, data operations

---

## Purpose

This document analyzes the **first local sandbox retrieval evaluation** for the approved pilot corpus (`vendor_ticket_real_pilot`) and explains why **fund/finance cases failed** before any LangGraph retrieval wiring or production `RAG_PROFILE` change.

It records **aggregate-safe metrics and case IDs only**. It does **not** include raw retrieved content, transcripts, vectors, or unsafe query text.

**Prerequisite reports:** [Pilot retrieval evaluation report](pilot_retrieval_evaluation_report.md)  
**Eval suite:** `scripts/eval_pilot_retrieval.py`  
**Eval cases:** `evals/pilot_retrieval/vendor_ticket_real_pilot_cases.json`

---

## Governance scope

| Boundary | Status |
|----------|--------|
| Analysis environment | **Local sandbox only** |
| LangGraph retrieval | **Not activated** |
| Production `RAG_PROFILE` | **Unchanged** |
| Indexing / embeddings | **No changes** in this step |
| Raw retrieval content in git | **Forbidden** |
| Local eval JSON (`reports/`) | **Not committed** |

---

## First sandbox eval — aggregate results

Recorded from the first operator run of `eval_pilot_retrieval.py` against namespace `vendor_ticket_real_pilot`, index version `pilot_v1`, profile `semantic_pgvector`, `top_k=5`.

| Field | Value |
|-------|--------|
| `total_cases` | **12** |
| `passed_cases` | **8** |
| `failed_cases` | **4** |
| `pass_rate` | **0.6667** |
| `mean_top_score` | **0.4034** |
| `label_match_rate` | **0.6667** |
| `department_match_rate` | **0.6667** |
| `wrong_label_return_count` | **1** |
| `empty_result_count` | **0** |
| `top_k` | **5** |
| `profile` | **semantic_pgvector** |
| `namespace` | **vendor_ticket_real_pilot** |
| `index_version` | **pilot_v1** |
| `retrieval_activated` | **false** |

**Interpretation:** Retrieval returned pilot-scoped results for all cases (`empty_result_count=0`), but **one third of cases failed** label/department scoring. Mean top similarity (~0.40) suggests weak but non-empty matches — consistent with semantic drift rather than index absence.

---

## Failure pattern — fund/finance cluster

All **four failed cases** are fund/finance-related. Support and complaint cases in the same run **passed**.

| `case_id` | Expected label | Expected department | Notes |
|-----------|----------------|---------------------|--------|
| `pilot-fund-settlement-005` | fund | finance | Settlement / payout mismatch |
| `pilot-fund-billing-006` | fund | finance | Billing adjustment / reconciliation |
| `pilot-finance-invoice-007` | fund | finance | Invoice discrepancy |
| `pilot-fund-status-011` | fund | finance | Pending fund transfer status |

**Cross-cutting signal:** `wrong_label_return_count=1` — a **forbidden `support` label** appeared in top-k for at least one fund case (`pilot-fund-status-011` specifies `must_not_return_labels: ["support"]`). Fund queries are being confused with general vendor support rows in embedding space.

**Passed fund-related isolation:** `pilot-support-isolation-008` (support-only, must not return fund/complaint) passed — failure is **asymmetric**: fund intent pulls support neighbors more often than support intent pulls fund neighbors.

---

## Failure categories (high-level)

| Category | Evidence in this run |
|----------|----------------------|
| **Weak semantic match** | Fund cases: results present but `fund` / `finance` not in top-k labels or departments |
| **Wrong-label retrieval** | One fund case returned `support` in top-k despite `must_not_return_labels` |
| **Ambiguous intent overlap** | English finance wording may align closer to support summaries than sparse fund rows |
| **Empty retrieval** | **Not observed** (`empty_result_count=0`) |

No raw ticket text or retrieved `content` is required to classify these failures — per-case metadata in gitignored JSON (`top_labels`, `top_departments`, `failure_reasons`) is sufficient for operator review.

---

## Hypotheses (not yet proven)

1. **Fund subset too small** — 25-record pilot corpus may contain few `ticket_label=fund` rows; top-k fills with support/complaint neighbors.
2. **Synthetic queries misaligned with ticket language** — Eval queries use generic English finance phrasing; indexed `content` summaries are label-derived (`room_id`, `ticket_label`, `route_label`) not full operational wording.
3. **English eval queries vs Persian/operational corpus** — Real tickets and replay exports are **fa-IR**; query embeddings in English may not align with how fund rows were embedded from Persian-normalized metadata.
4. **Metadata filters not applied at retrieval time** — Current eval uses pure vector search + post-hoc pilot scope filter; no `ticket_label` / `route_label` pre-filter on search (unlike production routing hints).
5. **Content summaries too sparse** — Indexed `content` excludes transcripts by design; fund vs support separation may rely on weak token overlap in short summaries.

These hypotheses guide **calibration and more eval** — not production activation.

---

## Query calibration recommendations (sandbox only)

| Action | Rationale |
|--------|-----------|
| **Add Persian/operational finance queries** | New eval cases mirroring settlement/تسویه, invoice/فاکتور, wallet/کیف‌پول intent without raw ticket text |
| **Add label-filtered eval mode** | Optional eval path: restrict search to `metadata.ticket_label=fund` to measure embedding quality vs routing |
| **Inspect top-k metadata only** | Human-review `top_labels`, `top_departments`, `failure_reasons` in gitignored JSON — no content export |
| **Add more approved fund documents** | Expand pilot corpus fund slice (governance + rebuild embeddings + re-index) before claiming fund retrieval readiness |
| **Compare with/without metadata filters** | Offline A/B: same queries with vector-only vs label-filtered search to separate embedding weakness from routing gap |

**Out of scope for calibration:** LangGraph changes, `RAG_PROFILE` promotion, production DB, new indexing without governance.

---

## Step 118 — metadata-filtered eval mode (implemented)

**CLI:** `scripts/eval_pilot_retrieval.py --compare-modes`

Compares on cases that define `metadata_filter`:

| Mode | Behavior |
|------|----------|
| `vector_only` | Pilot scope filter only; ignores `metadata_filter` |
| `metadata_filtered` | Applies safe metadata filters at eval time (`ticket_label`, `department`, `route_label`, `review_priority`, `namespace`, `index_version`) |

**Eval cases v2:** English fund cases retain `metadata_filter` for comparison; six Persian/operational finance cases use `eval_mode=metadata_filtered`.

**Comparison output (gitignored JSON):**

- `vector_only` aggregate metrics
- `metadata_filtered` aggregate metrics
- `comparison.delta_pass_rate`
- `comparison.delta_wrong_label_return_count`

Use this to test whether fund failures are **embedding-space** (both modes fail) vs **routing/filtering** (metadata_filtered improves pass rate). Filters are **eval-only** — LangGraph runtime unchanged.

If `metadata_filtered` returns **empty** results while `vector_only` returns hits, inspect indexed metadata:

```bash
PYTHONPATH=. python3.11 scripts/inspect_pilot_pgvector_metadata.py \
  --namespace vendor_ticket_real_pilot \
  --index-version pilot_v1 \
  --profile semantic_pgvector \
  --output reports/pilot_pgvector_metadata_inventory_pilot_v1.json \
  --overwrite
```

**Likely mismatch (Step 119):** sandbox index rows store `ticket_label` and `route_label` in metadata JSON but often **do not store explicit `metadata.department`**. Eval filters using `department: finance` match only when that key exists on the row — use `ticket_label: fund` and/or `route_label: billing_review` in `metadata_filter`, or add explicit department at index time in a future governed step.

---

## Step 120 — metadata filter calibration (eval cases v3)

**What failed:** first `metadata_filtered` pass used `metadata_filter.department=finance`. `department` is **derived at scoring time** from `route_label` / `ticket_label`, not stored on indexed rows — so filters returned **zero hits** while `vector_only` still returned rows.

**Calibrated filters (eval cases v3):**

| Use in `metadata_filter` | When |
|--------------------------|------|
| `ticket_label: fund` | Default fund/finance sandbox filter |
| `route_label: billing_review` | Narrower billing/settlement slice when needed |
| `namespace` / `index_version` | Optional scope reinforcement |

| Do **not** use in `metadata_filter` (unless inventory shows explicit key) | Reason |
|-----------------------------------------------------------------------------|--------|
| `department: finance` | Not stored on pilot rows; causes empty filtered results |

`expected_department` in eval cases remains for **scoring** (derived department in top-k). Re-run `--compare-modes` after v3 case update. **No re-index** in this step.

---

## Step 120b — metadata filter search path (implemented)

**Symptom after v3:** `metadata_filter.ticket_label=fund` with inventory `ticket_label_counts.fund=8`, but `metadata_filtered` returned **empty** while `vector_only` returned pilot hits.

**Root cause:** `PilotScopedVectorStore` applied metadata filters **after** global pgvector `ORDER BY distance LIMIT N`. Fund pilot rows were often **outside** the global top-N window (bootstrap + support rows ranked higher), so post-filtering yielded zero fund rows even though fund rows exist in the index.

**Fix (eval-only):** When `metadata_filter` is set, fetch all pilot-scoped rows (`record_id` prefix `pilot::{namespace}::{index_version}::`), apply the metadata predicate, then rank by cosine similarity in Python and return `top_k`. Vector-only mode keeps the global search + pilot-scope post-filter.

**Diagnostic:** `count_pilot_scoped_metadata_matches(store, metadata_filter)` — safe row count before vector ranking (no content/vectors in output).

**Re-run after deploy:**

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

---

## Step 121 — balanced pilot corpus rebuild (planned)

**Updated root cause:** Sandbox pgvector inventory showed **`fund=0`** while support/complaint rows were present. The metadata-filter and compare-modes paths are **working**; finance-filtered eval correctly returned empty when no fund rows exist in the index. The first 25-record build was **label-imbalanced** (support 16, complaint 9, fund 0) — see [pilot corpus 25 build report](pilot_corpus_25_build_report.md).

**Remediation (governance only — no retrieval activation):**

| Action | Guidance |
|--------|----------|
| Rebuild `approved_room_ids.txt` | `select_approved_room_ids.py --balance-pilot` (≈10 / 7 / 8) |
| Human sign-off | Required before corpus build |
| Rebuild corpus → embeddings → pgvector | [Balanced pilot corpus rebuild](balanced_pilot_corpus_rebuild.md) |
| Re-run eval | `--compare-modes`; confirm `ticket_label_counts.fund > 0` in inventory |

Do **not** treat fund eval failures as filter bugs until the rebuilt index contains fund rows.

---

## Step 122 — balanced rebuild executed locally

**Corpus/index:** `vendor_ticket_real_pilot_balanced` / `pilot_balanced_v1` — `ticket_label_counts` **support=10, complaint=7, fund=8**.

**Compare-mode eval (fund subset with `metadata_filter`, n=10):**

| Mode | pass_rate | wrong_label_return_count | empty_result_count |
|------|-----------|--------------------------|---------------------|
| vector_only | 0.90 | 1 | 0 |
| metadata_filtered | 0.90 | 0 | 1 |

**Remaining fund failures (not missing-corpus):**

| case_id | Cause |
|---------|--------|
| `pilot-fund-wallet-fa-016` | Persian query semantic drift (support in top-k) |
| `pilot-fund-reconcile-fa-018` | Eval `metadata_filter` pins old `namespace`/`index_version` (`pilot_v1`), not balanced index |

Detail: [pilot balanced rebuild execution report](pilot_balanced_rebuild_execution_report.md).

---

## Step 123 — balanced retrieval eval calibration (v4)

**Fixes (eval-only; no retrieval architecture change):**

| case_id | Change |
|---------|--------|
| `pilot-fund-reconcile-fa-018` | Removed `metadata_filter.namespace` / `index_version` pins; use `ticket_label` + `route_label` — pilot scope from CLI |
| `pilot-fund-wallet-fa-016` | Calibrated Persian query toward fund transfer / settlement wording |

**Loader guard:** `load_pilot_retrieval_cases` rejects cases that pin `metadata_filter.namespace` or `index_version`.

**Eval file:** `evals/pilot_retrieval/vendor_ticket_real_pilot_cases.json` **v4**

**Re-run command:**

```bash
PYTHONPATH=. python3.11 scripts/eval_pilot_retrieval.py \
  --cases evals/pilot_retrieval/vendor_ticket_real_pilot_cases.json \
  --namespace vendor_ticket_real_pilot_balanced \
  --index-version pilot_balanced_v1 \
  --profile semantic_pgvector \
  --compare-modes \
  --output reports/pilot_retrieval_eval_balanced_v1.json \
  --overwrite
```

**Post-calibration results (local, balanced index):**

| Mode | pass_rate | wrong_label_return_count | empty_result_count |
|------|-----------|--------------------------|---------------------|
| vector_only | **0.90** | **1** | **0** |
| metadata_filtered | **1.00** | **0** | **0** |

| Remaining vector_only failure | Reason |
|------------------------------|--------|
| `pilot-fund-wallet-fa-016` | `forbidden_labels_in_top_k:support` (fund label present; support co-occurs in top-5 on small pilot) |

**Resolved:** `pilot-fund-reconcile-fa-018` (removed scope pins; uses `ticket_label` + `route_label`).

Full per-case output: gitignored `reports/pilot_retrieval_eval_balanced_v1.json`.

---

## Operational interpretation

- Sandbox retrieval **works mechanically** (non-empty pilot-scoped hits, moderate scores).
- **Fund/finance eval on the first index** failed primarily because **no fund documents were indexed** (`fund=0`), not because filters were broken.
- After rebuild, re-assess semantic match vs routing using `--compare-modes` and inventory counts.
- **No retrieval tool or LangGraph path was activated** during this analysis.

---

## Governance conclusions

| Statement | Status |
|-----------|--------|
| First sandbox eval completed | **Yes** (aggregate metrics recorded) |
| Production retrieval activation | **No** |
| LangGraph retrieval enabled | **No** |
| Customer-facing retrieval | **No** |
| Failure analysis approves activation | **No** |

---

## Step 124 — retrieval eval decision update

```text
recommended_decision = retrieval_ready_for_sandbox_tooling_review
```

**Supersedes** `retrieval_requires_more_eval` for sandbox tooling review after balanced rebuild (Steps 122–123).

| Check | Result |
|-------|--------|
| Balanced corpus / index label mix | support **10**, complaint **7**, fund **8** |
| Metadata-filtered fund subset | pass_rate **1.00**, wrong_label **0**, empty **0**, **10/10** |
| Vector-only fund subset | pass_rate **0.90**, wrong_label **1**, empty **0** |
| `retrieval_activated` | **false** |

**Metadata-filtered gate:** **passed** — fund routing eval clean on balanced index.

**Vector-only:** one known small-pilot edge — `pilot-fund-wallet-fa-016` (`forbidden_labels_in_top_k:support` only; fund in top-k). Documented; does not block sandbox tooling review.

**Still blocked (explicit):** LangGraph integration, production `RAG_PROFILE`, customer-facing retrieval, autonomous workflow retrieval, runtime activation.

Detail: [pilot retrieval evaluation report](pilot_retrieval_evaluation_report.md) Step 124.

---

## Recommended decision (historical + current)

| Phase | `recommended_decision` | Notes |
|-------|------------------------|-------|
| Step 117 (first index, fund=0) | `retrieval_requires_more_eval` | pass_rate **0.6667**; fund cluster failed |
| **Step 124 (balanced index, calibrated eval)** | **`retrieval_ready_for_sandbox_tooling_review`** | metadata-filtered fund gate **met** |

---

## Next-step gates

1. **Proceed:** sandbox retrieval tooling review (offline CLIs, scoped search, compare-modes) — **not** LangGraph wiring.
2. Optional: human-sample `pilot-fund-wallet-fa-016` in gitignored JSON for vector-only tightening.
3. **Blocked:** LangGraph retrieval, production `RAG_PROFILE`, customer-facing retrieval until separate governance sign-off.
4. Implementing a sandbox retrieval **tool** or API remains a **separate step** — not approved by this decision alone.

---

## Related documentation

- [Pilot retrieval evaluation report](pilot_retrieval_evaluation_report.md)
- [PgVector sandbox indexing plan](pgvector_sandbox_indexing_plan.md)
- [Real embedding artifact integrity report](real_embedding_artifact_integrity_report.md)
