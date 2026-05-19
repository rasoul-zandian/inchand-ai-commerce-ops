# Pilot Retrieval Evaluation Report

**Status:** Sanitized operational record — evaluation methodology and governance only  
**Audience:** Retrieval evaluation, AI platform governance, data operations

---

## Purpose

This report documents the **sandbox-only retrieval evaluation** of the approved 25-record pilot corpus (`vendor_ticket_real_pilot`) after local OpenAI embeddings and pgvector sandbox indexing.

It is a **governance and operations record** only. It summarizes **aggregate-safe metrics** from the pilot retrieval eval suite. It does **not** authorize LangGraph retrieval activation, production `RAG_PROFILE` changes, or customer-facing retrieval.

**Eval suite:** `scripts/eval_pilot_retrieval.py`  
**Eval cases:** `evals/pilot_retrieval/vendor_ticket_real_pilot_cases.json` (synthetic label/intent queries; no raw ticket text)  
**Local JSON output (gitignored):** `reports/pilot_retrieval_eval_pilot_v1.json`

---

## Governance scope

| Boundary | Status |
|----------|--------|
| Environment | **Local sandbox only** — operator machine |
| Database | **Local Postgres** — not production or shared staging |
| Eval cases in git | **Yes** — sanitized synthetic queries only |
| Local eval JSON | **No** — `reports/` gitignored |
| Pilot corpus / embeddings | **Local/private** — not committed |
| LangGraph retrieval | **Disabled** — no runtime wiring |
| Production `RAG_PROFILE` | **Unchanged** |
| Customer-facing retrieval | **Forbidden** |
| CI | **No** Postgres or OpenAI for pilot eval |

---

## Sandbox-only evaluation status

| Stage | State |
|-------|--------|
| Pilot corpus (25 records) | Local/private — reviewer-approved scope |
| Real OpenAI embeddings | Local — `artifacts/embeddings/vendor_ticket_real_pilot_openai/` |
| Sandbox pgvector index | Local — `record_id` prefix `pilot::vendor_ticket_real_pilot::pilot_v1::` |
| Retrieval eval suite | **Implemented** (Step 115) |
| This operational report | **Documentation** (Step 116) |
| Retrieval activation | **No** |

---

## Provenance chain

```
approved pilot corpus (vendor_ticket_real_pilot)
  → real OpenAI embedding artifacts (text-embedding-3-small, 1536-D)
  → sandbox pgvector index (namespace=pilot, index_version=pilot_v1)
  → pilot retrieval eval suite (semantic_pgvector profile gate)
  → aggregate eval report (this document + gitignored JSON)
```

Each stage requires **separate governance**; passing one stage does not approve the next.

---

## Evaluation methodology

1. **Prerequisites:** Sandbox indexing completed (`index_pilot_embeddings_pgvector.py` with `--confirm-sandbox`); local Postgres available; embedding integrity passed.
2. **Cases:** 18 eval cases (v3) — English baseline + Persian finance calibration; `metadata_filter` uses **stored** fields (`ticket_label`, `route_label`) — not derived `department` (see Step 120 in [failure analysis](pilot_retrieval_failure_analysis.md)).
3. **Profile gate:** `semantic_pgvector` only (1536-D); `semantic_pgvector_16` rejected.
4. **Scope filter:** Results limited to pilot rows via `record_id` prefix and metadata `namespace` / `index_version`.
5. **Query embeddings:** OpenAI `text-embedding-3-small` locally (`OPENAI_API_KEY`); same model family as indexed vectors.
6. **Scoring (per case):**
   - At least one result in top-k
   - Expected `ticket_label` present in top-k labels
   - Expected `department` present in top-k departments (derived from metadata)
   - No `must_not_return_labels` in top-k when specified
7. **Output:** Aggregate metrics + per-case metadata (`case_id`, `query_hash`, labels/departments, pass/fail reasons). **No** raw query text, transcript content, or vectors in committed artifacts.
8. **Compare modes (Step 118):** `--compare-modes` runs `vector_only` vs `metadata_filtered` on cases with `metadata_filter`; writes `delta_pass_rate` and `delta_wrong_label_return_count` (eval-only; not runtime retrieval).

---

## Safety constraints

| Constraint | Enforcement |
|------------|-------------|
| No raw ticket text in eval cases | Synthetic intent queries (English + Persian operational wording) |
| No transcripts in index content | Label-derived summary in `content` column only |
| No vectors in reports | JSON schema excludes embedding arrays |
| No raw queries in committed JSON | `query_hash` only in per-case results |
| No production DB | URL host checks in eval/index CLIs |
| No LangGraph changes | Eval script does not touch runtime graph |
| No automatic activation | `retrieval_activated=false` on all reports |

---

## Aggregate metrics (safe fields only)

Operators copy aggregate values from `reports/pilot_retrieval_eval_pilot_v1.json` after a local eval run. **Do not commit** that file.

