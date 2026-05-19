# LangGraph Sandbox Retrieval Node Plan

**Status:** Plan (Step 133) + shadow node implemented (Step 134) + local smoke test (Step 135) — default flag **false**  
**Governance:** `recommended_decision = retrieval_ready_for_sandbox_tooling_review` (Step 124)  
**Audience:** LangGraph workflow owners, retrieval governance, HITL reviewers, platform ops

---

## Purpose

Define a **future, feature-flagged LangGraph node** that runs the validated sandbox retrieval chain in **shadow mode**:

1. Retrieval policy gate  
2. Sandbox retrieval executor (if allowed)  
3. Retrieval state helpers  
4. Sanitized retrieval state snapshot fields  

The node records **aggregate-safe metadata only** for governance and replay analysis. It does **not** change draft/final responses, approval behavior, or customer-visible behavior in the shadow phase.

**This step does not:** add node code, modify graph edges, enable flags by default, call pgvector/OpenAI from the graph when the flag is off, or change production `RAG_PROFILE`.

**Validated chain reference:** [dry-run retrieval chain smoke test report](dry_run_retrieval_chain_smoke_test_report.md) (Step 132).

---

## Current readiness

| Prerequisite | Status |
|--------------|--------|
| Retrieval policy gate contract | **Defined** (Step 129) |
| Sandbox retrieval tool contract + executor | **Defined / implemented** (Steps 125–126) |
| Retrieval state fields + helpers | **Defined** (Step 130) |
| Gate → executor → state dry-run CLI | **Implemented** (Step 131) |
| Dry-run chain smoke test | **Passed** (Step 132) |
| LangGraph integration plan | **Defined** (Step 128) |
| Existing `retrieve_context` node | **Unchanged** — production/mock RAG path |
| `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED` | **Implemented** — default **false** (`app/config.py`) |
| `retrieval_activated` (runtime) | **false** |
| Shadow replay JSONL export | **Implemented** (Step 137) — `scripts/export_shadow_replay_jsonl.py` |
| Shadow replay metrics dashboard | **Implemented** (Step 136) — `scripts/build_shadow_retrieval_metrics_dashboard.py` |
| Shadow replay metrics report (166-ticket batch) | **Recorded** (Step 138) — [shadow replay metrics report](shadow_replay_metrics_report.md) |

---

## Non-goals (Step 133)

| Non-goal | Policy |
|----------|--------|
| Implement LangGraph node in Step 133 | **Plan only** |
| Modify `retrieve_context` / `RAG_PROFILE` | **Blocked** |
| Enable feature flag by default | **Blocked** — default **false** |
| Use retrieval hits in draft/final response | **Blocked** in shadow mode |
| Customer-facing retrieval | **Blocked** |
| Expose retrieved content to operators in UI | **Blocked** in shadow v1 |
| Autonomous retrieval loops | **Blocked** |
| Vector-only unrestricted fallback | **Blocked** |
| pgvector schema / re-index / embeddings | **Blocked** |

---

## Shadow-mode architecture

When `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=true` (operator/dev only, separate approval):

```
normalize_request
  → route_workflow
  → [sandbox_retrieve_pilot_shadow]   ← NEW (parallel shadow; see placement)
  → retrieve_context                  ← EXISTING (unchanged RAG_PROFILE path)
  → vendor_ticket_node                ← MUST NOT read sandbox retrieval_* for drafting
  → … review / validate / approval …
```

**Shadow-mode rules:**

| Rule | Requirement |
|------|-------------|
| Feature flag | Node body runs **only** when `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=true` |
| Default flag | **false** — zero sandbox retrieval side effects |
| State writes | Sanitized `retrieval_*` fields only (see below) |
| Draft / final | **No** consumption of sandbox hits or `retrieved_context` from sandbox path |
| Customer visibility | **No** change to API responses or outbound messages |
| Existing RAG | `retrieve_context` continues on current `RAG_PROFILE` / mock path |

---

## Feature flag design

| Flag | Default | Effect |
|------|---------|--------|
| `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED` | **false** | Master switch for shadow node execution |
| `RETRIEVAL_SANDBOX_ONLY` | **true** (when node runs) | Forces sandbox namespace/index validators |
| `RETRIEVAL_REQUIRE_METADATA_FILTER` | **true** | No vector-only open search in node |

