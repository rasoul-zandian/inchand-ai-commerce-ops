# AI Assist Shadow Metrics Report

**Status:** Validated batch recorded after Step 148 export DB fix (Step 149) — governance reporting only  
**Governance:** `recommended_decision = retrieval_ready_for_sandbox_tooling_review` (Step 124)  
**Audience:** Vendor-ticket operators, HITL reviewers, retrieval governance, platform ops

---

## Purpose

Record the **successful 166-ticket AI assist shadow replay batch** after offline export and dashboard aggregation (Steps 147–148). This report documents aggregate-safe operator-assist metadata only — **no** raw messages, retrieval hit bodies, vectors, or customer-facing behavior.

It does **not** approve HITL UI, draft/final consumption, or non-shadow retrieval consumption.

**Gitignored artifacts:** `reports/ai_assist_shadow_replay_v1.jsonl`, `reports/ai_assist_shadow_metrics_dashboard.json`, `reports/ai_assist_shadow_metrics_dashboard.md`

---

## Scope

| In scope | Out of scope |
|----------|--------------|
| Shadow AI assist replay metrics (aggregate) | HITL review panel / operator UI |
| Relationship to Steps 145–148 | Draft / `final_response` consumption |
| Step 148 DB/runtime fix summary | Customer-facing AI assist |
| Safety and governance status | Production `RAG_PROFILE` promotion |
| Approval status for next governance steps | Autonomous send / approval bypass |

---

## Relationship to Steps 145–148

| Step | Outcome |
|------|---------|
| **145** | Rule-based shadow assist evaluator + models (`evaluate_vendor_ticket_ai_assist_shadow`) |
| **146** | LangGraph node `vendor_ticket_ai_assist_shadow`; `VENDOR_TICKET_AI_ASSIST_SHADOW_ENABLED` default **false** |
| **147** | Offline export `scripts/export_ai_assist_shadow_replay_jsonl.py` + dashboard `scripts/build_ai_assist_shadow_metrics_dashboard.py` |
| **148** | Export DB fix: `resolve_sandbox_export_database_url()` passes local sandbox `database_url` when shadow retrieval chain runs |
| **149** | This report — validated metrics after Step 148 re-export |

**Workflow concept (unchanged):**

```
ticket → routing → shadow retrieval metadata → AI operational assist → HITL visibility only (future)
```

---

## Replay / export workflow

Local operator batch (gitignored inputs/outputs):

```bash
PYTHONPATH=. LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=true \
  VENDOR_TICKET_AI_ASSIST_SHADOW_ENABLED=true \
  python3.11 scripts/export_ai_assist_shadow_replay_jsonl.py \
  data/private/vendor_tickets_400.redacted.jsonl \
  --namespace vendor_ticket_real_pilot_balanced \
  --index-version pilot_balanced_v1 \
  --profile semantic_pgvector \
  --confirm-sandbox --overwrite

PYTHONPATH=. python3.11 scripts/build_ai_assist_shadow_metrics_dashboard.py \
  reports/ai_assist_shadow_replay_v1.jsonl --overwrite
```

Each export row contains allowlisted fields only (`ai_assist_*`, routing labels, `errors[]`). Forbidden keys and unsafe flags are rejected at write/load time per [vendor ticket AI assist shadow workflow](vendor_ticket_ai_assist_shadow_workflow.md).

---

## Step 148 correction (summary)

**Issue (pre–148):** All 166 rows carried `shadow_chain_error: database_url is required when executor runs` because AI assist export reused the shadow retrieval chain without resolving a sandbox Postgres URL when `PGVECTOR_DATABASE_URL` was unset.

**Fix:** `resolve_sandbox_export_database_url()` in `app/corpus_planning/shadow_replay_jsonl_export.py` — settings → env → local sandbox default (`127.0.0.1`) with `assert_sandbox_database_url()` when `--confirm-sandbox`.

**Post-fix expectation:** `error_count=0` on dashboard; assist suggestions unchanged (routing-driven heuristics).

---

## Replay batch summary

| Item | Value |
|------|-------|
| Input | Redacted vendor ticket export JSONL (166 valid tickets in balanced pilot batch) |
| Output | `reports/ai_assist_shadow_replay_v1.jsonl` |
| Dashboard | `reports/ai_assist_shadow_metrics_dashboard.json` |
| Shadow retrieval | Enabled for export (`LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=true`, local only) |
| Shadow AI assist | Enabled for export (`VENDOR_TICKET_AI_ASSIST_SHADOW_ENABLED=true`, local only) |
| Repository graph defaults | Both flags remain **false** |

