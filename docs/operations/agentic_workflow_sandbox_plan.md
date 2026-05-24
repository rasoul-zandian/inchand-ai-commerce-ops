# Agentic Workflow Sandbox Plan

**Status:** Step 193 — sandbox graph + CLI implemented; **not** wired to operator console or production graph  
**Audience:** LangGraph owners, HITL operators, draft calibration, platform governance

---

## Purpose

Model existing **safe, first-turn** assist components as a **linear LangGraph** sandbox workflow:

1. First-turn context isolation  
2. Intent detection + conceptual intent (draft node)  
3. Operational entity extraction  
4. Sandbox knowledge hints  
5. Suggested action taxonomy  
6. Actionability validation  
7. Internal draft generation + style/completion calibration  
8. Safety gates (no send, no execution)  
9. Human review handoff (read-only payload)

**Agentic** here means **orchestration of deterministic/tool nodes with shared state** — not autonomous customer-facing execution.

Implementation package: `app/agentic_sandbox/`  
CLI: `scripts/run_agentic_sandbox_workflow.py`

---

## Boundaries

| Allowed | Blocked |
|---------|---------|
| First-turn `original_vendor_issue_preview` only | Multi-turn thread context in prompts |
| Internal draft for operator review | Customer auto-send |
| Sandbox knowledge hints (`KNOWLEDGE_HINTS_ENABLED` path) | Production `RAG_PROFILE` / `retrieve_context` consumption |
| Actionability identifier requests | Operational API execution |
| Read-only HITL handoff payload | Ticket/order/product mutation |
| Mock or explicit OpenAI draft (`--confirm-real-openai`) | Default production graph replacement |

**State invariants (always):**

- `human_review_required = true`
- `execution_allowed = false`
- `customer_send_allowed = false`

---

## Graph nodes

| Node | Responsibility | Existing module |
|------|----------------|-----------------|
| `build_first_turn_context` | Validate first-turn text; no thread fields | `app/evals/first_turn_draft_context.py` |
| `detect_intent` | Rule-based `detected_intent` | `app/workflows/vendor_ticket_intent_detection.py` |
| `extract_entities` | Order/product/tracking/IBAN extraction | `app/workflows/operational_entity_extraction.py` |
| `retrieve_knowledge_hints` | Sandbox policy hints (optional flag) | `app/operator_console/knowledge_hints.py` |
| `suggest_action` | Taxonomy mapping | `app/workflows/suggested_action_taxonomy.py` |
| `validate_actionability` | Missing identifier check | `app/evals/actionability_validation.py` |
| `generate_draft` | LLM draft + completion/style/actionability post-process | `app/evals/offline_draft_generation.py`, `conceptual_intent_fa.py` |
| `safety_gate` | Forbidden fields, send/execution flags | `app/evals/draft_prompt_leakage.py` (patterns) |
| `human_review_handoff` | Allowlisted review payload | `app/hitl/hitl_visibility_contract.py` (aligned fields) |

**Flow (linear, no conditional tools yet):**

```
START → build_first_turn_context → detect_intent → extract_entities
      → retrieve_knowledge_hints → suggest_action → validate_actionability
      → generate_draft → safety_gate → human_review_handoff → END
```

---

## State fields

`AgenticSandboxState` (`app/agentic_sandbox/agentic_state.py`):

| Field | Description |
|-------|-------------|
| `room_id`, `ticket_label`, `route_label` | Ticket metadata |
| `first_turn_text` | Seller initial issue only |
| `detected_intent`, `conceptual_intent_fa` | Intent labels |
| `extracted_entities` | Aggregated entity dict (no raw transcript) |
| `suggested_action`, `suggested_action_reason` | Internal action metadata |
| `actionability` | Step 191 validation metadata |
| `knowledge_hints` | Hint summaries (no full retrieval dump) |
| `draft_reply` | Internal draft text |
| `safety_status` | `passed` / `failed` |
| `human_review_payload` | Read-only handoff for operator console (future) |
| `node_results` | Per-node status summaries |
| `errors` | Non-fatal error strings |

Runtime-only keys (`_llm_provider`, `_llm_model`, `_generate_fn`) are stripped from written reports.

---

## Safety gates

` safety_gate` enforces:

- `execution_allowed == false`
- `customer_send_allowed == false`
- `human_review_required == true`
- Draft must not contain auto-send / transcript / gold markers
- No forbidden state keys (`messages`, `transcript`, `retrieved_context`, …)

CLI output: `reports/agentic_sandbox_run_<room_id>.json` — **no** raw transcript, prompts, or customer send flags enabled.

---

## Non-goals (Step 193)

| Non-goal | Policy |
|----------|--------|
| Wire into Streamlit operator console | **Future** |
| Replace `app/graph/main_graph.py` vendor path | **Blocked** |
| Conditional tool / action execution branches | **Future** |
| Multi-turn conversation memory | **Blocked** |
| Production retrieval activation | **Blocked** — `retrieval_activated=false` |
| Auto-send / auto-approve | **Blocked** |

---

## Future path

1. **Operator console integration** — render `human_review_payload` beside existing draft preview (session-only).  
2. **Conditional edges** — branch on `actionability.should_request_identifier` vs policy-only replies (still no execution).  
3. **Shadow parity** — optional parallel run vs `vendor_ticket_ai_assist_shadow` for diff metrics.  
4. **Retrieval shadow node** — compose with `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED` under separate flag (see [langgraph_sandbox_retrieval_node_plan.md](langgraph_sandbox_retrieval_node_plan.md)).  
5. **Production graph** — only after HITL sign-off, governance review, and explicit feature flags.

---

## Governance

- Pair with [hitl_read_only_visibility_contract.md](hitl_read_only_visibility_contract.md).  
- Draft calibration metrics: `build_draft_review_metrics_report.py`, `build_draft_quality_slice_analysis.py`.  
- Actionability: Step 191 `actionability_validation.py`.  
- **No** automatic prompt or taxonomy changes from sandbox runs.

---

## CLI

```bash
PYTHONPATH=. python3.11 scripts/run_agentic_sandbox_workflow.py \
  --room-id ROOM_123 \
  --replay-jsonl reports/ai_assist_shadow_replay_v1.jsonl \
  --redacted-jsonl data/redacted/tickets.jsonl \
  --provider mock \
  --overwrite
```

OpenAI (local approval only):

```bash
PYTHONPATH=. python3.11 scripts/run_agentic_sandbox_workflow.py \
  --room-id ROOM_123 \
  --provider openai \
  --confirm-real-openai \
  --overwrite
```