**Step 133 does not add env parsing or wire flags into the graph.** Implementation step must read flags at node entry and no-op when false.

Optional future flags (not in Step 133): `LANGGRAPH_SANDBOX_RETRIEVAL_BLOCK_ON_ERROR` (default **false** — workflow continues).

---

## Node placement proposal

**Recommended (conservative):** add a **new** node `sandbox_retrieve_pilot_shadow` immediately **after** `route_workflow` and **before** `vendor_ticket_node`, without removing or replacing `retrieve_context`.

| Position | Rationale |
|----------|-----------|
| After `normalize_request` / `route_workflow` | `ticket_label`, `route_label`, and routing metadata available for policy gate |
| Before `vendor_ticket_node` | Intent/routing settled; shadow run does not alter drafter inputs in v1 |
| Parallel to `retrieve_context` | Existing RAG path unchanged; avoids mixing production profile with sandbox executor |

**Proposed edge pattern (implementation step):**

```
route_workflow → sandbox_retrieve_pilot_shadow → retrieve_context → vendor_ticket_node
```

Alternative (not recommended for v1): run shadow **after** `retrieve_context` — higher risk of confusion in observability; keep sandbox path clearly labeled in audit.

---

## Node input / output contract (proposal)

**Node name:** `sandbox_retrieve_pilot_shadow`  
**Does not exist in codebase until Step 134+.**

### Inputs (from `CommerceAIState` + config)

| Source | Fields |
|--------|--------|
| State | `ticket_label`, `route_label`, `review_priority`, `detected_intent` |
| State (query source) | Bounded text from routing context — **not** logged raw; hash only in state |
| Config (frozen pilot) | `namespace`, `index_version` — e.g. balanced pilot constants |
| Config | `top_k` cap ≤ policy gate max (10) |
| Flag | `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED` |

### Outputs (state writes only)

| Field | Content |
|-------|---------|
| `retrieval_gate_decision` | `allow` / `skip` / `deny` |
| `retrieval_scenario` | e.g. `fund_finance` |
| `retrieval_policy_reasons` | Audit-safe strings |
| `retrieval_query_hash` | Set only if executor ran |
| `retrieval_result_count` | Aggregate count only |
| `retrieval_metadata_filter` | Allowlisted dict |
| `retrieval_sandbox_only` | **true** |
| `retrieval_activated` | **false** |

**Explicitly not written:** raw query, hit bodies, `record_id` lists, vectors, `results[]`, changes to `final_response`, `retrieved_context` (sandbox path), or `rag_sources` from sandbox executor.

### Delegation (implementation must mirror dry-run CLI)

```text
if not LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED: return state unchanged

build RetrievalPolicyGateInput → evaluate_retrieval_policy_gate
apply_retrieval_gate_result_to_state

if decision != allow: return state  # no executor, no OpenAI

build RetrievalToolRequest → execute_sandbox_retrieval_tool(profile=...)
apply_retrieval_tool_response_to_state   # hash + count only

append audit_log entry from sanitize_retrieval_state_snapshot slice
```

Reuse: `app/corpus_planning/retrieval_policy_gate.py`, `sandbox_retrieval_tool.py`, `app/state/retrieval_state.py`, `sandbox_retrieval_chain_dry_run.py` patterns.

---

## Retrieval policy gate usage

| Step | Behavior |
|------|----------|
| 1 | Build `RetrievalPolicyGateInput` from state + pilot namespace/index constants |
| 2 | `evaluate_retrieval_policy_gate` — **always** before store/embedding |
| 3 | `skip` / `deny` → no executor; safe reasons on state; workflow continues |
| 4 | `allow` → proceed with `required_metadata_filter` only |

Same rules as [retrieval policy gate contract](retrieval_policy_gate_contract.md) — no graph-specific relaxations in shadow mode.

---

## Failure fallback

| Condition | Behavior |
|-----------|----------|
| Flag off | No-op; state unchanged for retrieval_* |
| Gate `skip` | No executor; reasons on state; **continue** workflow |
| Gate `deny` | No executor; reasons on state; **continue** workflow |
| Executor / DB / embedding error | Append safe `ToolError` + `retrieval_policy_reasons`; **do not** block workflow unless future flag explicitly enabled |
| Empty hits | `retrieval_result_count=0`; continue |
| Forbidden output | Fail closed for sandbox slice; strip; never inject mock content into drafter |

