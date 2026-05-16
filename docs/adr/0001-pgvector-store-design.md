# ADR 0001: PgVector Store Design

## 1. Status

**Partially implemented (staging / opt-in)**

The pgvector adapter, migrations, offline indexing, retrieval profiles, and staging evaluation tooling exist in the repo. **Default runtime and CI remain in-memory/mock**—no Docker, OpenAI, or Postgres in **`make ci`**. Production default path, HNSW tuning, connection pooling, hybrid search, and reranking are **not** implemented.

## 2. Context

Today the copilot uses **`InMemoryVectorStore`** (`app/rag/vector_store.py`), which implements the **`VectorStore`** interface (`upsert`, `search`, `count`) over **`VectorRecord`** rows (`app/rag/vector_records.py`). **`semantic_retrieve`** embeds a query and calls **`VectorStore.search`**; workflow nodes depend on **`retrieve_for_workflow`** and **`RetrievalConfig`**, not on a specific storage engine.

That design works well for:

- Unit tests and CI (deterministic, no external services)
- Local demos (`semantic_local` profile, bootstrap corpus, mock embeddings)
- Offline corpus governance (manifest, lockfile, eval cases)

Production retrieval needs **persistent** vector search: embeddings and metadata must survive process restarts, support re-indexing from the versioned corpus under `corpus/vendor_ticket/`, and scale beyond a single in-memory dict.

**PostgreSQL + pgvector** is a reasonable first production backend because:

- The broader platform already targets **relational** storage for operational data
- **JSONB** can hold document metadata and traceability fields without a separate document store
- **pgvector** provides cosine / L2 distance operators inside Postgres
- Operators can reuse familiar backup, migration, and observability tooling

The **`VectorStore`** interface remains the boundary: workflow nodes, LangGraph topology, and FastAPI routes must not import SQL or pgvector types.

## 3. Goals

- Implement **`VectorStore`** with **PostgreSQL + pgvector**
- Persist **`VectorRecord`** rows (content, embedding, provenance)
- Support **cosine similarity** search aligned with **`InMemoryVectorStore`** scoring semantics
- Preserve **metadata** and **source traceability** (`document_id`, `source_type`, embedding model)
- Avoid coupling workflow nodes to database connection details
- Support **future re-indexing** from the corpus manifest (offline job, not inline in `retrieve_context`)

## 4. Non-goals

- Hybrid search (BM25 + vector) in the first adapter
- Cross-encoder or LLM **reranking**
- Multi-tenant sharding or per-vendor physical isolation
- Async ingestion workers or queue-based embedding pipelines
- Direct workflow / LangGraph node dependency on SQLAlchemy sessions
- Replacing **`InMemoryVectorStore`** (it stays for tests and local demos)

## 5. Proposed table schema

Single table for MVP (name configurable):

### `rag_vector_records`

