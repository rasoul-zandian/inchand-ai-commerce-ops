# OpenAI multi-turn behavioral baseline

Frozen **behavioral contract** for the multi-turn support sandbox when run with:

- `provider=openai`
- knowledge hints enabled
- rule-based final draft reflection enabled

This directory stores **safe metadata only** (fingerprints, intents, actions, reflection flags). It does **not** store draft text, prompts, transcripts, or API keys.

## Why this exists

The frozen baseline is the known-good OpenAI reference point for:

- detecting regressions after prompt, routing, reflection, or model changes
- comparing future experiments (local models, provider swaps, RAG changes)
- preserving reflection rewrite rates and issue-type distributions

## CI policy

**Do not run OpenAI baseline freeze or compare in normal CI.** The mock multi-turn suite remains CI-safe. OpenAI baseline workflows are **manual or nightly** only.

## Freeze baseline (destructive write)

Requires explicit `--update-baseline` and `--confirm-real-openai`:

```bash
PYTHONPATH=. python3.11 scripts/freeze_openai_multi_turn_baseline.py \
  --confirm-real-openai \
  --enable-knowledge-hints \
  --update-baseline \
  --overwrite
```

Writes:

- `data/evals/golden_outputs/openai_baseline/{scenario_id}.json`
- `data/evals/golden_outputs/openai_baseline/manifest.json`
- `reports/openai_baseline_freeze_summary.json`
- `reports/openai_baseline_freeze_report.md`

Freeze succeeds only when:

- all eval scenarios pass
- triage reports zero real failures after acceptable-variance downgrade
- no critical or high triage severities

## Compare against baseline (read-only)

```bash
PYTHONPATH=. python3.11 scripts/compare_openai_baseline.py \
  --provider openai \
  --enable-knowledge-hints \
  --confirm-real-openai \
  --overwrite
```

Writes:

- `reports/openai_baseline_compare_summary.json`
- `reports/openai_baseline_compare_report.md`

Without `--update-baseline`, baseline files are never overwritten.

## Drift classes

| Class | Meaning |
|-------|---------|
| `none` | No meaningful drift |
| `acceptable` | Draft fingerprint only (cosmetic wording) |
| `review_required` | Intent, action, reflection, or gating metadata changed |
| `critical_regression` | Eval regression, gating break, or failed critical scenarios |

## See also

- [Step 228 — OpenAI Multi-Turn Baseline Freeze](../../../docs/operations/openai_multi_turn_baseline_freeze.md)
- [Multi-turn golden outputs (mock)](../README.md)