**Never:** fallback to vector-only unrestricted retrieval; never set `retrieval_activated=true` in shadow v1.

---

## Audit and snapshot behavior

| Requirement | Detail |
|-------------|--------|
| Audit payload | `sanitize_retrieval_state_snapshot(state)` JSON slice only |
| Query privacy | `retrieval_query_hash` only |
| Trace correlation | `request_id`, `ticket_id`, `room_id` — no message bodies |
| LangSmith | Tag run as `sandbox_retrieval_shadow=true` (implementation step) |
| Committed artifacts | No raw query or hits in git |

---

## HITL boundaries

| Boundary | Shadow v1 rule |
|----------|----------------|
| Draft generation | `vendor_ticket_node` **must not** read sandbox `retrieval_*` or sandbox hits |
| Human approval | Unchanged — retrieval metadata does not auto-approve |
| Reviewer UI | **No** display of sandbox hits until separate UI approval |
| Customer | **No** exposure of retrieval metadata in customer channels |
| QA attention | May force gate `skip` via policy (implementation config) |

---

## Eval gates before non-shadow activation

Shadow mode may run locally/staging only after:

| Gate | Requirement |
|------|-------------|
| Dry-run chain smoke | **Passed** — Step 132 |
| Executor smoke | **Passed** — Step 127 |
| Metadata-filtered fund eval | pass_rate ≥ **1.0** on fund compare subset |
| Policy + state contracts | Unit tests green |
| Explicit governance sign-off | Separate from shadow enable |

**Non-shadow activation** (using retrieval in drafter/HITL/customer paths) requires additional gates not defined here: production index, security review, `retrieval_activated` promotion plan, and `RAG_PROFILE` decision.

---

## Required future implementation constraints (Step 134+)

The implementation **must**:

1. Call `evaluate_retrieval_policy_gate` **first**  
2. Call `execute_sandbox_retrieval_tool` **only** if decision is `allow`  
3. Use `apply_retrieval_gate_result_to_state` and `apply_retrieval_tool_response_to_state`  
4. Store only: `query_hash`, `result_count`, `decision`, `reasons`, `scenario`, `metadata_filter`  
5. Keep `retrieval_activated=false` and `retrieval_sandbox_only=true`  
6. Default `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=false`  
7. Leave `retrieve_context` and production `RAG_PROFILE` **unchanged**  
8. Not alter `final_response` or approval nodes based on sandbox retrieval  

---

## Explicit governance statements (Step 133)

| Statement | Status |
|-----------|--------|
| Shadow node code (`sandbox_retrieve_pilot_shadow`) | **Yes** (Step 134) — flag default off |
| Shadow node operational smoke test | **Passed** (Step 135) — [smoke test report](langgraph_shadow_retrieval_smoke_test_report.md) |
| Shadow replay metrics dashboard | **Implemented** (Step 136) — `scripts/build_shadow_retrieval_metrics_dashboard.py` |
| Shadow mode — no draft/final consumption | **Yes** |
| Default flag false | **Yes** |
| No runtime `retrieval_activated` | **Yes** |
| No production `RAG_PROFILE` change | **Yes** |
| No customer-facing retrieval | **Yes** |
| No LangGraph wiring in Step 133 | **Yes** |

---

## Related documentation

- [LangGraph shadow retrieval smoke test report](langgraph_shadow_retrieval_smoke_test_report.md) — Step 135 local graph smoke test
- `scripts/export_shadow_replay_jsonl.py` — Step 137 sanitized shadow replay JSONL export (gitignored `reports/`)
- `scripts/build_shadow_retrieval_metrics_dashboard.py` — Step 136 offline aggregate dashboard (gitignored `reports/`)
- [Shadow replay metrics report](shadow_replay_metrics_report.md) — Step 138 local batch governance summary
- [LangGraph retrieval integration plan](langgraph_retrieval_integration_plan.md)
- [Dry-run retrieval chain smoke test report](dry_run_retrieval_chain_smoke_test_report.md)
- [Retrieval policy gate contract](retrieval_policy_gate_contract.md)
- [Sandbox retrieval tool contract](sandbox_retrieval_tool_contract.md)
- [Sandbox retrieval tool smoke test report](sandbox_retrieval_tool_smoke_test_report.md)
