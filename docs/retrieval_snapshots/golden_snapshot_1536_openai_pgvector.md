# Golden Retrieval Evaluation Snapshot — 1536-D OpenAI + PgVector

**Snapshot ID:** `golden-1536-openai-pgvector-v1`  
**Status:** Known-good staging baseline (first golden snapshot)  
**Captured:** 2026-05-16 (UTC validation window; API smoke `2026-05-16T06:19:19Z`)

This artifact records the first trusted operational retrieval baseline after strict staging evaluation and FastAPI smoke. Use it as the reference for future corpus changes, embedding model changes, pgvector tuning, reranking, hybrid retrieval, and regression analysis.

---

## A. Snapshot identity

| Field | Value |
|-------|--------|
| Retrieval profile | `semantic_pgvector` |
| RAG strategy (runtime) | `semantic` |
| Vector store provider | `pgvector` |
| PgVector table | `rag_vector_records` |
| PgVector dimensions | `1536` |
| Embedding provider | `openai` |
| Embedding model | `text-embedding-3-small` |
| LLM provider (smoke) | `mock` |
| Baseline compare mode | `BASELINE_PROVIDER=same_embedding` |
| Eval case count | 15 |
| Manifest version | `1` |
| Eval version | `1` |
| Corpus lock version | `1` |
| Indexed document count | 5 |
| Migration | `db/migrations/0001_create_rag_vector_records.sql` |

### Corpus lock fingerprint (`eval_cases.json`)

| File | SHA-256 |
|------|---------|
| `corpus/vendor_ticket/eval_cases.json` | `6ca0e22665606fe249f8d64c5c2045ff339a012672b747c9606f68dfd90f9a9f` |
| `corpus/vendor_ticket/manifest.json` | `adf6274fa19facbfd3997f84ff9d727829a6a88b8ed3792431f9328d900ce2e5` |

Full inventory: `corpus/vendor_ticket/corpus.lock.json` (regenerated Step 64 after near-miss query fixes).

### Production path validation steps

| Step | Outcome |
|------|---------|
| 63 | Same-embedding compare; storage parity (`cases_with_different_results=0`); near-miss blocked golden |
| 64 | Near-miss query fixes; strict `pg-eval` / `pg-compare` passed |
| 65 | `semantic_pgvector` API smoke passed |
| 66 | This snapshot captured |

---

## B. Evaluation results (strict gates)

Strict staging profile enabled (`RETRIEVAL_QUALITY_GATES=true`, min pass/recall/hit = 1.0, min MRR = 0.8, max near-miss = 0, `RETRIEVAL_REQUIRE_MATCHING_CASE_RESULTS=true`, zero regression tolerances on pass/recall/hit).

### `make pg-eval` (PgVector path)

| Metric | Value |
|--------|--------|
| Exit code | 0 |
| `pass_rate` | 1.0000 |
| `mean_recall_at_k` | 1.0000 |
| `mean_hit_rate` | 1.0000 |
| `mean_mrr` | 0.9167 |
| `near_miss_violation_count` | 0 |
| Quality gates | **passed** |

### `make pg-compare` (`BASELINE_PROVIDER=same_embedding`)

| Metric | Baseline (in-memory) | PgVector | Delta |
|--------|----------------------|----------|-------|
| Exit code | — | — | 0 |
| `pass_rate` | 1.0000 | 1.0000 | 0.0000 |
| `mean_recall_at_k` | 1.0000 | 1.0000 | 0.0000 |
| `mean_hit_rate` | 1.0000 | 1.0000 | 0.0000 |
| `mean_mrr` | 0.9167 | 0.9167 | 0.0000 |
| `near_miss_violation_count` | 0 | 0 | 0 |
| `cases_with_different_results` | — | — | **0** |
| Quality gates | — | — | **passed** |

**Parity:** Same-embedding in-memory baseline vs Postgres pgvector — no storage regression; ranking and near-miss behavior matched on all 15 cases.

---

## C. API smoke confirmation (Step 65)

| Check | Result |
|-------|--------|
| Command | `make smoke-semantic` (after `make config-check`) |
| Exit code | 0 |
| Mock retrieval fallback | **No** (`effective_strategy=semantic`) |

### `retrieval_summary` (expected vs observed)

| Field | Expected | Observed |
|-------|----------|----------|
| `rag_profile` | `semantic_pgvector` | `semantic_pgvector` |
| `requested_strategy` | `semantic` | `semantic` |
| `effective_strategy` | `semantic` | `semantic` |
| `vector_store_provider` | `pgvector` | `pgvector` |
| `pgvector_table` | `rag_vector_records` | `rag_vector_records` |
| `pgvector_dimensions` | 1536 | 1536 |
| `provider` | `semantic` | `semantic` |
| `count` | > 0 | 5 |
| `embedding_provider` | `openai` | `openai` |
| `embedding_model` | `text-embedding-3-small` | `text-embedding-3-small` |

### Workflow

| Field | Value |
|-------|--------|
| `workflow_type` | `vendor_ticket` |
| `workflow_status` | `awaiting_approval` |
| `errors` | `[]` |
| `rag_document_count` (evidence) | 5 |
| `rag_sources` (evidence) | `approved_pattern,policy,style_guide` |

---

## D. Safe environment metadata (no secrets)

Reproduce staging validation with these **non-secret** settings (set embedding API key and Postgres URL locally only; never commit them):

```bash
export RAG_PROFILE=semantic_pgvector
export RAG_STRATEGY=semantic
export VECTOR_STORE_PROVIDER=pgvector
export PGVECTOR_TABLE=rag_vector_records
export PGVECTOR_DIMENSIONS=1536
export EMBEDDING_PROVIDER=openai
export EMBEDDING_MODEL=text-embedding-3-small
export LLM_PROVIDER=mock
export BASELINE_PROVIDER=same_embedding
# Strict gates: see README "Strict Staging Retrieval Quality Profile"
```

**Never commit:** API keys, database passwords, or connection URLs containing credentials.

---

## E. Governance notes

- This is the **first trusted staging baseline** for vendor-ticket retrieval over **1536-D OpenAI embeddings** and **`semantic_pgvector`**.
- **Strict quality gates were enabled** and passed; gates were not weakened to produce this snapshot.
- **Same-embedding baseline** (`BASELINE_PROVIDER=same_embedding`) was used for `pg-compare` so parity reflects **storage/backend** behavior, not mock-vs-OpenAI embedding drift.
- **Default CI** remains mock/in-memory only; this snapshot is **manual/staging** and is not enforced in GitHub Actions.
- Before promoting future changes, re-run `make pg-index` (when corpus or embedding model changes), then `make pg-eval`, `make pg-compare`, and `make smoke-semantic`; compare metrics and gate status to this snapshot.
- Near-miss eval fixes in Step 64 (queries for `vt-tone-respectful-002`, `vt-short-escalation-005`) are part of this baseline; intentional eval edits require lockfile regeneration and a new snapshot if promoted.

**Companion JSON:** [golden_snapshot_1536_openai_pgvector.json](golden_snapshot_1536_openai_pgvector.json)
