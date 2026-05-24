# LangGraph Retrieval Integration Plan

**Status:** Planning only (Step 128) — **no implementation in this step**  
**Governance:** `recommended_decision = retrieval_ready_for_sandbox_tooling_review` (Step 124)  
**Audience:** AI Commerce OS platform, LangGraph workflow owners, retrieval governance, HITL reviewers

---

## Purpose

Define a **future, governed path** for wiring sandbox-validated retrieval into the vendor-ticket LangGraph workflow **without** activating production retrieval in this step.

This document answers:

- What is **ready today** (sandbox stack)
- What remains **forbidden** until separate approvals
- How a future LangGraph retrieval node should **delegate** to the Step 125–126 contract
- Which **gates** (eval, policy, HITL, feature flags) must pass before any runtime activation

**This step does not add graph nodes, change `RAG_PROFILE`, register agent tools, or expose customer APIs.**

---

## Current readiness state

| Layer | Status | Evidence |
|-------|--------|----------|
| Balanced pilot corpus | **Ready** (local) | `vendor_ticket_real_pilot_balanced` — [balanced pilot corpus rebuild](balanced_pilot_corpus_rebuild.md) |
| OpenAI embeddings | **Ready** (local) | Artifacts under gitignored `artifacts/embeddings/` |
| pgvector sandbox index | **Ready** (local) | `vendor_ticket_real_pilot_balanced` / `pilot_balanced_v1` |
| Offline retrieval eval | **Passed** (fund gate) | [pilot retrieval evaluation report](pilot_retrieval_evaluation_report.md) — metadata_filtered **1.0** on fund compare subset |
| Metadata-filtered routing gate | **Operational** | Eval + executor path |
| Retrieval tool contract | **Defined** | [sandbox retrieval tool contract](sandbox_retrieval_tool_contract.md) |
| Sandbox retrieval executor | **Implemented** | `execute_sandbox_retrieval_tool` + CLI |
| Local smoke test | **Passed** | [sandbox retrieval tool smoke test report](sandbox_retrieval_tool_smoke_test_report.md) |
| LangGraph retrieval wiring | **Not implemented** | `retrieve_context` uses existing `RAG_PROFILE` / mock — **unchanged** |
| `retrieval_activated` (runtime) | **false** | Workflow + tool responses |
| Production `RAG_PROFILE` | **Unchanged** | No promotion in Step 128 |

---

## Non-goals (Step 128 and default until explicit approval)

| Non-goal | Policy |
|----------|--------|
| Implement LangGraph retrieval in this step | **Plan only** |
| Add or modify graph nodes | **Blocked** |
| Enable production `RAG_PROFILE` | **Blocked** |
| Register autonomous retrieval tools | **Blocked** |
| Add FastAPI / customer endpoints | **Blocked** |
| Customer-facing retrieval | **Blocked** |
| Unrestricted semantic search | **Blocked** — metadata-filtered path required for routing scenarios |
| Autonomous retrieval loops | **Blocked** — no self-triggered re-query without policy gate |
| pgvector schema changes | **Blocked** |
| Re-index / regenerate embeddings | **Blocked** |
| Raw transcript or vector exposure in graph state | **Blocked** |

---

## Proposed future architecture

High-level flow when integration is **separately approved** (not built in Step 128):

```
Vendor ticket graph
  → normalize / route (existing)
  → [RETRIEVAL POLICY GATE]     ← new: allow/deny/skip + scenario
  → [SANDBOX RETRIEVAL NODE]    ← new: calls execute_sandbox_retrieval_tool
  → map hits → aggregate grounding (no raw content)
  → specialist / drafter (existing, HITL-gated)
  → audit + trace (existing)
```

**Design principles:**

1. **Thin node** — LangGraph node builds `RetrievalToolRequest`, calls sandbox executor, maps `RetrievalToolResponse` into state; no direct pgvector or OpenAI calls in the node.
2. **Policy before search** — Retrieval policy gate runs **before** any embedding or store access.
3. **Metadata-first routing** — Default eval mode for workflow routing: `metadata_filtered` with `ticket_label` / `route_label` from routing state, not vector-only open search.
4. **Fail closed** — On policy deny, validation failure, or store error → skip retrieval, set `retrieval_activated=false`, append audit entry; do not fall back to unrestricted search.
5. **Parity with sandbox CLI** — Same namespace/index/profile validators as Step 125–126.

**Out of scope for first integration slice:** hybrid rerankers, multi-index fusion, cross-namespace search, streaming hits, production DB hosts.

---

## Retrieval policy gate (proposal)

A dedicated **pre-retrieval** gate (function or mini-node) evaluates whether retrieval may run for the current turn.

