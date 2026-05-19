# LangGraph Shadow Retrieval Smoke Test Report

**Status:** Local operational smoke test passed (Step 135) — governance reporting only  
**Governance:** `recommended_decision = retrieval_ready_for_sandbox_tooling_review` (Step 124)  
**Audience:** LangGraph workflow owners, retrieval governance, sandbox operators

---

## Purpose

Record a **successful local operational smoke test** of the feature-flagged LangGraph shadow node `sandbox_retrieve_pilot_shadow` (Step 134) with `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=true` on an operator machine only.

This report confirms:

- The shadow node runs inside the vendor-ticket graph when the flag is **explicitly enabled locally**
- Only **sanitized** `retrieval_*` metadata is written to `CommerceAIState`
- **Draft/final responses are not influenced** by sandbox retrieval output
- **Production behavior remains unchanged** when the flag is false (repository default)

**Node:** `app/nodes/sandbox_retrieval_shadow.py`  
**Graph:** `app/graph/main_graph.py` — `route_workflow` → `sandbox_retrieve_pilot_shadow` → `retrieve_context` → `vendor_ticket_node`

---

## Flag and default behavior

| Setting | Smoke test | Repository default |
|---------|------------|-------------------|
| `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED` | **true** (local operator only) | **false** |
| Shadow node executed | **true** | **false** when flag off |
| `retrieve_context` / `RAG_PROFILE` | **Unchanged** — existing mock/semantic path | Unchanged |
| `retrieval_activated` | **false** | **false** |

Enabling the flag locally does **not** change CI, production defaults, or committed configuration.

---

## Local smoke test scenario

| Step | Outcome |
|------|---------|
| Flag enabled locally | `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=true` |
| Sandbox scope | `namespace=vendor_ticket_real_pilot_balanced`, `index_version=pilot_balanced_v1` |
| Routing | Metadata-filtered **fund** path (`ticket_label=fund`, `route_label=billing_review`) |
| Policy gate | **allow** before executor |
| Graph run | Vendor-ticket workflow **completed** (shadow node invoked) |
| State writes | Sanitized `retrieval_*` fields only |
| `vendor_ticket_node` | **Did not** read `retrieval_*` fields |
| Draft / final response | **Not influenced** by sandbox retrieval metadata |
| Downstream consumption | `downstream_consumed_retrieval=false` |

Operator workflow: local Postgres + `OPENAI_API_KEY` for query embedding when gate allows (same sandbox policy as dry-run CLI). Raw query text is **not** recorded in this report.

---

## Graph placement (smoke path)

```
normalize_request
  → route_workflow
  → sandbox_retrieve_pilot_shadow   ← shadow metadata only
  → retrieve_context              ← unchanged RAG_PROFILE path
  → vendor_ticket_node            ← does not consume retrieval_*
  → … validate / approval …
```

---

## Safety boundaries

| Boundary | Enforced |
|----------|----------|
| No raw query in committed docs | **Yes** — `retrieval_query_hash` only |
| No retrieved content / hit bodies in state | **Yes** |
| No transcripts / message bodies in report | **Yes** |
| No vectors / embeddings in state or report | **Yes** |
| No API keys in output | **Yes** |
| No customer-facing retrieval | **Yes** |
| LangGraph default in repo | Flag **false** — shadow inert |

Local trace/state dumps remain **operator-only** and are **not** committed to git.

---

## Aggregate-safe execution metrics

| Field | Value |
|-------|-------|
| `shadow_node_executed` | **true** |
| `retrieval_gate_decision` | **allow** |
| `retrieval_scenario` | **fund_finance** |
| `retrieval_policy_reasons` | `["retrieval_allowed for fund"]` |
| `retrieval_query_hash` | `c24189e23ea1c12c` |
| `retrieval_result_count` | **5** |
| `retrieval_metadata_filter` | `ticket_label=fund`, `route_label=billing_review` |
| `retrieval_sandbox_only` | **true** |
| `retrieval_activated` | **false** |
| `downstream_consumed_retrieval` | **false** |
| `namespace` | `vendor_ticket_real_pilot_balanced` |
| `index_version` | `pilot_balanced_v1` |

**Not recorded here:** raw query text, retrieved content, transcripts, vectors, embeddings, API keys, per-hit `record_id` lists, or tool `results` payloads.

---

## Governance conclusions

1. **Shadow node works in the LangGraph path** when the flag is enabled locally — graph completes with sanitized `retrieval_*` metadata written.
2. **Policy gate runs before retrieval** — fund metadata-filtered routing matches dry-run chain behavior (Step 132).
3. **State remains sanitized** — aggregate fields only; no hits stored on `CommerceAIState`.
4. **Downstream did not consume retrieval** — `vendor_ticket_node` uses existing `retrieved_context` / RAG path only; draft/final not driven by sandbox `retrieval_*`.
5. **No runtime activation** — `retrieval_activated=false`.
6. **Flag default false** — repository and CI behavior unchanged; shadow is opt-in locally only.
7. **No production `RAG_PROFILE` changes** — `retrieve_context` unchanged.
8. **No customer-facing retrieval** — no API or customer-visible behavior change.

This smoke test **does not** approve non-shadow consumption of retrieval metadata in drafting, HITL UI, or customer channels.

---

## Related documentation

- Shadow replay JSONL export — `scripts/export_shadow_replay_jsonl.py` → `reports/shadow_replay_*.jsonl` (Step 137; gitignored)
- Shadow replay metrics dashboard — `scripts/build_shadow_retrieval_metrics_dashboard.py` → `reports/shadow_retrieval_metrics_dashboard.md` (Step 136; gitignored)
- [Shadow replay metrics report](shadow_replay_metrics_report.md) — Step 138 local 166-ticket batch governance summary
- Step 140 shadow replay export hardening — `route_label`, `retrieval_result_count`, `executor_called` in export JSONL
- Step 141 hit-count diagnosis — `scripts/diagnose_shadow_replay_hits.py` (export `review_priority` vs index mismatch)
- Step 142 export filter alignment — shadow export uses `ticket_label` + `route_label` only in `retrieval_metadata_filter`
- [Shadow replay metrics refresh report](shadow_replay_metrics_refresh_report.md) — Step 143 corrected batch metrics
- [LangGraph sandbox retrieval node plan](langgraph_sandbox_retrieval_node_plan.md)
- [LangGraph retrieval integration plan](langgraph_retrieval_integration_plan.md)
- [Dry-run retrieval chain smoke test report](dry_run_retrieval_chain_smoke_test_report.md)
- [Retrieval policy gate contract](retrieval_policy_gate_contract.md)
- [Sandbox retrieval tool smoke test report](sandbox_retrieval_tool_smoke_test_report.md)
