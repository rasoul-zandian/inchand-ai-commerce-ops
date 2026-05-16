# Retrieval evaluation snapshots

Version-controlled **known-good** retrieval baselines captured after manual staging validation (`pg-eval`, `pg-compare`, API smoke). Not used in CI; no secrets stored here.

| Snapshot | Description |
|----------|-------------|
| [golden_snapshot_1536_openai_pgvector.md](golden_snapshot_1536_openai_pgvector.md) | First trusted **1536-D OpenAI + pgvector** staging baseline (strict gates, same-embedding parity, API smoke) |
| [golden_snapshot_1536_openai_pgvector.json](golden_snapshot_1536_openai_pgvector.json) | Machine-readable companion metadata |

Future corpus, embedding-model, index, or retrieval-stack changes should re-run strict staging and compare metrics against this snapshot before promotion.