| Input (from state) | Use |
|--------------------|-----|
| `workflow_type` | Allowlist: vendor-ticket workflows only in v1 |
| `ticket_label`, `route_label`, `review_priority` | Drive metadata filter + scenario |
| `workflow_status`, `human_approval_required` | May force skip or HITL-only path |
| Feature flags (see below) | Global kill switch |
| `retrieval_activated` (requested) | Must remain false until governance promotes |

| Output | Meaning |
|--------|---------|
| `retrieval_allowed: false` | Skip retrieval node; no store access |
| `retrieval_allowed: true` | Proceed with bounded `RetrievalToolRequest` |
| `retrieval_scenario: <enum>` | Selects allowed scenario template (see below) |
| `retrieval_skip_reason: str` | Audit-safe reason (no PII) |

**Hard rules:**

- Gate returns `retrieval_allowed=false` if feature flag off, sandbox-only flag off, or eval gates not met.
- Gate returns `retrieval_allowed=false` if metadata filter cannot be derived (no `ticket_label` for routing scenario).
- Gate **never** sets `retrieval_activated=true` in sandbox phase.

---

## Allowed retrieval scenarios (future)

| Scenario ID | When | Filter | eval_mode | top_k cap |
|-------------|------|--------|-----------|-----------|
| `pilot_routing_grounding` | After route decision; need similar prior tickets for grounding summary | `ticket_label` + optional `route_label` | `metadata_filtered` | ≤ 5 |
| `pilot_review_priority_hint` | Review queue enrichment only | `review_priority` + `ticket_label` | `metadata_filtered` | ≤ 3 |
| `pilot_operator_debug` | Explicit operator/debug flag only; not customer | As CLI | `metadata_filtered` | ≤ 5 |

All scenarios: sandbox namespace/index from **config or frozen pilot constants**, not from LLM-generated filters.

---

## Forbidden retrieval scenarios

| Scenario | Why forbidden |
|----------|----------------|
| Open semantic search (no metadata filter) | Wrong-label risk; eval showed vector-only gaps |
| Customer / vendor self-serve lookup | No customer-facing retrieval |
| Autonomous multi-hop retrieval | Unbounded loops; no policy contract yet |
| Cross-namespace / production index | Sandbox scope only |
| Retrieval on every graph step | Cost, leakage, and noise |
| Returning raw `content`, transcripts, or vectors into state | Contract violation |
| Agent tool registration without HITL | Autonomous retrieval not approved |
| Production host / shared staging DB | Sandbox host policy |

---

## LangGraph node contract proposal

**Node name (proposal):** `sandbox_retrieve_pilot_context`  
**Does not exist in codebase until a later implementation step.**

### Inputs (from `CommerceAIState` + gate output)

| Field | Source |
|-------|--------|
| Query text | Derived from `user_input` or bounded `grounding_summary` — never logged raw in audit |
| `namespace`, `index_version` | Config / pilot constants |
| `metadata_filter` | From gate (`ticket_label`, `route_label`, `review_priority` only) |
| `top_k` | Gate cap |
| `eval_mode` | `metadata_filtered` default for routing scenarios |

### Outputs (written to state)

| Field | Content |
|-------|---------|
| `retrieval_activated` | **false** (sandbox phase) |
| `retrieval_sandbox_only` | **true** |
| `retrieval_query_hash` | From `RetrievalToolResponse` |
| `retrieval_hits` | List of contract-safe hits: `record_id`, `score`, labels only |
| `retrieved_context` | **Aggregate grounding only** — no indexed document bodies |
| `rag_sources` | Record IDs + labels; no content snippets in v1 |
| `errors` | On failure, `ToolError` with safe message |

### Delegation

```text
RetrievalToolRequest → execute_sandbox_retrieval_tool(store, query_embedding_fn)
                    → RetrievalToolResponse → map to state (strip forbidden keys)
```

Reuse: `retrieval_tool_models.py`, `retrieval_tool_validation.py`, `sandbox_retrieval_tool.py`.

**Do not** call `retrieve_for_workflow` / production semantic path from this node until a separate production promotion plan exists.

---

## State fields (Step 130 contract)

Additive optional fields on `CommerceAIState` (`app/state/commerce_state.py`):

| Field | Type | Default / notes |
|-------|------|-----------------|
| `retrieval_gate_decision` | `str \| None` | `allow` / `skip` / `deny` from policy gate |
| `retrieval_scenario` | `str \| None` | e.g. `fund_finance` |
| `retrieval_policy_reasons` | `list[str]` | `[]` |
| `retrieval_query_hash` | `str \| None` | Audit fingerprint only — **no raw query** |
| `retrieval_result_count` | `int \| None` | Aggregate hit count |
| `retrieval_metadata_filter` | `dict[str, str] \| None` | Allowlisted keys only |
| `retrieval_sandbox_only` | `bool` | **true** |
| `retrieval_activated` | `bool` | **false** |

