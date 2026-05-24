# HITL Read-Only Visibility Contract

**Status:** Contract + payload builder + local mock preview + operator console (Steps 150–156) — **no** production HITL UI  
**Governance:** `recommended_decision = retrieval_ready_for_sandbox_tooling_review` (Step 124)  
**Audience:** HITL reviewers, vendor-ticket operators, retrieval governance, platform engineering

---

## Purpose

Define the **read-only human-in-the-loop (HITL) visibility boundary** for aggregate AI assist and sandbox retrieval metadata — moving from shadow observability toward **safe operator visibility** without AI-driven drafting, customer-facing behavior, or retrieval content exposure.

This contract is the prerequisite for any future HITL panel implementation. It does **not** wire UI, change LangGraph runtime defaults, or consume `ai_assist_*` / `retrieval_*` in draft or final responses.

**Code:** `app/hitl/hitl_visibility_contract.py`, `app/hitl/hitl_payload_builder.py`, `app/hitl/hitl_read_only_panel_preview.py`  
**Tests:** `tests/test_hitl_visibility_contract.py`, `tests/test_hitl_payload_builder.py`, `tests/test_hitl_read_only_panel_preview.py`  
**CLIs:** `scripts/build_hitl_read_only_payload_sample.py`, `scripts/render_hitl_read_only_panel_preview.py`

---

## Scope

| In scope | Out of scope |
|----------|--------------|
| Allowlisted aggregate fields for operator display | HITL UI / API implementation |
| Forbidden fields and reviewer action boundaries | `vendor_ticket_node` changes |
| Audit and rollback expectations | Draft / `final_response` consumption |
| Approval gates before UI work | Customer-facing AI assist |
| Readiness helper `hitl_visibility_ready_for_ui()` | Production `RAG_PROFILE` promotion |
| Alignment with Steps 145–149 evidence | Raw retrieval hits, vectors, queries |

---

## Non-goals

- **Implement UI** — no panels, routes, or front-end in Step 150  
- **Auto-send** — no outbound customer messages from HITL actions  
- **Approve customer responses from assist** — no “send as reply” from `ai_assist_*`  
- **Expose retrieved content** — no hit bodies, snippets, scores tied to identifiable text  
- **Expose raw queries / vectors / embeddings**  
- **Trigger retrieval or override policy gate** from HITL  
- **Change LangGraph runtime** — shadow flags remain default **off** until separate activation  
- **Customer-facing APIs** — internal operator visibility only  

---

## Relationship to prior steps

| Step | Relevance |
|------|-----------|
| **145–146** | Shadow AI assist evaluator + LangGraph node (`ai_assist_*` metadata) |
| **147–149** | Offline export, Step 148 DB fix, [AI assist shadow metrics report](ai_assist_shadow_metrics_report.md) (`error_count=0`, 166 rows) |
| **144** | [Non-shadow retrieval consumption governance plan](non_shadow_retrieval_consumption_governance_plan.md) — HITL-only lane (a) |
| **138–143** | Shadow retrieval replay metrics (aggregate `retrieval_*`) |
| **150 (this)** | Formal HITL read-only field and action contract |

---

## Read-only visibility boundary

HITL may **display** allowlisted aggregate metadata and record **non-destructive** reviewer actions. HITL must **not** mutate workflow state that affects `draft_response`, `final_response`, retrieval execution, or customer channels.

```
Shadow graph (flags off by default)
  → ai_assist_* + retrieval_* on state (aggregate only)
  → [FUTURE: HITL read-only panel reads allowlisted snapshot]
  → reviewer actions → audit log only (no customer send)
```

`vendor_ticket_node` **does not** read `ai_assist_*` fields today and remains **out of scope** for HITL v1.

---

## Allowed visible fields

### AI assist (aggregate)

| Field | Notes |
|-------|--------|
| `ai_assist_shadow_generated` | Whether assist metadata was produced |
| `ai_assist_suggested_priority` | `low` / `medium` / `high` hint |
| `ai_assist_escalation_recommended` | Boolean hint |
| `ai_assist_duplicate_possible` | Boolean hint (heuristic) |
| `ai_assist_suggested_action` | Enum string (`monitor`, `escalate`, etc.) |
| `ai_assist_confidence_band` | `low` / `medium` / `high` |
| `ai_assist_human_review_required` | Must display **true** in v1 |
| `ai_assist_shadow_only` | Must display **true** in v1 |

