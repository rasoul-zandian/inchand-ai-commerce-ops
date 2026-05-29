# Step 228 — OpenAI Multi-Turn Baseline Freeze

## Purpose

Freeze a **stable OpenAI-backed operational baseline** for the multi-turn support system. This is behavioral preservation, not a new product feature.

The baseline becomes the trusted reference for:

- regression detection after prompt, routing, reflection, or model changes
- comparing local-model or provider experiments before trust
- tracking silent reflection degradation (rewrite rates, issue-type mix)

## Scope

Frozen behavior includes the full multi-turn eval pack:

- operational sufficiency and acknowledgment patterns
- cancellation / delivery / shipment / panel / settlement / Sheba routing
- reflection rewrites (rule-based provider)
- closed-ticket gating
- product wording and photo gating

**Provider:** `openai` with knowledge hints enabled.

## What is stored

Per scenario (`data/evals/golden_outputs/openai_baseline/{scenario_id}.json`):

- normalized draft SHA-256 fingerprint (not draft text)
- `detected_intent`, `suggested_action`
- `reflection_rewrite_applied`, `should_generate_draft`, `skip_reason`
- `policy_question_type`, `reflection_issue_types`, `graph_status`

Manifest (`manifest.json`):

- provider, model name, feature flags
- freeze timestamp
- reflection aggregate metrics (rewrite rate, save rate, issue-type counts)

**Never stored:** raw prompts, chain-of-thought, transcripts, embeddings, API keys, live customer data.

## Normalization

Draft fingerprints use `normalize_baseline_draft_text()` before hashing:

- trim whitespace
- Persian/Arabic digit normalization
- ZWNJ normalization
- repeated dot / ellipsis collapse
- whitespace collapse
- safe ASCII lowercasing

This reduces cosmetic fingerprint drift while still catching substantive wording changes.

## Workflows

### Freeze (writes baseline)

```bash
PYTHONPATH=. python3.11 scripts/freeze_openai_multi_turn_baseline.py \
  --confirm-real-openai \
  --enable-knowledge-hints \
  --update-baseline \
  --overwrite
```

`--update-baseline` is **required**; without it, no baseline files are written.

### Compare (read-only)

```bash
PYTHONPATH=. python3.11 scripts/compare_openai_baseline.py \
  --provider openai \
  --enable-knowledge-hints \
  --confirm-real-openai \
  --overwrite
```

## Drift philosophy

| Class | When |
|-------|------|
| **acceptable** | Draft fingerprint only; routing/reflection/gating metadata unchanged |
| **review_required** | Intent, action, reflection flags, or policy type changed |
| **critical_regression** | Eval pass → fail, closed-ticket gating break, critical scenario regressions |

## CI policy

- **Normal CI:** mock multi-turn eval only (`scripts/run_multi_turn_eval_suite.py --provider mock`)
- **OpenAI baseline:** manual or scheduled nightly job with API key; never required for merge

## Implementation

- Core module: `app/evals/openai_multi_turn_baseline.py`
- Freeze CLI: `scripts/freeze_openai_multi_turn_baseline.py`
- Compare CLI: `scripts/compare_openai_baseline.py`
- Tests: `tests/test_openai_multi_turn_baseline.py`

## Philosophy

> The frozen baseline is the behavioral contract of the support system.

Future changes must compare against this baseline before they are trusted in production-facing operator workflows.