**Helpers:** `app/state/retrieval_state.py` — `apply_retrieval_gate_result_to_state`, `apply_retrieval_tool_response_to_state`, `sanitize_retrieval_state_snapshot` (no hit bodies, vectors, or transcripts in state).

Existing fields (`retrieved_context`, `rag_sources`, `audit_log`) remain unchanged by Step 130; future nodes must not populate them with raw indexed content.

---

## Failure fallback behavior

| Condition | Behavior |
|-----------|----------|
| Policy gate deny | Skip retrieval; `retrieval_hits=[]`; continue workflow without RAG |
| Validation error (request) | Skip retrieval; append `ToolError`; **no** retry with relaxed filters |
| Store / DB unreachable | Skip retrieval; audit `retrieval_store_unavailable`; **no** mock content injection unless existing mock RAG path explicitly enabled for dev |
| Embedding failure | Skip retrieval; do not call pgvector |
| Empty hits | Continue; specialist may proceed with routing-only context; flag low grounding in trace |
| Forbidden output detected | Treat as bug; strip fields; fail closed for retrieval slice |

**Explicitly not allowed:** falling back from `metadata_filtered` to unfiltered vector search to “get something back.”

---

## Audit and logging requirements

| Requirement | Detail |
|-------------|--------|
| Query privacy | Log `query_hash` only in committed traces/reports |
| Hit privacy | Log `record_id`, `score`, `ticket_label`, `route_label`, `review_priority` only |
| No content | Never log indexed `content`, transcripts, or embedding arrays |
| Activation flag | Every retrieval attempt logs `retrieval_activated=false` during sandbox phase |
| Scenario + gate | Log `retrieval_scenario`, `retrieval_allowed`, `retrieval_skip_reason` |
| Namespace scope | Log `namespace`, `index_version` (pilot constants) |
| Correlation | `request_id`, `ticket_id`, `room_id` where present — no message bodies |

Align with existing `audit_log: list[AuditLogEntry]` on `CommerceAIState`.

---

## HITL boundaries

| Boundary | Rule |
|----------|------|
| Draft / send | Retrieval hits **do not** auto-approve replies; existing HITL and `human_approval_required` unchanged |
| QA attention | Tickets with `qa_requires_human_attention` may skip retrieval or require reviewer-only scenarios |
| Low confidence | If routing confidence below threshold → skip retrieval or HITL-only path (gate config) |
| Customer visibility | Retrieved metadata never exposed directly to end customers |
| Operator override | Debug retrieval only via explicit sandbox flags + operator role — not in MVP customer API |

Retrieval is **assistive grounding** for internal draft/routing, not a substitute for human review on high-risk fund/complaint paths.

---

## Feature flag and sandbox-only rollout

| Flag (proposal) | Default | Effect |
|-----------------|---------|--------|
| `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED` | **false** | Master switch for pilot retrieval node |
| `RETRIEVAL_SANDBOX_ONLY` | **true** | Forces sandbox namespace/index validators |
| `RETRIEVAL_REQUIRE_METADATA_FILTER` | **true** | Deny vector-only open search in workflow |
| `RAG_PROFILE` | **unchanged** | Production profile not switched by sandbox flags |

Rollout order (future):

1. Local dev with flags on + sandbox DB  
2. Internal replay / shadow mode (retrieval runs, results not shown to customer)  
3. HITL-visible grounding in reviewer UI (separate UI approval)  
4. Production profile promotion (separate governance doc)

---

## Eval gates required before any activation

All must pass or be explicitly waived by governance **before** `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=true`:

| Gate | Threshold (pilot) | Source |
|------|-------------------|--------|
| Metadata-filtered fund routing | pass_rate ≥ **1.0** on fund compare subset | Step 123–124 eval |
| Sandbox executor smoke | **Passed** | Step 127 report |
| Contract output safety | No forbidden fields in tests | `test_retrieval_tool_contract.py`, `test_sandbox_retrieval_tool.py` |
| No scope pins in eval filters | Enforced | eval v4 loader |
| Full compare suite (optional) | Documented pass rates | `eval_pilot_retrieval.py --compare-modes` |
| Human review of wallet vector edge | Optional waiver for vector-only | `pilot-fund-wallet-fa-016` |

**Production activation** requires additional gates not defined here: production index, security review, customer API prohibition re-confirmed, and `RAG_PROFILE` promotion plan.

---

## Explicit governance statements (Step 128)

