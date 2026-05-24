# Vendor Ticket AI Assist Shadow Workflow

**Status:** Shadow assist evaluator (Steps 145–146) + offline metrics (Steps 147–149) — **no** HITL UI, **no** customer effects  
**Governance:** `recommended_decision = retrieval_ready_for_sandbox_tooling_review` (Step 124)  
**Audience:** Vendor-ticket operators, HITL reviewers, workflow owners

---

## Purpose

Introduce the **first product-facing AI operational workflow** on top of existing sandbox retrieval and governance infrastructure — while keeping everything **shadow-only**, **assistive**, and **HITL-safe**.

The workflow concept:

```
ticket → routing → shadow retrieval metadata → AI operational assist → HITL/operator visibility only
```

This step adds **operator suggestions** (priority, escalation hints, duplicate checks) from **sanitized state only**. It does **not** deepen retrieval architecture, auto-send messages, or change customer-visible behavior.

**Code:**

- Models: `app/workflows/vendor_ticket_ai_assist_models.py`
- Evaluator: `app/workflows/vendor_ticket_ai_assist_shadow.py`
- State helpers: `app/state/ai_assist_state.py`
- LangGraph node: `app/nodes/vendor_ticket_ai_assist_shadow.py` (`vendor_ticket_ai_assist_shadow`)
- CLI: `scripts/run_vendor_ticket_ai_assist_shadow.py`
- Export: `scripts/export_ai_assist_shadow_replay_jsonl.py` → `reports/ai_assist_shadow_replay_v1.jsonl`
- Dashboard: `scripts/build_ai_assist_shadow_metrics_dashboard.py`
- Tests: `tests/test_vendor_ticket_ai_assist_shadow.py`, `tests/test_vendor_ticket_ai_assist_shadow_node.py`, `tests/test_ai_assist_shadow_replay_export.py`, `tests/test_ai_assist_shadow_metrics_dashboard.py`

---

## Scope

| In scope | Out of scope |
|----------|--------------|
| Rule-based shadow assist from aggregate routing + retrieval metadata | HITL UI panel |
| LangGraph shadow node (`vendor_ticket_ai_assist_shadow`) behind `VENDOR_TICKET_AI_ASSIST_SHADOW_ENABLED` | Draft / `final_response` consumption |
| HITL-only suggestion payloads | Customer-facing APIs or UI |
| Sanitized replay row / minimal JSON input | LLM-generated customer replies |
| Local synthetic tests | Production `RAG_PROFILE` |
| Optional CLI for operator dry-runs | Draft / `final_response` consumption |
| Governance documentation | Agent loops, memory, rerankers |

---

## Non-goals (strict)

- **Auto-send responses** — no outbound messaging  
- **Expose retrieval content** to customers or operators (hit bodies, queries, vectors)  
- **Autonomous execution** — suggestions require human review  
- **Production `RAG_PROFILE`** — unchanged  
- **Retrieval in `final_response`** — blocked  
- **Customer-visible behavior** — no change  
- **Multi-agent orchestration / memory / hybrid retrieval** — not in this phase  

---

## Assist-only behavior

The shadow evaluator (`evaluate_vendor_ticket_ai_assist_shadow`) produces `VendorTicketAIAssistResult` with:

| Field | Meaning |
|-------|---------|
| `suggested_priority` | Operator hint from `review_priority` / routing (`low` / `medium` / `high`) |
| `escalation_recommended` | True for complaint / escalation routes |
| `duplicate_possible` | Heuristic when sandbox `retrieval_result_count` ≥ 3 and gate `allow` |
| `suggested_action` | Primary action enum (`monitor`, `escalate`, `billing_review`, etc.) |
| `retrieval_summary_available` | **Bool only** — aggregate metadata present, not hit content |
| `confidence_band` | `low` / `medium` / `high` from routing + retrieval metadata presence |
| `assist_generated_at` | UTC ISO timestamp |
| `suggestions` | Short safe summaries + `reason_codes` (no chain-of-thought) |

**Never included:** raw retrieval content, generated customer replies, hidden reasoning, autonomous actions.

---

## Relationship to shadow retrieval

| Layer | Role in Step 145 |
|-------|------------------|
| Shadow retrieval node | Populates aggregate `retrieval_*` on state (when flag on) |
| Shadow replay export | Sanitized JSONL rows for metrics |
| AI assist shadow evaluator | **Reads** allowlisted metadata only (`retrieval_result_count`, `retrieval_gate_decision`, `retrieval_query_hash`, etc.) |
| Non-shadow consumption plan (Step 144) | HITL visibility gates — assist aligns with HITL-only lane; still shadow until wired |