| Column | Type | Notes |
|--------|------|--------|
| `record_id` | `TEXT PRIMARY KEY` | Idempotency key; maps to `VectorRecord.record_id` (e.g. `vec-{document_id}`) |
| `document_id` | `TEXT NOT NULL` | Corpus / manifest document id |
| `source_type` | `TEXT NOT NULL` | e.g. `policy`, `approved_pattern`, `style_guide` |
| `content` | `TEXT NOT NULL` | Chunk or full body used for embedding |
| `embedding_provider` | `TEXT NOT NULL` | e.g. `mock`, `openai` |
| `embedding_model` | `TEXT NOT NULL` | e.g. `text-embedding-3-small` |
| `dimensions` | `INTEGER NOT NULL` | Redundant with vector width; used for validation |
| `vector` | `vector(N)` | pgvector column; **fixed N per deployment** |
| `metadata` | `JSONB NOT NULL DEFAULT '{}'` | Title, locale, chunk info, embedding metadata |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | Insert time |
| `updated_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | Last upsert time |

Optional later columns (not MVP): `workflow_type`, `corpus_version`, `manifest_version`, `content_hash`.

### Dimension strategy

pgvector requires a **fixed dimension** per vector column. Options:

| Approach | Pros | Cons |
|----------|------|------|
| **One `VECTOR(d)` per deployment** (recommended MVP) | Simple schema, one index | Model change ⇒ new table or migration |
| Separate tables per embedding model | Clean isolation | More ops overhead |
| Multiple vector columns on one row | Single row per record | Wide rows, only one model active |

**Recommendation:** configure **`PGVECTOR_DIMENSIONS`** (e.g. `1536` for `text-embedding-3-small`) at deploy time. Changing the production embedding model is a **re-index** event (new table or truncate + reload), not an in-place ALTER of vector width.

## 6. Indexing strategy

**MVP (small / medium corpus):**

- Enable the **`vector`** extension
- **No approximate index** initially; use ordered scan with cosine distance for correctness and simplicity
- Query pattern: `ORDER BY vector <=> query_embedding LIMIT top_k` (cosine distance; convert to similarity in application layer to match in-memory behavior)

**Later (scale):**

- **HNSW** or **IVFFlat** index on `vector` with `vector_cosine_ops`
- Tune `lists` / `m` / `ef_construction` based on row count and recall targets
- Rebuild index after bulk re-index from manifest

**Operational note:** when **`embedding_model`** or **`dimensions`** change, treat as a **new index generation**: run offline indexing from `corpus/vendor_ticket/manifest.json`, verify eval cases, update lockfile if corpus bodies change, then cut over retrieval config.

## 7. Adapter behavior

### `class PgVectorStore(VectorStore)`

Constructor: database URL, table name, expected dimensions, distance metric (`cosine` for MVP).

| Method | Behavior |
|--------|----------|
| `upsert(records: list[VectorRecord]) -> int` | `INSERT ... ON CONFLICT (record_id) DO UPDATE`; update `updated_at` |
| `search(query_vector, *, top_k=5) -> list[VectorSearchResult]` | Parameterized query; order by distance; map to `VectorSearchResult` with cosine-like **score** |
| `count() -> int` | `SELECT count(*) FROM rag_vector_records` |

### Semantics (aligned with in-memory store)

- **Upsert idempotency:** `record_id` is the primary key; repeated upserts replace content, vector, and metadata.
- **Search:** return top‑k by similarity; empty store ⇒ `[]`.
- **Score:** expose a float in `[−1, 1]` compatible with **`cosine_similarity`** where possible (derive from pgvector distance operator).

### Dimension mismatch policy

| Operation | Policy | Rationale |
|-----------|--------|-----------|
| **upsert** | **Fail fast** if `len(record.vector) != configured dimensions` or `record.dimensions` disagrees | Prevents corrupt rows in the index |
| **search** | **Return no results** (empty list) if `len(query_vector) != configured dimensions`; log at warning | Matches in-memory “skip” behavior; avoids raising in hot path |

In-memory store **skips** mismatched records during search; pgvector adapter should not query with wrong-dimension vectors.

## 8. Configuration

Implemented environment variables (see `.env.example`, `app/config.py`):

| Variable | Purpose |
|----------|---------|
| `VECTOR_STORE_PROVIDER` | `memory` (default) \| `pgvector` |
| `PGVECTOR_DATABASE_URL` | Postgres URL for `PgVectorStore` (secret; never log) |
| `PGVECTOR_TABLE` | Table name; default `rag_vector_records` (or `rag_vector_records_16` for mock smoke) |
| `PGVECTOR_DIMENSIONS` | Fixed vector width (e.g. `1536` or `16`) |
| `RAG_PROFILE` | `semantic_pgvector`, `semantic_pgvector_16`, `semantic_local`, etc. |

Wiring (implemented):

- `vector_store_factory.create_vector_store` builds `InMemoryVectorStore` or `PgVectorStore` from settings
- `retrieve_context` passes an explicit **`VectorStore`** into `retrieve_for_workflow` for semantic strategies (no global singleton)
- Pgvector profiles require prior offline indexing; no request-time upsert

**Not implemented:** `PGVECTOR_DISTANCE` env (cosine only), connection pooling, async driver.

**Secrets:** `PGVECTOR_DATABASE_URL` must not appear in logs, LangSmith metadata, API responses, or **`retrieval_summary`**.

## 9. Migration plan

| Step | Status |
|------|--------|
| Dev Docker Compose + pgvector image | **Done** (`docker-compose.yml`, `make pg-up`) |
| SQL migrations (`rag_vector_records`, `rag_vector_records_16`) | **Done** |
| **`PgVectorStore`** + marked integration tests | **Done** (`pytest -m pgvector`, not default CI) |
| Offline indexing script | **Done** (`scripts/index_corpus_to_pgvector.py`, `make pg-index` / `pg-index-16`) |
| Local Postgres smoke | **Done** (`make pg-smoke-16`, profile smoke docs in README) |
| Factory + `VECTOR_STORE_PROVIDER=pgvector` | **Done** |
| Retrieval profiles **`semantic_pgvector`**, **`semantic_pgvector_16`** | **Done** (opt-in via `retrieve_context`) |
| Staging eval (`pg-eval`, `pg-compare`, quality gates, runbook) | **Done** (manual only) |
| Re-index runbook (model/corpus change) | **Documented** in README staging sections |
| **Not done:** HNSW/IVFFlat, pooling, hybrid search, reranking, CI pgvector, production default | See §4 non-goals and §12 open questions |

## 10. Risks and tradeoffs

| Risk | Mitigation |
|------|------------|
| **Embedding model / dimension change** | Versioned re-index; separate table or generation id; eval suite before cutover |
| **Stale index vs manifest** | Offline indexer reads manifest + lockfile; CI corpus checks unchanged |
| **JSONB metadata growth** | Keep metadata lean; index only filter keys if needed later |
| **Index tuning** | Start exact search; add HNSW when row count warrants |
| **DB cost / latency** | Connection pooling; read replicas later; top_k kept small (5) |
| **Local dev complexity** | Document Docker Postgres; keep in-memory default |
| **Score parity** | Test against `InMemoryVectorStore` on same records in integration tests |

## 11. Decision

- Keep **`VectorStore`** as the retrieval storage boundary
- **`PgVectorStore`** is a drop-in adapter implementing the existing interface (staging/opt-in)
- **`retrieve_context`** selects store via **`RAG_PROFILE`** / factory; workflow nodes do not import SQL or pgvector types
- **`InMemoryVectorStore`** remains the default for tests, CI, and `semantic_local`
- Corpus manifest + lockfile remain the **source of truth**; Postgres is a **materialized index** rebuilt offline
- Promote pgvector beyond manual staging only after **`pg-eval`** + **`pg-compare`** pass with documented quality gates

## 12. Open questions

1. **Production embedding model and dimension** — OpenAI `text-embedding-3-small` (1536) vs another model?
2. **Sync vs async DB access** — sync SQLAlchemy/psycopg for MVP vs async for FastAPI lifespan?
3. **Migration tooling** — raw SQL in repo vs Alembic vs framework migrations?
4. **Corpus partitioning** — single table with `workflow_type` column vs table per workflow?
5. **Metadata filtering** — do we need `WHERE source_type = ANY(...)` in SQL before vector search (policy-only at DB layer)?
6. **Deletion strategy** — full table replace on re-index vs tombstone `record_id`s not in manifest?
7. **Connection ownership** — per-request store vs pooled singleton behind factory?

---

*Related code: `app/rag/pgvector_store.py`, `app/rag/vector_store_factory.py`, `app/rag/config.py`, `app/nodes/common.py` (`retrieve_context`), `scripts/index_corpus_to_pgvector.py`, `scripts/evaluate_pgvector_retrieval.py`, `corpus/vendor_ticket/manifest.json`.*
