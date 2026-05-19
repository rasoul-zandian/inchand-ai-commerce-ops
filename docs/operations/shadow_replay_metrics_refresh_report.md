# Shadow Replay Metrics Refresh Report

**Status:** Corrected metrics recorded after Step 142 filter alignment (Step 143) — governance reporting only  
**Governance:** `recommended_decision = retrieval_ready_for_sandbox_tooling_review` (Step 124)  
**Audience:** LangGraph workflow owners, retrieval governance, sandbox operators

---

## Purpose

Update the governance record for the **166-ticket shadow replay batch** after:

1. **Step 141** — diagnosed zero `retrieval_result_count` (metadata filter / index vocabulary mismatch)  
2. **Step 142** — aligned export `retrieval_metadata_filter` to `ticket_label` + `route_label` only  
3. **Local re-export + dashboard** — corrected aggregate metrics  

This report supersedes the **result-count sections** of [shadow replay metrics report](shadow_replay_metrics_report.md) (Step 138 baseline). It does **not** approve non-shadow retrieval consumption.

**Gitignored artifacts:** `reports/shadow_replay_balanced_v1.jsonl`, `reports/shadow_retrieval_metrics_dashboard.json`, `reports/shadow_retrieval_metrics_dashboard.md`

---

## Timeline (Steps 138–142)

| Step | Outcome |
|------|---------|
| **138** | Initial 166-ticket shadow replay batch; all rows `gate_decision=allow` |
| **140** | Export hardening: `route_label`, `executor_called`, chain snapshot fields |
| **141** | Diagnosis: `review_priority` in filter (`LOW`/`MEDIUM`) vs index (`normal`/`high`) → 0 index matches |
| **142** | Fix: omit `review_priority` from search filter; keep top-level `review_priority` on export row |
| **143** | This refresh report — corrected metrics after re-export |

---

## Step 141 diagnosis (summary)

**Tool:** `scripts/diagnose_shadow_replay_hits.py` → `reports/shadow_replay_hit_diagnosis.md` (gitignored)

| Finding | Detail |
|---------|--------|
| Index present | 25 rows (`support=10`, `complaint=7`, `fund=8`) |
| Executor ran | `executor_called=true` on all 166 rows |
| Queries non-empty | 166/166 sampled tickets had non-empty bounded query text |
| Filter mismatch | Export filter included `review_priority=LOW`/`MEDIUM`; index stores `normal`/`high` |
| Smoke test contrast | Dry-run CLI uses `ticket_label` + `route_label` only → non-zero hits |

**Conclusion:** Zero hits were from **over-constrained metadata filtering**, not missing index or empty queries.

---

## Step 142 filter alignment (summary)

**Change:** `build_chain_config_from_state()` in `app/corpus_planning/shadow_replay_jsonl_export.py` sets `review_priority=None` for the sandbox chain.

| Field | In `retrieval_metadata_filter` (search) | Top-level export row |
|-------|----------------------------------------|----------------------|
| `ticket_label` | **Yes** | Yes |
| `route_label` | **Yes** (deterministic from label) | Yes |
| `review_priority` | **No** (Step 142) | Yes (aggregate only) |

Aligns shadow export with standalone smoke / dry-run CLI behavior. **No** policy gate rule changes, **no** re-index, **no** graph runtime changes.

### Re-export commands (local only)

```bash
PYTHONPATH=. LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=true python3.11 \
  scripts/export_shadow_replay_jsonl.py \
  data/private/vendor_tickets_400.redacted.jsonl \
  --output reports/shadow_replay_balanced_v1.jsonl \
  --namespace vendor_ticket_real_pilot_balanced \
  --index-version pilot_balanced_v1 \
  --profile semantic_pgvector \
  --confirm-sandbox --overwrite

PYTHONPATH=. python3.11 scripts/build_shadow_retrieval_metrics_dashboard.py \
  reports/shadow_replay_balanced_v1.jsonl --overwrite

PYTHONPATH=. python3.11 scripts/diagnose_shadow_replay_hits.py --overwrite
```