| Field | Description | First local run (Step 117) |
|-------|-------------|----------------------------|
| `total_cases` | Eval cases executed | **12** |
| `passed_cases` | Cases passing all scoring rules | **8** |
| `failed_cases` | Cases with any failure reason | **4** |
| `pass_rate` | `passed_cases / total_cases` | **0.6667** |
| `mean_top_score` | Mean similarity score of top hit (when results exist) | **0.4034** |
| `label_match_rate` | Share of cases with expected label in top-k | **0.6667** |
| `department_match_rate` | Share of cases with expected department in top-k | **0.6667** |
| `wrong_label_return_count` | Cases where forbidden labels appeared in top-k | **1** |
| `empty_result_count` | Cases with zero pilot-scoped results | **0** |
| `top_k` | Retrieval depth per case | **5** |
| `profile` | Retrieval profile gate | **semantic_pgvector** |
| `namespace` | Pilot sandbox namespace | **vendor_ticket_real_pilot** |
| `index_version` | Sandbox index version | **pilot_v1** |
| `retrieval_activated` | Runtime activation flag | **false** |

**Excluded from this report and from committed JSON:** raw retrieved `content`, conversation transcripts, embedding vectors, exact distance values per hit, raw query strings, API keys.

---

## Failure analysis (high-level categories only)

When `pass_rate < 1.0`, classify failures without raw ticket content:

| Category | Indicators | Typical causes |
|----------|------------|----------------|
| **Wrong-label retrieval** | `forbidden_labels_in_top_k` or unexpected label in `top_labels` | Semantic overlap between support/complaint/fund intents; insufficient label separation in embedding space |
| **Empty retrieval** | `no_results_returned` | Index not populated; namespace/index_version mismatch; DB connectivity; over-strict pilot filter |
| **Weak semantic match** | Results present but `expected_ticket_label_not_in_top_k` or `expected_department_not_in_top_k` | Query embedding drift; sparse pilot corpus (25 records); generic queries matching wrong route |
| **Ambiguous intent overlap** | Partial label match, department mismatch | Similar vendor phrasing across departments; eval case intent too broad |

**Remediation (sandbox only):** re-index after corpus change; tighten eval cases; human-sample top-k metadata; adjust queries — not production activation.

**First-run deep dive:** All four failures were fund/finance cases; see [pilot retrieval failure analysis](pilot_retrieval_failure_analysis.md) for hypotheses and query calibration actions.

---

## Operational interpretation

- Retrieval was evaluated against a **sandbox pgvector index** scoped to pilot rows only.
- Eval queries are **synthetic** and do not reproduce production ticket wording.
- A passing local eval run demonstrates **sandbox tooling readiness**, not production readiness.
- **LangGraph retrieval remains disabled**; FastAPI default paths unchanged.
- **No customer-facing retrieval** was enabled by this step.
- This report alone does **not** approve runtime retrieval or `RAG_PROFILE` promotion.

---

## Governance conclusions

| Statement | Status |
|-----------|--------|
| Retrieval evaluated in sandbox only | **Yes** |
| Production retrieval activation | **No** |
| LangGraph retrieval enabled | **No** |
| Customer-facing retrieval | **No** |
| Runtime / indexing code changed by this step | **No** |
| Evaluation alone approves activation | **No** |

Passing aggregate metrics are **necessary but not sufficient** for any retrieval activation proposal.

---

## Balanced index eval (Steps 122–123)

After [balanced pilot corpus rebuild](balanced_pilot_corpus_rebuild.md) and eval calibration (cases v4), operators re-ran compare-modes against:

| Field | Value |
|-------|-------|
| Corpus / index | `vendor_ticket_real_pilot_balanced` / `pilot_balanced_v1` |
| Corpus label mix | support **10**, complaint **7**, fund **8** |
| Eval subset | 10 cases with `metadata_filter` (fund/finance compare set) |
| Local JSON | `reports/pilot_retrieval_eval_balanced_v1.json` (gitignored) |

| Mode | pass_rate | wrong_label_return_count | empty_result_count | Fund subset |
|------|-----------|--------------------------|---------------------|-------------|
| **metadata_filtered** | **1.00** | **0** | **0** | **10/10** |
| **vector_only** | **0.90** | **1** | **0** | **9/10** |
| `retrieval_activated` | — | — | — | **false** |

**Metadata-filtered gate (fund routing):** **passed** — suitable for sandbox tooling review when label filters are available at query time.

**Vector-only note:** one known edge on small pilot — `pilot-fund-wallet-fa-016` (`forbidden_labels_in_top_k:support`; fund label still in top-k). Does not block metadata-filtered readiness.

---

## Recommended decision

```text
recommended_decision = retrieval_ready_for_sandbox_tooling_review
```

**Prior decision (Step 117, imbalanced index):** `retrieval_requires_more_eval` — superseded for sandbox tooling review after balanced rebuild and Step 123 calibration.

