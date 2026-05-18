# Pilot Corpus Repository Policy

**Status:** Active — governs storage and git treatment of real-data pilot corpus artifacts  
**Audience:** AI governance, data security, retrieval platform, project owners

---

## Purpose

The controlled pilot corpus (`corpus/vendor_ticket_real_pilot/`) contains **redacted real operational vendor-ticket data**. Before any **embedding generation** or **retrieval indexing**, the project must define **where** that corpus lives, **whether** it may enter version control, and **how** provenance is recorded.

This policy prevents accidental commit of sensitive artifacts, preserves auditability of corpus hashes, and separates **code/docs/tests** (safe to share in the main repository) from **real-data corpus payloads** (require explicit approval).

Related:

- [Pilot corpus 25 build report](pilot_corpus_25_build_report.md)
- [Pilot corpus planning](pilot_corpus_planning.md)
- [Reviewer sign-off workflow](reviewer_signoff_workflow.md)

---

## Current Decision

**`corpus/vendor_ticket_real_pilot/` remains local/private only for now and must not be committed by default.**

- The corpus may exist on developer machines after `build_pilot_corpus.py` runs.
- `.gitignore` excludes `corpus/vendor_ticket_real_pilot/` from git.
- CI and contributors should assume the pilot corpus is **absent** from the public/shared repository until governance explicitly approves a commit or alternate storage.

---

## Rationale

| Concern | Why it matters |
|---------|----------------|
| Residual sensitivity | Even redacted operational tickets can expose business context, seller behavior, and dispute details unsuitable for broad distribution |
| Irreversible git history | Removing committed real data from history is difficult and may not satisfy compliance |
| Embedding provenance | Future vectors must trace to a **specific** corpus lockfile hash; ad-hoc copies undermine reproducibility |
| Governance gate | Committing real-data artifacts requires explicit human approval beyond automated redaction/replay |
| Local verification | `check_pilot_corpus_integrity.py` validates structure and hashes **without** requiring git commit |

---

## Allowed to Commit Now

- Pilot corpus **builder** code (`app/corpus_planning/pilot_corpus_builder.py`, `scripts/build_pilot_corpus.py`)
- **Integrity checker** code (`app/corpus_planning/pilot_corpus_integrity.py`, `scripts/check_pilot_corpus_integrity.py`)
- Governance **docs** (this policy, planning, sign-off workflow, sanitized execution reports)
- **Tests** using synthetic fixtures only
- **Sanitized aggregate reports** (counts, batch IDs, no transcripts)
- **Manifest schema** documentation and planning contracts (`app/corpus_planning/models.py`, etc.)

---

## Not Allowed to Commit Now

| Path / artifact | Reason |
|-----------------|--------|
| `data/private/` | Raw, normalized, redacted exports; sign-off JSON |
| `reports/` | Replay JSONL, dashboards, privacy review outputs |
| `corpus/vendor_ticket_real_pilot/` | Redacted real ticket documents (25-record pilot) |
| Raw production exports | Unreviewed PII/secrets risk |
| Normalized / redacted JSONL | Source payloads for corpus build |
| `approved_room_ids.txt` | Identifies operational ticket scope |
| Reviewer sign-off JSON (full record) | Human governance metadata tied to real batch |
| Replay report JSONL / dashboard HTML | May contain operational detail |

---

## Future Storage Options

1. **Local-only (current)** — corpus on disk under `corpus/vendor_ticket_real_pilot/`; verified via integrity checker; never pushed.
2. **Private repository** — dedicated repo with restricted access; lockfile hash recorded in embedding metadata.
3. **Encrypted artifact storage** — tarball or object encrypted at rest; decryption keys outside git.
4. **Internal object storage** — S3/GCS bucket with IAM; versioned objects; hash recorded in build manifest.
5. **Sanitized public/demo corpus** — separate namespace (e.g. synthetic or heavily scrubbed) distinct from `vendor_ticket_real_pilot`.

---

## Conditions for Future Commit

All of the following are required before `corpus/vendor_ticket_real_pilot/` (or successor path) may be committed or moved to shared storage:

- [ ] Explicit **governance approval** documented (meeting note or sign-off record reference)
- [ ] **Reviewer sign-off** complete for the corpus scope (`reviewer_signoff_id` matches manifest)
- [ ] **Privacy verification** — residual warnings triaged; redaction verified for committed scope
- [ ] **`check_pilot_corpus_integrity.py` passes** on the exact tree to be stored
- [ ] **Project owner approval** for repository visibility and data classification
- [ ] **Repository visibility confirmed private** (if using git) or bucket access restricted
- [ ] **No unresolved warnings** from privacy review on the committed export subset
- [ ] **No raw exports** in the commit or storage bundle

Until then, treat the corpus as **local-only**.

---

## Embedding Implications

- Embeddings must record **corpus identity**, **corpus lockfile hash** (or equivalent content hash), and **manifest version**.
- Embeddings must **not** be generated from uncommitted or untracked corpora unless provenance is explicitly documented (path, hash, build timestamp, sign-off ID).
- **Embedding generation remains a separate future step** — not authorized by this policy or the build report alone.
- Re-indexing after corpus changes requires a **new** lockfile hash and governance review.

---

## Operational Rule

**Before embeddings:**

1. **Decide corpus storage** (local-only vs private repo vs object storage) per this policy.
2. **Re-run** `scripts/check_pilot_corpus_integrity.py` on the source-of-truth tree.
3. **Record** `corpus.lock.json` aggregate hash or full lockfile in embedding provenance metadata.
4. **Document** source of truth (machine path, bucket URI, or commit SHA if ever approved for git).

---

## Recommended Current Policy

| Action | Policy |
|--------|--------|
| Corpus location | **Local-only** under `corpus/vendor_ticket_real_pilot/` |
| Git commit | **Code, docs, tests only** — not the real corpus directory |
| CI | Default `make ci` does **not** require pilot corpus on disk |
| Embeddings / pgvector | **Blocked** until storage decision + separate approval |
| Integrity | Run `check_pilot_corpus_integrity.py` locally before any embedding plan |

---

## Governance

| Item | Current state |
|------|----------------|
| `corpus/vendor_ticket_real_pilot/` in git | **No** (gitignored) |
| `data/private/`, `reports/` in git | **No** (gitignored) |
| Embeddings generated | **No** (`not_started`) |
| pgvector indexing | **No** (`not_started`) |
| Retrieval activation | **No** |
