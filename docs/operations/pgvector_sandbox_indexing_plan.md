# PgVector Sandbox Indexing Plan

**Status:** Sandbox indexing implemented (local operator execution) — retrieval **not** activated  
**Audience:** Retrieval infrastructure, AI platform, data governance

---

## Purpose

Define a **governed, sandbox-only** plan to index **local OpenAI embedding artifacts** (25-record pilot corpus) into **pgvector** for offline evaluation—without activating production retrieval, LangGraph runtime changes, or shared staging databases.

This plan bridges:

- [Real embedding artifact integrity report](real_embedding_artifact_integrity_report.md) (embeddings verified locally)
- Future sandbox indexing execution (separate step)
- Retrieval evaluation gates (required before any activation)

Planning contract: `app/corpus_planning/pgvector_plan_models.py` (`pgvector_plan_ready_for_sandbox()`).

---

## Scope

### In scope

- Sandbox indexing **planning** and governance boundaries
- Proposed pgvector strategy (extension, cosine, 1536-D, metadata filters)
- **Schema proposal** (document-only)
- Provenance linkage to corpus lockfile and embedding artifacts
- Evaluation-before-activation policy
- Rollback expectations for sandbox experiments
- Profile comparison: `semantic_pgvector` vs `semantic_pgvector_16`

### Out of scope (non-goals)

- Creating or altering pgvector tables in this step
- Running SQL migrations or `make pg-init` as part of this deliverable
- Inserting vectors or upserting rows
- Activating retrieval in FastAPI / LangGraph
- Connecting production or shared staging databases
- Docker service creation or CI Postgres dependency
- Building new retrieval APIs
- Executing similarity search in production paths
- Committing embedding artifacts or vectors to git

---

## Sandbox boundaries

| Boundary | Policy |
|----------|--------|
| Environment | **Local/dev operator machine only** |
| Database | **Dedicated sandbox Postgres** — not production, not shared staging |
| Customer-facing usage | **Forbidden** |
| Automatic retrieval | **Forbidden** |
| Agent / LangGraph activation | **Forbidden** until eval gates pass |
| Corpus / embeddings in git | **No** — remain local/private/gitignored |

---

## Governance requirements

Before any sandbox indexing execution:

| Requirement | Evidence |
|-------------|----------|
| Real embeddings generated locally | [Real embedding integrity report](real_embedding_artifact_integrity_report.md) |
| Embedding artifact integrity passed | `check_embedding_artifact_integrity.py` — `integrity_issue_count=0` |
| Pilot corpus integrity passed | `check_pilot_corpus_integrity.py` |
| Repository policy reviewed | [Pilot corpus repository policy](pilot_corpus_repository_policy.md) |
| Explicit operator approval | `PgVectorSandboxPlan.status=approved_for_sandbox` |
| `retrieval_activation_allowed=false` | Enforced in planning model until eval sign-off |
| Sandbox-only flag | `sandbox_only=true` on plan record |

---

## Indexing prerequisites

1. **Embedding artifacts** at `artifacts/embeddings/vendor_ticket_real_pilot_openai/` with:
   - `embedding_provider=openai`
   - `embedding_model=text-embedding-3-small`
   - `embedding_dimensions=1536`
   - `embedding_status=real_generated`
   - `indexing_status=not_started` (artifact manifest; unchanged until indexing step)
2. **Corpus lockfile hash** recorded and matching current `corpus/vendor_ticket_real_pilot/corpus.lock.json`.
3. **Sandbox Postgres** running locally (operator-initiated; not CI).
4. **Table dimensions** align with `VECTOR(1536)` / `PGVECTOR_DIMENSIONS=1536`.
5. **Index version** assigned before insert (e.g. `pilot_sandbox_v1`) for rollback.

---

## Provenance requirements

Each indexed row (future execution) must retain:

| Field | Source |
|-------|--------|
| `source_corpus_id` | `vendor_ticket_real_pilot` |
| `source_corpus_lockfile_hash` | Pilot `corpus.lock.json` digest |
| `embedding_artifact_id` | `embedding_manifest.json` |
| `embedding_provider` | `openai` |
| `embedding_model` | `text-embedding-3-small` |
| `index_version` | Sandbox batch label (operator-assigned) |
| `indexed_at` | ISO-8601 UTC at index completion |

Re-index required if corpus lockfile or embedding artifact lockfile changes.

---

## Rollback expectations

| Scenario | Expected action |
|----------|-----------------|
| Wrong embedding artifact indexed | `DELETE` sandbox rows for `index_version` + `embedding_artifact_id` |
| Corpus lockfile drift | Abort index; re-verify integrity; regenerate embeddings if needed |
| Dimension mismatch | Fail before insert; do not pad vectors |
| Sandbox experiment complete | Drop sandbox table contents or destroy local Docker volume |
| Promotion to staging | **Separate** governance step — not automatic from sandbox |

