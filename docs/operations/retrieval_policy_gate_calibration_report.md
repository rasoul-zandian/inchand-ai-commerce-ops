# Retrieval Policy Gate Calibration Report

**Status:** Synthetic calibration passed (Step 139) — governance reporting only  
**Governance:** `recommended_decision = retrieval_ready_for_sandbox_tooling_review` (Step 124)  
**Audience:** Retrieval governance, LangGraph workflow owners, sandbox operators

---

## Purpose

After the Step 138 shadow replay batch showed **166/166 `gate_decision=allow`**, this step adds an explicit **synthetic edge-case calibration** for `evaluate_retrieval_policy_gate` to verify **allow**, **skip**, and **deny** paths before any non-shadow retrieval consumption.

Calibration is **policy evaluation only** — no pgvector, no OpenAI, no LangGraph runtime changes, no retrieval execution.

**Fixtures:** `evals/retrieval_policy_gate/policy_gate_calibration_cases.json`  
**Runner:** `scripts/eval_retrieval_policy_gate.py`  
**Local reports (gitignored):** `reports/retrieval_policy_gate_calibration.json`, `reports/retrieval_policy_gate_calibration.md`

---

## Why calibration was needed

| Observation (Step 138) | Calibration response |
|------------------------|------------------------|
| 166/166 shadow replay rows → `allow` | Does not prove skip/deny paths; may reflect corpus fit or permissive gate on real tickets |
| No skip/deny in batch metrics | Synthetic cases force skip (missing/unknown label) and deny (scope, bounds, filters) |
| `retrieval_result_count` zero in export | Step 141 diagnosed; Step 142 aligned filters; Step 143 refresh: 5/166 after re-export |

Shadow replay measures **real-ticket aggregate behavior**. Calibration measures **deterministic policy strictness** on controlled inputs.

---

## Execution summary

**Scope:** Local/CI-safe; pure Python policy gate.

```bash
PYTHONPATH=. python3.11 scripts/eval_retrieval_policy_gate.py --overwrite
```

| Setting | Value |
|---------|--------|
| pgvector / OpenAI | **Not called** |
| LangGraph | **Unchanged** |
| `retrieval_activated` | **false** on all gate results |
| Production `RAG_PROFILE` | **Unchanged** |

---

## Aggregate metrics (synthetic suite v1)

**Source:** `reports/retrieval_policy_gate_calibration.json` (generated from committed fixtures)

| Metric | Value |
|--------|------:|
| `total_cases` | 17 |
| `passed_cases` | 17 |
| `failed_cases` | 0 |
| `pass_rate` | 1.0 |

### Decision confusion matrix (expected × actual)

| Expected \\ Actual | allow | deny | skip | validation_error |
|--------------------|------:|-----:|-----:|-----------------:|
| allow | 4 | 0 | 0 | 0 |
| deny | 0 | 10 | 0 | 0 |
| skip | 0 | 0 | 2 | 0 |
| validation_error | 0 | 0 | 0 | 1 |

### Scenario counts (actual)

| Scenario | Count |
|----------|------:|
| `vendor_support` | 3 |
| `complaint_review` | 1 |
| `fund_finance` | 5 |
| `unknown` | 7 |

---

## Synthetic coverage

| Category | Cases |
|----------|------:|
| **allow** — support / complaint / fund (matching filters; fund with/without `billing_review`) | 4 |
| **skip** — missing or unknown `ticket_label` | 2 |
| **deny** — `sandbox_only=false`, production namespace, non-pilot index, `top_k` bounds | 5 |
| **deny** — fund without filter, fund wrong route, filter label mismatch, missing filter ticket_label, support without filter | 5 |
| **validation_error** — forbidden `department` key in metadata filter | 1 |

---

## Expected strictness

- **Skip** when `ticket_label` is missing or not in `{support, complaint, fund}`.
- **Deny** when sandbox scope, index version, `top_k`, or metadata filter rules fail.
- **Allow** only with matching `metadata_filter.ticket_label` and fund route gate satisfied when `route_label` is set.
- **Filter validation** rejects forbidden keys (`department`, `namespace`, `index_version`) before gate evaluation.

Real replay batches may still show high `allow` rates if tickets are well-formed and labels match pilot scenarios; calibration confirms deny/skip paths exist and fire on edge inputs.

---

## Governance conclusions

1. **Synthetic calibration passed** — 17/17 fixtures match expected decision, scenario, and reason substrings.
2. **Policy gate is not allow-only** — skip and deny paths verified on synthetic inputs.
3. **No retrieval execution** — calibration calls `evaluate_retrieval_policy_gate` only.
4. **No runtime activation** — `retrieval_activated=false` enforced on results.
5. **No production changes** — graph behavior, `RAG_PROFILE`, draft/final, and customer paths unchanged.
6. **No raw content exposure** — reports contain case ids and aggregate metrics only.

This step **does not** approve retrieval consumption in drafting, HITL, or production graph paths. **No policy rule changes** were made in Step 139.

---

## Related documentation

- [Retrieval policy gate contract](retrieval_policy_gate_contract.md)
- [Shadow replay metrics report](shadow_replay_metrics_report.md) — Step 138 real-ticket batch
- [LangGraph retrieval integration plan](langgraph_retrieval_integration_plan.md)
- `scripts/eval_retrieval_policy_gate.py`
- `evals/retrieval_policy_gate/policy_gate_calibration_cases.json`
