# Sandbox Retrieval Tool Contract

**Status:** Contract (Step 125) + sandbox executor (Step 126) + local smoke test (Step 127) — **not** LangGraph / production activation  
**Governance:** `recommended_decision = retrieval_ready_for_sandbox_tooling_review` (Step 124)  
**Audience:** AI Commerce OS retrieval layer, platform governance, sandbox operators

---

## Purpose

Define a **minimal, governed interface boundary** for sandbox-only pilot retrieval after balanced corpus indexing and eval calibration (Steps 122–124).

This contract specifies:

- Allowed **inputs** (query, scope, filters, top-k)
- Allowed **outputs** (aggregate-safe hit metadata only)
- **Safety** and **audit** expectations

It does **not** wire LangGraph, enable production `RAG_PROFILE`, or expose customer-facing APIs.

**Code:** `app/corpus_planning/retrieval_tool_models.py`, `app/corpus_planning/retrieval_tool_validation.py`, `app/corpus_planning/sandbox_retrieval_tool.py`  
**Policy gate (pre-search):** `app/corpus_planning/retrieval_policy_gate.py` — [retrieval policy gate contract](retrieval_policy_gate_contract.md) (Step 129)  
**State helpers:** `app/state/retrieval_state.py` — apply gate/tool results to `CommerceAIState` (Step 130)  
**CLI:** `scripts/run_sandbox_retrieval_tool.py` (requires `--confirm-sandbox`)  
**Chain dry-run CLI:** `scripts/dry_run_sandbox_retrieval_chain.py` — gate → executor → state snapshot (Step 131; not LangGraph)  
**Tests:** `tests/test_retrieval_tool_contract.py`, `tests/test_sandbox_retrieval_tool.py`, `tests/test_retrieval_policy_gate.py`, `tests/test_sandbox_retrieval_chain_dry_run.py`

---

## Scope

| In scope | Out of scope |
|----------|--------------|
| Request/response Pydantic models | LangGraph node wiring |
| Metadata filter allowlist | Production `RAG_PROFILE` promotion |
| Output field denylist | Customer-facing HTTP APIs |
| Sandbox namespace/index validation | Streaming retrieval |
| `query_hash` audit fingerprint | Rerankers / hybrid search |
| Contract unit tests (no network) | pgvector schema changes |
| Sandbox executor + CLI (Step 126) | LangGraph / agent tool registration |
| Operator/governance documentation | Re-indexing / embedding regeneration |

---

## Non-goals

- **Runtime activation** — `retrieval_activated` remains **false** on all tool responses.
- **Autonomous retrieval** in vendor-ticket workflows.
- **Raw ticket exposure** — no transcripts, message bodies, or indexed `content` in tool output.
- **Vector exposure** — no embedding arrays or pgvector distances beyond a single aggregate `score` float per hit.
- **Production databases** — sandbox Postgres only (local host policy unchanged from indexing/eval CLIs).

---

## Sandbox-only restriction

| Rule | Enforcement |
|------|-------------|
| `sandbox_only=true` on every response | Pydantic model default + validator |
| `retrieval_activated=false` on every response | Pydantic model default + validator |
| Namespace allowlist | `validate_sandbox_namespace()` — pilot sandbox names only |
| Index version pattern | `validate_sandbox_index_version()` — must start with `pilot_` |
| Profile (executor) | `semantic_pgvector` only — same gate as eval/indexing |
| Database URL (executor) | `assert_sandbox_database_url()` — local host only |

Pilot scope (`namespace`, `index_version`) is carried on the **request**, not in `metadata_filter`.

---

## Retrieval lifecycle (contract stages)

```
1. Governance approval     → retrieval_ready_for_sandbox_tooling_review (Step 124)
2. Contract validation     → RetrievalToolRequest + filter/output checks (Step 125)
3. Tool execution          → execute_sandbox_retrieval_tool + CLI (Step 126)
4. Response safety         → assert_no_forbidden_output_fields()
5. Audit log / report      → query_hash + aggregate hits only
```

**Implemented:** stages **2–4** for **local sandbox CLI only**. Stage 5 operational report: [sandbox retrieval tool smoke test report](sandbox_retrieval_tool_smoke_test_report.md) (aggregate metrics only; no raw query). Ad-hoc CLI JSON under `reports/` remains gitignored. **Not** wired into LangGraph or FastAPI runtime.

---

## Safety boundaries

| Boundary | Policy |
|----------|--------|
| Query text | Accepted on input; **never** echoed in committed artifacts — use `query_hash` only |
| Indexed content | Not returned by the tool contract |
| Metadata filter | Allowlist only — no scope pins, no arbitrary JSONB keys |
| top_k | **1–50** inclusive |
| eval_mode | Optional hint: `vector_only` \| `metadata_filtered` (executor may honor for parity with eval) |

---

## Approved metadata filters

Allowed on `RetrievalToolMetadataFilter` (at least one required when filter is present):

| Field | Description |
|-------|-------------|
| `ticket_label` | `support`, `complaint`, or `fund` |
| `route_label` | Stored route label on index row (e.g. `billing_review`) |
| `review_priority` | Stored review priority on index row |

**Explicitly rejected** in `metadata_filter` (use request fields instead):

| Forbidden in filter | Use instead |
|---------------------|-------------|
| `namespace` | `RetrievalToolRequest.namespace` |
| `index_version` | `RetrievalToolRequest.index_version` |
| `department` | Not stored reliably on pilot rows; use `ticket_label` / `route_label` |
| Any other key | Contract validation error |