Sandbox data is **disposable**; production tables must never receive pilot sandbox writes.

---

## Evaluation-before-activation policy

**No production retrieval** until all evaluation categories below pass with documented sign-off:

| Evaluation | Objective |
|--------------|-------------|
| Top-k precision | Retrieved docs match expected `document_id` / label for benchmark queries |
| Wrong-ticket retrieval rate | Cross-room leakage below agreed threshold |
| Metadata leakage risk | Filters prevent finance/complaint/support bleed |
| Complaint / finance isolation | Department-sensitive queries do not pull wrong label buckets |
| Hallucination risk review | Retrieved snippets cannot reintroduce unapproved raw text |
| Retrieval reproducibility | Same query + index version → stable ranking |
| Deterministic benchmark queries | Fixed query set in `eval_cases.json` or pilot-specific suite |
| Human review sampling | Operator review of retrieval traces (no transcript commit to git) |

Passing sandbox indexing **does not** satisfy this policy—eval execution and sign-off are separate.

---

## Pgvector strategy

### Proposed design choices

| Choice | Proposal |
|--------|----------|
| Extension | **pgvector** on Postgres 16 (local Docker image `pgvector/pgvector:pg16`) |
| Database | **Sandbox DB only** — dedicated database or schema prefix |
| Environment | **Local/dev** operator machine |
| Similarity | **Cosine distance** (existing `PgVectorStore` pattern) |
| Dimensions | **1536** (OpenAI `text-embedding-3-small`) |
| Metadata filters | `ticket_label`, `route_label`, `review_priority`, `source_corpus_id`, `index_version` |
| Namespace isolation | Table or `index_version` + `source_corpus_id` partition — no mixing with `corpus/vendor_ticket` mock corpus |
| Index versioning | `index_version` column (e.g. `pilot_openai_sandbox_v1`) |
| Provenance | `source_corpus_lockfile_hash`, `embedding_artifact_id`, provider/model on each row |

### Profile comparison

| Profile | Table / dims | Embedding source | Pilot fit |
|---------|----------------|------------------|-----------|
| **`semantic_pgvector`** | `rag_vector_records` — **VECTOR(1536)** | OpenAI 1536-D | **Recommended first** for real pilot artifacts |
| **`semantic_pgvector_16`** | `rag_vector_records_16` — **16-D mock** | Mock embeddings | Useful for CI/smoke; **not** for OpenAI pilot vectors |

**Why 1536-D / `semantic_pgvector` first:**

- Real OpenAI artifacts are **1536-dimensional**; inserting them into 16-D tables fails dimension checks.
- Existing staging path (`semantic_pgvector`, `make pg-eval`, `make pg-compare`) targets 1536-D.
- Pilot governance already recorded `text-embedding-3-small` at 1536.

**Why quantized / index-optimized variants wait:**

- No baseline eval metrics exist for the pilot corpus yet.
- Quantization (e.g. halfvec, binary) adds operational risk before precision/recall are measured.
- HNSW/IVFFlat tuning should follow initial brute-force or exact cosine validation on **25 rows** first.

---

## Proposed schema (document-only)

**Schema proposal only — not executed in this step.**

Candidate columns for a sandbox pilot table (or extended `rag_vector_records` with strict filters):

| Column | Type (conceptual) | Notes |
|--------|-------------------|--------|
| `document_id` | text | Primary business key from corpus |
| `room_id` | text | Ticket room identifier |
| `embedding` | vector(1536) | OpenAI embedding; never logged |
| `ticket_label` | text | Metadata filter |
| `route_label` | text | Metadata filter |
| `review_priority` | text | Metadata filter |
| `source_corpus_id` | text | `vendor_ticket_real_pilot` |
| `source_corpus_lockfile_hash` | text | Bind to corpus tree |
| `embedding_artifact_id` | text | Bind to embedding manifest |
| `embedding_provider` | text | `openai` |
| `embedding_model` | text | `text-embedding-3-small` |
| `indexed_at` | timestamptz | Index batch timestamp |
| `index_version` | text | Sandbox rollback label |

No DDL is run as part of Step 113.

---

## Retrieval safety gates (summary)

Indexing ⊄ retrieval activation. Even after sandbox index population:

- **`RAG_PROFILE`** remains default (mock/in-memory) in CI and production-oriented configs.
- **`semantic_pgvector`** pilot usage requires explicit env + prior `make pg-index` equivalent for pilot artifacts.
- LangGraph **`retrieve_context`** must not auto-switch to pilot index without governance flag.

---

## Sandbox indexing execution

**Module:** `app/corpus_planning/pgvector_sandbox_indexing.py`  
**CLI:** `scripts/index_pilot_embeddings_pgvector.py`

### Operator command (local only)

