# Developer commands (mock-only, offline-safe; mirrors CI checks).

PYTHON ?= python3.11
MOCK_ENV = LLM_PROVIDER=mock \
	LLM_MODEL=mock-vendor-ticket-drafter \
	EMBEDDING_PROVIDER=mock \
	EMBEDDING_MODEL=mock-embedding-small \
	RAG_STRATEGY=mock \
	LANGSMITH_TRACING=false

.DEFAULT_GOAL := help

.PHONY: help install lint format format-check test test-pgvector corpus-check lockfile lockfile-check config-check smoke-semantic smoke-openai pg-up pg-down pg-logs pg-init pg-init-16 pg-index pg-index-dry-run pg-index-16 pg-index-16-dry-run pg-smoke-16 pg-eval pg-compare ci

help:
	@echo "Available targets:"
	@echo "  install         Install project with dev dependencies"
	@echo "  lint            Run Ruff linter (app, tests, scripts)"
	@echo "  format          Run Ruff formatter (writes changes)"
	@echo "  format-check    Verify Ruff formatting without writing"
	@echo "  test            Run pytest (mock providers only)"
	@echo "  test-pgvector   Run pgvector integration tests (requires PGVECTOR_TEST_DATABASE_URL)"
	@echo "  corpus-check    Run corpus integrity, lockfile, and eval consistency"
	@echo "  lockfile        Regenerate corpus.lock.json after intentional corpus changes"
	@echo "  lockfile-check  Verify corpus.lock.json is fresh without rewriting it"
	@echo "  config-check    Validate local .env / AppSettings (no secrets printed)"
	@echo "  smoke-semantic  Run semantic RAG smoke test against local FastAPI"
	@echo "  smoke-openai    Run OpenAI vendor ticket smoke test against local FastAPI"
	@echo "  pg-up           Start local Postgres + pgvector (docker compose)"
	@echo "  pg-down         Stop local Postgres + pgvector"
	@echo "  pg-logs         Follow local Postgres logs"
	@echo "  pg-init         Apply rag_vector_records migration (local dev only)"
	@echo "  pg-index        Index vendor_ticket corpus into PgVectorStore (offline)"
	@echo "  pg-index-dry-run  Validate indexing without writing to Postgres"
	@echo "  pg-init-16      Apply rag_vector_records_16 migration (local mock smoke)"
	@echo "  pg-index-16-dry-run  Validate 16-D mock indexing (no DB writes)"
	@echo "  pg-index-16     Index corpus into rag_vector_records_16 (mock 16-D)"
	@echo "  pg-smoke-16     End-to-end mock index + semantic search smoke (local)"
	@echo "  pg-eval         Run retrieval eval cases against PgVectorStore (manual)"
	@echo "  pg-compare      Compare in-memory vs pgvector retrieval eval (manual)"
	@echo "  ci              Run lint, format-check, test, corpus-check, lockfile-check"

install:
	python -m pip install --upgrade pip
	pip install -e ".[dev]"

lint:
	ruff check app tests scripts

format:
	ruff format app tests scripts

format-check:
	ruff format --check app tests scripts

test:
	$(MOCK_ENV) pytest

test-pgvector:
	PGVECTOR_TEST_DATABASE_URL?=postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai \
	PYTHONPATH=. $(MOCK_ENV) pytest -m pgvector

corpus-check:
	$(MOCK_ENV) PYTHONPATH=. $(PYTHON) scripts/check_corpus_integrity.py

lockfile:
	$(MOCK_ENV) PYTHONPATH=. $(PYTHON) scripts/regenerate_corpus_lockfile.py

lockfile-check:
	$(MOCK_ENV) PYTHONPATH=. $(PYTHON) scripts/check_corpus_lockfile_fresh.py

config-check:
	PYTHONPATH=. $(PYTHON) scripts/check_config.py

smoke-semantic:
	./scripts/smoke_semantic_rag_vendor_ticket.sh

smoke-openai:
	./scripts/smoke_openai_vendor_ticket.sh

pg-up:
	docker compose up -d

pg-down:
	docker compose down

pg-logs:
	docker compose logs -f postgres

pg-init:
	./scripts/db_init_pgvector.sh

pg-index:
	PYTHONPATH=. $(PYTHON) scripts/index_corpus_to_pgvector.py

pg-index-dry-run:
	DRY_RUN=true PYTHONPATH=. $(PYTHON) scripts/index_corpus_to_pgvector.py

pg-init-16:
	./scripts/db_init_pgvector_16.sh

pg-index-16-dry-run:
	DRY_RUN=true PGVECTOR_TABLE=rag_vector_records_16 PGVECTOR_DIMENSIONS=16 PYTHONPATH=. $(PYTHON) scripts/index_corpus_to_pgvector.py

pg-index-16:
	PGVECTOR_TABLE=rag_vector_records_16 PGVECTOR_DIMENSIONS=16 PYTHONPATH=. $(PYTHON) scripts/index_corpus_to_pgvector.py

pg-smoke-16:
	PGVECTOR_TABLE=rag_vector_records_16 PGVECTOR_DIMENSIONS=16 PYTHONPATH=. $(PYTHON) scripts/smoke_pgvector_16.py

pg-eval:
	PYTHONPATH=. $(PYTHON) scripts/evaluate_pgvector_retrieval.py

pg-compare:
	PYTHONPATH=. $(PYTHON) scripts/compare_retrieval_backends.py

ci:
	$(MAKE) lint
	$(MAKE) format-check
	$(MAKE) test
	$(MAKE) corpus-check
	$(MAKE) lockfile-check