Assist does **not** call pgvector, OpenAI, or the retrieval executor.

---

## LangGraph shadow node (Step 146)

Graph order:

```
route_workflow → sandbox_retrieve_pilot_shadow → vendor_ticket_ai_assist_shadow → retrieve_context → vendor_ticket_node
```

| Setting | Default |
|---------|---------|
| `VENDOR_TICKET_AI_ASSIST_SHADOW_ENABLED` | **false** |

When enabled, the node writes only `ai_assist_*` fields on `CommerceAIState`:

- `ai_assist_shadow_generated`
- `ai_assist_suggested_priority`
- `ai_assist_escalation_recommended`
- `ai_assist_duplicate_possible`
- `ai_assist_suggested_action`
- `ai_assist_confidence_band`
- `ai_assist_human_review_required` (default **true**)
- `ai_assist_shadow_only` (default **true**)

`vendor_ticket_node` does **not** read `ai_assist_*` fields. Downstream draft/final paths are unchanged.

---

## Governance constraints

| Control | Value |
|---------|--------|
| `retrieval_activated` | **false** (input rejected if true) |
| `downstream_consumed_retrieval` | **false** (input rejected if true) |
| Assist suggestions | **HITL-only** — `human_review_required=true` |
| Operator review | **Required** before any future UI action |
| Workflow mode | **Shadow-only** — `assist_shadow_only=true` |
| Customer-facing effects | **None** |
| Draft / final response | **Not used** |
| HITL UI | **Not implemented** (Step 146) |

---

## Example (CLI)

```bash
PYTHONPATH=. python3.11 scripts/run_vendor_ticket_ai_assist_shadow.py \
  reports/shadow_replay_balanced_v1.jsonl \
  --output reports/vendor_ticket_ai_assist_sample.json \
  --overwrite
```

Input must be a **single sanitized JSON object** (one replay row). Output is safe assist JSON only.

## Offline shadow replay metrics (Step 147)

Export sanitized rows across a ticket batch (routing + optional retrieval + assist):

```bash
PYTHONPATH=. LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=true \
  VENDOR_TICKET_AI_ASSIST_SHADOW_ENABLED=true \
  python3.11 scripts/export_ai_assist_shadow_replay_jsonl.py \
  data/private/vendor_tickets_400.redacted.jsonl \
  --namespace vendor_ticket_real_pilot_balanced \
  --index-version pilot_balanced_v1 \
  --profile semantic_pgvector \
  --confirm-sandbox --overwrite
```

Build aggregate dashboard:

```bash
PYTHONPATH=. python3.11 scripts/build_ai_assist_shadow_metrics_dashboard.py \
  reports/ai_assist_shadow_replay_v1.jsonl --overwrite
```

**Gitignored outputs:** `reports/ai_assist_shadow_replay_v1.jsonl`, `reports/ai_assist_shadow_metrics_dashboard.md`, `.json`

Row contract rejects forbidden keys, `retrieval_activated=true`, `downstream_consumed_retrieval=true`, and `ai_assist_shadow_only=false`.

**Validated batch (Step 149):** [AI assist shadow metrics report](ai_assist_shadow_metrics_report.md) — 166 rows, `error_count=0` after Step 148 `database_url` fix.

---

## Recommended sequencing

| Step | Topic |
|------|--------|
| **145** | Shadow assist evaluator + docs + tests |
| **146** | LangGraph `vendor_ticket_ai_assist_shadow` node; flag default off |
| **147–148** | Offline export + dashboard; sandbox `database_url` resolution for embedded retrieval chain |
| **149** | [AI assist shadow metrics report](ai_assist_shadow_metrics_report.md) — validated 166-ticket batch |
| **150** | [HITL read-only visibility contract](hitl_read_only_visibility_contract.md) — allowlists + reviewer boundaries (no UI) |
| **Future** | HITL read-only panel implementation per contract |
| **Blocked** | Draft-assist, customer-facing retrieval, production `RAG_PROFILE` |

---

## Related documentation

- [Non-shadow retrieval consumption governance plan](non_shadow_retrieval_consumption_governance_plan.md) — Step 144  
- [LangGraph retrieval integration plan](langgraph_retrieval_integration_plan.md)  
- [Shadow replay metrics refresh report](shadow_replay_metrics_refresh_report.md)  
- [Sandbox retrieval tool contract](sandbox_retrieval_tool_contract.md)