### Retrieval metadata (aggregate; no hit content)

| Field | Notes |
|-------|--------|
| `retrieval_gate_decision` | `allow` / `skip` / `deny` |
| `retrieval_scenario` | Scenario label only |
| `retrieval_result_count` | Integer count only |
| `retrieval_metadata_filter` | `ticket_label`, `route_label` only (no `review_priority` in search filter) |
| `retrieval_sandbox_only` | Expected **true** |
| `retrieval_activated` | Must be **false** in HITL payloads |

**Not allowed in v1 HITL UI:** `retrieval_query_hash`, `retrieval_policy_reasons` (optional future governance review).

### Ticket text preview (redacted excerpt only)

| Field | Notes |
|-------|--------|
| `ticket_text_preview` | Optional; **redacted** + **truncated** (max 400 chars). Latest seller message preferred. **Not** full transcript, **not** `messages[]`. |

**Rules:** built via `app/hitl/ticket_text_preview.py` — PII patterns redacted (`[PHONE_NUMBER]`, `[EMAIL]`, etc.); rejects unredacted phone/card/IBAN-like text; rejects transcript markers.

### Open ticket snapshot (operational; Step 157 / Step 159)

| Field | Notes |
|-------|--------|
| `original_vendor_issue_preview` | First **seller** message in the room (original issue); redacted + truncated |
| `latest_vendor_message` | Latest **seller** turn before the snapshot point; excludes later support replies |
| `recent_context_preview` | Up to 3 prior non-internal (`system` / `unknown` excluded) messages before the latest seller turn |
| `open_ticket_preview` | Compact combined summary (`Original:` / `Latest:` / `Recent:`); redacted + truncated |

**Rules:** built via `app/live_feed/open_ticket_snapshot.py` — combined max **600** chars across the three body fields (`original_*`, `latest_*`, `recent_*`); per-field caps; no `messages[]`; simulates active ticket review, not full closed conversation replay. Rejects remaining phone/card/IBAN-like patterns after redaction.

### Ticket metadata

| Field | Notes |
|-------|--------|
| `room_id` | Ticket identifier |
| `ticket_label` | `support` / `complaint` / `fund` |
| `route_label` | Operational route |
| `review_priority` | Queue priority label |
| `assigned_department` | Routing department |

---

## Forbidden fields

Must **never** appear in HITL visibility payloads or UI rendering:

| Category | Forbidden keys (representative) |
|----------|-------------------------------|
| Raw conversation | `user_input`, `messages`, `content`, `transcript`, `raw_text` |
| Retrieval content | `results`, `retrieved_context`, hit bodies, record lists at scale |
| Sensitive retrieval | `retrieval_query_hash`, raw `query` (v1) |
| Draft / customer output | `draft_response`, `final_response`, `customer_reply`, `generated_response` |
| Vectors | `vector`, `vectors`, `embedding`, `embeddings` |
| Tool / agent internals | `specialist_output`, `tool_results`, `rag_sources`, `suggestions` (full list) |
| Secrets | API keys, tokens, connection strings |

Enforcement: `assert_hitl_visible_payload_safe()` in `app/hitl/hitl_visibility_contract.py`.

**Payload builder (Step 151):** `build_hitl_read_only_payload_from_state()` and `build_hitl_read_only_payload_from_replay_row()` copy only allowlisted fields, sanitize `retrieval_metadata_filter` to `ticket_label` + `route_label`, and reject forbidden source keys. `assert_hitl_payload_ready()` validates the built payload before any future UI render.

---

## Reviewer actions

### Allowed (audit-only in v1)

| Action | Purpose |
|--------|---------|
| `view` | Open read-only panel |
| `acknowledge` | Reviewer saw assist/retrieval summary |
| `mark_helpful` | Qualitative signal for governance |
| `mark_noisy` | Qualitative signal for governance |
| `request_human_followup` | Escalate to human queue (no auto-send) |
| `add_internal_note` | Internal operator note (not customer text) |

### Forbidden

| Action | Reason |
|--------|--------|
| `auto_send` | No customer messaging |
| `approve_customer_response` | No customer reply from assist |
| `modify_final_response` | No draft/final consumption |
| `draft_from_assist` | Lane (b) blocked |
| `trigger_retrieval` | No operator-triggered search |
| `override_policy_gate` | Policy gate remains upstream |
| `expose_externally` | No export to customer channels |
| `send_customer_message` | Same as auto-send |

