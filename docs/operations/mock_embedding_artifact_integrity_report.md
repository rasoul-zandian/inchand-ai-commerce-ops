# Mock Embedding Artifact Integrity Report

**Status:** Planning / verification template — aggregate metadata only  
**Audience:** Retrieval platform, AI governance, data operations

---

## Purpose

This report documents verification of **mock** embedding artifacts produced by `build_pilot_corpus_embeddings.py` (Step 108). Passing integrity checks confirms artifact structure, provenance, and governance flags before any **real OpenAI** embedding generation or **pgvector** indexing.

Integrity checker: `scripts/check_embedding_artifact_integrity.py`  
Library: `app/corpus_planning/embedding_integrity.py`

---

## Source safety

| Item | Policy |
|------|--------|
| Embedding artifacts | **Local/private** under `artifacts/embeddings/` — **gitignored** |
| Pilot corpus | **Local/private** — `corpus/vendor_ticket_real_pilot/` gitignored |
| Transcripts in git | **No** — artifacts must not contain transcript/raw text fields |
| OpenAI embeddings | **Not generated** in mock pipeline |
| pgvector indexing | **Not performed** — `indexing_status=not_started` |

---

## Artifact structure

```
artifacts/embeddings/vendor_ticket_real_pilot/
  embeddings.jsonl
  embedding_manifest.json
  embedding.lock.json
```

---

## Integrity checks

| Check | Description |
|-------|-------------|
| Required files | `embedding_manifest.json`, `embeddings.jsonl`, `embedding.lock.json` |
| Lockfile hashes | SHA-256 and size match on-disk files |
| Record count | `embeddings.jsonl` lines == `manifest.document_count` |
| Dimensions | All vectors same length; match `manifest.embedding_dimensions` |
| Provider/model | Consistent across manifest and every record |
| Corpus provenance | `source_corpus_lockfile_hash` present on manifest and records |
| Forbidden fields | No `conversation_transcript`, `transcript`, `raw_text`, `draft_response`, `final_response`, `messages`, `retrieved_context` |
| Governance | `embedding_status=mock_generated`, `indexing_status=not_started`, `pgvector_indexed=false`, `retrieval_activated=false` |

```bash
PYTHONPATH=. python3.11 scripts/check_embedding_artifact_integrity.py \
  artifacts/embeddings/vendor_ticket_real_pilot
```

---

## Expected local result (25-record pilot dry-run)

After a successful Step 108 dry-run against the local pilot corpus:

| Field | Expected value |
|-------|----------------|
| `document_count` | **25** |
| `embedding_record_count` | **25** |
| `embedding_dimensions` | **1536** |
| `embedding_provider` | **mock** |
| `embedding_model` | **mock-embedding-1536** |
| `embedding_status` | **mock_generated** |
| `indexing_status` | **not_started** |
| `pgvector_indexed` | **false** |
| `retrieval_activated` | **false** |

Run the checker locally to confirm `embedding_artifact_integrity: passed` and `issue_count=0`.

---

## Governance interpretation

- **Mock artifact integrity passing does not approve real embeddings** — separate governance step required.
- **Real OpenAI embedding generation** requires explicit approval, API key handling, and updated provenance metadata.
- **pgvector indexing** remains blocked until embedding eval plan and indexing sign-off.
- **Retrieval activation** in production runtime is out of scope.

---

## Recommended next steps

1. Run **embedding artifact integrity check** after every mock dry-run or corpus lockfile change.
2. After [real OpenAI run](real_openai_embedding_generation_plan.md), re-run this checker on `vendor_ticket_real_pilot_openai/` — see [real embedding integrity report](real_embedding_artifact_integrity_report.md).
3. Keep all embedding and corpus payloads **local/private**.
4. **Do not index pgvector** until eval gates and indexing approval are documented.

Related: [Offline embedding generation plan](offline_embedding_generation_plan.md), [Pilot corpus 25 build report](pilot_corpus_25_build_report.md), [Repository policy](pilot_corpus_repository_policy.md).
