# Pilot Corpus 25 Build Report

**Status:** Integrity verified (local build) — embeddings and indexing **not** started  
**Note:** First build was **label-imbalanced** (support 16, complaint 9, fund 0). For balanced rebuild guidance see [balanced pilot corpus rebuild](balanced_pilot_corpus_rebuild.md).  
**Audience:** Retrieval platform, AI governance, data operations

---

## Purpose

Documents the first controlled pilot corpus artifact built from **25** approved, **redacted** real vendor-ticket records. This report is **sanitized** (aggregate metadata only). It does **not** authorize embedding generation, pgvector indexing, or production retrieval activation.

---

## Source Safety

| Artifact | Location | Committed to git |
|----------|----------|------------------|
| Raw / normalized export | `data/private/` | **No** |
| Redacted JSONL | `data/private/vendor_tickets_400.redacted.jsonl` | **No** |
| Approved room ID list | `data/private/approved_room_ids.txt` | **No** |
| Reviewer sign-off record | `data/private/reviewer_signoff_replay_166_redacted.json` | **No** |
| Pilot corpus (25 documents) | `corpus/vendor_ticket_real_pilot/` | **No** — [local-only per repository policy](pilot_corpus_repository_policy.md) |

- Source export remains **local/private**.
- Corpus includes **only** manually approved records from the redacted export.
- No raw unreviewed export is committed.
- No transcripts or private paths appear in this report.

---

## Build Summary

| Field | Value |
|-------|-------|
| `corpus_id` | `vendor_ticket_real_pilot` |
| `corpus_version` | `1` |
| `approved_record_count` | **25** |
| `source_batch_id` | `replay_166_redacted_v1` |
| `reviewer_signoff_id` | `signoff_replay_166_redacted_v1` |
| `embedding_status` | `not_started` |
| `indexing_status` | `not_started` |
| `ticket_label_counts` | support: 16, complaint: 9 |

**Builder:** `scripts/build_pilot_corpus.py`  
**Lockfile generator:** `app/corpus_planning/pilot_corpus_builder.py`

---

## Corpus Structure

```
corpus/vendor_ticket_real_pilot/
  manifest.json
  corpus.lock.json
  documents/           # one JSON per approved room_id
  metadata/
    build_summary.json
  governance/
    reviewer_signoff_reference.json
```

- **`manifest.json`** — corpus identity, document IDs, label counts, governance flags, embedding/indexing status.
- **`corpus.lock.json`** — SHA-256 hashes for manifest, documents, metadata, and governance files (excludes lockfile itself).
- **`documents/`** — approved redacted conversation payloads (local review before any git commit).
- **`metadata/build_summary.json`** — build provenance (batch, sign-off, ordering); export path stays private.
- **`governance/reviewer_signoff_reference.json`** — sign-off reference only; full sign-off JSON remains under `data/private/`.

---

## Integrity Verification

Run locally (no network, no OpenAI, no Postgres):

```bash
PYTHONPATH=. python3.11 scripts/check_pilot_corpus_integrity.py \
  corpus/vendor_ticket_real_pilot
```

Checks performed:

| Check | Description |
|-------|-------------|
| Required paths | `manifest.json`, `corpus.lock.json`, `documents/`, `metadata/build_summary.json`, `governance/reviewer_signoff_reference.json` |
| Document count | On-disk `documents/*.json` count equals `manifest.approved_record_count` |
| Manifest ↔ files | Every `manifest.document_ids` entry has a document file; no extra document files |
| Lockfile hashes | Each `corpus.lock.json` entry matches current SHA-256 and size |
| Embedding / indexing | `embedding_status` and `indexing_status` are `not_started` |
| Governance flags | `raw_exports_committed`, `embeddings_generated`, `indexed_to_pgvector` are **false** |

The checker prints **aggregate summary only** (no transcripts).

---

## Governance Status

- Corpus is approved as a **pilot artifact** for offline evaluation planning (human sign-off + approved room list).
- Corpus is **not** indexed; retrieval is **not** activated.
- Embeddings are **not** generated (`embedding_status=not_started`).
- Embedding vectors are **sensitive derived artifacts** — see [offline embedding generation plan](offline_embedding_generation_plan.md); default output under gitignored `artifacts/embeddings/`.
- Future steps (embedding execution, pgvector, semantic RAG in runtime) require **separate** governance approval; `indexing_status` remains **`not_started`**.

---

## Recommended Next Steps

1. **Follow [repository policy](pilot_corpus_repository_policy.md)** — corpus remains **local-only**; do not commit `corpus/vendor_ticket_real_pilot/` until explicit governance approval.
2. **Add integrity check to CI** only after a repository policy decision to store corpus in-repo (`check_pilot_corpus_integrity.py` is available but not wired into `make ci` by default).
3. **Embedding artifacts** — mock: [mock integrity report](mock_embedding_artifact_integrity_report.md); real OpenAI (local): [real integrity report](real_embedding_artifact_integrity_report.md); artifacts gitignored.
4. **Do not index into pgvector** until embedding and eval plans are approved and documented.

Related: [Pilot corpus planning](pilot_corpus_planning.md), [Repository policy](pilot_corpus_repository_policy.md), [Reviewer sign-off workflow](reviewer_signoff_workflow.md), [Redacted replay execution report](redacted_replay_166_ticket_execution_report.md).