| Statement | Status |
|-----------|--------|
| No production activation in Step 128 | **Yes** — plan only |
| No autonomous retrieval loops | **Yes** — policy gate + single-shot retrieval per turn |
| No unrestricted semantic search | **Yes** — metadata-filtered default |
| No customer-facing retrieval | **Yes** |
| No LangGraph wiring in Step 128 | **Yes** — no nodes added |
| `retrieval_activated` remains false | **Yes** until separate approval |
| Production `RAG_PROFILE` unchanged | **Yes** |

---

## Implementation checklist (future steps — not executed in Step 128)

1. **Retrieval policy gate contract** — **Defined** (Step 129) — [retrieval policy gate contract](retrieval_policy_gate_contract.md); `evaluate_retrieval_policy_gate` in `app/corpus_planning/retrieval_policy_gate.py`  
2. **LangGraph state fields contract** — **Defined** (Step 130) — `CommerceAIState` + `app/state/retrieval_state.py`  
3. **Gate + executor CLI dry-run** — **Implemented** (Step 131) — `scripts/dry_run_sandbox_retrieval_chain.py` (not LangGraph)  
4. **Dry-run chain smoke test** — **Passed** (Step 132) — [dry-run retrieval chain smoke test report](dry_run_retrieval_chain_smoke_test_report.md)  
5. **Sandbox retrieval node plan (shadow)** — **Defined** (Step 133) — [LangGraph sandbox retrieval node plan](langgraph_sandbox_retrieval_node_plan.md)  
6. **Sandbox retrieval node implementation** — **Implemented** (Step 134) — `sandbox_retrieve_pilot_shadow`; default flag off  
7. **Shadow node operational smoke test** — **Passed** (Step 135) — [smoke test report](langgraph_shadow_retrieval_smoke_test_report.md)  
8. **Wire node behind feature flags** — default off  
9. **Replay eval with graph shadow** — **Recorded** (Steps 137–138) — [shadow replay metrics report](shadow_replay_metrics_report.md); aggregate metrics only  
10. **Policy gate synthetic calibration** — **Passed** (Step 139) — [calibration report](retrieval_policy_gate_calibration_report.md); no retrieval execution  
11. **HITL / reviewer UI contract** — **Governance plan defined** (Step 144) — [non-shadow retrieval consumption governance plan](non_shadow_retrieval_consumption_governance_plan.md); HITL-only visibility is the **only** lane that may be considered next; implementation **not approved**  
12. **Vendor ticket AI assist (shadow)** — **Evaluator + LangGraph node + metrics** (Steps 145–149) — [workflow](vendor_ticket_ai_assist_shadow_workflow.md), [metrics report](ai_assist_shadow_metrics_report.md); flag default **false**; **no** HITL UI, **no** customer send  
13. **HITL read-only visibility** — **Contract defined** (Step 150) — [HITL read-only visibility contract](hitl_read_only_visibility_contract.md); UI **not** implemented  
14. **Production promotion plan** — separate from this document  

---

## Related documentation

- [HITL read-only visibility contract](hitl_read_only_visibility_contract.md) — Step 150
- [AI assist shadow metrics report](ai_assist_shadow_metrics_report.md) — Step 149 validated assist replay batch
- [Vendor ticket AI assist shadow workflow](vendor_ticket_ai_assist_shadow_workflow.md) — Steps 145–148 shadow HITL assist
- [Non-shadow retrieval consumption governance plan](non_shadow_retrieval_consumption_governance_plan.md) — Step 144 HITL-only consumption gates (plan only)
- [LangGraph sandbox retrieval node plan](langgraph_sandbox_retrieval_node_plan.md) — Steps 133–134 shadow node
- [LangGraph shadow retrieval smoke test report](langgraph_shadow_retrieval_smoke_test_report.md) — Step 135
- [Shadow replay metrics report](shadow_replay_metrics_report.md) — Step 138 local 166-ticket batch
- [Retrieval policy gate calibration report](retrieval_policy_gate_calibration_report.md) — Step 139 synthetic edge cases
- [Dry-run retrieval chain smoke test report](dry_run_retrieval_chain_smoke_test_report.md) — Step 132 local chain validation
- [Retrieval policy gate contract](retrieval_policy_gate_contract.md) — Step 129 pre-search gate
- [Sandbox retrieval tool contract](sandbox_retrieval_tool_contract.md)
- [Sandbox retrieval tool smoke test report](sandbox_retrieval_tool_smoke_test_report.md)
- [Pilot retrieval evaluation report](pilot_retrieval_evaluation_report.md)
- [Pilot retrieval failure analysis](pilot_retrieval_failure_analysis.md)
- [Balanced pilot corpus rebuild](balanced_pilot_corpus_rebuild.md)
- [PgVector sandbox indexing plan](pgvector_sandbox_indexing_plan.md)