---

## Corrected aggregate metrics (post–Step 142)

**Source:** `reports/shadow_retrieval_metrics_dashboard.json` (after Step 142 re-export)  
**Input:** `reports/shadow_replay_balanced_v1.jsonl`

### Required summary

| Metric | Value |
|--------|------:|
| `total_rows` | 166 |
| `shadow_node_executed_count` | 166 |
| `gate_decision_counts.allow` | 166 |
| `gate_decision_counts.skip` | 0 |
| `gate_decision_counts.deny` | 0 |
| `retrieval_error_count` | 0 |
| `retrieval_activated_true_count` | 0 |
| `downstream_consumed_retrieval_true_count` | 0 |

### Result count distribution

`result_count_distribution`:

| `retrieval_result_count` | Count |
|--------------------------|------:|
| `5` | 166 |

All rows returned `retrieval_result_count=5` (sandbox `top_k=5`; eligible index rows per label/route were available after filter alignment).

### Diagnosis confirmation

| Check | Post–Step 142 |
|-------|----------------|
| `export_filter_patterns_all_zero_hits` | **false** |
| Index row count (balanced pilot) | 25 |
| `query_empty_count` (sampled) | 0 |

### Export metadata_filter patterns (3)

| Pattern (aggregate) | Replay rows |
|---------------------|------------:|
| `ticket_label=support`, `route_label=general_vendor_support` | 109 |
| `ticket_label=complaint`, `route_label=escalation_review` | 37 |
| `ticket_label=fund`, `route_label=billing_review` | 20 |

No `review_priority` key in `retrieval_metadata_filter`.

---

## Safety status

| Control | Status |
|---------|--------|
| Raw query / content / vectors in committed docs | **Not included** |
| `retrieval_activated` on export rows | **false** (166/166) |
| `downstream_consumed_retrieval` | **false** (166/166) |
| `vendor_ticket_node` reads `retrieval_*` | **No** |
| Draft / final responses use sandbox hits | **No** |
| Production `RAG_PROFILE` | **Unchanged** |
| `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED` default | **false** |
| Customer-facing retrieval | **Not enabled** |

---

## Governance conclusions

1. **Shadow replay metrics are now internally consistent** — executor runs, filters match index vocabulary, non-zero `retrieval_result_count` where `top_k=5` and rows exist.
2. **Step 141 root cause is resolved for export** — filter alignment only; no retrieval architecture redesign.
3. **High `allow` rate on real tickets remains** — 166/166; synthetic calibration (Step 139) still documents skip/deny paths separately.
4. **No runtime activation** — aggregate `retrieval_activated_true_count=0`.
5. **No downstream consumption** — shadow metadata is observability-only.

This step **does not** approve retrieval consumption in drafting, HITL UI, or production graph paths.

**Next governance (Step 144):** [non-shadow retrieval consumption governance plan](non_shadow_retrieval_consumption_governance_plan.md) — defines evidence and approval gates before HITL-only visibility; draft-assist and customer-facing usage remain **blocked**.

---

## Related documentation

- [Non-shadow retrieval consumption governance plan](non_shadow_retrieval_consumption_governance_plan.md) — Step 144 consumption gates (plan only)
- [Shadow replay metrics report](shadow_replay_metrics_report.md) — Step 138 batch (historical baseline)
- [Retrieval policy gate calibration report](retrieval_policy_gate_calibration_report.md) — Step 139 synthetic edge cases
- [LangGraph shadow retrieval smoke test report](langgraph_shadow_retrieval_smoke_test_report.md)
- [LangGraph sandbox retrieval node plan](langgraph_sandbox_retrieval_node_plan.md)
- `scripts/export_shadow_replay_jsonl.py`, `scripts/build_shadow_retrieval_metrics_dashboard.py`, `scripts/diagnose_shadow_replay_hits.py`
