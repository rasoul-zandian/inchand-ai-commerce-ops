# Real Embedding Artifact Integrity Report

**Status:** Local execution verified — aggregate metadata only  
**Audience:** Retrieval platform, AI governance, data operations, infrastructure

---

## Purpose

This report documents the **successful local generation** and **integrity verification** of **real OpenAI** embedding artifacts for the approved 25-record pilot corpus (`vendor_ticket_real_pilot`).

It is a **sanitized operational record** only. It does **not** authorize pgvector indexing, retrieval activation, or production runtime changes.

Integrity checker: `scripts/check_embedding_artifact_integrity.py`  
Generation: `scripts/build_pilot_corpus_embeddings.py` (`--provider openai --confirm-real-openai`)

---

## Governance scope

| Boundary | Status |
|----------|--------|
| Artifact storage | **Local/private** — not committed to git |
| Git path | `artifacts/embeddings/` — **gitignored** |
| Pilot corpus | **Local/private** — `corpus/vendor_ticket_real_pilot/` gitignored |
| Production runtime | **Unchanged** — no retrieval wiring |
| pgvector | **Sandbox indexing available** — local CLI only; not run in CI |
| CI / tests | **No** OpenAI calls |

---

## Artifact location policy

Real OpenAI artifacts live under:

```
artifacts/embeddings/vendor_ticket_real_pilot_openai/
  embeddings.jsonl
  embedding_manifest.json
  embedding.lock.json
```

| Rule | Policy |
|------|--------|
| Commit to repository | **No** — explicit governance approval required |
| Share outside operator machine | **No** without data-classification review |
| Transcripts in artifacts | **Excluded** by generator design |
| API keys in artifacts | **Never** stored |

---

## Integrity verification summary

Local run of `check_embedding_artifact_integrity.py` against `artifacts/embeddings/vendor_ticket_real_pilot_openai/`:

| Outcome | Value |
|---------|--------|
| Result | **passed** |
| `integrity_issue_count` | **0** |

Checks validated: required files present; lockfile SHA-256 matches; record count alignment; uniform 1536 dimensions; provider/model consistency; corpus lockfile hash on manifest and records; forbidden text fields absent; governance flags (`real_generated`, `not_started`, `pgvector_indexed=false`, `retrieval_activated=false`).

---

## Verified metrics (aggregate only)

| Field | Value |
|-------|--------|
| `document_count` | **25** |
| `embedding_record_count` | **25** |
| `embedding_provider` | **openai** |
| `embedding_model` | **text-embedding-3-small** |
| `embedding_dimensions` | **1536** |
| `source_corpus_id` | **vendor_ticket_real_pilot** |
| `source_corpus_lockfile_hash_prefix` | **8cfc18e1c392...** |
| `embedding_status` | **real_generated** |
| `indexing_status` | **not_started** |
| `pgvector_indexed` | **false** |
| `retrieval_activated` | **false** |
| `integrity_issue_count` | **0** |

No embedding vectors, transcripts, or API key material appear in this report.

---

## Provenance chain

```
normalized export (local/private, data/private/)
  → PII redaction (scripts/redact_ticket_export.py)
  → validate redacted JSONL
  → replay + privacy review (166-ticket batch)
  → reviewer sign-off (local/private)
  → approved room_id list (local/private)
  → pilot corpus build (corpus/vendor_ticket_real_pilot/, 25 records)
  → pilot corpus integrity check (passed)
  → mock embedding dry-run (optional baseline)
  → real OpenAI embedding generation (local, OPENAI_API_KEY)
  → embedding artifact integrity check (passed)
```

Each stage is **governed separately**. This report covers only the **final embedding artifact** stage.

---

## Operational interpretation

- **Real embeddings exist locally** and passed structural/provenance integrity checks.
- **Artifacts are local-only** and remain **gitignored** per [repository policy](pilot_corpus_repository_policy.md).
- **No retrieval activation** occurred — FastAPI/LangGraph runtime unchanged.
- **No pgvector indexing** is implied by this report alone — use the sandbox indexing CLI locally when ready.
- **No production runtime** was affected by this step.
- **No raw transcripts or embedding vectors** are committed to the repository.
- **`OPENAI_API_KEY`** was used from the local environment only and was **not** written to manifests, lockfiles, or logs.

Passing this report **does not** approve pgvector indexing or production retrieval.

---

## Safety notes

| Topic | Assurance |
|-------|-----------|
| Artifact contents | **Vectors + governance metadata** only |
| Transcripts | **Excluded** from `embeddings.jsonl` records |
| Message payloads | **Not** present in embedding artifacts |
| `retrieved_context` | **Absent** |
| `draft_response` / `final_response` | **Absent** |
| Lockfile | Hashes for `embeddings.jsonl` and `embedding_manifest.json` validated |
| Corpus binding | `source_corpus_lockfile_hash` recorded on manifest and each record |

---

## Next-step gates

| Step | Gate |
|------|------|
| pgvector sandbox indexing | **Local CLI** — `scripts/index_pilot_embeddings_pgvector.py` with `--confirm-sandbox`; see [pgvector sandbox indexing plan](pgvector_sandbox_indexing_plan.md) |
| Retrieval activation | **Separate approval** — not implied by real embeddings |
| Commit embedding artifacts | **Separate approval** — default remains gitignored |
| Production ingestion | **Out of scope** |

---

## Recommended next steps

1. Preserve artifacts under `artifacts/embeddings/vendor_ticket_real_pilot_openai/` locally; do not commit without governance decision.
2. Re-run `check_embedding_artifact_integrity.py` after any corpus lockfile change before indexing experiments.
3. Run sandbox indexing locally when ready:

```bash
PYTHONPATH=. python3.11 scripts/index_pilot_embeddings_pgvector.py \
  artifacts/embeddings/vendor_ticket_real_pilot_openai \
  --namespace vendor_ticket_real_pilot \
  --index-version pilot_v1 \
  --profile semantic_pgvector \
  --confirm-sandbox
```

4. Run pilot retrieval eval (evaluation only; requires `OPENAI_API_KEY` for query embeddings):

```bash
PYTHONPATH=. python3.11 scripts/eval_pilot_retrieval.py \
  --cases evals/pilot_retrieval/vendor_ticket_real_pilot_cases.json \
  --namespace vendor_ticket_real_pilot \
  --index-version pilot_v1 \
  --profile semantic_pgvector \
  --top-k 5 \
  --output reports/pilot_retrieval_eval_pilot_v1.json \
  --overwrite
```

5. Review `reports/pilot_retrieval_eval_pilot_v1.json` and human-sample failures — **no** LangGraph/`RAG_PROFILE` activation.
6. Document outcomes in [pilot retrieval evaluation report](pilot_retrieval_evaluation_report.md) (aggregate metrics only).
7. **Do not** enable production retrieval until eval gates pass.

Related: [Mock embedding artifact integrity report](mock_embedding_artifact_integrity_report.md), [Pilot corpus 25 build report](pilot_corpus_25_build_report.md), [Offline embedding generation plan](offline_embedding_generation_plan.md).
