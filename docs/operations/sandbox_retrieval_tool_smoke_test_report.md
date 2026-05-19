# Sandbox Retrieval Tool Smoke Test Report

**Status:** Local smoke test passed (Step 127) — governance reporting only  
**Governance:** `recommended_decision = retrieval_ready_for_sandbox_tooling_review` (Step 124)  
**Audience:** AI Commerce OS retrieval layer, platform governance, sandbox operators

---

## Purpose

Record a **successful local smoke test** of the sandbox retrieval tool executor (`execute_sandbox_retrieval_tool`) and CLI (`scripts/run_sandbox_retrieval_tool.py`) after Step 126.

This report confirms that the executor runs against the balanced pilot pgvector sandbox index, honors the Step 125 contract, and returns **aggregate-safe** output only. It does **not** approve runtime activation, LangGraph wiring, production `RAG_PROFILE`, or customer-facing retrieval.

---

## Sandbox-only scope

| Rule | Smoke test |
|------|------------|
| Local Postgres only | **Yes** — sandbox host policy (`assert_sandbox_database_url`) |
| Pilot namespace / index | `vendor_ticket_real_pilot_balanced` / `pilot_balanced_v1` |
| Profile | `semantic_pgvector` |
| CLI gate | `--confirm-sandbox` required |
| `sandbox_only` on response | **true** |
| `retrieval_activated` on response | **false** |

---

## Local execution command

Operator command used for this smoke test (query text is **not** reproduced in this report):

```bash
PYTHONPATH=. python3.11 scripts/run_sandbox_retrieval_tool.py \
  --namespace vendor_ticket_real_pilot_balanced \
  --index-version pilot_balanced_v1 \
  --profile semantic_pgvector \
  --top-k 5 \
  --ticket-label fund \
  --confirm-sandbox
```

Additional flags: `--query` (operator-supplied; omitted here). Requires `OPENAI_API_KEY` for **query embedding only**; key is never printed.

---

## Safety boundaries

| Boundary | Enforced |
|----------|----------|
| No raw query in committed docs | **Yes** — audit via `query_hash` only |
| No transcript / message bodies | **Yes** |
| No indexed `content` payloads | **Yes** |
| No embedding vectors | **Yes** |
| No API keys in output | **Yes** |
| Output field allowlist | `record_id`, `score`, `ticket_label`, `route_label`, `review_priority` only |
| Metadata filter allowlist | `ticket_label`, `route_label`, `review_priority` only |

Full CLI JSON responses remain **local/operator-only** and are **not** committed to git.

---

## Retrieval contract used

| Item | Reference |
|------|-----------|
| Contract doc | [Sandbox retrieval tool contract](sandbox_retrieval_tool_contract.md) |
| Request/response models | `app/corpus_planning/retrieval_tool_models.py` |
| Validation | `app/corpus_planning/retrieval_tool_validation.py` |
| Executor | `app/corpus_planning/sandbox_retrieval_tool.py` |

Smoke test path: **metadata-filtered** retrieval (`--ticket-label fund`) against the balanced pilot index.

---

## Aggregate-safe execution metrics

| Field | Value |
|-------|-------|
| `namespace` | `vendor_ticket_real_pilot_balanced` |
| `index_version` | `pilot_balanced_v1` |
| `query_hash` | `c24189e23ea1c12c` |
| `result_count` | **5** |
| `retrieval_activated` | **false** |
| `sandbox_only` | **true** |
| `profile` | `semantic_pgvector` |
| `metadata_filter` | `ticket_label=fund` (aggregate label only) |

Per-hit fields in response: `record_id`, `score`, `ticket_label`, `route_label`, `review_priority` — no forbidden keys observed.

**Not recorded here:** raw query text, transcript text, vectors, embeddings, retrieved content payloads, API keys, or per-record content snippets.

---

## Governance status

| Gate | Status |
|------|--------|
| Sandbox retrieval executor works locally | **Passed** |
| Metadata-filtered retrieval path operational | **Passed** |
| Response shape contract-safe | **Passed** |
| Runtime `retrieval_activated` | **false** — unchanged |
| LangGraph integration | **Not implemented** — blocked |
| Production `RAG_PROFILE` | **Not changed** — blocked |
| Customer-facing retrieval | **Not implemented** — blocked |
| Autonomous agent tool registration | **Not approved** |

---

## Governance conclusions

1. **Sandbox retrieval executor works locally** — CLI completed successfully against the balanced pilot pgvector index with `--confirm-sandbox`.
2. **Metadata-filtered retrieval path is operational** — `--ticket-label fund` filter applied; five contract-safe hits returned.
3. **Response shape remains contract-safe** — `query_hash` present; no raw query, transcripts, vectors, or content payloads in output.
4. **No runtime activation** — `retrieval_activated=false` on the smoke response; vendor-ticket workflow retrieval remains off.
5. **No LangGraph integration** — executor is not wired into LangGraph nodes or agent tool registries.
6. **No production `RAG_PROFILE` changes** — production retrieval profile unchanged.
7. **No customer-facing retrieval** — no HTTP APIs or customer endpoints added.

This smoke test **does not** supersede Step 124 gates for LangGraph, production promotion, or customer APIs. It supports continued **sandbox tooling review** only.

---

## Related documentation

- [Sandbox retrieval tool contract](sandbox_retrieval_tool_contract.md)
- [LangGraph retrieval integration plan](langgraph_retrieval_integration_plan.md) (Step 128 — plan only)
- [Pilot retrieval evaluation report](pilot_retrieval_evaluation_report.md)
- [Balanced pilot corpus rebuild](balanced_pilot_corpus_rebuild.md)
- [PgVector sandbox indexing plan](pgvector_sandbox_indexing_plan.md)
