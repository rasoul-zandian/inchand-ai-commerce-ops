# Shadow Replay Metrics Report

**Status:** Local batch execution passed (Step 138) — governance reporting only  
**Governance:** `recommended_decision = retrieval_ready_for_sandbox_tooling_review` (Step 124)  
**Audience:** LangGraph workflow owners, retrieval governance, sandbox operators

---

## Purpose

Record a **successful local shadow replay batch** on the **166-ticket redacted export**: sanitized JSONL export (Step 137), aggregate metrics dashboard (Step 136), and governance conclusions.

This report contains **aggregate metrics only**. It does **not** approve non-shadow retrieval consumption in drafting, HITL, or customer channels.

**Related (gitignored local artifacts):** `reports/shadow_replay_balanced_v1.jsonl`, `reports/shadow_retrieval_metrics_dashboard.md`, `reports/shadow_retrieval_metrics_dashboard.json`

---

## Source safety

| Artifact | In git? | Notes |
|----------|---------|--------|
| Redacted ticket export | **No** | `data/private/vendor_tickets_400.redacted.jsonl` |
| Shadow replay JSONL | **No** | `reports/shadow_replay_balanced_v1.jsonl` |
| Metrics dashboard | **No** | `reports/shadow_retrieval_metrics_dashboard.*` |

- **No** raw queries, retrieved content, vectors, embeddings, transcripts, API keys, or replay message text in this document.
- Figures below are copied from the **sanitized dashboard JSON** (`generated_at: 2026-05-19T15:20:24Z`).

---

## Execution summary

**Scope:** Local operator machine only; not CI, not production.

| Setting | Value |
|---------|--------|
| `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED` | **true** (local only; repository default **false**) |
| Sandbox namespace | `vendor_ticket_real_pilot_balanced` |
| Sandbox index version | `pilot_balanced_v1` |
| Retrieval profile | `semantic_pgvector` (sandbox chain; not production `RAG_PROFILE`) |
| Input tickets | 166 redacted export rows |
| Shadow node path | Export runs normalize → route → sandbox retrieval chain (no `vendor_ticket_node` draft) |

### Commands (sanitized; no secrets)

**1. Shadow replay JSONL export (Step 137):**

```bash
PYTHONPATH=. LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=true python3.11 \
  scripts/export_shadow_replay_jsonl.py \
  data/private/vendor_tickets_400.redacted.jsonl \
  --output reports/shadow_replay_balanced_v1.jsonl \
  --namespace vendor_ticket_real_pilot_balanced \
  --index-version pilot_balanced_v1 \
  --profile semantic_pgvector \
  --confirm-sandbox
```

**2. Aggregate metrics dashboard (Step 136):**

```bash
PYTHONPATH=. python3.11 scripts/build_shadow_retrieval_metrics_dashboard.py \
  reports/shadow_replay_balanced_v1.jsonl --overwrite
```

Both steps completed successfully on the operator machine. Dashboard input passed safety validation (no forbidden keys; `retrieval_activated` and `downstream_consumed_retrieval` false on all rows).

---

## Aggregate metrics

**Source:** `reports/shadow_retrieval_metrics_dashboard.json`  
**Input:** `reports/shadow_replay_balanced_v1.jsonl`

### Required summary

| Metric | Value |
|--------|------:|
| `total_rows` | 166 |
| `shadow_node_executed_count` | 166 |
| `gate_decision_counts.allow` | 166 |
| `gate_decision_counts.skip` | 0 |
| `gate_decision_counts.deny` | 0 |
| `retrieval_activated_true_count` | 0 |
| `downstream_consumed_retrieval_true_count` | 0 |

### Scenario counts

| Scenario | Count |
|----------|------:|
| `vendor_support` | 109 |
| `complaint_review` | 37 |
| `fund_finance` | 20 |

### Other aggregates

| Metric | Value |
|--------|------:|
| `retrieval_error_count` | 0 |

**Result count distribution:**

| `retrieval_result_count` bucket | Count |
|--------------------------------|------:|
| `(null)` | 166 |

All exported rows recorded `retrieval_result_count` as null in the sanitized JSONL (Step 138 baseline). Aggregate export metadata (gate, scenario, policy reasons) is present; per-row hit counts were not populated because the sandbox executor did not complete on the operator path (e.g. missing pgvector/OpenAI), not because the gate denied retrieval.

**Step 140 export hardening** updates `scripts/export_shadow_replay_jsonl.py` to:
- populate `route_label` via deterministic ticket-label routing before the shadow chain;
- copy sanitized retrieval fields from the chain snapshot (`retrieval_result_count`, `retrieval_query_hash`, `retrieval_metadata_filter`, `executor_called`);
- leave `retrieval_result_count` null only when the gate skips/denies or the executor does not run.

