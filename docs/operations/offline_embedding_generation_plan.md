# Offline Embedding Generation Plan

**Status:** Planning only — no embeddings generated, no API calls, no indexing  
**Audience:** Retrieval platform, AI governance, data operations

---

## Purpose

This plan defines **how** embeddings may be generated from the approved **local/private** pilot corpus (`corpus/vendor_ticket_real_pilot/`) in a **future controlled execution step**. It does **not** authorize embedding generation, OpenAI usage, pgvector indexing, or production retrieval activation.

Related:

- [Pilot corpus repository policy](pilot_corpus_repository_policy.md)
- [Pilot corpus 25 build report](pilot_corpus_25_build_report.md)
- [Pilot corpus planning](pilot_corpus_planning.md)

---

## Scope

### In scope

- Offline embedding generation **planning** and governance gates
- Corpus **provenance** requirements (lockfile hash, manifest fields)
- Model and **dimension** selection policy
- Output **artifact** policy (local/private paths, gitignore)
- Integrity and **reproducibility** expectations
- Future **dry-run** steps (mock-first, then optional real provider)

### Out of scope

- Actual embedding generation (future Step 108+)
- pgvector indexing or Postgres vector tables
- Retrieval activation in FastAPI / LangGraph runtime
- Production serving or ingestion jobs
- OpenAI/API calls in **this** planning step
- Committing embedding artifacts to the main repository

---

## Preconditions

All of the following must be satisfied **before** any embedding dry-run or production-local batch:

| Precondition | Current state |
|--------------|---------------|
| Pilot corpus integrity check passes | Run `check_pilot_corpus_integrity.py` on local corpus |
| Corpus remains approved / local-private | Per [repository policy](pilot_corpus_repository_policy.md) |
| `corpus.lock.json` hash recorded | Capture SHA-256 entries or aggregate digest in plan metadata |
| Repository policy reviewed | Pilot corpus gitignored; embeddings gitignored |
| Embedding model selected | Default proposed below — change only with governance note |
| Output storage policy decided | `artifacts/embeddings/` local/private only |

---

## Proposed embedding configuration

Default configuration for a **future** execution step (not active):

| Setting | Value |
|---------|--------|
| Provider | `openai` |
| Model | `text-embedding-3-small` |
| Dimensions | `1536` |
| Source corpus | `corpus/vendor_ticket_real_pilot/` |
| Source lockfile | `corpus/vendor_ticket_real_pilot/corpus.lock.json` |
| Output | Local/private artifacts only (see below) |
| Corpus `embedding_status` | Remains `not_started` until execution updates manifest |

Planning contract: `app/corpus_planning/embedding_plan_models.py` (`EmbeddingGenerationPlan`, `embedding_plan_ready_for_dry_run()`).

---

## Corpus provenance

Every embedding batch (mock or real) must record:

| Field | Source |
|-------|--------|
| `corpus_id` | `manifest.json` |
| `corpus_version` | `manifest.json` |
| `source_batch_id` | `manifest.json` |
| `reviewer_signoff_id` | `manifest.json` / governance reference |
| `corpus_lockfile_hash` | SHA-256 of `corpus.lock.json` or canonical digest of lockfile `files[]` |
| `document_ids` | `manifest.document_ids` (25 for current pilot) |
| `embedding_model` | Plan / runtime config |
| `embedding_dimensions` | Plan / runtime config (must match model) |
| `generated_at` | ISO-8601 UTC at batch completion |
| `generator_version` | Script or package version string |

Embeddings without provenance metadata are **not** eligible for indexing or eval comparison.

---

## Output artifact policy

Future local output layout (directories are **not** created in this planning step):

```
artifacts/embeddings/vendor_ticket_real_pilot/
  embeddings.jsonl
  embedding_manifest.json
  embedding.lock.json
```

| Rule | Policy |
|------|--------|
| `artifacts/embeddings/` | **Gitignored** by default |
| `artifacts/vector_indexes/` | **Gitignored** by default (reserved for future index exports) |
| Sensitivity | Embeddings are **derived from real operational data** — treat as sensitive as source corpus |
| Git commit | Do **not** commit embedding files unless explicit governance approval |
| Indexing | Separate step; requires eval gates and `indexing_status` governance |

---

## Safety / governance

- **Embedding generation ≠ retrieval approval** — vectors alone do not enable production RAG.
- **Indexing requires separate approval** — pgvector / `indexing_status` remain `not_started` until documented.
- **No production retrieval** without eval gates (`eval_cases.json`, `pg-eval`, governance sign-off).
- **Regenerate embeddings** if `corpus.lock.json` changes (any document hash mismatch).
- **No OpenAI calls** in CI; dry-run uses **mock** embeddings only (`build_pilot_corpus_embeddings.py`).

---

## Dry-run strategy (Step 108 — implemented)

**Script:** `scripts/build_pilot_corpus_embeddings.py`  
**Library:** `app/corpus_planning/embedding_dry_run.py`

```bash
PYTHONPATH=. python3.11 scripts/build_pilot_corpus_embeddings.py \
  corpus/vendor_ticket_real_pilot \
  --output-dir artifacts/embeddings/vendor_ticket_real_pilot \
  --provider mock \
  --model mock-embedding-1536 \
  --dimensions 1536
```

Behavior:

1. Runs pilot corpus integrity verification before generation.
2. Records `source_corpus_lockfile_hash` in manifest and each embedding record.
3. Writes `embeddings.jsonl`, `embedding_manifest.json`, `embedding.lock.json` under `artifacts/embeddings/` (**gitignored**).
4. Sets manifest `embedding_status=mock_generated`, `indexing_status=not_started`, `pgvector_indexed=false`.
5. **No** transcript text in artifacts; **no** OpenAI; **no** pgvector indexing.

Only after mock dry-run passes locally should operators plan **real OpenAI** embedding generation (separate future step).

**Verify artifacts:**

```bash
PYTHONPATH=. python3.11 scripts/check_embedding_artifact_integrity.py \
  artifacts/embeddings/vendor_ticket_real_pilot
```

See [mock embedding artifact integrity report](mock_embedding_artifact_integrity_report.md).

---

## Risks

| Risk | Mitigation |
|------|------------|
| Embedding leakage | Keep artifacts local/private; gitignore; no logs of vector payloads |
| Corpus drift | Bind batch to `corpus_lockfile_hash`; fail if integrity check fails |
| Model/dimension mismatch | Validate dimensions before any pgvector index step |
| Untracked artifact risk | Manifest + lockfile for embedding outputs; document path on disk |
| Accidental indexing before eval | Separate scripts; `indexing_status` governance; no runtime wiring |
| Cost / API key exposure | Keys in `.env` only; never commit; no keys in reports |

---

## Recommended next steps

1. Run **mock dry-run** locally (command above); verify manifest lockfile hash matches corpus.
2. Add embedding artifact integrity checker (optional) before real provider batch.
3. Optional [real OpenAI run](real_openai_embedding_generation_plan.md) — same script with `--provider openai --confirm-real-openai` (local only).
4. Keep **pgvector indexing** as a separate later step after eval plan approval.

---

## Governance status

| Item | State |
|------|--------|
| Mock embedding dry-run script | **Available** (`build_pilot_corpus_embeddings.py`) |
| Embedding artifacts in git | **No** (`artifacts/embeddings/` gitignored) |
| `embedding_status` (corpus manifest on disk) | `not_started` until corpus manifest updated separately |
| `embedding_status` (embedding manifest) | `mock_generated` after dry-run |
| `indexing_status` (corpus manifest) | `not_started` |
| pgvector indexing | **No** |
| Retrieval activation | **No** |