---

## Allowed outputs

Per-hit (`RetrievalToolResult`):

| Field | Type | Notes |
|-------|------|-------|
| `record_id` | string | Pilot-scoped pgvector row id |
| `score` | float | Aggregate similarity score only |
| `ticket_label` | string | From index metadata |
| `route_label` | string | From index metadata |
| `review_priority` | string | From index metadata |

Envelope (`RetrievalToolResponse`):

| Field | Value / notes |
|-------|----------------|
| `results` | List of `RetrievalToolResult` |
| `retrieval_activated` | **false** (required) |
| `sandbox_only` | **true** (required) |
| `query_hash` | SHA-256 prefix of query (audit) |
| `result_count` | Must equal `len(results)` |

---

## Forbidden outputs

Must not appear in serialized tool responses (keys checked recursively):

- `conversation_transcript`, `transcript`, `messages`, `raw_text`
- `content`, `retrieved_context`, `draft_response`, `final_response`
- `vector`, `embedding`, `embeddings`
- `query` (raw query text)

---

## Auditability expectations

| Artifact | Content |
|----------|---------|
| Operator logs | `namespace`, `index_version`, `top_k`, `query_hash`, `result_count` |
| Committed docs/reports | Aggregate metrics only — no raw queries or hit content |
| Gitignored local JSON | May include per-case metadata under `reports/` — do not commit |

Executor should log validation failures and scope parameters without logging query plaintext to shared systems.

---

## Sandbox executor (Step 126)

**Function:** `execute_sandbox_retrieval_tool(request, store, query_embedding_fn, profile=...)`

| Step | Behavior |
|------|----------|
| Validate | `validate_retrieval_tool_request()` + `assert_eval_profile()` |
| Scope | `PilotScopedVectorStore` must match `request.namespace` / `request.index_version` |
| Embed | Injected `query_embedding_fn(query)` — CLI uses OpenAI locally |
| Search | Scoped pilot rows only; optional metadata filter per `eval_mode` |
| Respond | `RetrievalToolResponse` with `retrieval_activated=false`, `sandbox_only=true` |

**CLI example:**

```bash
PYTHONPATH=. python3.11 scripts/run_sandbox_retrieval_tool.py \
  --query "settlement payment status" \
  --namespace vendor_ticket_real_pilot_balanced \
  --index-version pilot_balanced_v1 \
  --profile semantic_pgvector \
  --top-k 5 \
  --ticket-label fund \
  --confirm-sandbox
```

Requires local Postgres, `OPENAI_API_KEY` for query embedding only, and `--confirm-sandbox`. **Does not** print API keys or raw query text in output.

---

## Relationship to pilot retrieval eval

| Eval CLI | Sandbox tool |
|----------|----------------|
| `scripts/eval_pilot_retrieval.py` | Offline batch eval — **exists** |
| `scripts/run_sandbox_retrieval_tool.py` | Single-query sandbox executor — **exists** (Step 126) |

Eval cases v4 already avoid pinning `namespace` / `index_version` in `metadata_filter`; this contract encodes the same rule for tooling.

---

## Governance conclusions

| Statement | Status |
|-----------|--------|
| Contract models defined | **Yes** |
| Sandbox executor + CLI (local) | **Yes** (Step 126) |
| Local smoke test (aggregate report) | **Passed** (Step 127) |
| LangGraph / workflow retrieval | **Not approved** |
| Production `RAG_PROFILE` | **Not approved** |
| Customer-facing retrieval API | **Not approved** |
| Autonomous agent tool registration | **Not approved** |
| LangGraph integration plan | **Defined** (Step 128) — implementation **not approved** |
| Retrieval policy gate | **Defined** (Step 129) — allow/skip/deny before search |
| LangGraph retrieval state fields | **Defined** (Step 130) — additive `retrieval_*` on `CommerceAIState` |
| Gate + executor chain dry-run CLI | **Implemented** (Step 131) — local operator validation only |
| Dry-run chain smoke test | **Passed** (Step 132) — [smoke test report](dry_run_retrieval_chain_smoke_test_report.md) |
| Non-shadow consumption governance | **Defined** (Step 144) — [governance plan](non_shadow_retrieval_consumption_governance_plan.md); HITL-only visibility may be reviewed next; draft/customer **blocked** |

---

## Related documentation

- [Non-shadow retrieval consumption governance plan](non_shadow_retrieval_consumption_governance_plan.md) — Step 144 consumption approval gates (plan only)
- [Dry-run retrieval chain smoke test report](dry_run_retrieval_chain_smoke_test_report.md) — Step 132 chain smoke test
- [Retrieval policy gate contract](retrieval_policy_gate_contract.md) — Step 129 pre-search gate
- [Sandbox retrieval tool smoke test report](sandbox_retrieval_tool_smoke_test_report.md) — Step 127 local smoke test (aggregate-safe)
- [LangGraph retrieval integration plan](langgraph_retrieval_integration_plan.md) — Step 128 future wiring (plan only)
- [Pilot retrieval evaluation report](pilot_retrieval_evaluation_report.md) — Step 124 decision
- [Pilot retrieval failure analysis](pilot_retrieval_failure_analysis.md)
- [Balanced pilot corpus rebuild](balanced_pilot_corpus_rebuild.md)
- [PgVector sandbox indexing plan](pgvector_sandbox_indexing_plan.md)
