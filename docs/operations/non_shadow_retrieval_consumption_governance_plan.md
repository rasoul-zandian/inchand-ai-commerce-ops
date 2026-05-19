# Non-Shadow Retrieval Consumption Governance Plan

**Status:** Plan only (Step 144) — **no implementation** of retrieval consumption in this step  
**Governance:** `recommended_decision = retrieval_ready_for_sandbox_tooling_review` (Step 124)  
**Audience:** LangGraph workflow owners, retrieval governance, HITL reviewers, platform ops

---

## Purpose

Define the **evidence and approval gates** required before sandbox retrieval metadata (`retrieval_*` fields and governed hit summaries) may be **consumed** outside shadow-only observability — starting with **HITL-only visibility** as the sole mode that may be considered next.

This document does **not**:

- Wire `vendor_ticket_node` or draft/final responses to retrieval hits  
- Enable `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED` by default  
- Promote production `RAG_PROFILE`  
- Expose raw retrieved content, vectors, or queries to operators or customers  
- Implement UI, graph nodes, or runtime flags beyond governance models  

**Code (governance helpers only):** `app/corpus_planning/retrieval_consumption_governance.py`

---

## Current readiness evidence

| Evidence | Status | Reference |
|----------|--------|-----------|
| Sandbox retrieval executor | **Works** (local) | [sandbox retrieval tool smoke test report](sandbox_retrieval_tool_smoke_test_report.md) |
| LangGraph shadow node | **Implemented**; default flag **off** | [LangGraph sandbox retrieval node plan](langgraph_sandbox_retrieval_node_plan.md) |
| Dry-run chain smoke test | **Passed** | [dry-run retrieval chain smoke test report](dry_run_retrieval_chain_smoke_test_report.md) |
| Shadow replay batch (166 tickets) | **Reviewed** | [shadow replay metrics refresh report](shadow_replay_metrics_refresh_report.md) |
| Shadow `result_count_distribution` | **`{"5": 166}`** (post–Step 142) | Refresh report + gitignored dashboard JSON |
| Shadow `retrieval_error_count` | **0** | Refresh report |
| Shadow `retrieval_activated_true_count` | **0** | Refresh report |
| Shadow `downstream_consumed_retrieval_true_count` | **0** | Refresh report |
| Policy gate synthetic calibration | **pass_rate=1.0** | [retrieval policy gate calibration report](retrieval_policy_gate_calibration_report.md) |
| Metadata-filtered fund routing (eval) | **Passed** | [pilot retrieval evaluation report](pilot_retrieval_evaluation_report.md) |
| Filter alignment (export) | **Done** (Step 142) | `ticket_label` + `route_label` only in search filter |

**Conclusion:** Sandbox **execution** and **shadow observability** are validated. **Consumption** by drafting or customer channels remains **blocked** until this plan’s gates are satisfied per mode.

---

## What “non-shadow consumption” means

| Mode | Shadow (current) | Non-shadow consumption |
|------|------------------|-------------------------|
| Data written | `retrieval_*` on state for audit/metrics | Same fields **read** by another node or UI |
| Draft / final | **Not** influenced | Would influence text generation |
| Operator UI | **Not** shown | Would show governed summaries |
| `retrieval_activated` | **false** | Would stay **false** until a separate activation approval |
| Raw hits / content | **Never** in state or reports | Still **forbidden** in v1 |

**Shadow** = retrieve + record aggregate metadata only.  
**Non-shadow consumption** = any downstream use of that metadata (HITL display, draft context, or customer-facing features).

---

## Allowed future consumption modes (governance lanes)

| Lane | ID | Description | Step 144 stance |
|------|-----|-------------|-----------------|
| **HITL-only visibility** | (a) | Reviewers see aggregate-safe retrieval summaries (counts, labels, hashes, policy reasons) in review UI | **Only lane that may be considered next** |
| **Draft-assist context** | (b) | Specialist/drafter nodes read retrieval metadata to shape drafts | **Blocked** until separate plan + approval after (a) |
| **Production / customer-facing** | (c) | Customer APIs, autonomous replies, production `RAG_PROFILE` | **Blocked** indefinitely without new governance decision |

Lanes (b) and (c) require **new** evidence, contracts, and sign-off beyond Step 144.

---

## Decision states

| `RetrievalConsumptionDecision` | Meaning |
|--------------------------------|---------|
| `not_ready` | Default; consumption not approved |
| `ready_for_hitl_visibility_review` | Evidence met; awaiting human governance review for HITL-only |
| `approved_for_hitl_visibility` | HITL-only visibility approved; implementation still feature-flagged |
| `blocked` | Explicit deny (incident, policy change, or scope halt) |

Helper: `retrieval_consumption_ready_for_hitl(plan)` returns **true** only when status is `ready_for_hitl_visibility_review` or `approved_for_hitl_visibility` **and** all checklist fields below pass (does **not** enable runtime).

---

## Approval gates before HITL-only visibility (lane a)

All must be satisfied before any implementation of HITL-only retrieval display:

| Gate | Requirement |
|------|-------------|
| Shadow metrics reviewed | [Shadow replay metrics refresh report](shadow_replay_metrics_refresh_report.md) accepted by retrieval governance |
| `retrieval_error_count` | **0** on shadow replay batch |
| `retrieval_activated` | **false** on all rows until a separate activation decision |
| `downstream_consumed_retrieval` | **false** until HITL path explicitly sets consumption audit fields |
| Human reviewer sign-off | Named governance + HITL owner approval recorded (ticket/doc) |
| Safe HITL output contract | UI shows only allowlisted aggregate fields; no raw query, hit bodies, vectors |
| No raw sensitive content | No transcripts, message text, or embedding arrays in HITL payloads |
| Rollback plan | Feature flag or config toggle documented to disable HITL retrieval panel without deploy rollback |
| Production / customer-facing | **false** |
| Draft-assist | **false** (lane b blocked) |
| Feature flag default | `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED` remains **false**; separate flag required for HITL consumption if any |

### HITL-safe output contract (v1 allowlist)

May display:

- `retrieval_gate_decision`, `retrieval_scenario`, `retrieval_policy_reasons`  
- `retrieval_query_hash`, `retrieval_result_count`  
- `retrieval_metadata_filter` (ticket_label, route_label only)  
- `retrieval_sandbox_only`, `executor_called`  
- Aggregate pilot scope labels (namespace/index version as text, not secrets)  

Must **not** display:

- Raw query text, hit `content`, `record_id` lists at scale, scores distributions tied to identifiable text  
- Vectors, embeddings, full `results` payloads  
- Autonomous “recommended reply” based on retrieval  

---

## Blocked items (all lanes until explicit unblock)

| Blocked item | Policy |
|--------------|--------|
| Autonomous drafting from retrieval | No self-serve draft generation using `retrieval_*` |
| Final response generation from retrieval | `final_response` must not be driven by sandbox hits |
| Customer-facing retrieval | No public or vendor-facing retrieval APIs |
| Production `RAG_PROFILE` promotion | Existing `retrieve_context` / production path unchanged |
| Unrestricted vector-only retrieval | Metadata-filtered pilot path only |
| `retrieval_activated=true` without activation review | Runtime flag remains false by default |
| Raw sensitive content in operator UI | Fail closed on contract violation |
| pgvector schema change / re-index / embedding regen | Out of scope for consumption approval |

---

## Rollback plan (HITL-only, when implemented)

1. **Disable** HITL retrieval panel via feature flag (preferred).  
2. **Revert** UI-only change without altering shadow export pipelines.  
3. **Confirm** `downstream_consumed_retrieval` audit remains false when panel off.  
4. **Re-run** shadow replay + dashboard to verify no regression in shadow path.  

No requirement to delete pgvector index or corpus on rollback.

---

## Readiness helper (checklist model)

```python
from app.corpus_planning.retrieval_consumption_governance import (
    RetrievalConsumptionDecision,
    RetrievalConsumptionReadinessPlan,
    retrieval_consumption_ready_for_hitl,
)

plan = RetrievalConsumptionReadinessPlan(
    status=RetrievalConsumptionDecision.READY_FOR_HITL_VISIBILITY_REVIEW,
    shadow_metrics_reviewed=True,
    shadow_replay_total_rows=166,
    shadow_retrieval_error_count=0,
    shadow_retrieval_activated_true_count=0,
    shadow_downstream_consumed_true_count=0,
    human_reviewer_signoff=True,
    hitl_safe_output_contract_defined=True,
    rollback_plan_documented=True,
    production_or_customer_facing=False,
    draft_assist_enabled=False,
    autonomous_drafting_enabled=False,
    unrestricted_vector_only=False,
)
assert retrieval_consumption_ready_for_hitl(plan) is True  # governance check only
```

This helper does **not** modify LangGraph, enable flags, or expose data.

---

## Recommended sequencing (after Step 144)

| Order | Step type | Topic |
|-------|-----------|--------|
| 1 | **Plan** | HITL visibility contract + UI mock (aggregate fields only) |
| 2 | **Shadow assist (Steps 145–149)** | [Vendor ticket AI assist shadow workflow](vendor_ticket_ai_assist_shadow_workflow.md) + [AI assist shadow metrics report](ai_assist_shadow_metrics_report.md) — validated 166-ticket batch; **no** HITL UI yet |
| 3 | **Implementation** | HITL panel behind flag; shadow path unchanged |
| 4 | **Review** | Operator dry-run on pilot tickets; no draft linkage |
| — | **Blocked** | Draft-assist (b), customer-facing (c) |

---

## Governance conclusions

1. **Sandbox retrieval is ready for tooling and shadow replay** — not for autonomous or customer consumption.  
2. **Only HITL-only visibility (a)** may be proposed next; draft-assist and production remain **blocked**.  
3. **`retrieval_activated=false`** and **`downstream_consumed_retrieval=false`** remain mandatory until explicit per-lane approval.  
4. **Step 144 does not implement consumption** — it defines gates only.  

---

## Related documentation

- [AI assist shadow metrics report](ai_assist_shadow_metrics_report.md) — Step 149 validated assist replay batch
- [Vendor ticket AI assist shadow workflow](vendor_ticket_ai_assist_shadow_workflow.md) — Steps 145–148 shadow HITL assist (no consumption of hit content)
- [Shadow replay metrics refresh report](shadow_replay_metrics_refresh_report.md) — Step 143 corrected metrics  
- [LangGraph retrieval integration plan](langgraph_retrieval_integration_plan.md)  
- [Sandbox retrieval tool contract](sandbox_retrieval_tool_contract.md)  
- [Retrieval policy gate contract](retrieval_policy_gate_contract.md)  
- [LangGraph sandbox retrieval node plan](langgraph_sandbox_retrieval_node_plan.md)
