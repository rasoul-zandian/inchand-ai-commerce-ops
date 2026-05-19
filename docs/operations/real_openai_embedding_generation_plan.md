# Real OpenAI Embedding Generation Plan

**Status:** Planning only — no OpenAI API calls, no embedding generation, no indexing  
**Audience:** Retrieval platform, AI governance, data operations, project owners

---

## Purpose

This plan defines **governance, safety, provenance, and execution criteria** for a **future** controlled step that generates **real OpenAI embeddings** from the approved **local/private** pilot corpus (`corpus/vendor_ticket_real_pilot/`).

It does **not** authorize execution in this document alone. Mock dry-run and artifact integrity must pass first.

Related:

- [Offline embedding generation plan](offline_embedding_generation_plan.md)
- [Mock embedding artifact integrity report](mock_embedding_artifact_integrity_report.md)
- [Pilot corpus repository policy](pilot_corpus_repository_policy.md)
- Planning contract: `app/corpus_planning/embedding_plan_models.py` (`real_embedding_plan_ready()`)

---

## Scope

### In scope

- Real embedding **execution planning** (local operator-run batch)
- OpenAI **model and dimension** policy
- **API key** safety rules
- Local/private **artifact** policy
- Cost, rate-limit, and retry considerations
- **Provenance** requirements for manifests and records
- Post-generation **validation** and integrity checks
- Post-generation **governance** (what real embeddings do *not* approve)

### Out of scope

- Actual OpenAI API calls in this planning step
- Embedding generation in CI or tests
- pgvector indexing or Postgres vector tables
- Retrieval activation in FastAPI / LangGraph
- Production ingestion or serving
- Committing embedding artifacts to git

---

## Preconditions

All of the following are required **before** a real OpenAI embedding run:

| Precondition | Verification |
|--------------|--------------|
| Pilot corpus integrity | `check_pilot_corpus_integrity.py` passes |
| Mock embedding dry-run | `build_pilot_corpus_embeddings.py` completed (`provider=mock`) |
| Mock artifact integrity | `check_embedding_artifact_integrity.py` passes on mock output |
| Repository policy reviewed | [Pilot corpus repository policy](pilot_corpus_repository_policy.md) |
| Corpus lockfile hash recorded | SHA-256 of `corpus/vendor_ticket_real_pilot/corpus.lock.json` |
| `OPENAI_API_KEY` | Present in **local** environment only — never committed |
| Output directory | Under `artifacts/embeddings/` — **gitignored** |
| Operator approval | Explicit human sign-off for real embedding run |

---

## Proposed configuration

| Setting | Value |
|---------|--------|
| Provider | `openai` |
| Model | `text-embedding-3-small` |
| Dimensions | `1536` |
| Source corpus | `corpus/vendor_ticket_real_pilot/` |
| Output directory | `artifacts/embeddings/vendor_ticket_real_pilot_openai/` |
| Manifest `embedding_status` (after future run) | `real_generated` |
| Manifest `indexing_status` | `not_started` (unchanged until indexing step) |

---

## API key safety

| Rule | Requirement |
|------|-------------|
| Storage | `OPENAI_API_KEY` in `.env` or shell env **only** |
| Logging | **Never** print, manifest, or log the API key |
| CI | **No** OpenAI calls in `make ci` or unit tests |
| Tests | Mock/no-network only |
| Execution | **Local operator machine** only |
| Missing key | Fail early before any batch work |
| Scripts | Read key from environment; do not accept key via CLI flags |

---

## Provenance requirements

Each real embedding record and `embedding_manifest.json` must include:

| Field | Source |
|-------|--------|
| `corpus_id` | Pilot `manifest.json` |
| `corpus_version` | Pilot `manifest.json` |
| `source_batch_id` | Pilot `manifest.json` |
| `reviewer_signoff_id` | Pilot `manifest.json` |
| `corpus_lockfile_hash` | SHA-256 of pilot `corpus.lock.json` |
| `document_ids` | Pilot `manifest.document_ids` |
| `embedding_provider` | `openai` |
| `embedding_model` | `text-embedding-3-small` |
| `embedding_dimensions` | `1536` |
| `generated_at` | ISO-8601 UTC at batch completion |
| `generator_version` | Script/package version string |

Regenerate if pilot corpus lockfile changes.

---

## Artifact policy

Future output layout (not created in this planning step):

```
artifacts/embeddings/vendor_ticket_real_pilot_openai/
  embeddings.jsonl
  embedding_manifest.json
  embedding.lock.json
```