```bash
# Prerequisites: make pg-up && make pg-init (local sandbox Postgres)
# Embedding integrity must pass first.

PYTHONPATH=. python3.11 scripts/check_embedding_artifact_integrity.py \
  artifacts/embeddings/vendor_ticket_real_pilot_openai

PYTHONPATH=. python3.11 scripts/index_pilot_embeddings_pgvector.py \
  artifacts/embeddings/vendor_ticket_real_pilot_openai \
  --namespace vendor_ticket_real_pilot \
  --index-version pilot_v1 \
  --profile semantic_pgvector \
  --confirm-sandbox
```

### Safety gates

| Gate | Enforcement |
|------|-------------|
| `--confirm-sandbox` | Required |
| Profile | **`semantic_pgvector` only** — rejects `semantic_pgvector_16` |
| Database | **`PGVECTOR_DATABASE_URL`** must be localhost / `127.0.0.1` / `host.docker.internal` |
| Production/staging DB | **Rejected** (hostname heuristics) |
| Embedding integrity | Runs `check_embedding_artifact_integrity` before upsert |
| Transcripts | **Not** indexed — provenance in `metadata` JSON only |
| Golden/bootstrap corpus | **Unchanged** — pilot rows use `record_id` prefix `pilot::` |

### Summary report

After successful indexing, writes **aggregate-only** JSON (gitignored):

`reports/pgvector_sandbox_indexing_pilot_v1.json`

Fields include: `indexed_count`, `namespace`, `index_version`, `profile`, `dimensions`, `embedding_provider`, `embedding_model`, `source_corpus_id`, `source_corpus_lockfile_hash_prefix`, `embedding_artifact_id`, `indexing_status=sandbox_indexed`, `retrieval_activated=false`.

### Schema note

Pilot provenance is stored in **`rag_vector_records.metadata`** (JSONB). No migration required for this step. The `content` column holds label-derived summary text only (no transcript).

---

## Governance status

| Item | State |
|------|--------|
| Sandbox indexing code | **Yes** (`pgvector_sandbox_indexing.py`, CLI) |
| Operator-local vectors inserted | **When CLI run locally** |
| Retrieval activated | **No** |
| LangGraph / default `RAG_PROFILE` changed | **No** |
| Planning model available | **Yes** (`pgvector_plan_models.py`) |

---

## Pilot retrieval evaluation (Step 115)

**Module:** `app/corpus_planning/pilot_retrieval_eval.py`  
**CLI:** `scripts/eval_pilot_retrieval.py`  
**Cases:** `evals/pilot_retrieval/vendor_ticket_real_pilot_cases.json`

```bash
PYTHONPATH=. python3.11 scripts/eval_pilot_retrieval.py \
  --cases evals/pilot_retrieval/vendor_ticket_real_pilot_cases.json \
  --namespace vendor_ticket_real_pilot \
  --index-version pilot_v1 \
  --profile semantic_pgvector \
  --top-k 5 \
  --output reports/pilot_retrieval_eval_pilot_v1.json \
  --overwrite
```

- **Evaluation only** — filters results to `pilot::{namespace}::{index_version}::` rows
- Requires local sandbox Postgres + prior sandbox indexing
- Query embeddings use OpenAI (`OPENAI_API_KEY`); **not** used in CI (mocked)
- Output: `reports/pilot_retrieval_eval_pilot_v1.json` (gitignored)
- **Does not** activate LangGraph retrieval or change `RAG_PROFILE`

---

## Pilot retrieval evaluation report (Step 116)

**Doc:** [pilot_retrieval_evaluation_report.md](pilot_retrieval_evaluation_report.md) — sanitized operational record for sandbox eval runs (aggregate metrics only; `retrieval_activated=false`). After balanced index + eval calibration: **`recommended_decision = retrieval_ready_for_sandbox_tooling_review`** (metadata-filtered fund gate met; production/LangGraph still blocked).

**Sandbox retrieval tool contract (Step 125):** [sandbox_retrieval_tool_contract.md](sandbox_retrieval_tool_contract.md) — governed request/response boundary (`RetrievalToolRequest` / `RetrievalToolResponse`). **Does not** execute retrieval, activate LangGraph, or expose transcripts/vectors. Tool executor remains a future step.

---

## Recommended next steps

1. Run sandbox indexing locally after embedding integrity passes (command above).
2. Run **pilot retrieval eval** (`eval_pilot_retrieval.py`) against the sandbox index.
3. Record aggregates per [pilot retrieval evaluation report](pilot_retrieval_evaluation_report.md).
4. Perform **human sampling** on failed/near-miss cases.
5. **Do not** enable production retrieval or shared staging DB until evaluation gates pass.

Related: [Real OpenAI embedding generation plan](real_openai_embedding_generation_plan.md), [Real embedding artifact integrity report](real_embedding_artifact_integrity_report.md), [Pilot retrieval evaluation report](pilot_retrieval_evaluation_report.md), [Pilot corpus repository policy](pilot_corpus_repository_policy.md).
