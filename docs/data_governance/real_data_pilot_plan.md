# Real Data Pilot Plan — Vendor Ticket Retrieval

**Status:** Planning only (no import, no production wiring)  
**Audience:** Retrieval, data governance, and operator reviewers  
**Baseline reference:** [Golden Snapshot 1536-D OpenAI + PgVector](../retrieval_snapshots/golden_snapshot_1536_openai_pgvector.md)

---

## 1. Pilot goals

This pilot validates whether the **semantic_pgvector** retrieval stack behaves acceptably on **small, anonymized, real Inchand vendor-ticket content**—not whether we are ready for full production rollout.

| Goal | What we learn |
|------|----------------|
| **Real-language behavior** | Persian seller support wording, typos, and informal phrasing vs curated bootstrap corpus |
| **Semantic ambiguity** | Irrelevant top-k hits, near-miss patterns, and category bleed (settlement vs escalation vs tone) |
| **Governance under noise** | Lockfile, manifest/eval consistency, and review discipline when data is not hand-authored |
| **Regression awareness** | How real-data retrieval compares to [Golden Snapshot](../retrieval_snapshots/golden_snapshot_1536_openai_pgvector.md) expectations (metrics + qualitative review) |

**This is a controlled pilot:** local/staging, human-reviewed exports, explicit sign-off. It is **not** production rollout, not live customer traffic, and not automated sync from operational databases.

---

## 2. Pilot scope (small and bounded)

### In scope

| Parameter | Recommendation |
|-----------|----------------|
| Volume | **20–50** closed or resolved tickets (not hundreds) |
| Review | **Manually reviewed** by at least one operator + one retrieval reviewer before indexing |
| Language | **Persian (fa-IR)** seller/vendor support cases |
| Mix | Intentional category spread (see below) |

**Suggested category mix (illustrative quotas):**

| Theme | ~Count | RAG role |
|-------|--------|----------|
| Settlement / billing discrepancy | 8–12 | Policies + approved reply patterns |
| Escalation / SLA / repeat complaint | 5–8 | Escalation policy |
| Tone / respectful reply / threat avoidance | 5–8 | Style guide + approved patterns |
| Ambiguous or multi-intent tickets | 5–10 | Stress-test ranking and near-miss guards |

Derived **RAG documents** should be short, approved snippets (policy excerpts, approved reply patterns, style notes)—not full raw threads in the index.

### Explicitly out of scope

- Full production ticket export or continuous ETL
- Automated ingestion pipelines or background workers
- Customer PII, payment identifiers, phone numbers, emails, national IDs, IBANs, addresses
- Internal secrets (API keys, internal URLs, employee names tied to accounts)
- Mixing real pilot documents into `corpus/vendor_ticket/` bootstrap corpus in the first iteration
- Changing retrieval runtime, FastAPI, LangGraph, or CI pgvector requirements for this pilot

---

## 3. Anonymization policy

**Rule:** Raw exports **never** enter git. Only **reviewed, anonymized derivatives** may be committed after sign-off.

### Must remove or redact

| Category | Examples | Action |
|----------|----------|--------|
| Direct identifiers | Phone (`09…`), email, national ID | Remove or replace with placeholder |
| Financial identifiers | Card numbers, IBAN/Sheba (`IR…`), wallet IDs | Remove |
| Location | Street addresses, precise geo | Generalize or remove |
| Account linkage | Real vendor/seller/order IDs in text | Replace with stable placeholders |
| People | Customer/agent personal names when feasible | Role labels (`فروشنده`, `پشتیبان`) or placeholders |
| Secrets | Tokens, passwords, internal system names | Remove entirely |

Use `app/data_readiness/anonymization.py` for deterministic pattern masking, then **manual spot-check** every document—regex alone is insufficient for Persian free text.

**Export shape:** multi-message rooms use the [Conversation Ticket Snapshot](real_ticket_export_format.md) contract (`app/tickets/conversation_models.py`) — UTF-8 JSONL, one room per line, placeholders only in git-safe files. Validated snapshots can be mapped offline via `conversation_snapshot_to_workflow_input()` (`app/tickets/workflow_mapping.py`).

**Offline observation (before pilot corpus):** run `scripts/validate_ticket_export.py`, then `scripts/replay_ticket_export.py` with mock LLM to produce a local `reports/*.jsonl` artifact (gitignored). Purpose is routing/QA observation on real anonymized exports—not production execution, indexing, or auto-approval.

### Placeholder strategy (recommended)

Stable placeholders preserve eval consistency across re-runs:

| Real (never in git) | Placeholder |
|---------------------|-------------|
| Vendor `V-92841` | `SELLER_ID_001` |
| Order `ORD-7721` | `ORDER_ID_001` |
| Ticket `T-445901` | `TICKET_ID_001` |

Maintain a **local-only mapping table** (encrypted disk, not in repo) from placeholder → internal id for debugging during pilot review only.

### Why this matters for retrieval governance

- Prevents accidental **secret or PII commit** during corpus/lockfile updates
- Keeps **eval cases** and manifests safe to diff in PRs
- Ensures future **Golden Snapshots** for real-data pilots are trustworthy references, not leaked production data

---

## 4. Corpus strategy

Keep the **curated bootstrap** corpus (`corpus/vendor_ticket/`) unchanged as the CI-safe reference. Real pilot content lives in a **separate namespace** until deliberately promoted.

### Recommended layout (future; not implemented yet)

```text
corpus/vendor_ticket_real_pilot/
  manifest.json          # pilot_manifest_version, document list
  eval_cases.json        # pilot-specific labeled queries (separate eval_version)
  corpus.lock.json       # regenerated after any body change
  policies/              # derived policy snippets from real cases (approved)
  approved_patterns/     # approved reply excerpts only
  style_guides/          # tone fragments if needed
  metadata/
    pilot_charter.md     # scope, dates, reviewers (no PII)
```