| Gate | Criterion | Balanced run (Step 123) |
|------|-----------|-------------------------|
| **Metadata-filtered fund routing** | `pass_rate=1.0`, `wrong_label_return_count=0`, `empty_result_count=0` on fund compare subset | **Met** (10/10) |
| **Balanced corpus / index** | fund rows present in corpus and pgvector inventory | **Met** (fund=8) |
| **Vector-only semantic** | `pass_rate=1.0` | **Not met** (0.90; one co-label edge) — documented, non-blocking for tooling review |
| **`retrieval_activated`** | Must remain false in eval reports | **false** |

**What this decision approves**

- Proceed to **sandbox retrieval tooling review** (offline eval CLIs, scoped store, compare-modes, metadata inventory) using the balanced pilot index.
- Continue human sampling of gitignored per-case JSON as good practice.

**What this decision does NOT approve**

| Out of scope | Status |
|--------------|--------|
| LangGraph retrieval integration | **Not approved** |
| Production `RAG_PROFILE` promotion | **Not approved** |
| Customer-facing retrieval | **Not approved** |
| Autonomous retrieval in workflows | **Not approved** |
| Runtime retrieval activation | **Not approved** (`retrieval_activated=false`) |

**Rationale:** Fund routing failures on the first index were traced to **missing fund corpus rows** and eval scope pins, not broken filters. After balanced rebuild, **metadata-filtered** eval satisfies the fund routing gate. Vector-only semantic retrieval retains one small-corpus co-label edge; sandbox tooling can still be reviewed with metadata filters as the primary routing path.

---

## Sandbox retrieval tool (Steps 125–127)

**Status:** Contract + **local sandbox executor** + **local smoke test passed** — **not** LangGraph, production `RAG_PROFILE`, or customer APIs.

| Item | Detail |
|------|--------|
| Contract | [sandbox retrieval tool contract](sandbox_retrieval_tool_contract.md) |
| Smoke test report | [sandbox retrieval tool smoke test report](sandbox_retrieval_tool_smoke_test_report.md) |
| Models / validation | `retrieval_tool_models.py`, `retrieval_tool_validation.py` |
| Executor | `app/corpus_planning/sandbox_retrieval_tool.py` |
| CLI | `scripts/run_sandbox_retrieval_tool.py` (`--confirm-sandbox`, local DB only) |

**Step 127 smoke metrics (aggregate only):** `namespace=vendor_ticket_real_pilot_balanced`, `index_version=pilot_balanced_v1`, `query_hash=c24189e23ea1c12c`, `result_count=5`, `retrieval_activated=false`, `sandbox_only=true`, metadata filter `ticket_label=fund`.

---

## LangGraph retrieval integration (Step 128)

**Status:** [LangGraph retrieval integration plan](langgraph_retrieval_integration_plan.md) — **plan only**; no graph nodes, no runtime activation, production `RAG_PROFILE` unchanged.

| Topic | Plan summary |
|-------|----------------|
| Retrieval policy gate | Pre-retrieval allow/deny before store access |
| Node contract | Thin wrapper over `execute_sandbox_retrieval_tool` |
| HITL | Retrieval assistive only; no auto-send |
| Feature flags | Default off (`LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=false`) |
| Eval gates | Metadata-filtered fund gate + smoke test required before any flag on |

---

## Next-step gates

| Step | Gate |
|------|------|
| Sandbox tooling review | **Proceed** under `retrieval_ready_for_sandbox_tooling_review` |
| Sandbox retrieval tool contract | **Defined** (Step 125) |
| Sandbox retrieval executor CLI | **Implemented** (Step 126) — local operator use only |
| Sandbox retrieval smoke test | **Passed** (Step 127) — [smoke test report](sandbox_retrieval_tool_smoke_test_report.md) |
| LangGraph integration plan | **Defined** (Step 128) — [integration plan](langgraph_retrieval_integration_plan.md); implementation blocked |
| LangGraph / runtime integration | **Separate approval** — blocked |
| LangGraph / runtime retrieval | **Separate approval** — blocked |
| Production `RAG_PROFILE` | **Separate approval** — blocked |
| Commit local artifacts | **Separate approval** — default remains gitignored |
| Full 18-case suite re-run | Optional — compare subset is the fund routing gate |

---

## Related documentation

- [Sandbox retrieval tool smoke test report](sandbox_retrieval_tool_smoke_test_report.md)
- [LangGraph retrieval integration plan](langgraph_retrieval_integration_plan.md)
- [Pilot retrieval failure analysis](pilot_retrieval_failure_analysis.md) (includes `--compare-modes` guidance)
- [PgVector sandbox indexing plan](pgvector_sandbox_indexing_plan.md)
- [Real embedding artifact integrity report](real_embedding_artifact_integrity_report.md)
- [Pilot corpus repository policy](pilot_corpus_repository_policy.md)
- Eval cases: `evals/pilot_retrieval/vendor_ticket_real_pilot_cases.json`
