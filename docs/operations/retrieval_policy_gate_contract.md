# Retrieval Policy Gate Contract

**Status:** Contract only (Step 129) — **no** LangGraph node, **no** retrieval execution  
**Governance:** `recommended_decision = retrieval_ready_for_sandbox_tooling_review` (Step 124)  
**Audience:** LangGraph workflow owners, retrieval governance, sandbox operators

---

## Purpose

Define a **minimal pre-retrieval policy gate** that decides whether sandbox retrieval is **allowed**, **denied**, or **skipped** before any pgvector search or query embedding.

The gate sits **upstream** of `execute_sandbox_retrieval_tool` (Step 126) and implements the “policy before search” rule from the [LangGraph retrieval integration plan](langgraph_retrieval_integration_plan.md) (Step 128).

**This step does not:** wire LangGraph, call pgvector, call OpenAI, change `RAG_PROFILE`, or set `retrieval_activated=true`.

**Code:** `app/corpus_planning/retrieval_policy_gate.py`  
**Tests:** `tests/test_retrieval_policy_gate.py`  
**Synthetic calibration (Step 139):** `evals/retrieval_policy_gate/policy_gate_calibration_cases.json`, `scripts/eval_retrieval_policy_gate.py`, [calibration report](retrieval_policy_gate_calibration_report.md)

---

## Decision types

| `RetrievalGateDecision` | Meaning |
|-------------------------|---------|
| `allow` | May proceed to sandbox retrieval executor with `required_metadata_filter` |
| `skip` | Do not search; workflow continues without retrieval (e.g. missing label) |
| `deny` | Do not search; policy violation (unsafe scope, missing filter, bounds) |

---

## Scenarios

| `RetrievalScenario` | `ticket_label` |
|---------------------|----------------|
| `vendor_support` | `support` |
| `complaint_review` | `complaint` |
| `fund_finance` | `fund` |
| `unknown` | missing or unrecognized |

---

## Gate rules (deterministic)

Evaluated by `evaluate_retrieval_policy_gate(input) -> RetrievalPolicyGateResult`.

| Rule | Outcome |
|------|---------|
| `sandbox_only` is not `true` | **deny** |
| `namespace` not approved sandbox pilot | **deny** |
| `index_version` does not start with `pilot_` | **deny** |
| `requested_top_k` outside **1–10** | **deny** |
| `ticket_label` missing or unknown | **skip** |
| No `metadata_filter` | **deny** (all labels; fund explicitly blocked for vector-only) |
| `metadata_filter.ticket_label` missing | **deny** |
| Filter label ≠ workflow `ticket_label` | **deny** |
| `support` + filter `ticket_label=support` | **allow** |
| `complaint` + filter `ticket_label=complaint` | **allow** |
| `fund` + filter `ticket_label=fund` | **allow** if route gate passes |
| `fund` + `route_label` provided and ≠ `billing_review` | **deny** |
| `retrieval_activated` on result | always **false** |
| `sandbox_only` on result | always **true** |

Approved sandbox namespaces match the retrieval tool validators (`vendor_ticket_real_pilot*`, `vendor_ticket_real_pilot_balanced`).

---

## Metadata filter requirements

| Label | Required filter |
|-------|-----------------|
| `support` | `metadata_filter.ticket_label == "support"` |
| `complaint` | `metadata_filter.ticket_label == "complaint"` |
| `fund` | `metadata_filter.ticket_label == "fund"` |

Optional filter fields (`route_label`, `review_priority`) may be present on the filter model but **ticket_label match is mandatory** for allow.

**Fund route gate:** when `route_label` is set on gate input, it must be `billing_review`.

**No unrestricted semantic search:** absent or mismatched `metadata_filter.ticket_label` → **deny** (not allow).

---

## Sandbox-only rule

- Input `sandbox_only` must be `true` or the gate **denies**.
- Output `sandbox_only` is always `true`.
- Output `retrieval_activated` is always `false` (enforced on `RetrievalPolicyGateResult` model).

---

## No runtime activation

| Boundary | Status |
|----------|--------|
| LangGraph node | **Not implemented** |
| pgvector / OpenAI | **Not called** by gate |
| Production `RAG_PROFILE` | **Unchanged** |
| Customer-facing retrieval | **Not approved** |
| Autonomous retrieval loops | **Not approved** |

---

## Future LangGraph usage (not Step 129)

When separately approved:

1. Build `RetrievalPolicyGateInput` from `CommerceAIState` (routing fields only).
2. Call `evaluate_retrieval_policy_gate`.
3. `apply_retrieval_gate_result_to_state` (`app/state/retrieval_state.py`) — aggregate-safe gate fields only.
4. On `allow` → build `RetrievalToolRequest` using `required_metadata_filter`.
5. On `skip` / `deny` → skip `execute_sandbox_retrieval_tool`; append audit reasons.

**Operator dry-run (Step 131):** `scripts/dry_run_sandbox_retrieval_chain.py` runs gate → optional executor → `sanitize_retrieval_state_snapshot` without LangGraph.  
**Chain smoke test (Step 132):** [dry-run retrieval chain smoke test report](dry_run_retrieval_chain_smoke_test_report.md) — aggregate-safe snapshot metrics only.  
**LangGraph shadow node (Step 133):** [LangGraph sandbox retrieval node plan](langgraph_sandbox_retrieval_node_plan.md) — plan only; gate-first; flag default off.

Feature flag `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED` remains **false** until a later implementation step.

---

## Related documentation

- [Retrieval policy gate calibration report](retrieval_policy_gate_calibration_report.md) — Step 139 synthetic allow/skip/deny fixtures
- [Shadow replay metrics report](shadow_replay_metrics_report.md) — Step 138 real-ticket shadow batch
- [LangGraph sandbox retrieval node plan](langgraph_sandbox_retrieval_node_plan.md)
- [Dry-run retrieval chain smoke test report](dry_run_retrieval_chain_smoke_test_report.md)
- [LangGraph retrieval integration plan](langgraph_retrieval_integration_plan.md)
- [Sandbox retrieval tool contract](sandbox_retrieval_tool_contract.md)
- [Sandbox retrieval tool smoke test report](sandbox_retrieval_tool_smoke_test_report.md)
- [Pilot retrieval evaluation report](pilot_retrieval_evaluation_report.md)