### Governance rules

| Rule | Rationale |
|------|-----------|
| **No mixing** with `corpus/vendor_ticket/` in v1 | Avoids polluting Golden Snapshot bootstrap and CI corpus checks |
| **Versioned manifest** | `manifest_version` / `pilot_id` in manifest metadata |
| **Lockfile required** | Run `make lockfile` after any committed body or eval change; `make corpus-check` in PR |
| **Separate indexing profile** | Optional future `RAG_PROFILE` or table prefix; pilot index must not overwrite staging Golden index without intent |
| **Re-index after every corpus change** | Same rule as staging: `make pg-index` with matching `EMBEDDING_*` |

---

## 5. Evaluation strategy

### Baseline

The [Golden Snapshot](../retrieval_snapshots/golden_snapshot_1536_openai_pgvector.md) remains the **reference for curated 1536-D staging** (pass_rate 1.0, mean_mrr 0.9167, near_miss 0, same-embedding parity).

The real-data pilot will **not** replace that snapshot initially. It adds a **second comparison plane**: curated golden vs real-pilot corpus behavior.

### Eval cases for real data

| Phase | Approach |
|-------|----------|
| **Phase 1** | **Manual review** — operators run queries, inspect top-k, record notes (spreadsheet or markdown, no PII) |
| **Phase 2** | **Labeled eval_cases.json** — 10–20 cases derived from real tickets, with expected doc ids and optional `near_miss_document_ids` |
| **Phase 3** | **Staging automation** — `pg-eval` / `pg-compare` with `BASELINE_PROVIDER=same_embedding` when corpus is stable |

Do **not** add strict CI gates on real-data eval until cases are stable and reviewed.

### Metrics to track

| Metric | Use |
|--------|-----|
| `pass_rate` | All expected ids + source types in top-k |
| `mean_recall_at_k` / `mean_hit_rate` | Coverage of multi-doc expectations |
| `mean_mrr` | Ranking quality |
| `near_miss_violation_count` | Plausible-but-wrong docs ranking before expected hits |
| **Qualitative** | Irrelevant snippets, wrong category, unsafe policy bleed |

Compare trends against Golden Snapshot where comparable; expect **lower or noisier** metrics on real data—that is a pilot outcome, not automatic failure.

---

## 6. Operational safety

| Control | Requirement |
|---------|-------------|
| Environment | **Local/staging only**; same strict manual flow as README staging runbook |
| Production | **No** auto-sync, **no** live traffic, **no** customer-facing experiments |
| Secrets | API keys and DB URLs only in `.env`; never in corpus or snapshots |
| Indexing | Re-index after corpus or embedding model change; document row counts |
| Snapshots | New **pilot snapshot** (separate file) only if governance meaningfully changes—not every typo fix |
| Sign-off | Checklist: anonymization reviewed → corpus-check passed → lockfile committed → pg-eval/pg-compare (when applicable) → reviewer named in pilot metadata |

---

## 7. Success criteria (pilot complete)

The pilot is **successful enough to plan the next phase** (not production) when:

1. **Semantic relevance** — Top-k usually returns correct policy/pattern/style for labeled queries; irrelevant hits are rare and explainable.
2. **Eval consistency** — 10+ pilot eval cases can be written with stable `expected_document_id`s and pass manual replay.
3. **Near-miss clarity** — Violations are understood (query wording, corpus overlap, or true limitation)—not mysterious storage bugs.
4. **Governance intact** — `make corpus-check` / lockfile discipline holds; no raw exports in git.
5. **Golden comparison documented** — Written note on how real pilot differs from Golden Snapshot (metrics + examples).
6. **No safety incidents** — No PII/secrets committed; no accidental overwrite of production-like indexes.

**Pilot failure signals (pause and fix):** frequent wrong-category retrieval, unexplainable pgvector vs in-memory divergence, or inability to write consistent eval cases.

---

## 8. Future directions (brief)

After a successful small pilot, consider **separately** (no commitment in this plan):

- **Reranking** or cross-encoder second stage for near-miss-heavy queries
- **Hybrid retrieval** (BM25 + vector) for short Persian queries
- **Larger corpora** with batch anonymization pipelines
- **Automated ingestion** from approved export buckets (still not live DB)
- **Production deployment** only after DPA, retention, monitoring, and rollback profiles exist

---

## 9. Suggested next steps (execution order)

1. **Charter sign-off** — Approve this plan; name reviewers and pilot date range.
2. **Export sample** — 20–50 closed tickets to local encrypted storage (out of git).
3. **Anonymize + derive** — Mask PII; extract approved snippets; map to `VendorTicketRecord` / future `RAGDocument` shapes per `app/data_readiness/README.md`.
4. **Create pilot corpus namespace** — Manifest, bodies, eval draft; `make lockfile` + `make corpus-check`.
5. **Manual retrieval review** — Staging queries before automation.
6. **Staging eval** — `pg-eval` / `pg-compare` vs same-embedding baseline; optional new pilot snapshot.
7. **Decision memo** — Promote, expand, or pivot (reranking/hybrid) based on success criteria above.

**Do not start step 4 until steps 1–3 are complete.**

---

## Related documentation

- [app/data_readiness/README.md](../../app/data_readiness/README.md) — export contract, masking, schema mapping
- [Staging Retrieval Evaluation Runbook](../../README.md#staging-retrieval-evaluation-runbook) — pg-eval, pg-compare, strict gates
- [Retrieval evaluation snapshots](../retrieval_snapshots/README.md) — Golden Snapshot artifacts
