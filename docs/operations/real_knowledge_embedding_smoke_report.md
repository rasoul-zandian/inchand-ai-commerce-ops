# Real OpenAI Knowledge Embedding Smoke Report

**Status:** Local smoke test passed (Step 165) — governance reporting only  
**Audience:** Operational knowledge / retrieval sandbox operators, platform governance

---

## Purpose

Record a **successful local smoke test** of operational knowledge chunk indexing and semantic query using **real OpenAI** embeddings (`text-embedding-3-small`, 1536-D) after Step 164 mock indexing proved non-semantic.

This report confirms sandbox pgvector retrieval returns **lane-appropriate official policy** hits for Persian operational queries. It does **not** approve production `RAG_PROFILE`, operator-console wiring, knowledge retrieval tools, draft/final consumption, or customer-facing retrieval.

---

## Sandbox-only scope

| Rule | Smoke test |
|------|------------|
| Local Postgres only | **Yes** — `assert_sandbox_database_url` |
| Namespace | `knowledge_operations_sandbox` |
| Index version (OpenAI) | `knowledge_v1_openai` |
| Prior mock index (Step 164) | `knowledge_v1` (unchanged; separate metadata filter) |
| CLI gates | `--confirm-sandbox` required; OpenAI requires `--confirm-real-openai` |
| `retrieval_activated` | **false** (indexing summary + record metadata) |
| `sandbox_only` on records | **true** |

---

## Indexing (OpenAI re-index)

Command pattern (operator-local; API key not reproduced):

```bash
PYTHONPATH=. python3.11 scripts/index_knowledge_chunks_pgvector.py \
  reports/knowledge_chunks_preview.jsonl \
  --namespace knowledge_operations_sandbox \
  --index-version knowledge_v1_openai \
  --provider openai \
  --model text-embedding-3-small \
  --dimensions 1536 \
  --confirm-real-openai \
  --confirm-sandbox
```

| Field | Value |
|-------|-------|
| indexed_count | 40 |
| chunk_count | 40 |
| skipped_unsafe | 0 |
| embedding_provider | openai |
| embedding_model | text-embedding-3-small |
| dimensions | 1536 |
| official_policy chunks | 35 (`priority_rank=10`) |
| historical_memory chunks | 5 (`priority_rank=1`) |
| conflict_resolution | official_policy_overrides_historical_memory |
| indexing_status | sandbox_indexed |
| retrieval_activated | false |
| generated_at_utc (index run) | 2026-05-20T12:49:51+00:00 |

Full indexing JSON remains under gitignored `reports/knowledge_pgvector_indexing_summary.json` (operator-local).

---

## Mock vs OpenAI (why Step 165)

| Aspect | Step 164 (`knowledge_v1`, mock) | Step 165 (`knowledge_v1_openai`, OpenAI) |
|--------|----------------------------------|------------------------------------------|
| Embedding | Deterministic hash vectors | `text-embedding-3-small` semantic vectors |
| Semantic quality | **Not meaningful** for Persian ops queries | **Meaningful** — top hits align with query intent |
| Cost / network | Offline-safe (CI) | Requires `OPENAI_API_KEY` (local only) |
| Use | CI + plumbing validation | Pre-tooling quality gate |

---

## Smoke query design

Queries are identified by ID only in this report (Persian query text is **not** committed). Operators used five operational probes covering settlement, non-original listing rules, prohibited goods, product image rules, and product title length.

CLI pattern:

```bash
PYTHONPATH=. python3.11 scripts/query_knowledge_pgvector.py \
  --query "<operator-supplied Persian text>" \
  --namespace knowledge_operations_sandbox \
  --index-version knowledge_v1_openai \
  --top-k 5 \
  --provider openai \
  --confirm-real-openai \
  --confirm-sandbox
```

Ranking policy: **`priority_rank` descending, then vector `score` descending** (`official_policy`=10 before `historical_memory`=1).

---

## Aggregate-safe smoke results

**Snippets omitted** below (private operational text). Only `document_type`, `section_title`, `source_lane`, and rounded scores are recorded.

### KQ1 — vendor settlement timing