| Rule | Policy |
|------|--------|
| Location | **Local/private** — parent `artifacts/embeddings/` is gitignored |
| Sensitivity | Derived from **real operational** redacted tickets — same governance as corpus |
| Git commit | **Do not** commit without explicit governance approval |
| Separation | Distinct directory from mock artifacts (`vendor_ticket_real_pilot/` vs `vendor_ticket_real_pilot_openai/`) |

Artifact status constant (planning): `real_generated` — see `EMBEDDING_ARTIFACT_STATUS_REAL_GENERATED` in `embedding_plan_models.py`.

---

## Cost / rate limit considerations

- Pilot corpus is **tiny** (25 records) — expected **low** dollar cost for `text-embedding-3-small`.
- Still implement **retry with backoff** for transient API errors.
- **Fail safely** on partial runs — do not write a complete manifest if batch aborted mid-way unless explicitly resumable with governance review.
- **No duplicate API calls** if output directory exists — require `--overwrite` after operator confirmation.
- Log **aggregate** counts and token estimates only — not per-record text.

---

## Validation plan

After a future real generation run:

1. Run `check_embedding_artifact_integrity.py` (extended for `real_generated` in a future step).
2. Verify **25** records (current pilot size).
3. Verify **1536** dimensions on every vector.
4. Verify `embedding_provider=openai`, `embedding_model=text-embedding-3-small`.
5. Verify `source_corpus_lockfile_hash` matches current pilot `corpus.lock.json`.
6. Verify `indexing_status=not_started`, `pgvector_indexed=false`, `retrieval_activated=false`.
7. Confirm **no** transcript or forbidden fields in artifacts.

---

## Governance gates

**Real embeddings do not imply:**

| Gate | Status after real embeddings |
|------|------------------------------|
| pgvector indexing | **Not approved** — separate step |
| Retrieval activation | **Not approved** — separate step |
| Production usage | **Not approved** — eval + sign-off required |

Each gate requires its own documentation and operator approval.

---

## Risks

| Risk | Mitigation |
|------|------------|
| API key leakage | Env-only key; no logs; gitignore `.env` |
| Embedding artifact sensitivity | Local-only paths; gitignore; no vector dumps in reports |
| Corpus drift | Bind to `corpus_lockfile_hash`; re-run corpus integrity first |
| Partial generation | Atomic write or explicit `--overwrite`; integrity check fails incomplete trees |
| Model/dimension mismatch | Hard-code validation to 1536 + `text-embedding-3-small` for pilot |
| Accidental indexing | No index scripts in embedding generator; `indexing_status` governance |
| Cost surprise | Small batch; confirm record count before API loop |
| Derived-data governance | Treat OpenAI artifacts like corpus — no commit by default |

---

## Local execution (Step 111 — implemented)

**Script:** `scripts/build_pilot_corpus_embeddings.py` (extended)  
**Library:** `app/corpus_planning/real_embedding_generation.py`

```bash
PYTHONPATH=. python3.11 scripts/build_pilot_corpus_embeddings.py \
  corpus/vendor_ticket_real_pilot \
  --output-dir artifacts/embeddings/vendor_ticket_real_pilot_openai \
  --provider openai \
  --model text-embedding-3-small \
  --dimensions 1536 \
  --confirm-real-openai
```

Requirements:

- `OPENAI_API_KEY` in local environment (never printed or written to artifacts)
- `--confirm-real-openai` (explicit operator approval)
- Pilot corpus integrity passes before generation
- Mock dry-run + mock artifact integrity recommended first

**Verify output:**

```bash
PYTHONPATH=. python3.11 scripts/check_embedding_artifact_integrity.py \
  artifacts/embeddings/vendor_ticket_real_pilot_openai
```

**Operational report:** [real embedding artifact integrity report](real_embedding_artifact_integrity_report.md) — aggregate verification summary (local run; not committed).

## Recommended next steps

1. Run real embedding command **locally only** after governance approval.
2. Run **embedding artifact integrity checker** on OpenAI output directory.
3. Follow [pgvector sandbox indexing plan](pgvector_sandbox_indexing_plan.md) before any sandbox index execution.
4. **Do not** activate retrieval or production ingestion.

---

## Governance status

| Item | Current state |
|------|----------------|
| Real OpenAI generator | **Available** (`--provider openai --confirm-real-openai`) |
| Real OpenAI embeddings generated | **Operator-run only** (not in CI) |
| Mock dry-run | **Available** (Step 108) |
| Mock artifact integrity | **Available** (Step 109) |
| pgvector indexing | **No** |
| Retrieval activation | **No** |