---

## Metrics table (validated)

**Source:** `reports/ai_assist_shadow_metrics_dashboard.json` (after Step 148 re-export)

| Metric | Value |
|--------|------:|
| `total_rows` | 166 |
| `ai_assist_shadow_generated_count` | 166 |
| `error_count` | 0 |
| `escalation_recommended_count` | 37 |
| `duplicate_possible_count` | *(per dashboard; driven by retrieval hit count ≥ 3 when gate allow)* |
| `retrieval_activated_true_count` | 0 |
| `downstream_consumed_retrieval_true_count` | 0 |
| `ai_assist_shadow_only_false_count` | 0 |

### Suggested action distribution

| `ai_assist_suggested_action` | Count |
|------------------------------|------:|
| `monitor` | 109 |
| `escalate` | 37 |
| `billing_review` | 20 |

Distribution aligns with pilot label mix (`support` / `complaint` / `fund`) and deterministic route labels — **not** evidence of autonomous customer actions.

---

## Safety / governance status

| Control | Status |
|---------|--------|
| `retrieval_activated` on export rows | **false** (166/166) |
| `downstream_consumed_retrieval` | **false** (166/166) |
| `ai_assist_shadow_only` | **true** (required; `false` rejected at load) |
| `ai_assist_human_review_required` | **true** (operator review required) |
| Raw message text / draft / final in committed docs | **Not included** |
| Retrieval hit bodies / vectors in export rows | **Not included** |
| `vendor_ticket_node` reads `ai_assist_*` | **No** |
| Draft / final responses use assist metadata | **No** |
| Customer-facing AI assist | **Not enabled** |
| Production `RAG_PROFILE` | **Unchanged** |
| HITL UI panel | **Not implemented** |
| `VENDOR_TICKET_AI_ASSIST_SHADOW_ENABLED` default | **false** |
| `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED` default | **false** |

---

## Known limitations

1. **Rule-based assist only** — no LLM-generated operator text or customer replies in this phase.  
2. **Export-local flags** — metrics reflect operator re-export with both shadow flags **on**; production graph defaults remain off.  
3. **Duplicate heuristic** — `duplicate_possible` depends on aggregate `retrieval_result_count` when gate `allow`; not a confirmed duplicate ticket ID list.  
4. **No HITL consumption** — metrics validate export safety, not operator UI or downstream workflow wiring.  
5. **Non-shadow consumption** — still governed by [non-shadow retrieval consumption governance plan](non_shadow_retrieval_consumption_governance_plan.md); HITL-only visibility remains the sole lane that may be proposed next.

---

## Approval status

| Decision | Status |
|----------|--------|
| Shadow AI assist export + metrics (Steps 147–149) | **Recorded** — batch validated (`error_count=0`) |
| HITL read-only panel | **Not approved** — separate design/implementation step |
| Draft-assist consumption of `ai_assist_*` | **Blocked** |
| Customer-facing AI assist | **Blocked** |
| Non-shadow retrieval consumption (general) | **Blocked** until Step 144 gates satisfied per lane |

**Recommended next step:** Human qualitative review of [HITL read-only preview batch report](hitl_read_only_preview_report.md) (Step 153) and [HITL read-only visibility contract](hitl_read_only_visibility_contract.md) (Steps 150–152). Optional future **production HITL UI** behind new flags — local mock preview via `scripts/render_hitl_read_only_panel_preview.py`; still no draft/final linkage or customer send.

---

## Governance conclusions

1. **Shadow AI assist replay is internally consistent** after Step 148 — all 166 rows generated assist metadata with zero export errors.  
2. **Suggested actions match routing expectations** — support → monitor, complaint → escalate, fund → billing review.  
3. **No runtime activation or downstream consumption** — activation and consumption counts remain zero.  
4. **This step does not implement HITL UI or retrieval consumption** — reporting only.

---

## Related documentation

- [HITL read-only visibility contract](hitl_read_only_visibility_contract.md) — Steps 150–152 (contract + payload + mock preview)  
- [HITL read-only preview batch report](hitl_read_only_preview_report.md) — Step 153
- [Vendor ticket AI assist shadow workflow](vendor_ticket_ai_assist_shadow_workflow.md) — Steps 145–148  
- [Shadow replay metrics refresh report](shadow_replay_metrics_refresh_report.md) — retrieval shadow batch (Step 143)  
- [Non-shadow retrieval consumption governance plan](non_shadow_retrieval_consumption_governance_plan.md) — Step 144  
- [LangGraph retrieval integration plan](langgraph_retrieval_integration_plan.md)
