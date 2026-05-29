# Golden draft fingerprints (multi-turn eval)

Lightweight regression snapshots for `scripts/run_multi_turn_eval_suite.py`.

Each file `{scenario_id}.json` stores a normalized draft SHA-256 fingerprint — not full draft text.

## Update baselines

```bash
PYTHONPATH=. python3.11 scripts/run_multi_turn_eval_suite.py \
  --provider mock \
  --update-golden \
  --overwrite
```

## Check regression

```bash
PYTHONPATH=. python3.11 scripts/run_multi_turn_eval_suite.py \
  --provider mock \
  --check-golden \
  --overwrite
```

Synthetic scenarios only; no live customer data.