Enforcement: `assert_hitl_reviewer_action_allowed()`.

---

## Audit expectations

1. Every allowed reviewer action records: `action`, `room_id`, `reviewer_id` (or role), `timestamp`, optional short `note` (no customer text).  
2. HITL payloads logged for audit must pass `assert_hitl_visible_payload_safe()`.  
3. No retrieval hit content, vectors, or raw queries in audit stores.  
4. `retrieval_activated=false` and `downstream_consumed_retrieval=false` on displayed snapshots.  

---

## Rollback / disable strategy

1. **Feature flag** (future): `HITL_READ_ONLY_PANEL_ENABLED=false` (default off) — hide panel without graph deploy rollback.  
2. **Disable panel only** — shadow export and LangGraph shadow nodes continue unchanged.  
3. **Incident** — set decision to `blocked` on `HITLReadOnlyVisibilityContract`; panel hidden via flag.  
4. **No index/corpus rollback** required to disable HITL visibility.  

---

## Approval gates before UI implementation

| Gate | Requirement |
|------|-------------|
| Shadow metrics | [AI assist shadow metrics report](ai_assist_shadow_metrics_report.md) reviewed (`error_count=0`) |
| Retrieval metrics | [Shadow replay metrics refresh report](shadow_replay_metrics_refresh_report.md) reviewed |
| This contract | Step 150 documented and signed off |
| Read-only mode | `visibility_mode=read_only` only |
| Consumption plan | Step 144 lane (a) only; lanes (b)/(c) blocked |
| Human sign-off | Named HITL + governance owners |
| Rollback documented | Flag-based disable path |
| Runtime defaults | `VENDOR_TICKET_AI_ASSIST_SHADOW_ENABLED=false`, `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=false` |
| `vendor_ticket_node` | Confirmed non-consumer of `ai_assist_*` |

Helper: `hitl_visibility_ready_for_ui(contract)` returns **true** only when:

- `visibility_mode == read_only`
- `customer_facing == false`
- `auto_send_allowed == false`
- `draft_consumption_allowed == false`
- `retrieval_content_visible == false`
- `human_review_required == true`

This helper does **not** enable UI or change runtime.

---

## Safety / governance status

| Control | Required value |
|---------|----------------|
| `retrieval_activated` | **false** |
| `downstream_consumed_retrieval` | **false** (display + workflow) |
| `ai_assist_shadow_only` | **true** |
| `ai_assist_human_review_required` | **true** |
| `vendor_ticket_node` consumes `ai_assist_*` | **No** |
| Draft / final use assist or retrieval hits | **No** |
| Customer-facing HITL | **No** |
| HITL UI implemented (Step 150) | **No** |

---

## Approval status

| Item | Status |
|------|--------|
| HITL read-only visibility contract (Step 150) | **Defined** |
| HITL UI implementation | **Not approved** — separate step after gates |
| Draft-assist consumption | **Blocked** |
| Customer-facing assist | **Blocked** |

**Recommended next step:** Governance sign-off on this contract, then **HITL read-only panel implementation** behind a new feature flag consuming `build_hitl_read_only_payload_from_replay_row()` output — still no draft/final linkage or customer send.

### Sample payload build (local)

```bash
PYTHONPATH=. python3.11 scripts/build_hitl_read_only_payload_sample.py \
  reports/ai_assist_shadow_replay_v1.jsonl \
  --limit 5 --overwrite
```

### Mock panel preview (Step 152)

```bash
PYTHONPATH=. python3.11 scripts/render_hitl_read_only_panel_preview.py \
  reports/hitl_read_only_payload_sample.json \
  --output reports/hitl_read_only_panel_preview.md --overwrite
```

Renders Markdown sections: ticket metadata, AI assist summary, retrieval aggregate summary, human review note, and read-only safety footer. **No** FastAPI route, **no** reviewer actions that mutate workflow state.

---

## Related documentation

- [HITL read-only preview batch report](hitl_read_only_preview_report.md) — Step 153  
- [AI assist shadow metrics report](ai_assist_shadow_metrics_report.md) — Step 149  
- [Vendor ticket AI assist shadow workflow](vendor_ticket_ai_assist_shadow_workflow.md)  
- [Non-shadow retrieval consumption governance plan](non_shadow_retrieval_consumption_governance_plan.md)  
- [LangGraph retrieval integration plan](langgraph_retrieval_integration_plan.md)
