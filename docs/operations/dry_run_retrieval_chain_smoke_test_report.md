# Dry-run Retrieval Chain Smoke Test Report

**Status:** Local smoke test passed (Step 132) — governance reporting only  
**Governance:** `recommended_decision = retrieval_ready_for_sandbox_tooling_review` (Step 124)  
**Audience:** AI Commerce OS retrieval layer, platform governance, sandbox operators

---

## Purpose

Record a **successful local smoke test** of the full sandbox retrieval **dry-run chain** after Step 131:

1. Retrieval policy gate  
2. Sandbox retrieval tool executor (when gate allows)  
3. Retrieval state helpers on `CommerceAIState`  
4. Safe retrieval state snapshot output  

This report confirms the integration boundary works end-to-end **without** LangGraph, runtime activation, production `RAG_PROFILE` promotion, or customer-facing retrieval.

**CLI:** `scripts/dry_run_sandbox_retrieval_chain.py`  
**Library:** `app/corpus_planning/sandbox_retrieval_chain_dry_run.py`

---

## Sandbox-only scope

| Rule | Smoke test |
|------|------------|
| Local Postgres only | **Yes** — `assert_sandbox_database_url` when executor runs |
| Pilot namespace / index | `vendor_ticket_real_pilot_balanced` / `pilot_balanced_v1` |
| Profile | `semantic_pgvector` |
| CLI gate | `--confirm-sandbox` required |
| Policy gate before search | **Yes** — executor not called on deny/skip |
| `retrieval_sandbox_only` in snapshot | **true** |
| `retrieval_activated` in snapshot | **false** |
| Retrieval hits in state | **No** — aggregate counts/hash only |

---

## Local execution command

Operator command used for this smoke test (query text is **not** reproduced in this report):

```bash
PYTHONPATH=. python3.11 scripts/dry_run_sandbox_retrieval_chain.py \
  --ticket-label fund \
  --route-label billing_review \
  --namespace vendor_ticket_real_pilot_balanced \
  --index-version pilot_balanced_v1 \
  --profile semantic_pgvector \
  --top-k 5 \
  --confirm-sandbox
```

Additional flags: `--query` (operator-supplied; omitted here). Requires `OPENAI_API_KEY` for **query embedding only** when the gate returns **allow**; key is never printed.

---

## Retrieval chain stages

| Stage | Component | Smoke outcome |
|-------|-----------|---------------|
| 1 | `evaluate_retrieval_policy_gate` | **allow** for fund + metadata filter |
| 2 | `execute_sandbox_retrieval_tool` | **called** (`executor_called=true`) |
| 3 | `apply_retrieval_gate_result_to_state` | Gate fields written |
| 4 | `apply_retrieval_tool_response_to_state` | `query_hash` + `result_count` only |
| 5 | `sanitize_retrieval_state_snapshot` | Safe JSON/summary printed |

On **deny** or **skip**, stages 2 and 4 are skipped; no OpenAI embedding call.

---

## Governance and safety boundaries

| Boundary | Enforced |
|----------|----------|
| No raw query in committed docs | **Yes** — `retrieval_query_hash` only |
| No transcript / message bodies | **Yes** |
| No indexed `content` in state snapshot | **Yes** |
| No embedding vectors | **Yes** |
| No API keys in output | **Yes** |
| No raw retrieval hits in state | **Yes** — hits not stored on `CommerceAIState` |
| Metadata filter allowlist | `ticket_label`, `route_label`, `review_priority` only |
| LangGraph / runtime | **Not invoked** |

Full CLI output remains **local/operator-only** and is **not** committed to git.

---

## State sanitization behavior

`sanitize_retrieval_state_snapshot` exports only:

- `retrieval_gate_decision`, `retrieval_scenario`, `retrieval_policy_reasons`
- `retrieval_query_hash`, `retrieval_result_count`, `retrieval_metadata_filter`
- `retrieval_sandbox_only`, `retrieval_activated`

Forbidden keys (e.g. `query`, `content`, `vector`, `results`) are rejected if present on metadata or snapshot payloads.

---

## Current activation status

| Item | Status |
|------|--------|
| Dry-run chain (local CLI) | **Passed** — this report |
| LangGraph retrieval node | **Not implemented** |
| Runtime `retrieval_activated` | **false** |
| Production `RAG_PROFILE` | **Unchanged** |
| Customer-facing retrieval | **Not approved** |
| Autonomous agent tool | **Not approved** |

---

## Aggregate-safe execution metrics

| Field | Value |
|-------|-------|
| `retrieval_gate_decision` | **allow** |
| `retrieval_scenario` | **fund_finance** |
| `retrieval_policy_reasons` | `["retrieval_allowed for fund"]` |
| `retrieval_query_hash` | `c24189e23ea1c12c` |
| `retrieval_result_count` | **5** |
| `retrieval_metadata_filter` | `ticket_label=fund`, `route_label=billing_review` |
| `retrieval_sandbox_only` | **true** |
| `retrieval_activated` | **false** |
| `executor_called` | **true** |
| `namespace` | `vendor_ticket_real_pilot_balanced` |
| `index_version` | `pilot_balanced_v1` |

**Not recorded here:** raw query text, retrieved content, transcripts, vectors, embeddings, API keys, per-hit `record_id` lists, or tool `results` payloads.

---

## Governance conclusions

1. **Dry-run retrieval chain works locally** — gate → executor → state helpers → sanitized snapshot completes successfully.
2. **Policy gate executes before retrieval** — fund routing with metadata filter evaluated before pgvector/OpenAI access.
3. **Metadata-filtered fund routing works** — `ticket_label=fund` and `route_label=billing_review` align with gate allow path.
4. **State remains sanitized** — snapshot contains aggregate-safe fields only; no hits stored in state.
5. **No runtime activation** — `retrieval_activated=false` on snapshot; vendor-ticket graph retrieval unchanged.
6. **No LangGraph node** — chain was CLI-only at Step 132; shadow graph node added in Step 134 (flag default off).
7. **No production `RAG_PROFILE` changes** — production profile unchanged.
8. **No customer-facing retrieval** — no HTTP APIs or customer endpoints added.

This smoke test **does not** supersede Step 124 gates for LangGraph integration, production promotion, or customer APIs.

---

## Related documentation

- [LangGraph sandbox retrieval node plan](langgraph_sandbox_retrieval_node_plan.md) (Steps 133–134 — shadow node; flag default off)
- [LangGraph shadow retrieval smoke test report](langgraph_shadow_retrieval_smoke_test_report.md) (Step 135 — graph shadow smoke test)
- [Retrieval policy gate contract](retrieval_policy_gate_contract.md)
- [Sandbox retrieval tool contract](sandbox_retrieval_tool_contract.md)
- [Sandbox retrieval tool smoke test report](sandbox_retrieval_tool_smoke_test_report.md)
- [LangGraph retrieval integration plan](langgraph_retrieval_integration_plan.md)
- [Pilot retrieval evaluation report](pilot_retrieval_evaluation_report.md)