Re-run export + dashboard after Step 140 to refresh metrics.

### Step 141 hit-count diagnosis

**Status:** Diagnosis complete — see [`shadow_replay_hit_diagnosis.md`](../reports/shadow_replay_hit_diagnosis.md) (gitignored) from `scripts/diagnose_shadow_replay_hits.py`.

**Root cause (aggregate):** Export passed `review_priority` (`LOW` / `MEDIUM`) into `retrieval_metadata_filter`, but the pgvector index stores `normal` / `high`. Exact filtering yielded **0** matching index rows per search.

**Step 142 fix:** Shadow export omits `review_priority` from `retrieval_metadata_filter` (keeps `ticket_label` + `route_label` only; `review_priority` remains a top-level aggregate field).

**Step 143 refresh:** Corrected metrics after re-export — see [shadow replay metrics refresh report](shadow_replay_metrics_refresh_report.md) (`result_count_distribution`: **5** for all 166 rows; `retrieval_activated_true_count=0`).

**Not the cause:** Empty queries; missing index rows (25 rows present for balanced namespace).

### Label × gate decision (summary)

| `ticket_label` | allow | skip | deny |
|----------------|------:|-----:|-----:|
| `support` | 109 | 0 | 0 |
| `complaint` | 37 | 0 | 0 |
| `fund` | 20 | 0 | 0 |

### Route label × scenario (summary)

Step 138 rows reported `route_label` as null (export did not run vendor routing). Step 140 adds deterministic `route_label` from `ticket_label`. Step 138 scenario alignment by label:

| Route (exported) | `complaint_review` | `fund_finance` | `vendor_support` |
|------------------|-------------------:|---------------:|-------------------:|
| `(none)` | 37 | 20 | 109 |

---

## Governance conclusions

1. **Shadow replay batch completed successfully** — 166/166 tickets exported to sanitized JSONL; dashboard built without safety violations.
2. **Retrieval policy gate executed on every row** — `shadow_node_executed_count=166`; gate evaluated before any sandbox executor path in the export pipeline.
3. **Retrieval remained sandbox-only** — `retrieval_activated_true_count=0`; export contract enforces `retrieval_sandbox_only` semantics.
4. **Downstream did not consume retrieval** — `downstream_consumed_retrieval_true_count=0`; `vendor_ticket_node` does not read `retrieval_*` fields; draft/final paths unchanged.
5. **No customer-visible behavior changes** — batch is offline reporting only; no API or customer channel changes.
6. **No runtime activation** — aggregate activation count is zero; repository default `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=false` unchanged.
7. **No production `RAG_PROFILE` changes** — sandbox profile used only in local export chain; existing `retrieve_context` / production RAG path untouched.
8. **No raw content in committed docs** — this report and committed code contain aggregate fields only.

This step **does not** approve retrieval consumption in drafting, HITL UI, or production graph paths.

---

## Observations (informational only)

- **Uniform `allow` decisions:** All 166 rows received `gate_decision=allow` (0 skip, 0 deny). This may indicate the redacted 166-ticket batch aligns well with current allowed scenarios, **or** that the policy gate is permissive for this corpus slice.
- **Scenario mix:** Majority `vendor_support` (109), then `complaint_review` (37), `fund_finance` (20) — consistent with label distribution in the redacted replay baseline.
- **`retrieval_result_count` null on all rows:** Worth a future calibration pass to confirm whether the export chain should populate counts when the gate allows (e.g. executor/pgvector availability during export). Not a policy change for Step 138.
- **Route labels null in export:** Routing metadata may not have been promoted to `route_label` before export row serialization; matrices use `(none)` for route. Future export hardening could align route labels with replay reports.

**Recommendation (observational):** Compare this batch with **Step 139 synthetic calibration** — [retrieval policy gate calibration report](retrieval_policy_gate_calibration_report.md) confirms skip/deny paths on edge-case fixtures; high `allow` on real tickets may still reflect corpus fit.

**Step 138 makes no policy, graph, or gate rule changes.**

---

## Related documentation

- [LangGraph sandbox retrieval node plan](langgraph_sandbox_retrieval_node_plan.md)
- [LangGraph shadow retrieval smoke test report](langgraph_shadow_retrieval_smoke_test_report.md)
- [LangGraph retrieval integration plan](langgraph_retrieval_integration_plan.md)
- [Retrieval policy gate contract](retrieval_policy_gate_contract.md)
- [Redacted replay execution report — 166-ticket batch](redacted_replay_166_ticket_execution_report.md)
- `scripts/export_shadow_replay_jsonl.py` — Step 137 export
- `scripts/build_shadow_retrieval_metrics_dashboard.py` — Step 136 dashboard
