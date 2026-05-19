# Pilot Balanced Rebuild — Execution Report (Step 122)

**Status:** Local rebuild completed — sandbox eval improved; **retrieval not activated**  
**Audience:** Retrieval evaluation, data operations, AI governance

---

## Purpose

Sanitized record of the **balanced pilot corpus** local rebuild after Step 121 planning. Confirms **fund rows exist** in corpus, embeddings, and pgvector before further eval calibration.

**Local detail (gitignored):** `reports/pilot_balanced_rebuild_step122_execution.md`

---

## Root cause addressed

| Prior state (imbalanced build) | Balanced rebuild |
|------------------------------|------------------|
| Corpus/index fund count **0** | Corpus/index fund count **8** |
| Metadata-filtered fund eval empty (no rows) | Fund hits returned for 9/10 compare cases |

---

## Room selection summary

| Step | Outcome |
|------|---------|
| `--balance-pilot --exclude-qa-attention` | **fund shortfall 0/8** — all fund replay rows QA-flagged |
| Merged selection (documented exception) | support **10**, complaint **7**, fund **8** → **25** rooms |
| Export validation | **passed** (25/25) |

Fund bucket includes QA-flagged tickets by necessity; support/complaint selected with `--exclude-qa-attention`.

---

## Build and integrity

| Artifact | Result |
|----------|--------|
| Corpus dir | `corpus/vendor_ticket_real_pilot_balanced/` (local-only) |
| Corpus integrity | **passed** |
| `ticket_label_counts` | support **10**, complaint **7**, fund **8** |
| OpenAI embeddings | **25** records, integrity **passed** |
| pgvector namespace / version | `vendor_ticket_real_pilot_balanced` / `pilot_balanced_v1` |
| pgvector inventory | support **10**, complaint **7**, fund **8** |

---

## Retrieval eval (compare-modes, fund subset n=10)

**Profile:** `semantic_pgvector` · **top_k:** 5 · **retrieval_activated:** false

| Metric | vector_only | metadata_filtered |
|--------|-------------|-------------------|
| `pass_rate` | **0.9000** | **0.9000** |
| `wrong_label_return_count` | **1** | **0** |
| `empty_result_count` | **0** | **1** |
| `delta_pass_rate` | — | **0.0000** |
| `delta_wrong_label_return_count` | — | **-1** |

### Remaining fund-case failures

| `case_id` | Mode | Issue |
|-----------|------|--------|
| `pilot-fund-wallet-fa-016` | vector_only | Semantic mismatch (support label in top-k) |
| `pilot-fund-reconcile-fa-018` | metadata_filtered | **Eval filter mismatch** — case pins `namespace`/`index_version` for old `pilot_v1` index, not `pilot_balanced_v1` |

**Not a missing-fund corpus regression** — inventory shows `fund=8`.

---

## Governance conclusions

| Statement | Status |
|-----------|--------|
| Balanced corpus built locally | **Yes** |
| Fund records in sandbox index | **Yes** |
| LangGraph / production retrieval | **No** |
| `recommended_decision` (Step 124) | **`retrieval_ready_for_sandbox_tooling_review`** |
| `retrieval_activated` | **false** |

---

## Step 123 — eval calibration (v4)

**Changes:** eval cases v4 — removed `metadata_filter.namespace` / `index_version` pins (pilot scope from CLI); reconciled `pilot-fund-reconcile-fa-018` uses `ticket_label` + `route_label` only; calibrated Persian wallet query (`pilot-fund-wallet-fa-016`).

**Re-run** against `vendor_ticket_real_pilot_balanced` / `pilot_balanced_v1`:

| Mode | pass_rate | wrong_label | empty |
|------|-----------|-------------|-------|
| vector_only | 0.90 | 1 | 0 |
| metadata_filtered | **1.00** | 0 | 0 |

**Resolved:** `pilot-fund-reconcile-fa-018`. **Remaining vector_only edge:** `pilot-fund-wallet-fa-016` (`forbidden_labels_in_top_k:support` only; fund in top-k).

See [failure analysis](pilot_retrieval_failure_analysis.md) Step 123.

---

## Step 124 decision

```text
recommended_decision = retrieval_ready_for_sandbox_tooling_review
```

Metadata-filtered fund subset **10/10**; sandbox tooling review may proceed. Production activation and LangGraph remain **blocked**.

---

## Recommended next steps

1. Begin **sandbox retrieval tooling review** (no runtime activation).
2. Optional: human-sample `pilot-fund-wallet-fa-016` for vector-only edge in gitignored JSON.
3. **Do not** implement LangGraph retrieval or production `RAG_PROFILE` without separate sign-off.

---

## Related

- [Balanced pilot corpus rebuild plan](balanced_pilot_corpus_rebuild.md)
- [Pilot retrieval failure analysis](pilot_retrieval_failure_analysis.md)
- [Pilot retrieval evaluation report](pilot_retrieval_evaluation_report.md)