| Rank | source_lane | document_type | section_title | score (approx) |
|------|-------------|---------------|---------------|----------------|
| 1 | official_policy | settlement_rules | خلاصه قانون | 0.425 |
| 2 | official_policy | product_publishing_rules | خلاصه قانون | 0.354 |
| 3–5 | official_policy | mixed (support tone sections) | نکات پاسخ‌گویی به فروشنده | ≤0.328 |

**Top document_type:** `settlement_rules` — aligns with settlement intent.

### KQ2 — non-original product listing rules

| Rank | source_lane | document_type | section_title | score (approx) |
|------|-------------|---------------|---------------|----------------|
| 1 | official_policy | product_publishing_rules | خلاصه قانون | 0.398 |
| 2 | official_policy | product_publishing_rules | استثناها | 0.359 |
| 3 | official_policy | prohibited_goods | شرایط اصلی | 0.347 |

**Top document_type:** `product_publishing_rules`.

### KQ3 — prohibited goods on platform

| Rank | source_lane | document_type | section_title | score (approx) |
|------|-------------|---------------|---------------|----------------|
| 1 | official_policy | prohibited_goods | شرایط اصلی | 0.465 |
| 2 | official_policy | product_publishing_rules | خلاصه قانون | 0.358 |
| 3 | official_policy | prohibited_goods | خلاصه قانون | 0.353 |

**Top document_type:** `prohibited_goods`.

### KQ4 — original product image conditions

| Rank | source_lane | document_type | section_title | score (approx) |
|------|-------------|---------------|---------------|----------------|
| 1 | official_policy | product_publishing_rules | استثناها | 0.388 |
| 2 | official_policy | product_publishing_rules | شرایط اصلی | 0.352 |
| 3 | official_policy | product_publishing_rules | خلاصه قانون | 0.338 |

**Top document_type:** `product_publishing_rules`.

### KQ5 — minimum product title length

| Rank | source_lane | document_type | section_title | score (approx) |
|------|-------------|---------------|---------------|----------------|
| 1 | official_policy | product_publishing_rules | شرایط اصلی | 0.381 |
| 2 | official_policy | prohibited_goods | شرایط اصلی | 0.353 |
| 3 | official_policy | product_publishing_rules | خلاصه قانون | 0.331 |

**Top document_type:** `product_publishing_rules` (section covers naming length rules).

---

## Lane precedence check

| Check | Result |
|-------|--------|
| historical_memory in any top-5 hit (KQ1–KQ5) | **No** |
| official_policy in all top-5 hits | **Yes** (30/30 ranked slots) |
| official_policy outranked historical_memory | **Yes** — historical chunks never surfaced in top-5 |
| Policy conflict rule honored | **Yes** — `official_policy_overrides_historical_memory` |

---

## Source lane distribution (all smoke top-5 slots)

| source_lane | Count (of 25 slots) |
|-------------|---------------------|
| official_policy | 25 |
| historical_memory | 0 |

---

## Safety boundaries

| Boundary | Enforced |
|----------|----------|
| No private knowledge files in git | **Yes** — `data/private/knowledge/` gitignored |
| No full knowledge text in this report | **Yes** — snippets omitted |
| No API keys in committed docs | **Yes** |
| No draft/final response use | **Yes** — not wired |
| No operator console wiring | **Yes** — not wired |
| No production RAG_PROFILE | **Yes** |
| No vendor ticket retrieval index change | **Yes** — `knowledge::` record prefix only |
| Local query JSONL | Gitignored under `reports/knowledge_openai_smoke_*.json` |

---

## Recommended next step (not in Step 165)

Implement a **sandbox knowledge retrieval tool** behind existing governance patterns (aggregate-safe response, `retrieval_activated=false`, policy gate shadow-only) — **after** human sign-off on this smoke report. Do **not** wire into draft/final or operator console until a separate step approves it.

---

## Related docs

- Repository `README.md` — Steps 162–165 (inventory, chunking, indexing, OpenAI smoke)
- `scripts/index_knowledge_chunks_pgvector.py`
- `scripts/query_knowledge_pgvector.py`
- `app/knowledge/knowledge_embedding_index.py`
