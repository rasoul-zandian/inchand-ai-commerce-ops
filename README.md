# Inchand AI — Commerce Operations Copilot (MVP)

Production-oriented skeleton for the **Vendor Ticket Assistant** workflow: a controlled LangGraph pipeline with shared state, mock tools first, and no destructive or outbound actions in early phases.

This repository is built **step by step**. Each step adds only the agreed files; graph code, nodes, tools, and the FastAPI application come in later steps.

## Tech stack (target)

- Python 3.11+
- LangGraph / LangChain
- Pydantic v2
- FastAPI
- pytest

**Default runtime:** mock LLM/embeddings and in-memory RAG (no Postgres in **`make ci`**). **Opt-in (manual/staging):** LangSmith tracing, OpenAI LLM/embeddings, and pgvector retrieval via **`RAG_PROFILE=semantic_pgvector`** or **`semantic_pgvector_16`**—validated with **`make pg-eval`** / **`make pg-compare`**, not enabled in CI.

## Layout

- `app/graph`, `app/nodes`, `app/tools` — workflow and orchestration (added incrementally).
- `app/state`, `app/schemas` — shared state and validation.
- `app/services`, `app/prompts`, `app/rag`, `app/memory` — services and retrieval (mock/in-memory default; opt-in pgvector profiles).
- `app/api` — HTTP surface (later).
- `tests` — pytest suite.

## Local setup

```bash
cd inchand_ai
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Run tests (when tests exist):

```bash
pytest
```

## CI

GitHub Actions runs:

- `ruff check app tests scripts` (lint)
- `ruff format --check app tests scripts` (formatting)
- `pytest` (with mock providers only: no OpenAI, no LangSmith secrets, no DB)
- `PYTHONPATH=. python3.11 scripts/check_corpus_integrity.py` to validate:
  - corpus SHA-256 integrity inventory + committed lockfile
  - manifest/eval consistency
- `PYTHONPATH=. python3.11 scripts/check_corpus_lockfile_fresh.py` to ensure `corpus.lock.json` is not stale

Corpus governance note: any change to `corpus/vendor_ticket/` must be accompanied by an intentional regeneration of `corpus/vendor_ticket/corpus.lock.json`.

## Developer Commands

From the project root, **`make ci`** runs the same offline checks as GitHub Actions (mock providers only—no OpenAI, no LangSmith secrets, no database):

```bash
make install       # pip install -e ".[dev]"
make lint          # ruff check app tests scripts
make format        # ruff format app tests scripts (writes changes)
make format-check  # ruff format --check (CI-style, no writes)
make test          # pytest with mock LLM/embeddings/RAG
make corpus-check  # integrity inventory + corpus.lock.json + manifest/eval consistency
make lockfile      # regenerate corpus/vendor_ticket/corpus.lock.json (after intentional edits)
make lockfile-check # verify lockfile is fresh (does not rewrite the file)
make config-check  # validate local .env / AppSettings (see Config validation)
make ci            # lint, format-check, test, corpus-check, lockfile-check
```

**Manual smoke tests** (not part of **`make ci`**; require a **running local FastAPI** server and your current shell environment—**no** **`.env`** auto-sourcing):

```bash
make smoke-semantic   # semantic RAG path; scripts run config preflight first
make smoke-openai     # OpenAI draft path; requires OPENAI_API_KEY in environment
```

- **`make smoke-semantic`**: expects **`RAG_STRATEGY=semantic`** or a compatible profile (e.g. **`RAG_PROFILE=semantic_local`**). Mock embeddings are fine; no OpenAI key required for retrieval validation.
- **`make smoke-openai`**: requires **`OPENAI_API_KEY`** and typically **`LLM_PROVIDER=openai`** when exercising the real OpenAI adapter. Secrets are never printed by the smoke scripts.

Run **`make config-check`** before **`uvicorn`**. Export env vars with **`set -a && source .env && set +a`** in the same shell as the server and smoke command.

**When to regenerate the lockfile:** after you intentionally change corpus bodies, `manifest.json`, or `eval_cases.json`. Recommended flow:

1. Edit corpus files under `corpus/vendor_ticket/`
2. `make corpus-check` (confirm manifest/eval consistency and current inventory)
3. `make lockfile` (writes new SHA-256 hashes to `corpus.lock.json`)
4. Review the diff (corpus + lockfile together)
5. Commit both the corpus changes and the updated lockfile

If **`make lockfile-check`** or CI fails with a stale lockfile message, run **`make lockfile`**, review the diff, and commit the updated `corpus.lock.json` intentionally.

### Config validation

**`make config-check`** validates your **local** `.env` / environment by loading **`AppSettings`** (no network, no LangSmith, no workflow run, no FastAPI startup). It prints only **safe operational fields**—never API keys or other secrets. Use it before **`uvicorn`**, manual workflow runs, and the [smoke tests](#manual-smoke-test-semantic-rag-vendor-ticket) below. **`make ci`** does **not** read your local `.env`; it injects deterministic mock env vars—**`config-check`** is for developer-machine validation only.

```bash
make config-check
```

Example success output:

```text
config check: passed
  environment=development
  llm_provider=mock
  embedding_provider=mock
  rag_profile=semantic_local
  rag_strategy=mock
  rag_top_k=5
```

Example failure (invalid profile):

```text
config check: failed
  rag_profile: Invalid RAG_PROFILE 'pinecone'; allowed values: mock, policy_only, ...
```

**`make ci`** vs **`make config-check`:**

| Command | Purpose |
|---------|---------|
| **`make ci`** | Deterministic offline CI checks (mock env vars injected; lint, tests, corpus governance) |
| **`make config-check`** | Validate **your** local runtime configuration as loaded from `.env` |

Equivalent manual commands:

```bash
ruff check app tests scripts
ruff format --check app tests scripts
pytest
PYTHONPATH=. python3.11 scripts/check_corpus_integrity.py
PYTHONPATH=. python3.11 scripts/check_corpus_lockfile_fresh.py
PYTHONPATH=. python3.11 scripts/regenerate_corpus_lockfile.py
```

## LangSmith Observability

[LangSmith](https://smith.langchain.com/) is used to trace LangGraph workflow execution (runs, latency, and nested steps) so you can debug and monitor the copilot without changing business logic in the graph.

**Enable tracing**

1. Copy `.env.example` to `.env` (keep `.env` out of version control).
2. Set:

   - `LANGSMITH_TRACING=true`
   - `LANGSMITH_API_KEY=your_key`
   - `LANGSMITH_PROJECT=inchand-ai-commerce-mvp`

3. Run the FastAPI app or the Python demo as usual. Traces should appear in the LangSmith project you configured.

**Security**

- Do not commit API keys. Use `.env` locally or inject secrets via your deployment platform in production.

**Scope of this step**

- This adds configuration and documentation only. No LLM or RAG is introduced here; tracing applies to the existing mock workflow when LangChain/LangGraph emit spans to LangSmith.

**Local run examples** (inline env vars; replace `your_key` with a real key from LangSmith)

FastAPI:

```bash
LANGSMITH_TRACING=true LANGSMITH_API_KEY=your_key LANGSMITH_PROJECT=inchand-ai-commerce-mvp python3.11 -m uvicorn app.api.main:app --reload
```

Python demo:

```bash
LANGSMITH_TRACING=true LANGSMITH_API_KEY=your_key LANGSMITH_PROJECT=inchand-ai-commerce-mvp python3.11 -c "from app.graph.main_graph import run_vendor_ticket_demo; print(run_vendor_ticket_demo('سلام، وضعیت تسویه را بررسی کنید.', 't-123')['workflow_status'])"
```

Run these from the project root with `PYTHONPATH=.` or after `pip install -e .` so `app` imports resolve.

**Current explicit tracing entry point**

- `run_vendor_ticket_demo` is decorated with `@traceable` (LangSmith SDK), so a top-level run is emitted even when the graph is mostly custom Python and mock tools.
- After exporting `LANGSMITH_*` variables (for example by sourcing `.env`), run the API or the Python demo; in LangSmith you should see a run named **`run_vendor_ticket_demo`** (run type **chain**), tagged `inchand`, `vendor_ticket`, `mvp`.

**Dependencies**

Tracing still relies on `LANGSMITH_*` environment variables. The `langsmith` package is available from existing LangChain/LangGraph dependencies; `app/graph/main_graph.py` imports `traceable` explicitly so this entry point always registers with LangSmith when tracing is enabled.

## LLM configuration

The vendor ticket node calls `app.llm.generate_text` only; provider choice comes from `AppSettings` (`LLM_PROVIDER`, `LLM_MODEL`) and optional secrets in `.env`.

### OpenAI provider

- Set `LLM_PROVIDER=openai`.
- Set `LLM_MODEL` to a valid OpenAI model for the [Responses API](https://platform.openai.com/docs/api-reference/responses) (for example a current GPT model slug from your account).
- Set `OPENAI_API_KEY` in the environment or `.env` (never commit keys).
- The workflow still **requires human approval** before any outbound ticket reply; drafts are operator-facing only until reviewed.
- Do not point real production ticket exports at the model until **anonymization** and data review are complete.

### Mock provider (default)

- `LLM_PROVIDER=mock` keeps deterministic Persian placeholder output for local development and CI.

## Multi-Agent Vendor Ticket Workflow

The vendor ticket LangGraph node (`vendor_ticket_node`) is internally structured into small specialist steps: **intent** (rule-based normalization), **policy grounding** (summarizes existing `retrieved_context` / RAG docs—no new retrieval), **drafting** (prompt + `generate_text`), **QA / self-check** (rule-based post-draft validation), **supervisor / router** (deterministic operational route labels such as `billing_review` or `qa_attention`—does **not** change LangGraph edges yet), **risk review** (deterministic scores, adjusted when QA issues exist), and **evidence building** (audit-friendly lines). This is an incremental agentic-architecture step inside `app/nodes/vendor_ticket.py`; the **external API response shape is unchanged** (additive `qa_*`, `route_label`, `routing_reasons`, and specialist-level `recommended_action` on `specialist_output`), human approval remains required, and **retrieval stays a supporting subsystem** rather than the main workflow graph.

Key agent outputs (`detected_intent`, grounding, QA, routing) are also promoted to **structured top-level `CommerceAIState` fields** (duplicated in `specialist_output` for compatibility) so future conditional LangGraph routing can read route signals without digging into nested dicts. The FastAPI `VendorTicketRunResponse` contract is unchanged.

**Graph-level conditional routing (observability-first):** after `vendor_ticket_node`, `route_after_vendor_ticket` branches to lightweight audit nodes (`billing_review`, `qa_attention_review`, `escalation_review`, `style_guidance_review`, or `general_vendor_review`). Each branch **rejoins** `validate_output` → `risk_and_approval_decision` → `persist_trace`. The **`qa_attention`** path sets `qa_requires_human_attention`, records QA issues in audit/evidence, and surfaces them before normal validation/approval—it does **not** auto-revise drafts or auto-send replies. **Human approval remains required** on all paths.

**Operator QA summary (additive API):** `POST /run-vendor-ticket` responses include **`qa_attention_summary`** (`requires_attention`, issue/warning counts, up to three `top_issues` / `top_warnings`, `summary`, `route_label`). It helps reviewers see why a draft needs attention without duplicating full draft text. It does not replace human approval or trigger auto-revision/send.

### Review queue metadata

`POST /run-vendor-ticket` also returns **`review_queue_metadata`** (`review_category`, `review_priority`, `review_reason`, approval flags, QA/risk signals). This is **metadata only**—no persistent queue, database, or dashboard yet—so future operator tooling can group and prioritize tickets. Categories follow `route_label` (e.g. `billing`, `qa_attention`, `escalation`). Priority is deterministic (`HIGH` / `MEDIUM` / `LOW`). **Human approval remains required**; nothing is auto-sent.

### Review queue persistence contract

`app/review_queue/` defines a **schema-first** contract for future operator queues:

- **`ReviewQueueItem`** — typed snapshot (`review_item_id`, workflow ids, category/priority/reason, QA/risk signals, compact `metadata`). Excludes draft text, secrets, and raw retrieval payloads.
- **`build_review_queue_item(state)`** — builds an item from `CommerceAIState` / `review_queue_metadata`.
- **`ReviewQueueAdapter`** — `enqueue_review_item()` + optional `healthcheck()`; implementations (Postgres, Redis, etc.) plug in later.
- **`NoOpReviewQueueAdapter`** — safe default; no external I/O.

Runtime remains **in-memory**: `persist_trace` may attach a JSON contract snapshot to audit metadata only (no enqueue, no DB). Workflow behavior and approval gates are unchanged.

### Operator review actions contract

`app/review_queue/actions.py` defines typed **operator decisions** on a `ReviewQueueItem`:

- **`ReviewActionType`** — `approve`, `reject`, `request_clarification`, `request_redraft`
- **`OperatorReviewAction`** — `action_id`, `review_item_id`, `action_type`, `operator_id`, `comment`, compact `metadata`, UTC `created_at`
- **`build_operator_review_action()`** / **`validate_operator_review_action()`** — deterministic validation (e.g. clarification requires a comment; approve may omit one)

This is **schema-only**: no graph re-run, draft mutation, enqueue, or persistence yet. It is the human-governed foundation for future approval tooling (`ReviewQueueItem` ← reviewed by → `OperatorReviewAction`).

### Review action intake API

`POST /review-actions` accepts a validated **`ReviewActionRequest`** (`review_item_id`, `action_type`, optional `operator_id`, `comment`, `metadata`, `execute`, `workflow_state_snapshot`) and returns **`ReviewActionResponse`**. Accepted actions pass through **`ReviewActionAdapter.record_action()`** (default **`noop`**). With `execute=false` (default), `execution_status="not_executed"`. Invalid actions return HTTP **422** with `validation_errors`.

### Controlled redraft execution

Only **`request_redraft`** may execute, and only when the operator sets **`execute=true`** with a **non-empty `comment`** and a compact **`workflow_state_snapshot`** (`user_input`, `specialist_output.draft_response`, optional grounding/retrieval fields). The API runs **`execute_controlled_redraft()`** (DraftingAgent-style prompt + QA re-check)—**not** the full LangGraph. On success: `execution_status="pending_approval"`, `redraft_response` set, `redraft_summary.requires_human_approval=true`. **No auto-send, no auto-approve.** `approve` / `reject` / `request_clarification` cannot execute. Future persistence can store both the action and redraft result.

### Department-aware review routing

`review_queue_metadata` includes a nested **`department_route`** (`assigned_department`, `reviewer_role`, `routing_source`, `routing_reasons`, `requires_senior_review`) from `app/review_queue/department_routing.py`. Routing uses `ticket_label` (when present), `route_label`, QA attention, and risk score—e.g. finance for billing topics, complaint for شکایت, `qa_review` + `senior_reviewer` when QA/high risk. **Metadata only**; no assignment UI, notifications, or DB queues yet.

### Redraft result contract & audit

Controlled redrafts materialize a **`RedraftResult`** (`app/review_queue/redraft_models.py`): `redraft_id`, `source_action_id`, SHA-256 **`previous_draft_hash`** / **`redraft_hash`** (via `hash_redraft_content()`), operator guidance, QA signals, and compact `metadata.audit`. The API returns **`redraft_result`** and **`redraft_audit`** alongside `redraft_response`—draft bodies are not stored in the artifact, only hashes for change tracking. Still **no auto-send or approval execution**; human approval remains required.

## Agent Workflow Visualization

Mermaid diagrams below describe the **current** vendor-ticket path. Retrieval is a **knowledge layer** (policies, patterns, style guides)—not the product workflow itself. `vendor_ticket_node` **orchestrates internal specialists**; future agentic steps (e.g. **QA / Self-Check Agent**, **Supervisor / Router Agent**) can plug in after drafting or before human approval without changing the external API contract.

**Rendered flowcharts (Graphviz):** [workflow `.svg`](docs/architecture/diagrams/vendor_ticket_agent_workflow.svg) ([`.dot`](docs/architecture/diagrams/vendor_ticket_agent_workflow.dot)) and a separate [visual notation legend `.svg`](docs/architecture/diagrams/vendor_ticket_agent_workflow_legend.svg) ([`.dot`](docs/architecture/diagrams/vendor_ticket_agent_workflow_legend.dot)). Regenerate both with `python3.11 scripts/render_agent_workflow_diagram.py` (writes DOT, then `dot -Tsvg`; requires [Graphviz](https://graphviz.org/) locally, e.g. `brew install graphviz`). CI checks committed DOT/SVG only—no Graphviz binary required in CI. See [docs/architecture/README.md](docs/architecture/README.md).

### Diagram 1 — High-level Commerce OS request flow

```mermaid
flowchart TD
    API[FastAPI Request] --> LG[LangGraph Workflow]
    LG --> N[normalize_request]
    N --> RW[route_workflow]
    RW --> RC[retrieve_context]
    RC --> VT[vendor_ticket_node]
    VT --> ROUTE{route_after_vendor_ticket}
    ROUTE -->|qa_attention| QAR["qa_attention_review\n(surfaces QA issues)"]
    ROUTE -->|escalation| ESC[escalation_review]
    ROUTE -->|billing| BIL[billing_review]
    ROUTE -->|style| STY[style_guidance_review]
    ROUTE -->|default| GEN[general_vendor_review]
    QAR --> VO[validate_output]
    ESC --> VO
    BIL --> VO
    STY --> VO
    GEN --> VO
    VO --> RAD[risk_and_approval_decision]
    RAD --> PT[persist_trace]
    PT --> HA[Human Approval / Final Response]
    HA -.->|operator action| RA[POST /review-actions]
    RA --> RD{execute=true request_redraft?}
    RD -->|yes| CR[Controlled Redraft Execution]
    CR --> NP[New Draft Pending Human Approval]
    NP -.->|re-approve| HA

    subgraph RET["Retrieval layer (supporting subsystem)"]
        direction TB
        RC --> RS[Retrieval Strategy]
        RS --> VS[VectorStore / RAG Documents]
    end
```

`retrieve_context` fills `retrieved_context` (ticket, vendor, policy, `rag_documents`) in shared state; the main graph then runs the specialist draft and approval gates.

### Diagram 2 — Vendor ticket internal multi-agent flow

```mermaid
flowchart TD
    VT[vendor_ticket_node orchestrator] --> TI[TicketIntentAgent]
    TI --> PG[PolicyGroundingAgent]
    PG --> DA[DraftingAgent]
    DA --> QA[QACheckAgent]
    QA --> SR[SupervisorRouterAgent]
    SR --> RR[RiskReviewAgent]
    RR --> EB[EvidenceBuilder]
    EB --> SO[specialist_output]
    VT --> AUD[audit metadata]

    CTX[retrieved_context / rag_documents] -.->|no new retrieval| PG
    DA --> PROMPT[build_vendor_ticket_prompt]
    PROMPT --> LLM[generate_text / LLM layer]
    LLM --> DA
    RR -.->|deterministic / rule-based scores| RR
    EB -.->|RAG + LLM + ticket/vendor lines| EB
```

| Specialist | Role |
|------------|------|
| **TicketIntentAgent** | Normalizes `detected_intent` (rule-based placeholder). |
| **PolicyGroundingAgent** | Summarizes policy + RAG already in state (`grounding_summary`, sources). |
| **DraftingAgent** | `build_vendor_ticket_prompt` + provider-agnostic LLM draft. |
| **QACheckAgent** | Rule-based post-draft checks (risky promises, tone, billing clarification); warnings only by default. |
| **SupervisorRouterAgent** | Picks internal `route_label` / specialist `recommended_action` from intent, grounding, and QA (human review always required). |
| **RiskReviewAgent** | `confidence_score` / `risk_score` for approval gating (deterministic; bumps risk when QA issues exist). |
| **EvidenceBuilder** | Consolidates ticket, vendor, policy, RAG, and LLM evidence lines. |

## Embeddings Foundation

Text **embeddings** back **semantic RAG** (similarity search over policy and ticket snippets). The default graph path still uses **mock** catalog retrieval; **`RAG_STRATEGY=semantic`** and pgvector profiles call **`generate_embedding`** in **`retrieve_context`**.

- **Default:** `EMBEDDING_PROVIDER=mock` and `EMBEDDING_MODEL=mock-embedding-small` yield a **deterministic 16-D vector** with no network I/O (see `app/embeddings/factory.py`).
- **OpenAI adapter:** when `provider="openai"`, the factory calls `client.embeddings.create` and requires **`OPENAI_API_KEY`** in the environment; use this **manually** only when you are ready to pay for tokens and have approved data handling.
- **Pgvector (opt-in):** Postgres + **`PgVectorStore`** for **`semantic_pgvector`** / **`semantic_pgvector_16`** profiles—staging/manual only, not CI. Pinecone, Qdrant, and hosted vector SaaS are **not** included.
- **Tests** exercise only the **mock** path and the **missing-key** guard for OpenAI; they **do not** call the OpenAI network.

Configure via `AppSettings` / env: **`EMBEDDING_PROVIDER`**, **`EMBEDDING_MODEL`** (see `.env.example`).

## Offline RAG Ingestion Foundation

The **`app/rag/ingestion.py`** module prepares **embedding-ready** `RAGDocument` rows from **approved / anonymized** support artifacts (`VendorTicketRecord`, `VendorTicketEvaluationExample`) and offers **character-based chunking** for long texts.

- **Purpose:** turn offline exports into a normalized document shape before any vector store or embedding batch job runs.
- **Chunking:** sliding character windows (`chunk_text`, `rag_document_to_chunks`) run **before** embeddings and **before** pgvector/Pinecone/Qdrant; chunk metadata records `parent_document_id`, `chunk_index`, and `chunk_count`.
- **Not here:** embedding vectors are **not** produced in this module (use `app/embeddings` later); **no database writes**; **no automatic ingestion** of raw production dumps—operators must anonymize and approve sources first.
- **Safety:** processing is **local, deterministic, and pure**; suitable for unit tests and offline pipelines only.

## Offline Embedding Record Preparation

**`app/rag/vector_records.py`** builds **`VectorRecord`** rows by calling **`generate_embedding`** on each `RAGDocument`’s `content` and merging document metadata with embedding metadata—**without** writing to Postgres, pgvector, Pinecone, Qdrant, or any external index.

- **Boundary:** ingestion/chunking (`ingestion.py`) → embeddings (`app/embeddings`) → **vector-ready records** (`vector_records.py`) → in-memory store, or offline **`make pg-index`** / **`make pg-index-16`** into **`PgVectorStore`**.
- **Mock default:** `embedding_provider="mock"` keeps **16-D deterministic** vectors for CI and local pipelines.
- **OpenAI:** you can pass `embedding_provider="openai"` in **manual** jobs when keys and data review are in place; **unit tests stick to mock** so nothing hits the network.

## Vector Store Interface

**`app/rag/vector_store.py`** defines a small **`VectorStore`** contract (`upsert`, `search`, `count`) with an **`InMemoryVectorStore`** used for **tests and local experiments**. Search uses **cosine similarity** over stored `VectorRecord.vector` values; **dimension mismatches are skipped** rather than scored.

- **Why:** keep retrieval and indexing **decoupled** from storage vendors; RAG retrievers depend on **`VectorStore`**, not a specific SDK.
- **Default path:** **`InMemoryVectorStore`** only—no PostgreSQL, no network, no OpenAI in **`make ci`**.
- **Pgvector adapter:** **`PgVectorStore`** implements the same interface for **opt-in** staging profiles; see [ADR 0001: PgVector Store Design](docs/adr/0001-pgvector-store-design.md).
- **Other backends:** Pinecone, Qdrant, Weaviate remain out of scope; additional adapters would implement **`VectorStore`** the same way.

## Local PgVector Development Environment

**Local development only.** The Docker Compose file uses fixed dev credentials (`inchand` / `inchand_dev_password`)—**never** reuse them in production.

This provides a Postgres + pgvector container and SQL migrations (`db/migrations/0001_create_rag_vector_records.sql`, `0002` for 16-D smoke). The **`PgVectorStore`** adapter (`app/rag/pgvector_store.py`) uses **`psycopg`**. **`retrieve_context`** uses **`InMemoryVectorStore`** by default; with **`RAG_PROFILE=semantic_pgvector`** or **`semantic_pgvector_16`**, it routes semantic retrieval through **`PgVectorStore`** (requires prior offline indexing).

```bash
make pg-up      # docker compose up -d  (image: pgvector/pgvector:pg16)
make pg-init    # apply migration via scripts/db_init_pgvector.sh
make pg-logs    # follow postgres logs
make pg-down    # docker compose down
```

Optional: set **`DATABASE_URL`** before **`make pg-init`** (not printed by the script). Default:

`postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai`

Verify the empty table:

```bash
psql "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai" \
  -c "SELECT COUNT(*) FROM rag_vector_records;"
```

**`make ci`** does not start Docker or require Postgres. **`pg-*`** targets are for manual local validation only.

## PgVectorStore Adapter

**`PgVectorStore`** (`app/rag/pgvector_store.py`) implements the existing **`VectorStore`** interface against **`rag_vector_records`** (cosine distance via pgvector, `ON CONFLICT` upsert by `record_id`).

- **Runtime (opt-in):** wired into **`retrieve_context`** when **`RAG_PROFILE`** is **`semantic_pgvector`** or **`semantic_pgvector_16`** (and **`VECTOR_STORE_PROVIDER=pgvector`**). Not the default; not used in **`make ci`**.
- **`InMemoryVectorStore`** remains the default for CI, unit tests, **`semantic_local`**, and unset **`RAG_PROFILE`**.
- Optional live integration tests (migration must be applied first):

```bash
make pg-up
make pg-init
make test-pgvector
# or:
PGVECTOR_TEST_DATABASE_URL=postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai \
  pytest -m pgvector
```

## Offline Corpus Indexing to PgVector

**`scripts/index_corpus_to_pgvector.py`** loads the manifest-backed **`vendor_ticket`** corpus (`default_vendor_ticket_documents`), builds **`VectorRecord`** rows (`rag_documents_to_vector_records`), and upserts into **`PgVectorStore`**. Indexing is **offline only** (no writes during HTTP requests). Runtime reads Postgres only when a pgvector **`RAG_PROFILE`** is active and the table is already indexed.

**Dimension alignment (important):**

| Setting | Default migration | Mock embeddings (`EMBEDDING_PROVIDER=mock`) |
|---------|-------------------|-----------------------------------------------|
| Table column | `VECTOR(1536)` | **16** dimensions |
| Env | `PGVECTOR_DIMENSIONS=1536` | Produces **16-D** vectors |

The script **fails cleanly** when record dimensions ≠ `PGVECTOR_DIMENSIONS` (no padding). With default mock embeddings, **`make pg-index-dry-run`** against `PGVECTOR_DIMENSIONS=1536` will **fail** until you either:

- Use a real embedding model that outputs **1536** dimensions (e.g. OpenAI `text-embedding-3-small` with `EMBEDDING_PROVIDER=openai` and a valid key—**not** used in CI), or
- Use a **test** Postgres schema with `VECTOR(16)` and `PGVECTOR_DIMENSIONS=16`.

Environment (passwords are never printed):

| Variable | Default |
|----------|---------|
| `PGVECTOR_DATABASE_URL` | local docker-compose URL |
| `PGVECTOR_TABLE` | `rag_vector_records` |
| `PGVECTOR_DIMENSIONS` | `1536` |
| `EMBEDDING_PROVIDER` | `mock` |
| `EMBEDDING_MODEL` | `mock-embedding-small` |
| `DRY_RUN` | unset (`true` = validate only, no DB writes) |

Recommended local flow:

```bash
make pg-up
make pg-init
# align PGVECTOR_DIMENSIONS with your embedding model + table schema
make pg-index-dry-run
make pg-index
```

## PgVector 16-D Local Smoke

The default **`rag_vector_records`** table uses **`VECTOR(1536)`** (production-like MVP). **Mock** embeddings are **16-D**, so they cannot be indexed into that table without a real 1536-D embedding model.

**`rag_vector_records_16`** is a **separate local smoke table** (`db/migrations/0002_create_rag_vector_records_16.sql`) for end-to-end validation:

**corpus → mock 16-D embeddings → `PgVectorStore` → PostgreSQL → `semantic_retrieve`**

This is **not** the production schema. Normal **`make ci`** does **not** require Docker or Postgres. Runtime pgvector is **opt-in** via **`RAG_PROFILE=semantic_pgvector_16`** (local mock) or **`semantic_pgvector`** (staging 1536-D); see linked smoke sections below.

```bash
make pg-up
make pg-init          # 1536-D production-like table (unchanged)
make pg-init-16       # 16-D smoke table
make pg-index-16-dry-run
make pg-index-16
make pg-smoke-16
```

## PgVector Retrieval Profile Smoke Test

End-to-end validation for the **opt-in** **`semantic_pgvector_16`** profile: offline index → FastAPI with pgvector env → **`make smoke-semantic`**. Default CI/runtime remain **memory/mock**; this is **local manual** only (Docker + Postgres required on your machine).

### A. Start and initialize pgvector

```bash
make pg-up
make pg-init
make pg-init-16
```

### B. Index corpus into the 16-D table

```bash
PGVECTOR_TABLE=rag_vector_records_16 \
PGVECTOR_DIMENSIONS=16 \
EMBEDDING_PROVIDER=mock \
EMBEDDING_MODEL=mock-embedding-small \
make pg-index-16
```

Confirm **`upserted_count > 0`** in the script output. The workflow does **not** index during HTTP requests.

### C. Start FastAPI with pgvector profile

In one terminal (project root):

```bash
set -a && source .env && set +a
export RAG_PROFILE=semantic_pgvector_16
export VECTOR_STORE_PROVIDER=pgvector
export PGVECTOR_TABLE=rag_vector_records_16
export PGVECTOR_DIMENSIONS=16
export EMBEDDING_PROVIDER=mock
export EMBEDDING_MODEL=mock-embedding-small
export LLM_PROVIDER=mock
export RAG_STRATEGY=semantic

PYTHONPATH=. python3.11 -m uvicorn app.api.main:app --reload --host 127.0.0.1 --port 8000
```

Set **`PGVECTOR_DATABASE_URL`** in **`.env`** (or export it) to match your local Postgres. **`make config-check`** before **`uvicorn`** is recommended.

### D. Run workflow smoke (second terminal)

Use the **same** retrieval env as the server. **`make smoke-semantic`** preflight requires **`RAG_STRATEGY=semantic`**; **`RAG_PROFILE=semantic_pgvector_16`** selects the pgvector store path in **`retrieve_context`**.

```bash
set -a && source .env && set +a
export RAG_PROFILE=semantic_pgvector_16
export VECTOR_STORE_PROVIDER=pgvector
export PGVECTOR_TABLE=rag_vector_records_16
export PGVECTOR_DIMENSIONS=16
export EMBEDDING_PROVIDER=mock
export EMBEDDING_MODEL=mock-embedding-small
export LLM_PROVIDER=mock
export RAG_STRATEGY=semantic

make smoke-semantic
```

### Expected output checks

Inspect JSON from **`POST /run-vendor-ticket`** (printed by the smoke script):

| Field | Expected |
|-------|----------|
| `workflow_status` | `"awaiting_approval"` |
| `errors` | `[]` |
| `retrieval_summary.rag_profile` | `"semantic_pgvector_16"` |
| `retrieval_summary.requested_strategy` | `"semantic"` |
| `retrieval_summary.effective_strategy` | `"semantic"` |
| `retrieval_summary.vector_store_provider` | `"pgvector"` |
| `retrieval_summary.pgvector_table` | `"rag_vector_records_16"` |
| `retrieval_summary.pgvector_dimensions` | `16` |
| `retrieval_summary.provider` | `"semantic"` |
| `specialist_output.evidence.rag_document_count` | `> 0` |

**`retrieval_summary`** must **not** contain **`database_url`** or credentials.

### Fallback troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| **`errors`** contains **`rag_strategy_error`**, **`effective_strategy`** is **`mock`** | Postgres not running, migration not applied, missing **`PGVECTOR_DATABASE_URL`**, or **`create_vector_store`** / search failed |
| **`effective_strategy`** is **`semantic`** but **`rag_document_count`** is **0** | Table empty—re-run **B** (`make pg-index-16`) |
| **`make pg-index-16`** fails before upsert | Dimension mismatch (mock **16-D** vs wrong **`PGVECTOR_DIMENSIONS`** / table schema) |
| Smoke script exits before curl | **`RAG_STRATEGY`** not **`semantic`** in the smoke terminal |
| Draft ignores corpus | Check **`specialist_output.evidence`**; retrieval may have fallen back to mock |

Do **not** use OpenAI for this smoke unless you are separately testing the LLM adapter (**`make smoke-openai`**).

## 1536-D PgVector Staging Profile

**`semantic_pgvector`** is an **opt-in staging/manual** profile for the production-like table **`rag_vector_records`** (`VECTOR(1536)`). It uses **`EMBEDDING_PROVIDER`** / **`EMBEDDING_MODEL`** from settings (typically OpenAI **`text-embedding-3-small`**)—**not** hardcoded mock. **Not** the default; **not** for CI; **no** request-time indexing; **no** secrets in **`retrieval_summary`**.

Index with the **same** embedding provider, model, and dimensions you use at retrieval time.

### A. Start DB and apply production-like migration

```bash
make pg-up
make pg-init
```

### B. Index corpus with 1536-D embeddings

```bash
export EMBEDDING_PROVIDER=openai
export EMBEDDING_MODEL=text-embedding-3-small
export OPENAI_API_KEY=...   # never commit; not required in CI
export PGVECTOR_TABLE=rag_vector_records
export PGVECTOR_DIMENSIONS=1536
make pg-index-dry-run
make pg-index
```

### C. Start API

```bash
set -a && source .env && set +a
export RAG_PROFILE=semantic_pgvector
export VECTOR_STORE_PROVIDER=pgvector
export PGVECTOR_TABLE=rag_vector_records
export PGVECTOR_DIMENSIONS=1536
export EMBEDDING_PROVIDER=openai
export EMBEDDING_MODEL=text-embedding-3-small
export RAG_STRATEGY=semantic
export LLM_PROVIDER=mock

PYTHONPATH=. python3.11 -m uvicorn app.api.main:app --reload --host 127.0.0.1 --port 8000
```

Set **`PGVECTOR_DATABASE_URL`** in **`.env`** as needed.

### D. Run smoke

Same env in a second terminal, then:

```bash
make smoke-semantic
```

### Expected response

| Field | Expected |
|-------|----------|
| `errors` | `[]` |
| `retrieval_summary.rag_profile` | `"semantic_pgvector"` |
| `retrieval_summary.vector_store_provider` | `"pgvector"` |
| `retrieval_summary.pgvector_table` | `"rag_vector_records"` |
| `retrieval_summary.pgvector_dimensions` | `1536` |
| `retrieval_summary.effective_strategy` | `"semantic"` |

## PgVector Retrieval Evaluation Run

**`scripts/evaluate_pgvector_retrieval.py`** runs **`corpus/vendor_ticket/eval_cases.json`** against a **PgVector-backed** **`semantic_retrieve`** path. **Manual/staging only**; **not** in CI; **no** request-time indexing; **no** API keys or database URLs printed. Index the corpus first with the **same** **`EMBEDDING_PROVIDER`** / **`EMBEDDING_MODEL`** / dimensions you use for evaluation.

**16-D local mock path:**

```bash
make pg-up
make pg-init
make pg-init-16
make pg-index-16
export VECTOR_STORE_PROVIDER=pgvector
export PGVECTOR_TABLE=rag_vector_records_16
export PGVECTOR_DIMENSIONS=16
export EMBEDDING_PROVIDER=mock
export EMBEDDING_MODEL=mock-embedding-small
make pg-eval
```

**1536-D staging path:**

```bash
make pg-up
make pg-init
export VECTOR_STORE_PROVIDER=pgvector
export PGVECTOR_TABLE=rag_vector_records
export PGVECTOR_DIMENSIONS=1536
export EMBEDDING_PROVIDER=openai
export EMBEDDING_MODEL=text-embedding-3-small
export OPENAI_API_KEY=...
make pg-index
make pg-eval
```

Set **`PGVECTOR_DATABASE_URL`** in **`.env`** as needed. Optional: **`OUTPUT_JSON=true`** for machine-readable **`RetrievalEvalReport`** JSON.

**Healthy run:** `pass_rate=1.0`, strong **`mean_recall_at_k` / `mean_hit_rate` / `mean_mrr`**, **`quality gates: passed`**, and `all retrieval eval cases passed`. If gates fail, inspect the **`quality gates`** block and per-case details.

## Retrieval Backend Baseline Comparison

**`scripts/compare_retrieval_backends.py`** runs **`eval_cases.json`** twice: an **in-memory** baseline vs **PgVector** (`semantic_retrieve` + `create_vector_store`). **Manual/staging only**; **not** in CI; **no** indexing in the script; index first with the **same** embedding settings you use at retrieval time.

**Baseline modes** (`BASELINE_PROVIDER`, default **`default`**):

| Mode | Baseline | Use when |
|------|----------|----------|
| **`default`** (unset) | `run_default_vendor_ticket_retrieval_eval()` — mock 16-D in-memory bootstrap | CI-safe checks; quick local compare |
| **`same_embedding`** | In-memory store built from the same corpus + **`EMBEDDING_PROVIDER`** / **`EMBEDDING_MODEL`** as pgvector | **1536-D staging** — storage/backend parity, not embedding-space drift |

With **`default`**, mock baseline vs OpenAI pgvector often yields **`cases_with_different_results > 0`** even when both pass all cases (different embedding spaces / ranking). **`RETRIEVAL_REQUIRE_MATCHING_CASE_RESULTS=true`** is only meaningful with **`BASELINE_PROVIDER=same_embedding`**.

Requires **`VECTOR_STORE_PROVIDER=pgvector`** for the pgvector side. Exit **0** only when **`baseline.pass_rate == pgvector.pass_rate`** and **`pgvector.pass_rate == 1.0`**. Optional **`OUTPUT_JSON=true`** for structured comparison JSON (includes **`baseline_provider`**, **`embedding_provider`**, **`embedding_model`** when applicable). No database URLs or API keys printed.

**16-D local:**

```bash
make pg-up
make pg-init
make pg-init-16
make pg-index-16
export VECTOR_STORE_PROVIDER=pgvector
export PGVECTOR_TABLE=rag_vector_records_16
export PGVECTOR_DIMENSIONS=16
export EMBEDDING_PROVIDER=mock
export EMBEDDING_MODEL=mock-embedding-small
make pg-compare
```

**1536-D staging (recommended strict compare):**

```bash
make pg-up
make pg-init
export VECTOR_STORE_PROVIDER=pgvector
export PGVECTOR_TABLE=rag_vector_records
export PGVECTOR_DIMENSIONS=1536
export EMBEDDING_PROVIDER=openai
export EMBEDDING_MODEL=text-embedding-3-small
export OPENAI_API_KEY=...
export BASELINE_PROVIDER=same_embedding
make pg-index
make pg-compare
```

**Healthy result:** same **`pass_rate`** as baseline, matching **`mean_recall_at_k` / `mean_hit_rate` / `mean_mrr`**, and **`cases_with_different_results=0`** (with **`same_embedding`** baseline). Use before promoting **`semantic_pgvector`** beyond manual validation.

## Retrieval Quality Threshold Gates

**`make pg-eval`** and **`make pg-compare`** apply **staging quality gates** from **`app/rag/evaluation.py`** (enabled by default via **`RETRIEVAL_QUALITY_GATES=true`**):

| Gate | Meaning |
|------|---------|
| **`RETRIEVAL_MIN_*`** | Minimum **`pass_rate`**, **`mean_recall_at_k`**, **`mean_hit_rate`**, **`mean_mrr`** on pgvector report |
| **`RETRIEVAL_MAX_*_REGRESSION`** | Max allowed drop vs in-memory baseline (delta = pgvector − baseline) |
| **`RETRIEVAL_REQUIRE_MATCHING_CASE_RESULTS`** | **`cases_with_different_results=0`** for **`pg-compare`** |
| **`RETRIEVAL_MAX_NEAR_MISS_VIOLATIONS`** | Optional max absolute **`near_miss_violation_count`** on a single report (unset = disabled) |
| **`RETRIEVAL_MAX_NEAR_MISS_VIOLATION_REGRESSION`** | Optional max increase in near-miss violations vs baseline on **`pg-compare`** (unset = disabled) |

Scripts print a **`quality gates:`** block (passed/failed per gate). Exit **0** only when all gates pass. Set **`RETRIEVAL_QUALITY_GATES=false`** to restore legacy exit rules (pass rate only). Near-miss gates are **optional**—set the env vars above (e.g. **`0`** for strict staging) to fail **`pg-eval`** / **`pg-compare`** when wrong-but-plausible docs outrank expected hits; they do **not** change per-case **`passed`** semantics. **Not** used in CI.

## Strict Staging Retrieval Quality Profile

**What this is:** a repeatable **operator env block** for **`make pg-eval`** and **`make pg-compare`** before promoting **`semantic_pgvector`**. It tightens retrieval quality gates beyond defaults where noted. **Disabled unless you export these variables**; **not** used in **`make ci`**.

Export after your normal **`VECTOR_STORE_PROVIDER`**, **`PGVECTOR_*`**, and **`EMBEDDING_*`** setup (see [Staging Retrieval Evaluation Runbook](#staging-retrieval-evaluation-runbook)):

```bash
export RETRIEVAL_QUALITY_GATES=true
export RETRIEVAL_MIN_PASS_RATE=1.0
export RETRIEVAL_MIN_MEAN_RECALL_AT_K=1.0
export RETRIEVAL_MIN_MEAN_HIT_RATE=1.0
export RETRIEVAL_MIN_MEAN_MRR=0.8
export RETRIEVAL_MAX_PASS_RATE_REGRESSION=0.0
export RETRIEVAL_MAX_MEAN_RECALL_AT_K_REGRESSION=0.0
export RETRIEVAL_MAX_MEAN_HIT_RATE_REGRESSION=0.0
export RETRIEVAL_MAX_MEAN_MRR_REGRESSION=0.05
export RETRIEVAL_REQUIRE_MATCHING_CASE_RESULTS=true
export RETRIEVAL_MAX_NEAR_MISS_VIOLATIONS=0
export RETRIEVAL_MAX_NEAR_MISS_VIOLATION_REGRESSION=0
```

**Why these values:** for the current curated **`eval_cases.json`**, **`pass_rate`**, **`mean_recall_at_k`**, and **`mean_hit_rate`** should stay at **1.0** when indexing matches retrieval—so minima are strict. **`mean_mrr`** can differ slightly between backends (ranking order); **`RETRIEVAL_MIN_MEAN_MRR=0.8`** allows a small tolerance while still catching large ranking collapse. **Near-miss** violations should be **zero** in strict staging (**`RETRIEVAL_MAX_NEAR_MISS_VIOLATIONS=0`** and **`RETRIEVAL_MAX_NEAR_MISS_VIOLATION_REGRESSION=0`**). **`RETRIEVAL_REQUIRE_MATCHING_CASE_RESULTS=true`** is meaningful for **`pg-compare`** only when **`BASELINE_PROVIDER=same_embedding`**; with the default mock baseline, ordering diffs may reflect embedding-model mismatch, not storage regression.

**Commands** (same shell as the exports; for 1536-D staging add **`export BASELINE_PROVIDER=same_embedding`** before **`make pg-compare`**):

```bash
make pg-eval
make pg-compare
```

**Promotion rule:** proceed only if **both** exit **0**. If either fails, read the **`quality gates:`** block and per-case output; fix index, env, or expectations—not the gates by default.

**If strict gates fail after intentional corpus changes:** re-run the in-memory baseline and **`pg-compare`** diffs; inspect **`cases_with_different_results`** and near-miss case IDs. Update **`eval_cases.json`** only when expectations were wrong. Do **not** loosen gates solely to pass—adjust the corpus, index, or embeddings first.

## Staging Retrieval Evaluation Runbook

**Purpose:** validate **pgvector** retrieval quality before widening rollout of **`semantic_pgvector`** or **`semantic_pgvector_16`**. Run **`make pg-eval`** and **`make pg-compare`** against the in-memory baseline after corpus, index, embedding-model, or profile changes. The eval corpus includes **ambiguous and ranking-sensitive** cases (short queries, near-miss wording, multi-document expectations)—not only the original smoke trio. For a **strict** env preset before **`semantic_pgvector`** promotion, see [Strict Staging Retrieval Quality Profile](#strict-staging-retrieval-quality-profile). **Manual/staging only**—**not** part of **`make ci`**.

### Recommended flow

**A. Environment verification**

```bash
make config-check
```

Confirm **`EMBEDDING_PROVIDER`** / **`EMBEDDING_MODEL`** match the index you will use. Confirm **`PGVECTOR_TABLE`** and **`PGVECTOR_DIMENSIONS`** match the table schema. Set the retrieval profile you intend to promote:

| Path | Profile | Table | Typical embeddings |
|------|---------|-------|-------------------|
| Local mock smoke | **`semantic_pgvector_16`** | `rag_vector_records_16` | `mock` / `mock-embedding-small` (16-D) |
| Staging / production-like | **`semantic_pgvector`** | `rag_vector_records` | `openai` / `text-embedding-3-small` (1536-D) |

Also set **`VECTOR_STORE_PROVIDER=pgvector`** and **`PGVECTOR_DATABASE_URL`** (via **`.env`**). See [PgVector Retrieval Evaluation Run](#pgvector-retrieval-evaluation-run) for full env blocks.

**B. Ensure corpus is indexed**

Indexing must use the **same** **`EMBEDDING_PROVIDER`** / **`EMBEDDING_MODEL`** (and dimensions) as evaluation and runtime retrieval.

| Path | Command |
|------|---------|
| 16-D local mock | **`make pg-index-16`** (after **`make pg-init-16`**) |
| 1536-D staging | **`make pg-index`** (after **`make pg-init`**) |

Optional: **`make pg-index-16-dry-run`** / **`make pg-index-dry-run`** to validate without writes.

**C. Run retrieval evaluation**

```bash
make pg-eval
```

| Output | Meaning |
|--------|---------|
| **`pass_rate`** | Fraction of eval cases that retrieved all expected document IDs |
| **`mean_recall_at_k`** | Average recall@k across cases |
| **`mean_hit_rate`** | Average binary hit (any expected doc in top-k) |
| **`mean_mrr`** | Average mean reciprocal rank of first expected hit |

Inspect per-case lines for misses. The **`quality gates:`** block enforces minimum metrics and fails the run on regression (see [Retrieval Quality Threshold Gates](#retrieval-quality-threshold-gates)).

**D. Run baseline comparison**

```bash
export BASELINE_PROVIDER=same_embedding   # required for meaningful 1536-D strict compare
make pg-compare
```

Runs **`eval_cases.json`** on **in-memory** baseline vs **pgvector** (use **`same_embedding`** for OpenAI 1536-D staging). Key comparison fields:

| Field | Meaning |
|-------|---------|
| **`pass_rate_delta`** | pgvector **`pass_rate`** − baseline **`pass_rate`** (want **0**) |
| **`mean_mrr_delta`** | pgvector **`mean_mrr`** − baseline **`mean_mrr`** (want **≥ 0**, comparable) |
| **`cases_with_different_results`** | Cases where pass/misses/**`retrieved_document_ids`** differ (want **0**) |

**E. Promotion decision**

**Healthy signals (proceed toward wider rollout):**

- **`pass_rate == 1.0`** on **`pg-eval`**
- **`cases_with_different_results == 0`** on **`pg-compare`**
- **`quality gates: passed`** on both commands
- **`mean_mrr`** (and recall/hit rate) **comparable to** in-memory baseline

**Warning signals (do not promote; fix index/env/corpus first):**

- Lower **`mean_recall_at_k`** or **`mean_mrr`** vs baseline
- Non-zero **`cases_with_different_results`**
- Unexpected **`retrieved_document_ids`** or new **`missing_document_ids`**
- Source-type coverage regressions (expected policy/example docs missing from top-k)

### Troubleshooting

| Symptom | Likely cause | Remediation |
|---------|--------------|-------------|
| Dimension mismatch on index/eval | **`PGVECTOR_DIMENSIONS`** or table ≠ embedding width | Align table migration, **`PGVECTOR_DIMENSIONS`**, and provider; re-index |
| **`pg-eval`** returns no / wrong hits | Empty or stale **`rag_vector_records*`** | Run **`make pg-index`** or **`make pg-index-16`**; verify row count in Postgres |
| Baseline passes, pgvector fails | Embedding **provider/model** differ between index and eval | Re-index with same **`EMBEDDING_*`** as **`pg-eval`** / **`pg-compare`** |
| Gate failures after corpus edit | Index not rebuilt; eval cases out of sync | **`make corpus-check`**; update **`eval_cases.json`** if needed; re-index |
| **`cases_with_different_results > 0`** | Store drift, wrong table/profile, or **mock vs OpenAI baseline** | For 1536-D staging use **`BASELINE_PROVIDER=same_embedding`**; confirm **`PGVECTOR_TABLE`**, profile, and env |

### Operator notes

- Pgvector retrieval evaluation is **staging/manual only**—never required for **`make ci`** (CI stays mock/in-memory).
- Do **not** paste **`OPENAI_API_KEY`** into tickets, logs, or screenshots; use **`.env`** locally only.
- Do **not** add pgvector eval to CI workflows without an explicit platform decision.
- **Re-run indexing** after any corpus change or **`EMBEDDING_MODEL`** change before trusting **`pg-eval`** / **`pg-compare`** results.

Detail for individual commands: [PgVector Retrieval Evaluation Run](#pgvector-retrieval-evaluation-run), [Retrieval Backend Baseline Comparison](#retrieval-backend-baseline-comparison).

## Retrieval evaluation snapshots

Known-good **manual staging** baselines live under [`docs/retrieval_snapshots/`](docs/retrieval_snapshots/). The first **Golden Snapshot** ([`golden_snapshot_1536_openai_pgvector.md`](docs/retrieval_snapshots/golden_snapshot_1536_openai_pgvector.md)) records strict-gate **`pg-eval`** / **`pg-compare`** (same-embedding parity) and **`semantic_pgvector`** API smoke for OpenAI **1536-D** + pgvector. Re-compare future corpus, embedding, or retrieval-stack changes against it before promotion—not part of **`make ci`**.

## Real data pilot (planning)

A controlled **anonymized real-ticket** retrieval pilot is documented in [`docs/data_governance/real_data_pilot_plan.md`](docs/data_governance/real_data_pilot_plan.md). No import or production wiring yet—see also [`app/data_readiness/README.md`](app/data_readiness/README.md).

### Conversation ticket snapshot contract

Vendor tickets are **chat-room conversations** (multi-message, role-labeled). Typed exports live in **`app/tickets/conversation_models.py`** (`ConversationTicketSnapshot`, `ConversationMessage`, `conversation_to_plain_text`). Recommended handoff format: **UTF-8 JSONL** — see [`docs/data_governance/real_ticket_export_format.md`](docs/data_governance/real_ticket_export_format.md). Use anonymization placeholders (`SELLER_ID_001`, etc.); raw production exports must not enter git.

Validate exports offline before any pilot import: `PYTHONPATH=. python3.11 scripts/validate_ticket_export.py path/to/export.jsonl` (exit `0` = all lines valid; does not index or import). Map validated rows with `conversation_snapshot_to_workflow_input()` in `app/tickets/workflow_mapping.py`.

### Real Replay Calibration

Offline replay runs the mock vendor-ticket workflow per ticket and records compact routing metrics (no draft/transcript in reports). Full first-cycle report: [`docs/operations/real_replay_calibration_report.md`](docs/operations/real_replay_calibration_report.md).

**Official governance pipeline (redact first, review residual risk):**

```text
normalize → redact → validate redacted JSONL → replay redacted export
  → privacy review (residual warnings) → reviewer sign-off
  → approved room_id subset → pilot corpus builder
```

- **Redaction** (`scripts/redact_ticket_export.py`, `app/privacy_review/redaction.py`) reduces warning volume; warnings after redaction are **residual risk** and still require human review.
- **Redaction ≠ corpus approval** — reviewer sign-off remains mandatory.
- Use **redacted** JSONL for validate, replay, privacy review, and `build_pilot_corpus.py` — **not** unredacted normalized JSONL.
- `data/private/` and `reports/` stay gitignored; no embeddings, pgvector indexing, or retrieval activation in these steps.

**166-ticket command sequence** (local/private paths; adjust batch names as needed):

```bash
# 1. Normalize
PYTHONPATH=. python3.11 scripts/normalize_ticket_export.py \
  data/private/vendor_tickets_400.json \
  --output data/private/vendor_tickets_400.normalized.jsonl \
  --skip-empty-messages

# 2. Redact (before validate / privacy review)
PYTHONPATH=. python3.11 scripts/redact_ticket_export.py \
  data/private/vendor_tickets_400.normalized.jsonl \
  --output data/private/vendor_tickets_400.redacted.jsonl \
  --overwrite

# 3. Validate redacted
PYTHONPATH=. python3.11 scripts/validate_ticket_export.py \
  data/private/vendor_tickets_400.redacted.jsonl

# 4. Replay redacted
PYTHONPATH=. python3.11 scripts/replay_ticket_export.py \
  data/private/vendor_tickets_400.redacted.jsonl \
  --output reports/vendor_tickets_400_redacted_replay.jsonl

# 5. Dashboard (redacted replay)
PYTHONPATH=. python3.11 scripts/build_replay_metrics_dashboard.py \
  reports/vendor_tickets_400_redacted_replay.jsonl \
  --output reports/vendor_tickets_400_redacted_dashboard.md \
  --json-output reports/vendor_tickets_400_redacted_dashboard.json

# 6. Privacy review — residual warnings on redacted export
PYTHONPATH=. python3.11 scripts/build_privacy_review_report.py \
  reports/vendor_tickets_400_redacted_replay.jsonl \
  --export-path data/private/vendor_tickets_400.redacted.jsonl \
  --output reports/privacy_review_166_redacted.md \
  --json-output reports/privacy_review_166_redacted.json
```

On the first 50-ticket sample (pre–redact-first policy), routing calibration reduced **label vs department mismatches from 32 → 0**. Re-run the 50-ticket path with redaction when refreshing baselines.

**Calibrated 50-ticket baseline:** [`docs/operations/real_replay_50_ticket_baseline.md`](docs/operations/real_replay_50_ticket_baseline.md) — sanitized snapshot (**mismatch 0**, **QA attention 13/50**). Aggregate metrics only.

**Larger replay runbook:** [`docs/operations/larger_replay_batch_plan.md`](docs/operations/larger_replay_batch_plan.md) — **100–500** ticket procedure (redact-first).

**166-ticket execution report:** [`docs/operations/larger_replay_166_ticket_execution_report.md`](docs/operations/larger_replay_166_ticket_execution_report.md) — **failed_replays=0**, **mismatch=0**, QA **51/166** (30.7%). Pre-redaction warning counts documented separately; use redact-first pipeline for new runs.

**Redacted replay execution (166-ticket):** [`docs/operations/redacted_replay_166_ticket_execution_report.md`](docs/operations/redacted_replay_166_ticket_execution_report.md) — redact-first pipeline executed: **residual warnings 0/166**, replay metrics unchanged vs unredacted. **Ready for reviewer sign-off**; corpus build not auto-approved.

**Privacy review execution (166-ticket):** [`docs/operations/privacy_review_166_ticket_execution_report.md`](docs/operations/privacy_review_166_ticket_execution_report.md) — historical pre-redaction metrics + **residual-warning** workflow. See redacted replay report for post-redaction outcome.

**Pilot corpus planning:** [`docs/operations/pilot_corpus_planning.md`](docs/operations/pilot_corpus_planning.md) — `build_pilot_corpus.py` must read **redacted** JSONL after sign-off (`embedding_status` / `indexing_status` remain `not_started`):

```bash
PYTHONPATH=. python3.11 scripts/build_pilot_corpus.py \
  data/private/vendor_tickets_400.redacted.jsonl \
  --approved-room-ids data/private/approved_room_ids.txt \
  --corpus-dir corpus/vendor_ticket_real_pilot \
  --source-batch-id replay_166_v1 \
  --reviewer-signoff-id SIGNOFF_001
```

**Pilot corpus 25 build report:** [`docs/operations/pilot_corpus_25_build_report.md`](docs/operations/pilot_corpus_25_build_report.md) — first controlled 25-record pilot corpus (integrity verification, no embeddings/indexing).

**Balanced pilot corpus rebuild (Step 121):** [`docs/operations/balanced_pilot_corpus_rebuild.md`](docs/operations/balanced_pilot_corpus_rebuild.md) — rebalance approved rooms (~10 support / ~7 complaint / ~5–8 fund) after Step 120 showed **`fund=0`** in sandbox index. Selection helper:

```bash
PYTHONPATH=. python3.11 scripts/select_approved_room_ids.py \
  reports/replay_166_redacted.jsonl \
  -o data/private/approved_room_ids.txt \
  --balance-pilot \
  --exclude-qa-attention \
  --overwrite
```

Human reviewer must confirm the list before `build_pilot_corpus.py`. Full operator flow (corpus → embeddings → pgvector → eval) is in the rebuild doc. **No retrieval activation.**

**Step 122 local execution:** [pilot balanced rebuild execution report](docs/operations/pilot_balanced_rebuild_execution_report.md) — balanced corpus indexed as `vendor_ticket_real_pilot_balanced` / `pilot_balanced_v1`; fund count **8**.

**Step 123 eval calibration (v4):** eval cases no longer pin `metadata_filter.namespace`/`index_version`; compare-mode **metadata_filtered pass_rate=1.0** on fund subset; vector_only **0.90** (one `must_not_return_labels` edge on `pilot-fund-wallet-fa-016`).

**Sandbox retrieval tool (Steps 125–127):** [`docs/operations/sandbox_retrieval_tool_contract.md`](docs/operations/sandbox_retrieval_tool_contract.md) — contract models (`app/corpus_planning/retrieval_tool_models.py`) + local executor (`app/corpus_planning/sandbox_retrieval_tool.py`). Local smoke test: [`docs/operations/sandbox_retrieval_tool_smoke_test_report.md`](docs/operations/sandbox_retrieval_tool_smoke_test_report.md). **Not** LangGraph, **not** production `RAG_PROFILE`, **not** customer-facing.

**LangGraph retrieval integration (Step 128, plan only):** [`docs/operations/langgraph_retrieval_integration_plan.md`](docs/operations/langgraph_retrieval_integration_plan.md) — future LangGraph wiring proposal; **no** runtime activation, **no** graph nodes in this step.

**Retrieval policy gate (Step 129, contract only):** [`docs/operations/retrieval_policy_gate_contract.md`](docs/operations/retrieval_policy_gate_contract.md) — `evaluate_retrieval_policy_gate` allow/skip/deny before search; **no** pgvector/OpenAI/LangGraph in this step.

**LangGraph retrieval state fields (Step 130, contract only):** additive `retrieval_*` keys on `CommerceAIState` + helpers in `app/state/retrieval_state.py`; **no** retrieval node or runtime activation.

**Sandbox retrieval chain dry-run (Steps 131–132):** policy gate → executor → state snapshot — **not** LangGraph, **not** production, **not** customer-facing. Local chain smoke test: [`docs/operations/dry_run_retrieval_chain_smoke_test_report.md`](docs/operations/dry_run_retrieval_chain_smoke_test_report.md).

**LangGraph sandbox retrieval node (Steps 133–135):** [`docs/operations/langgraph_sandbox_retrieval_node_plan.md`](docs/operations/langgraph_sandbox_retrieval_node_plan.md) — shadow node `sandbox_retrieve_pilot_shadow` implemented; default `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=false`; sanitized `retrieval_*` metadata only; **not** used for draft/final responses. Local shadow smoke test: [`docs/operations/langgraph_shadow_retrieval_smoke_test_report.md`](docs/operations/langgraph_shadow_retrieval_smoke_test_report.md).

**Shadow retrieval metrics dashboard (Step 136):** aggregate sanitized shadow replay JSONL → gitignored `reports/shadow_retrieval_metrics_dashboard.md` via `scripts/build_shadow_retrieval_metrics_dashboard.py` (no raw content; rejects `retrieval_activated=true`).

**Shadow replay JSONL export (Steps 137, 140, 142):** export sanitized shadow replay rows from local ticket JSONL → gitignored `reports/shadow_replay_*.jsonl` via `scripts/export_shadow_replay_jsonl.py` (requires `--confirm-sandbox` and `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=true` for chain execution; Step 142 aligns metadata filter to `ticket_label` + `route_label` only; no raw content).

```bash
PYTHONPATH=. LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=true python3.11 \
  scripts/export_shadow_replay_jsonl.py \
  data/private/vendor_tickets_400.redacted.jsonl \
  --output reports/shadow_replay_balanced_v1.jsonl \
  --namespace vendor_ticket_real_pilot_balanced \
  --index-version pilot_balanced_v1 \
  --profile semantic_pgvector \
  --confirm-sandbox

PYTHONPATH=. python3.11 scripts/build_shadow_retrieval_metrics_dashboard.py \
  reports/shadow_replay_balanced_v1.jsonl --overwrite
```

**Shadow replay metrics report (Step 138):** governance summary of local 166-ticket shadow batch — [`docs/operations/shadow_replay_metrics_report.md`](docs/operations/shadow_replay_metrics_report.md) (aggregate metrics only; no raw content).

**Shadow replay metrics refresh (Step 143):** corrected metrics after Step 142 filter alignment — [`docs/operations/shadow_replay_metrics_refresh_report.md`](docs/operations/shadow_replay_metrics_refresh_report.md) (`result_count_distribution` 5/166; `retrieval_activated_true_count=0`).

**Non-shadow retrieval consumption governance (Step 144, plan only):** [`docs/operations/non_shadow_retrieval_consumption_governance_plan.md`](docs/operations/non_shadow_retrieval_consumption_governance_plan.md) — approval gates before sandbox retrieval metadata may leave shadow-only observability; **only HITL-only visibility** may be considered next; draft-assist and customer-facing retrieval **blocked**; helpers in `app/corpus_planning/retrieval_consumption_governance.py` (governance check only; no runtime activation).

**Vendor ticket AI assist shadow workflow (Steps 145–148):** [`docs/operations/vendor_ticket_ai_assist_shadow_workflow.md`](docs/operations/vendor_ticket_ai_assist_shadow_workflow.md) — rule-based **shadow-only** operational assist; LangGraph node `vendor_ticket_ai_assist_shadow`; offline export + dashboard; default `VENDOR_TICKET_AI_ASSIST_SHADOW_ENABLED=false`. **Not** HITL UI, **not** customer-facing, **not** auto-send, **not** draft/final consumption.

**AI assist shadow metrics report (Step 149):** [`docs/operations/ai_assist_shadow_metrics_report.md`](docs/operations/ai_assist_shadow_metrics_report.md) — validated 166-ticket batch after Step 148 DB fix (`error_count=0`; `monitor=109`, `escalate=37`, `billing_review=20`; activation/consumption zero). Export: `scripts/export_ai_assist_shadow_replay_jsonl.py`, dashboard `scripts/build_ai_assist_shadow_metrics_dashboard.py`.

**HITL read-only visibility contract (Steps 150–153):** [`docs/operations/hitl_read_only_visibility_contract.md`](docs/operations/hitl_read_only_visibility_contract.md) — allowlisted aggregate fields + reviewer boundaries; payload builder `app/hitl/hitl_payload_builder.py`; sample CLI `scripts/build_hitl_read_only_payload_sample.py`; local mock preview `scripts/render_hitl_read_only_panel_preview.py` → `reports/hitl_read_only_panel_preview.md`. **HITL preview batch report (Step 153):** [`docs/operations/hitl_read_only_preview_report.md`](docs/operations/hitl_read_only_preview_report.md). **Not** production UI, **not** draft/final consumption, **not** customer-facing.

**Internal operator console (Steps 154–160, 167–168):** Streamlit MVP at `app/operator_console/` — review vendor tickets with AI assist + retrieval summaries. **Open ticket snapshot (default):** first vendor issue + latest vendor message + up to three lines of recent non-internal context before that turn (`app/live_feed/open_ticket_snapshot.py`) — no post-vendor support leakage, max 600 chars combined across the three body fields; **recent context** is shown **line-by-line** (vendor / support / finance labels) with **RTL-safe** HTML for Persian and mixed Persian/Latin/numbers (`app/operator_console/rtl_text.py`). **Historical preview:** legacy `ticket_text_preview` (latest seller line only), also RTL-wrapped in the UI. **Seller message class (Step 169, shadow/HITL only):** deterministic **`seller_notification`** vs **`seller_operational_request`** from safe preview text (`app/workflows/seller_notification_detection.py`). Notifications (e.g. shipment + tracking reported) map to `record_update`; operational asks (بررسی کنید / پیگیری کنید / …) map to `human_followup` or `review_product_status`. Uses operational entity extraction for 7-digit order IDs and carrier-aware tracking codes (see below). **Read-only** — **no** production order mutation, approval changes, auto-send, or external APIs.

**Suggested action taxonomy v1 (Step 180, advisory only):** `app/workflows/suggested_action_taxonomy.py` maps `detected_intent`, optional `conceptual_intent_fa`, extracted entities, and ticket labels to a richer **`suggested_action`** enum (e.g. `update_delivery_status`, `check_order_status`, `check_product_approval`, `answer_policy_question`, `request_missing_info`). Legacy values (`monitor`, `billing_review`, `human_followup`, `record_update`, …) remain valid. **`suggested_action_reason`** explains the mapping in the operator console and HITL export. **No action execution** — suggestions only; operators decide what to do.

**Operational intent taxonomy v1 (Step 170, shadow/HITL only):** broader **rule-based** intents for operator review (`app/workflows/vendor_ticket_intent_detection.py`) — e.g. `settlement_status_inquiry`, `settlement_panel_access_issue`, `product_approval_review`, `tracking_code_notification`, `complaint_escalation`. **Distinct from `ticket_label`:** coarse routing labels (`support` / `complaint` / `fund`) stay as-is; **`detected_intent`** is a finer operational category derived from Persian keywords + Step 169 seller detection (composed, not duplicated). Taxonomy v1 is **deterministic and reviewable** — **no LLM classifier** yet. AI assist shadow exports safe fields: `detected_intent`, `intent_confidence_band`, `intent_reasons_summary`, `intent_related_document_types` (plus Step 169 compat fields). Operator console shows intent, confidence, reasons, and related policy doc types under **Operational intent (taxonomy v1)**. **Replay JSONL from before Step 170** lacks those columns — the console **backfills** them from safe preview text when loading (`app/operator_console/intent_enrichment.py`), or re-export:

**Operational entity extraction (deterministic, shadow/HITL only):** `app/workflows/operational_entity_extraction.py` extracts **order IDs** (canonical `INC-` + 7 digits; any standalone exact 7-digit number with digit boundaries — in Inchand there is no separate complaint ID format; complaint numbers like `8201241` are order IDs; higher confidence near order/action keywords such as سفارش، تحویل، ارسال، برگشت، لغو، کنسل، رهگیری، شکایت; medium when standalone), **product IDs** (exactly 8 digits near product keywords — 7-digit spans are never product IDs), and **tracking codes** (Iran Post: 24 digits near post/tracking words; Tipax: 15–25 digits with `تیپاکس`; Chapar: 17 digits with `چاپار`; no 7-digit submatches inside longer digit runs). Persian/Arabic/English digits normalized. Flags **incomplete** 6-digit order candidates and **ambiguous** numbers with Persian warnings (`شماره سفارش ناقص احتمالی`, `شماره نامشخص`). **Boundaries:** no external APIs, no order/product existence checks, no mutations, no delivery-status updates, no customer send, **no LLM extraction**, no full transcripts in prompts. Step 169/170 integrations preserve compat fields `extracted_order_ids` / `extracted_tracking_code` and add `extracted_product_ids`, `extracted_tracking_carrier`, `entity_warnings_summary` where safe. Operator console **Extracted entities (AI assist)** shows order/product/tracking + carrier + warnings. Offline draft prompts may cite extracted entities **without claiming verification**.

```bash
LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=true \
VENDOR_TICKET_AI_ASSIST_SHADOW_ENABLED=true \
PYTHONPATH=. python3.11 scripts/export_ai_assist_shadow_replay_jsonl.py \
  data/private/vendor_tickets_400.redacted.jsonl \
  --namespace vendor_ticket_real_pilot_balanced \
  --index-version pilot_balanced_v1 \
  --confirm-sandbox --overwrite
```

**Full conversation mode (operator console only):** default **on** in Streamlit — loads redacted ticket JSONL (`data/private/vendor_tickets_400.redacted.jsonl` or sidebar path) and shows the **full** vendor/support/finance thread via `app/operator_console/full_ticket_view.py` (PII redacted, multiline preserved, **no** character truncation, system/internal messages excluded). **Compact preview mode** keeps existing truncated HITL fields (400/600-char budgets) for exports, governance, and JSONL payloads. **Knowledge hints (Steps 167–168, optional):** read-only **official policy** snippets from sandbox pgvector (`KNOWLEDGE_HINTS_ENABLED=true`; `app/operator_console/knowledge_hints.py` + Step 166 retrieval tool). Hint queries still use truncated safe snapshot fields — **not** the full thread. **Domain normalization (Step 168):** deterministic Persian synonym/misspelling fixes before retrieval (`app/knowledge/domain_query_normalization.py` — e.g. `تصفیه پنل` → `تسویه حساب فروشنده`) plus small `intent:` / route `boost:` phrases for fund/billing tickets; **no LLM rewrite**. **Local sandbox only** (`knowledge_operations_sandbox` / `knowledge_v1_openai`); **not** used for draft/final responses or customer send. **Replay mode:** `reports/ai_assist_shadow_replay_v1.jsonl` (snapshots enriched from redacted export). **Live mode:** read-only JSONL polling (`LIVE_FEED_ENABLED=true`). **Operator feedback:** optional append-only `reports/operator_feedback.jsonl` (aggregate fields + short internal note only; not used for training or AI assist). **Internal only** — no auth, no production DB writes, no customer send.

```bash
# Optional policy hints (local sandbox DB + OpenAI query embeddings)
KNOWLEDGE_HINTS_ENABLED=true PYTHONPATH=. python3.11 scripts/run_operator_console.py
```

**Historical reply benchmark (Step 161, offline only):** build evaluation rows from **redacted** vendor ticket JSONL (`data/private/vendor_tickets_400.redacted.jsonl` by default). Each case links an **open-ticket-style snapshot before reply** (`original_vendor_issue_preview`, `latest_vendor_message`, `recent_context_preview`) to the **next human** `support_agent` / `finance_agent` message as `gold_reference_reply` (truncated, PII-checked). Outputs stay under **gitignored** `reports/` (`historical_reply_benchmark_v1.jsonl`, `historical_reply_benchmark_summary.json`). **Does not** generate model replies or send customer messages — dataset prep only (`app/evals/historical_reply_benchmark.py`).

```bash
PYTHONPATH=. python3.11 scripts/build_historical_reply_benchmark.py --overwrite
```

**First-turn benchmark mode (recommended for draft eval):** one case per room when the **first non-internal message** is from the seller and a later `support_agent` / `finance_agent` reply exists (`--case-mode first_vendor_turn`). This avoids the noisy **all_adjacent_pairs** expansion (~1386 cases from 166 rooms). Default CLI mode remains `all_adjacent_pairs` for backward compatibility.

```bash
# 1) Build first-turn benchmark (~one row per room)
PYTHONPATH=. python3.11 scripts/build_historical_reply_benchmark.py \
  --case-mode first_vendor_turn \
  --output reports/historical_reply_benchmark_first_turn_v1.jsonl \
  --summary-output reports/historical_reply_benchmark_first_turn_summary.json \
  --overwrite

# 2) Offline drafts (mock or OpenAI)
PYTHONPATH=. python3.11 scripts/generate_offline_draft_suggestions.py \
  --input reports/historical_reply_benchmark_first_turn_v1.jsonl \
  --output reports/offline_draft_suggestions_first_turn_v1.jsonl \
  --summary-output reports/offline_draft_suggestions_first_turn_summary.json \
  --overwrite

# 3) Deterministic draft vs gold metrics
PYTHONPATH=. python3.11 scripts/evaluate_offline_draft_suggestions.py \
  --drafts reports/offline_draft_suggestions_first_turn_v1.jsonl \
  --benchmark reports/historical_reply_benchmark_first_turn_v1.jsonl \
  --output reports/offline_draft_evaluation_first_turn_v1.json \
  --markdown-output reports/offline_draft_evaluation_first_turn_v1.md \
  --overwrite
```

**Offline draft suggestions (Step 171, evaluation only):** generate **internal-only** Persian draft reply suggestions for historical benchmark cases (`app/evals/offline_draft_generation.py`). **First-turn isolation (Steps 175 + 179, default):** `DRAFT_GENERATION_MODE=first_turn_only` (`app/evals/draft_generation_mode.py`) calibrates drafts as **first support replies**. **`build_first_turn_draft_context`** (`app/evals/first_turn_draft_context.py`) forces intent detection, **entity extraction** (`entity_source=original_vendor_issue_preview`), conceptual intent, and sandbox **policy hint queries** to use **only** `original_vendor_issue_preview` — not `latest_vendor_message`, `recent_context_preview`, `open_ticket_preview`, `ticket_text_preview`, or precomputed entities from full-thread HITL rows. Leakage guards (`app/evals/draft_prompt_leakage.py`) fail if later-thread-only order/product/tracking values appear in prompts. **Draft style (Step 179):** `DRAFT_STYLE=operational_short` (`app/evals/draft_style.py`) — target ≤180 chars, hard max 300, max 2 sentences; bans generic fluff phrases; stores `draft_style`, `draft_char_count`, `draft_style_ok`, `draft_style_warnings` on offline rows and operator preview. Multi-turn **`live_thread_context`** mode exists for future work but is **not** active. Optional safe audit: `--write-prompt-audit` → `reports/offline_draft_prompt_audit.jsonl` (metadata only — **no** full prompt bodies). Gold human replies are **evaluation-only** (Step 172 metrics), not prompt inputs. Outputs (gitignored): `reports/offline_draft_suggestions_v1.jsonl`, `reports/offline_draft_suggestions_summary.json`. **Not** sent to customers, **not** wired to `final_response` or production `RAG_PROFILE`. Default CI/tests use **mock** LLM; real OpenAI requires `--provider openai --confirm-real-openai` and `OPENAI_API_KEY`.

**Internal draft preview + regenerate (Step 173, operator console only):** `app/operator_console/draft_preview.py` loads offline JSONL (e.g. `reports/offline_draft_suggestions_first_turn_v1.jsonl`) and shows an **Internal draft suggestion** block in Streamlit with caption *Internal preview only — not sent to customer.* UI shows **Draft mode: First-turn only**, **Entity source: original_vendor_issue_preview**, **Draft style: operational_short**, length, and style validation status (Step 179). **Conceptual intent (Steps 176–177, exploratory):** each generated draft may include `conceptual_intent_fa` — a short Persian label (≤4 words) for operator review (`app/evals/conceptual_intent_fa.py`). Labels are calibrated toward **operational request phrasing** (what the seller wants support to **do**, e.g. ثبت تحویل سفارش) rather than topic summaries (e.g. استعلام وضعیت سفارش). Rule-assisted hints (`extract_operational_request_phrase`) and validation reject overly generic labels when a specific request is detectable. **Rule-based `detected_intent` remains authoritative** for workflow/routing; conceptual labels are **not** used for actions yet. Future work: aggregate reviewed `conceptual_intent_fa` values into a candidate taxonomy dictionary (not auto-written today). **Generate new draft** regenerates via OpenAI into **session_state only** (no JSONL append, no DB, no production ticket writeback, no customer send). Flags (default **off**): `OPERATOR_DRAFT_PREVIEW_ENABLED`, `OPERATOR_DRAFT_GENERATION_ENABLED`, `OPERATOR_DRAFT_MODEL=gpt-4o-mini`, `OPERATOR_DRAFT_MAX_CHARS=700`, `DRAFT_GENERATION_MODE=first_turn_only`, `SHOW_GOLD_REPLY_IN_CONSOLE=false`. Regeneration uses first-turn isolated prompts — **no** gold reply, thread history, or retrieval hit bodies. Unsafe drafts are rejected via `assert_draft_reply_safe()`.

**First-turn draft entity isolation (operator console):** in `DRAFT_GENERATION_MODE=first_turn_only`, internal draft prompts, the **Extracted entities (first-turn only)** section, and **Draft entities (first-turn only)** all use `original_vendor_issue_preview` only. The entity leakage guard only fails when a value appears in the **assembled draft prompt** and is extracted from later/open fields but **not** as literal text in `original_vendor_issue_preview` (complaint numbers like `8201241` in the first message are allowed). On failure, the error names `leaked_value` and `source_field` (e.g. `latest_vendor_message`, `open_ticket_preview`) without printing the full prompt — not `OperatorTicket.extracted_order_ids` from open snapshot/AI assist. Open-snapshot / AI-assist entity fields remain available under **Open snapshot entities (debug)** in the console. In `live_thread_context` mode the main entity section uses open-snapshot fields as before. Debug: `PYTHONPATH=. python3.11 scripts/debug_first_turn_ticket_context.py --room-id <ROOM> --redacted-jsonl data/private/vendor_tickets_400.redacted.jsonl --replay-jsonl reports/ai_assist_shadow_replay_v1.jsonl` (outputs `first_turn_display_entities`, `open_snapshot_entities`, `draft_context_entities`).

**First-vendor-only console filtering (Step 182, operator console only):** when `OPERATOR_FIRST_VENDOR_ONLY=true` (default), the operator console lists only rooms where the **first non-internal message** is from **seller/vendor** (`app/operator_console/first_vendor_filter.py`). Rooms opened by `support_agent` or `finance_agent` are hidden from listing, sidebar counts, and draft review navigation. Uses the redacted tickets JSONL snapshot index by `room_id`; **does not** delete or rewrite benchmark/replay JSONL rows. Purpose: first-turn seller-initiated support calibration. Set `OPERATOR_FIRST_VENDOR_ONLY=false` to restore the previous all-rooms listing.

**Human draft review feedback (Step 181, operator console only):** structured scoring for internal drafts via `app/operator_console/draft_review_feedback.py` — checkboxes (intent/action/entities correct, draft usable, too verbose, hallucination) plus optional short notes (≤300 chars). **Append-only** local log: `reports/draft_review_feedback.jsonl` (gitignored). Sidebar shows reviewed count, usable %, hallucination %, and verbosity % from local JSONL only. Session badges after submit: ✅ good draft / ⚠️ verbose / ⚠️ hallucination risk. **Purpose:** offline behavior calibration and taxonomy/draft quality review — **no** auto-training, **no** automatic prompt or taxonomy updates, **no** customer send, **no** full prompts or transcripts stored.

**Informational reply completion calibration (Step 184, draft generation only):** `app/evals/draft_completion_calibration.py` reduces unnecessary operational follow-up filler on **informational** seller questions (policy, settlement timing, publishing rules). When the draft already answers the question and no human review/action is implied by `suggested_action`, trailing wait/review sentences (e.g. «لطفا صبر کنید»، «در حال بررسی»، «به تیم مربوطه ارجاع شد») are **not** appended — prompt instructions plus optional deterministic stripping of a **trailing** filler sentence only. Operational/escalation tickets (`human_followup`, `escalate`, `check_order_status`, …) still allow follow-up closure. **No** auto-send, **no** retrieval changes, **no** global rewrite of all drafts. Draft review metrics track `unnecessary_followup_detected` when operators submit reviews.

**Draft review metrics report (Step 183, evaluation only):** `app/evals/draft_review_metrics.py` aggregates `reports/draft_review_feedback.jsonl` into calibration insights — overall rates (usable, hallucination, verbosity, intent/action/entity accuracy), breakdowns by `detected_intent`, `conceptual_intent_fa`, `suggested_action`, and `ticket_label`, plus top failure patterns (checkbox + short note heuristics) and reviewer-note themes. **Evaluation-driven calibration** — metrics are **local/offline only** (gitignored `reports/draft_review_metrics_summary.json` and `reports/draft_review_metrics_report.md`); **no** automatic learning, prompt mutation, taxonomy changes, or production analytics. Build after ~10–20 manual reviews:

```bash
PYTHONPATH=. python3.11 scripts/build_draft_review_metrics_report.py --overwrite
```

**Suggested action mapping refinement v1 (Step 186, deterministic only):** `app/workflows/suggested_action_taxonomy.py` reduces **monitor** overuse — `monitor` is reserved for passive greetings, status-less notifications, and unclear low-action text. Operational signals (ask verbs, operational `conceptual_intent_fa`, extracted entities, Step 169 seller operational request types, specific intents) **suppress** monitor fallback and prefer actions such as `update_delivery_status`, `check_product_approval`, `check_settlement_status`, `human_followup`, or `record_update`. Mapping metadata: `monitor_blocked_by_operational_signals`, `fallback_reason` (calibration visibility only). **No** action execution or automatic taxonomy deployment.

**Monitor boundary refinement (Step 188, deterministic only):** Step 187 showed most action mismatches were **`monitor` on operational tickets**. `should_suppress_monitor()` blocks monitor when conceptual stems imply operations (ثبت/تایید/پیگیری/مرجوع/شکایت/…), when `general_vendor_support` pairs with operational `conceptual_intent_fa`, or when entities + ask verbs appear. Suppressed monitor maps to a **specific** advisory action (`check_product_approval`, `check_return_request`, `check_order_status`, `human_followup`, …); `request_missing_info` is refined when conceptual intent is already clear. **`monitor`** remains for greeting-only and vague passive notifications. Metadata: `monitor_suppressed`, `monitor_suppression_reason`. **Advisory only** — no action execution.

**Suggested action calibration report (Step 185, evaluation only):** `app/evals/suggested_action_calibration.py` analyzes `suggested_action` quality from the same draft review JSONL — action accuracy rate, weakest actions/intents, monitor and `human_followup` usage, **fallback overuse** (operational conceptual intent paired with `monitor`/`human_followup`), mismatch patterns, and **advisory** `suggested_mapping_adjustments` (not applied automatically). Outputs: `reports/suggested_action_calibration_summary.json` and `reports/suggested_action_calibration_report.md`. Use when draft quality is strong but **action accuracy** is the weakest metric. **No** auto-mapping changes, action execution, or production workflow updates.

```bash
PYTHONPATH=. python3.11 scripts/build_suggested_action_calibration_report.py --overwrite
```

**Action mismatch deep analysis (Step 187, evaluation only):** `app/evals/action_mismatch_analysis.py` explains **why** `action_accuracy_rate` may drop after Step 186 specificity increases — top wrong predicted actions, intent/conceptual mismatch slices, **confusion pairs** (predicted → inferred expected from reviewer note/conceptual hints), and **ambiguous action boundaries** (e.g. `billing_review` vs `check_settlement_status`). Outputs: `reports/action_mismatch_analysis_summary.json` and `reports/action_mismatch_analysis_report.md`. **Advisory only** — guides the next manual taxonomy refinement; does not change mappings.

```bash
PYTHONPATH=. python3.11 scripts/build_action_mismatch_analysis.py --overwrite
```

**Agentic workflow sandbox (Step 193, orchestration only):** `app/agentic_sandbox/` compiles a **linear LangGraph** that orchestrates existing safe components (first-turn context → intent → entities → knowledge hints → suggested action → actionability → draft → safety gate → HITL handoff). **Not** autonomous execution: `execution_allowed=false`, `customer_send_allowed=false`, `human_review_required=true` always. Does **not** replace `app/graph/main_graph.py` or operator console yet. Plan: [docs/operations/agentic_workflow_sandbox_plan.md](docs/operations/agentic_workflow_sandbox_plan.md).

```bash
PYTHONPATH=. python3.11 scripts/run_agentic_sandbox_workflow.py \
  --room-id <ROOM_ID> --provider mock --overwrite
```

**Agentic sandbox visualization & LangSmith tracing (Step 194, observability only):** Render the sandbox LangGraph as Mermaid/markdown (`reports/agentic_sandbox_graph.mmd`, `reports/agentic_sandbox_graph.md`; optional PNG when renderer deps exist). Optional LangSmith tracing via `--enable-langsmith` or `LANGSMITH_TRACING_ENABLED=true` — requires `LANGSMITH_API_KEY` at runtime (never committed); runs continue without tracing if the key is missing.

```bash
PYTHONPATH=. python3.11 scripts/render_agentic_sandbox_graph.py --overwrite

LANGSMITH_API_KEY=... \
PYTHONPATH=. python3.11 scripts/run_agentic_sandbox_workflow.py \
  --room-id 7743 \
  --replay-jsonl reports/ai_assist_shadow_replay_v1.jsonl \
  --redacted-jsonl data/private/vendor_tickets_400.redacted.jsonl \
  --provider mock \
  --enable-langsmith \
  --langsmith-project inchand-agentic-sandbox \
  --overwrite
```

Run JSON reports include `langsmith_tracing_enabled`, `langsmith_project`, and `langsmith_run_note` (no LangSmith URLs or secrets).

**Agentic sandbox batch report (Step 195, observability only):** Runs the sandbox graph in batch for **first-vendor rooms only** (seller/vendor first meaningful sender; excludes support/finance-first). Writes safe per-room rows (no full draft text), aggregate summary, and markdown report.

```bash
PYTHONPATH=. python3.11 scripts/run_agentic_sandbox_batch_report.py \
  --replay-jsonl reports/ai_assist_shadow_replay_v1.jsonl \
  --redacted-jsonl data/private/vendor_tickets_400.redacted.jsonl \
  --provider mock \
  --limit 20 \
  --overwrite
```

Outputs: `reports/agentic_sandbox_batch_runs.jsonl`, `reports/agentic_sandbox_batch_summary.json`, `reports/agentic_sandbox_batch_report.md`. Not wired to operator console or production graph.

**Agentic sandbox readiness analysis (Step 196, analytics only):** After a batch run, `app/agentic_sandbox/agentic_readiness_analysis.py` classifies each room into readiness buckets (ready for human review, missing identifier, knowledge review, node error, safety failed, draft missing/invalid), computes per-node success/error rates, and lists inspection targets. Validates sandbox workflow readiness without changing graph logic, draft generation, or operator console wiring.

```bash
PYTHONPATH=. python3.11 scripts/build_agentic_sandbox_readiness_report.py --overwrite
```

Outputs: `reports/agentic_sandbox_readiness_summary.json`, `reports/agentic_sandbox_readiness_report.md`. Safe fields only — no full draft text, prompts, or transcripts.

**Agentic knowledge hint coverage (Step 197, diagnostics only):** `app/agentic_sandbox/knowledge_hint_coverage_analysis.py` explains why policy-relevant sandbox runs return zero knowledge hints. Detects policy relevance from intent/action/label signals, infers likely gap reasons (missing query terms, index gap, filter strictness, normalization, action/intent mismatch), and lists inspection targets. **Analytics only** — no retrieval ranking, embedding, index, or draft changes.

```bash
PYTHONPATH=. python3.11 scripts/build_agentic_knowledge_hint_coverage_report.py --overwrite
```

Outputs: `reports/agentic_knowledge_hint_coverage_summary.json`, `reports/agentic_knowledge_hint_coverage_report.md`.

**Agentic batch knowledge hints smoke (Step 198, sandbox batch only):** `--enable-knowledge-hints` on `run_agentic_sandbox_batch_report.py` runs the sandbox graph with `knowledge_hints_enabled=true` (default remains **false** for safe batch baselines). Batch JSONL rows include `knowledge_hint_count` and `knowledge_hint_document_types` only — no raw snippets or retrieval query text. Batch summary adds `knowledge_hint_coverage_rate` for policy-relevant rooms.

```bash
PYTHONPATH=. python3.11 scripts/run_agentic_sandbox_batch_report.py \
  --replay-jsonl reports/ai_assist_shadow_replay_v1.jsonl \
  --redacted-jsonl data/private/vendor_tickets_400.redacted.jsonl \
  --provider mock \
  --limit 20 \
  --enable-knowledge-hints \
  --overwrite

PYTHONPATH=. python3.11 scripts/build_agentic_knowledge_hint_coverage_report.py --overwrite
```

**Operator console agentic sandbox preview (Step 199, optional):** When `OPERATOR_AGENTIC_SANDBOX_PREVIEW_ENABLED=true`, the internal console shows an **Agentic sandbox preview** section per ticket with **Run sandbox graph**. It runs the existing `app/agentic_sandbox/` LangGraph (first-turn only) into Streamlit `session_state` only — no DB writes, no send, no production graph. Default provider is **mock** (`OPERATOR_AGENTIC_SANDBOX_PROVIDER=mock`); knowledge hints follow `OPERATOR_AGENTIC_SANDBOX_KNOWLEDGE_HINTS_ENABLED` (default true). UI shows node statuses, intent/action, actionability, safe entity counts, hint document types, and draft length — **not** draft text, prompts, transcripts, or retrieval snippets. Distinct from **Internal draft suggestion** (offline JSONL / session regenerate).

```bash
OPERATOR_AGENTIC_SANDBOX_PREVIEW_ENABLED=true \
OPERATOR_AGENTIC_SANDBOX_PROVIDER=mock \
OPERATOR_AGENTIC_SANDBOX_KNOWLEDGE_HINTS_ENABLED=true \
PYTHONPATH=. python3.11 scripts/run_operator_console.py
```

**Agentic sandbox preview HITL review (Step 200, evaluation only):** Under **Agentic sandbox preview**, operators can submit structured graph-level feedback (intent/action/actionability/entities/hints/safety/readiness/draft length/overall usefulness) to `reports/agentic_preview_review_feedback.jsonl`. Sidebar shows aggregate usefulness and correctness rates from local JSONL only. **No auto-learning**, graph changes, or customer send.

```bash
OPERATOR_AGENTIC_SANDBOX_PREVIEW_ENABLED=true \
OPERATOR_AGENTIC_SANDBOX_PROVIDER=mock \
PYTHONPATH=. python3.11 scripts/run_operator_console.py
```

**Agentic preview review metrics report (Step 201, analytics only):** `app/agentic_sandbox/preview_review_metrics.py` aggregates operator sandbox preview review feedback from `reports/agentic_preview_review_feedback.jsonl` into JSON + markdown metrics (usefulness, graph-dimension accuracy, knowledge helpfulness, safety/readiness, top issue counts, weakest dimensions, optional breakdowns by `room_id` / `detected_intent` / `suggested_action` when present or joinable from batch runs). Outputs: `reports/agentic_preview_review_metrics_summary.json` and `reports/agentic_preview_review_metrics_report.md`. **Analytics only** — no graph logic changes, no auto-learning, no prompts/transcripts/snippets/draft text in reports.

```bash
PYTHONPATH=. python3.11 scripts/build_agentic_preview_review_metrics_report.py --overwrite
```

**Agentic sandbox graduation criteria (Step 205, governance only):** `app/agentic_sandbox/graduation_criteria.py` aggregates existing sandbox reports (readiness, knowledge coverage, preview review metrics, optional console/graph consistency, optional draft review metrics) into an explicit **graduation decision**: `not_ready`, `conditionally_ready`, or `ready_for_operator_assisted_phase`. Evaluates safety enforcement (no execution/send), preview usefulness, intent/action accuracy, policy coverage, human-review readiness, and consistency mismatch rates. Outputs guardrails and recommended next phase — **no production execution**, no auto-send, no workflow changes.

```bash
PYTHONPATH=. python3.11 scripts/build_agentic_sandbox_graduation_report.py --overwrite
```

Outputs: `reports/agentic_sandbox_graduation_summary.json` and `reports/agentic_sandbox_graduation_report.md`.

**Operator-assisted agentic mode (Step 206, HITL-only):** When `OPERATOR_AGENTIC_ASSISTED_MODE_ENABLED=true`, the operator console shows an **Operator-assisted agentic mode** section (distinct from **Agentic sandbox preview**). The sandbox LangGraph builds a **structured operator work package** in Streamlit `session_state` only — checklist plus safe graph metadata (intent, action, actionability, entities, hint document types, draft length, safety flags). **Graduation gate:** when `OPERATOR_AGENTIC_ASSISTED_REQUIRE_GRADUATION_READY=true` (default), reads `reports/agentic_sandbox_graduation_summary.json` and requires `overall_status=ready_for_operator_assisted_phase`; otherwise the section shows a warning and run stays disabled (console keeps working). **No execution, no customer send, no ticket mutation, no production graph.** Reuse **Sandbox preview review** feedback for graph evaluation (`reports/agentic_preview_review_feedback.jsonl`).

```bash
OPERATOR_AGENTIC_ASSISTED_MODE_ENABLED=true \
OPERATOR_AGENTIC_ASSISTED_PROVIDER=mock \
OPERATOR_AGENTIC_ASSISTED_KNOWLEDGE_HINTS_ENABLED=true \
PYTHONPATH=. python3.11 scripts/run_operator_console.py
```

Config: `OPERATOR_AGENTIC_ASSISTED_MODE_ENABLED` (default false), `OPERATOR_AGENTIC_ASSISTED_PROVIDER` (mock), `OPERATOR_AGENTIC_ASSISTED_KNOWLEDGE_HINTS_ENABLED` (default true), `OPERATOR_AGENTIC_ASSISTED_REQUIRE_GRADUATION_READY` (default true). Module: `app/operator_console/agentic_assisted_mode.py`.

**Operator console draft display + FA/EN UI (Step 207):** The internal Streamlit console defaults to **FA** (`st.session_state["operator_console_lang"]`). A top-level **فارسی / English** toggle switches Persian labels + **full RTL layout** (sidebar on the **right**, right-aligned widgets/text) vs English labels + default LTR. `app/operator_console/i18n.py` provides translations and `apply_console_direction_css()`. **Agentic sandbox preview** and **Operator-assisted agentic mode** show validated **internal draft text** (after `assert_draft_reply_safe` and `safety_status=passed`) with captions «این متن فقط برای بررسی اپراتور است…» / “Internal review only — not sent to the vendor.” Mock drafts are labeled. Still **no customer send**, no execution, no raw prompts/transcripts/snippets. Module: `app/operator_console/agentic_draft_display.py`.

**Operator-assisted review metrics (Step 207b, analytics only):** `app/operator_console/agentic_assisted_review_metrics.py` aggregates operator-assisted workflow quality from sandbox preview review feedback (`reports/agentic_preview_review_feedback.jsonl`) plus optional assisted extension (`reports/operator_assisted_review_feedback.jsonl`). Reports usefulness, operator trust, dimension accuracy, draft helpfulness, safety confidence, breakdowns by intent/action, weakest dimensions, and top issues — **no prompts, transcripts, snippets, or draft bodies**.

```bash
PYTHONPATH=. python3.11 scripts/build_operator_assisted_review_metrics_report.py --overwrite
```

Outputs: `reports/operator_assisted_review_metrics_summary.json` and `reports/operator_assisted_review_metrics_report.md`.

**Operator-assisted UI simplification + mock operational drafts (Step 208):** Operator-assisted mode shows a **concise operational work package** (seller summary, suggested action, information status, extracted IDs, internal draft read-only box, safety flags). Technical graph metadata (node statuses, hint types, char counts, checklist) moves to a collapsed **Technical / diagnostic** expander. Mock sandbox runs use `app/agentic_sandbox/mock_draft_templates.py` (`generate_mock_operational_draft`) for **deterministic Persian operational drafts** instead of the generic `[خروجی آزمایشی قطعی…]` LLM placeholder; UI shows a small **Draft source: mock template** label (not inside draft body). Still HITL-only — no send, no execution.

**Assisted mode pilot readiness gate (Step 211, governance only):** `app/operator_console/assisted_mode_pilot_readiness.py` aggregates existing sandbox/assisted/draft reports into a **limited internal pilot readiness** decision (`not_ready_for_pilot`, `ready_with_guardrails`, or `ready_for_limited_internal_pilot`). This is a reporting gate only — it does **not** enable production send, ticket/order/product mutation, action execution, auto-approval, or graph/mapping changes.

**Limited internal pilot definition:** first-turn seller-initiated tickets only; internal operators only; mock or OpenAI provider explicitly selected; session-only graph output; continue manual sandbox/assisted review logging. **Guardrails:** keep `OPERATOR_AGENTIC_ASSISTED_MODE_ENABLED` limited to the pilot cohort; `execution_allowed=false` and `customer_send_allowed=false`; no customer send button; no auto-send; assisted mode stays additive to the existing console workflow.

```bash
PYTHONPATH=. python3.11 scripts/build_assisted_mode_pilot_readiness_report.py --overwrite
```

Inputs (required): `reports/agentic_sandbox_graduation_summary.json`, `reports/agentic_sandbox_readiness_summary.json`, `reports/agentic_knowledge_hint_coverage_summary.json`, `reports/operator_assisted_review_metrics_summary.json`. Optional (missing → warnings only): draft review metrics, console/graph consistency, draft quality slice, action mismatch. Outputs: `reports/assisted_mode_pilot_readiness_summary.json` and `reports/assisted_mode_pilot_readiness_report.md` (no prompts, transcripts, snippets, draft bodies, or secrets).

**Live first-turn shadow intake (Step 212, read-only):** `app/live_shadow/live_first_turn_shadow_intake.py` connects the **live ticket JSONL feed** to the **agentic sandbox graph** in strict shadow mode. Scope: **first-turn seller-initiated** tickets only (no prior support reply, no multi-turn escalations, open/not-closed). Uses the same redacted open-ticket snapshot and full first-vendor extraction path as the operator console — **no governance bypass**. Persists safe rows only (`draft_char_count`, not draft bodies). **Dedupe** by `room_id` + `first_turn_signature`. **No send, no execution, no ticket mutation** (`execution_allowed=false`, `customer_send_allowed=false`, `human_review_required=true`).

```bash
PYTHONPATH=. python3.11 scripts/run_live_first_turn_shadow_intake.py \
  --provider mock \
  --limit 25 \
  --enable-knowledge-hints \
  --dedupe \
  --overwrite
```

Outputs: `reports/live_shadow_first_turn_runs.jsonl` (append-only) and `reports/live_shadow_first_turn_summary.json`. Operator console shows a small **“Live shadow intake active”** caption when a summary was generated in the last 24 hours.

**Live feed adapter contract (Step 213, integration spec):** [`docs/integration/live_feed_adapter_contract.md`](docs/integration/live_feed_adapter_contract.md) defines the **read-only** handoff for live seller-support tickets into shadow intake. **File-based pilot** (preferred): append or snapshot JSONL to `data/private/live_vendor_tickets.jsonl`. **API mode** (future): read-only `GET /support/live-tickets?updated_after=...&limit=...` — planned for a later integration phase. Contract covers required schema, sender normalization, eligibility rules, dedupe (`room_id` + `first_turn_signature`), and security boundaries. **No send, no execution, no ticket mutation.**

**Internal pilot PII policy:** `ALLOW_RAW_PII_INTERNAL_PILOT=true` (default) allows raw phone, IBAN, email, and card values **in feed inputs** so operators can validate entity extraction and review identifiers internally. Validation records these as **informational only** (`raw_identifiers_detected` — allowed in internal pilot mode). **Secrets still fail** (API keys, JWTs, session cookies). Future production feeds may set `ALLOW_RAW_PII_INTERNAL_PILOT=false` for strict redaction. Governance reports remain aggregate-only (no message bodies).

```bash
PYTHONPATH=. python3.11 scripts/validate_live_feed_contract.py \
  data/private/live_vendor_tickets.jsonl \
  --overwrite
```

Validator: `app/live_shadow/live_feed_contract.py`. Outputs: `reports/live_feed_contract_validation_summary.json` and `reports/live_feed_contract_validation_report.md`.

**OpenAI draft quality pilot (Step 214, draft-only):** `app/agentic_sandbox/openai_draft_provider.py` upgrades **only** Persian draft generation quality inside the existing agentic sandbox / operator-assisted / shadow intake flows. Intent detection, entity extraction, actionability, safety gates, suggested-action mapping, and graph routing stay deterministic and unchanged. **No send, no execution, no ticket mutation, no auto-approve, no prompt/transcript/snippet exposure.**

Provider selection: `mock` (deterministic templates) or `openai` (dedicated chat draft path with `OPENAI_DRAFT_MODEL`, `OPENAI_DRAFT_TEMPERATURE`, `OPENAI_DRAFT_MAX_TOKENS`). When OpenAI is unavailable, the provider **falls back to mock templates** with a warning only. UI labels: FA «منبع پیش‌نویس: OpenAI» / EN “Draft source: OpenAI”. Batch/shadow summaries track `openai_draft_quality_rate`, `generic_reply_rate`, `concise_reply_rate`, and `fallback_to_mock_rate`.

```bash
export OPENAI_API_KEY=...

OPERATOR_AGENTIC_ASSISTED_MODE_ENABLED=true \
OPERATOR_AGENTIC_ASSISTED_PROVIDER=openai \
OPERATOR_AGENTIC_ASSISTED_KNOWLEDGE_HINTS_ENABLED=true \
PYTHONPATH=. python3.11 scripts/run_operator_console.py
```

Shadow / batch OpenAI draft runs (read-only; requires explicit confirmation):

```bash
PYTHONPATH=. python3.11 scripts/run_live_first_turn_shadow_intake.py \
  --provider openai --confirm-real-openai --limit 10 --dedupe

PYTHONPATH=. python3.11 scripts/run_agentic_sandbox_batch_report.py \
  --replay-jsonl reports/ai_assist_shadow_replay_v1.jsonl \
  --provider openai --confirm-real-openai --overwrite
```

**Operational information sufficiency policies (Step 215, draft quality only):** `app/workflows/operational_information_sufficiency.py` teaches the sandbox/assisted draft path to request **only the minimum operationally required information** — like a marketplace operations copilot, not a generic customer-service chatbot. Deterministic scenario policies cover delivery/shipment confirmation, cancellation, product approval, settlement informational replies, and complaint follow-up. Adds over-questioning suppression (`detect_over_questioning`, `detect_unnecessary_detail_request`), OpenAI prompt policy hints, and post-generation calibration that removes generic «provide more details» phrasing when a request is already operationally complete. Batch metrics track `over_questioning_rate`, `unnecessary_clarification_rate`, and `operational_completion_success_rate`. Sandbox preview review adds optional operator checkbox: FA «درخواست اطلاعات اضافه غیرضروری داشت» / EN “Asked for unnecessary additional details”. **No send, no execution, no ticket mutation, HITL unchanged.**

**Grounded policy_explanation drafts (Step 216, draft quality only):** `app/knowledge/policy_fact_extraction.py` injects **safe capped policy facts** (≤300 chars per hint, ≤600 total) into `policy_explanation` draft prompts — not just `document_type` metadata. Graph state stores internal `knowledge_hints_for_prompt` (snippet text for prompt building only); batch JSONL / operator console still expose **doc types + counts + snippet_chars only** — raw knowledge documents are not exposed. Settlement timing must be grounded: wallet block → 3 days after order finalization → first settlement window/payout. Post-generation calibration (`app/evals/draft_policy_grounding_calibration.py`) replaces vague «depends on policy / refer to rules» settlement drafts with the canonical grounded answer when `settlement_rules` facts are present. **No retrieval index/ranking changes, no send/execution, HITL unchanged.**

**Console vs graph consistency check (Step 204, diagnostics only):** `app/agentic_sandbox/console_graph_consistency.py` compares operator-console **first-turn draft context** (internal draft path) with **agentic sandbox graph preview** for the same ticket. Flags `consistent`, `explainable_difference`, or `mismatch` per safe field (intent, action, actionability, entities, knowledge hints, safety). Explainable when AI assist open snapshot differs from first-turn graph path, knowledge-hint config differs, or graph extracts extra IDs from `full_first_vendor_message_text`. **No behavior changes** — reports only.

```bash
PYTHONPATH=. python3.11 scripts/check_console_graph_consistency.py \
  --room-id 7743 \
  --replay-jsonl reports/ai_assist_shadow_replay_v1.jsonl \
  --redacted-jsonl data/private/vendor_tickets_400.redacted.jsonl \
  --provider mock \
  --enable-knowledge-hints \
  --overwrite
```

Outputs: `reports/console_graph_consistency_<room_id>.json` and `.md` (single room), or batch `reports/console_graph_consistency_batch.jsonl`, `console_graph_consistency_summary.json`, `console_graph_consistency_report.md`.

**Full first-turn entity extraction source (Step 203):** First-turn **entity extraction** uses the full redacted first seller/vendor message (`full_first_vendor_message_text` from `data/private/vendor_tickets_400.redacted.jsonl` via `app/operator_console/console_loader.py` and `app/live_feed/open_ticket_snapshot.py`). **UI and draft prompts** stay on truncated `original_vendor_issue_preview` (~200 chars). Still **first-turn only** — never `latest_vendor_message`, `recent_context_preview`, or full transcript. Metadata: `entity_extraction_source`, `entity_extraction_source_char_count`, `display_preview_char_count` (no full message text in reports/review JSONL). Leakage guard allows entities present in the full first-turn source even when absent from the display preview. Fixes truncation-related misses (e.g. room `43992` with two `INC-` order IDs).

```bash
PYTHONPATH=. python3.11 -m pytest tests/test_full_first_turn_entity_extraction.py -q
```

**Entity extraction miss investigation (Step 202, diagnostics only):** `app/workflows/entity_extraction_investigation.py` compares operator-flagged sandbox preview entity misses (`entity_extraction_correct=false` in `reports/agentic_preview_review_feedback.jsonl`) against full first-turn reference extraction from redacted export, truncated `original_vendor_issue_preview`, and sandbox first-turn path (Step 203 uses `full_first_vendor_message_text` when attached). Classifies likely root causes (e.g. `first_turn_isolation_gap`, `extraction_rule_gap`, `review_mismatch`). Outputs: `reports/entity_extraction_investigation_summary.json` and `reports/entity_extraction_investigation_report.md`.

```bash
PYTHONPATH=. python3.11 scripts/build_entity_extraction_investigation_report.py --room-id 43992 --overwrite
```

**Draft quality slice analysis (Step 192, analytics only):** `app/evals/draft_quality_slice_analysis.py` breaks draft review metrics into operational **slices** (detected intent, conceptual intent, suggested action, ticket/route label, entity presence, actionability) to find weak categories instead of relying on global averages only. Marks weak slices when usable/action/entity rates fall below thresholds (minimum review count per slice, default ≥3). Aggregates failure patterns (verbose, hallucination, wrong action, missing entities, unnecessary followup, identifier/clarification issues). Optional enrichment from offline draft JSONL adds `route_label`, extracted entities, and Step 191 actionability fields. Outputs: `reports/draft_quality_slice_analysis_summary.json` and `reports/draft_quality_slice_analysis_report.md`. **Advisory only** — no prompt/mapping/behavior changes.

```bash
PYTHONPATH=. python3.11 scripts/build_draft_quality_slice_analysis.py --overwrite
```

**Actionability validation (Step 191, operational validation only):** `app/evals/actionability_validation.py` blocks drafts from claiming an operational action started, forwarded, or completed when required identifiers are missing from the **first vendor message** (e.g. `order_id` for delivery/order/return asks, `product_id` for product approval/edit, `tracking_code` or `order_id` for shipment record updates). Settlement and policy questions remain actionable without IDs. Before LLM draft generation, validation is injected into the prompt; after generation, deterministic post-processing replaces replies that still contain fake operational claims («ثبت شد»، «ارجاع شد»، «در حال بررسی») with a concise identifier request. Suggested action metadata keeps the operational action with `actionability=false`, `missing_required_entities`, and `requires_identifier_request=true` — **no** automatic downgrade to `monitor`. Operator console internal draft preview shows **Actionable**, **Missing entities**, and **Validation reason**. No ticket/order mutation, no auto-send, no external ID fetch.

```bash
PYTHONPATH=. python3.11 -m pytest tests/test_actionability_validation.py -q
```

**Sheba/IBAN entity extraction (Step 190, deterministic only):** `app/workflows/operational_entity_extraction.py` extracts Iranian Sheba/IBAN (`IR` + 24 digits, or 24 digits near شبا/حساب/واریز keywords) with **post/tracking precedence** over bare 24-digit runs (Iran Post tracking). Incomplete 23/25-digit candidates near banking keywords add warnings. **Internal calibration console** shows the **full normalized IBAN** when `SHOW_FULL_IBAN_IN_OPERATOR_CONSOLE=true` (default) so reviewers can verify extraction; set `false` to use `mask_sensitive_entity()` in the UI for future production/HITL rollout. No banking API verification, no payment mutation, no customer/public exposure. Order ID hardening: standalone 7-digit, `INC`/`inc_` variants, `سفارش:`, Persian digits — without 7-digit submatches inside IBAN/tracking spans.

**Operator console UX + review schema (Step 189):** `app/operator_console/display_text.py` replaces visible PII placeholders (`[PHONE_NUMBER]`, `[IBAN]`, …) with short Persian labels in **UI display only** (snapshot previews, RTL blocks, full conversation view) — underlying redaction and prompt paths unchanged. Draft review uses one Persian **entity** selector (**بررسی استخراج موجودیت**): *نیاز به استخراج بوده و استخراج شده* → `entities_applicable=true`, `entities_correct=true`; *نیاز به استخراج بوده ولی استخراج نکرده* → `true` / `false`; *نیاز به استخراج نداشته* → `false` / `null`. `entity_accuracy_rate` = correct ÷ applicable only. Ticket list uses **1-based row numbers** over the filtered visible set (`#1 — Ticket …`). **No** draft generation, taxonomy, or production workflow changes.

```bash
# Preview offline first-turn drafts in console
OPERATOR_DRAFT_PREVIEW_ENABLED=true \
PYTHONPATH=. python3.11 scripts/run_operator_console.py

# Session-only regeneration (requires OPENAI_API_KEY)
OPERATOR_DRAFT_PREVIEW_ENABLED=true \
OPERATOR_DRAFT_GENERATION_ENABLED=true \
PYTHONPATH=. python3.11 scripts/run_operator_console.py
```

```bash
# Mock drafts (no network)
PYTHONPATH=. python3.11 scripts/generate_offline_draft_suggestions.py --overwrite --limit 5

# Real OpenAI (local operator approval only)
PYTHONPATH=. python3.11 scripts/generate_offline_draft_suggestions.py \
  --provider openai --confirm-real-openai --overwrite

# Optional safe prompt audit (no full prompts in output)
PYTHONPATH=. python3.11 scripts/generate_offline_draft_suggestions.py \
  --overwrite --limit 5 --write-prompt-audit
```

**Offline draft vs gold evaluation (Step 172, evaluation only):** deterministic first-pass comparison of Step 171 drafts to historical human replies (`app/evals/offline_draft_evaluation.py`). Loads local `reports/offline_draft_suggestions_v1.jsonl` + `reports/historical_reply_benchmark_v1.jsonl` (gold text used **only** for offline metrics — never for draft generation or Step 173 console prompts). Writes gitignored `reports/offline_draft_evaluation_v1.json` and `.md` with aggregate counts, Jaccard **lexical_overlap_score_avg**, intent/action/label distributions, and low-overlap case ids (**no** raw draft/gold bodies in markdown). **Not** production quality approval; **not** customer send.

```bash
PYTHONPATH=. python3.11 scripts/evaluate_offline_draft_suggestions.py --overwrite
```

**Operational knowledge foundation (Step 162, inventory only):** two complementary lanes — **official operational knowledge** (policies, SOPs, FAQs; authoritative) under `data/private/knowledge/operations/` (not committed), and **historical ticket memory** (aggregate patterns from `reports/historical_reply_benchmark_summary.json` — reference experience only, **not** policy truth). If they conflict, **official policy wins**. Historical lane never stores gold replies in the inventory output. **Templates (safe placeholders):** `docs/templates/knowledge/*.md.example` — copy to the private directory after review. **Code:** `app/knowledge/` (`knowledge_models`, `knowledge_loader`, `historical_ticket_memory`). **Inventory CLI:** `scripts/build_operational_knowledge_inventory.py` → `reports/operational_knowledge_inventory.{json,md}` (gitignored). **Next (future):** embedding/indexing/retrieval — not in this step.

```bash
PYTHONPATH=. python3.11 scripts/build_operational_knowledge_inventory.py --overwrite
```

**Knowledge chunking (Step 163, metadata only):** dual-lane **retrieval-ready chunks** without embeddings or pgvector indexing. **Official policy** markdown under `data/private/knowledge/operations/` is split on `#` / `##` headings with `priority_rank=10`. **Historical memory** uses **aggregate-only** text from `reports/historical_reply_benchmark_summary.json` with `priority_rank=1` (reference experience, not policy truth). If lanes conflict at retrieval time, **official policy wins** (`official_policy_overrides_historical_memory`). **Code:** `app/knowledge/knowledge_chunking.py`. **CLI:** `scripts/build_knowledge_chunks.py` → gitignored `reports/knowledge_chunks_preview.jsonl`, `knowledge_chunks_summary.{json,md}`. Embeddings/indexing intentionally **not** enabled yet.

```bash
PYTHONPATH=. python3.11 scripts/build_knowledge_chunks.py --overwrite
```

**Knowledge embedding + sandbox index (Step 164):** embed and upsert Step 163 chunks into **local sandbox pgvector only** (`rag_vector_records` with `record_id` prefix `knowledge::`). **Official policy** chunks use `priority_rank=10`; **historical memory** uses `priority_rank=1`. Smoke queries rank **priority first, then vector score** — if lanes conflict, **official policy wins** (`official_policy_overrides_historical_memory`). Requires `--confirm-sandbox`; OpenAI embeddings require `--provider openai --confirm-real-openai` and `OPENAI_API_KEY`. **Not** wired to draft/final responses, operator console, or production `RAG_PROFILE`.

```bash
# Index (mock — CI/tests; use openai + --confirm-real-openai locally for real vectors)
PYTHONPATH=. python3.11 scripts/index_knowledge_chunks_pgvector.py \
  reports/knowledge_chunks_preview.jsonl \
  --namespace knowledge_operations_sandbox \
  --index-version knowledge_v1 \
  --provider mock \
  --model mock-knowledge \
  --dimensions 1536 \
  --confirm-sandbox

# Smoke query (ranking: official_policy before historical_memory, then score)
PYTHONPATH=. python3.11 scripts/query_knowledge_pgvector.py \
  --query "قوانین انتشار کالای غیر اصل چیست؟" \
  --namespace knowledge_operations_sandbox \
  --index-version knowledge_v1 \
  --top-k 5 \
  --provider mock \
  --confirm-sandbox
```

**Real OpenAI knowledge embedding smoke (Step 165):** re-index with **`knowledge_v1_openai`** using `text-embedding-3-small` (1536-D) for **semantic** validation; Step 164 **`knowledge_v1`** mock index remains for offline CI only. Smoke queries use `--provider openai --confirm-real-openai`. Aggregate results: [`docs/operations/real_knowledge_embedding_smoke_report.md`](docs/operations/real_knowledge_embedding_smoke_report.md). **Not** wired to operator console, draft/final, or production `RAG_PROFILE`.

```bash
# Re-index (local; OPENAI_API_KEY required)
PYTHONPATH=. python3.11 scripts/index_knowledge_chunks_pgvector.py \
  reports/knowledge_chunks_preview.jsonl \
  --namespace knowledge_operations_sandbox \
  --index-version knowledge_v1_openai \
  --provider openai \
  --model text-embedding-3-small \
  --dimensions 1536 \
  --confirm-real-openai \
  --confirm-sandbox

# Semantic smoke query (example)
PYTHONPATH=. python3.11 scripts/query_knowledge_pgvector.py \
  --query "تسویه فروشنده چند روزه انجام می‌شود؟" \
  --namespace knowledge_operations_sandbox \
  --index-version knowledge_v1_openai \
  --top-k 5 \
  --provider openai \
  --confirm-real-openai \
  --confirm-sandbox
```

**Sandbox knowledge retrieval tool (Step 166):** governed executor `app/knowledge/knowledge_retrieval_tool.py` + CLI `scripts/run_sandbox_knowledge_retrieval_tool.py`. Returns safe hits only (`snippet` ≤300 chars, `retrieval_activated=false`, `sandbox_only=true`). **Ranking:** `official_policy` (`priority_rank=10`) before `historical_memory` (`priority_rank=1`) when `prefer_official_policy=true` (default). **Not** wired to operator console, draft/final, LangGraph, or production `RAG_PROFILE`.

```bash
PYTHONPATH=. python3.11 scripts/run_sandbox_knowledge_retrieval_tool.py \
  --query "قوانین انتشار کالای غیراصل چیست؟" \
  --namespace knowledge_operations_sandbox \
  --index-version knowledge_v1_openai \
  --top-k 5 \
  --confirm-real-openai \
  --confirm-sandbox
```

| Mode | Source | Behavior |
|------|--------|----------|
| **Replay** | Pre-exported shadow replay JSONL | Static batch; full history |
| **Live** | `LIVE_FEED_SOURCE_PATH` (append-only JSONL) | Poll + checkpoint; newest tickets first |

**Safety (live):** read-only file ingest; HITL-safe payloads only; no raw transcripts/hits/vectors in UI; no auto-send; no workflow mutations.

```bash
pip install -e ".[operator]"
# Replay (default)
PYTHONPATH=. python3.11 scripts/run_operator_console.py

# Live feed (local JSONL; enable shadow flags for routing/retrieval/assist)
LIVE_FEED_ENABLED=true \
  LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=true \
  VENDOR_TICKET_AI_ASSIST_SHADOW_ENABLED=true \
  LIVE_FEED_SOURCE_PATH=data/private/live_vendor_tickets.jsonl \
  PYTHONPATH=. python3.11 scripts/run_operator_console.py
```

Point `LIVE_FEED_SOURCE_PATH` at an append-only export JSONL (or symlink `data/private/vendor_tickets_400.redacted.jsonl` for local dev). Checkpoint: `reports/live_feed_checkpoint.json`. Open `http://localhost:8501` → sidebar **Live** mode.

**Retrieval policy gate calibration (Step 139):** synthetic allow/skip/deny fixtures — [`evals/retrieval_policy_gate/policy_gate_calibration_cases.json`](evals/retrieval_policy_gate/policy_gate_calibration_cases.json), runner `scripts/eval_retrieval_policy_gate.py`, report [`docs/operations/retrieval_policy_gate_calibration_report.md`](docs/operations/retrieval_policy_gate_calibration_report.md) (no pgvector/OpenAI).

**Shadow replay hit-count diagnosis (Step 141):** `scripts/diagnose_shadow_replay_hits.py` — explains zero `retrieval_result_count` when export metadata filters over-constrain vs pgvector index (see `docs/operations/shadow_replay_metrics_report.md`).

```bash
PYTHONPATH=. python3.11 scripts/eval_retrieval_policy_gate.py --overwrite
```

```bash
PYTHONPATH=. python3.11 scripts/dry_run_sandbox_retrieval_chain.py \
  --query "settlement payment status" \
  --ticket-label fund \
  --route-label billing_review \
  --namespace vendor_ticket_real_pilot_balanced \
  --index-version pilot_balanced_v1 \
  --profile semantic_pgvector \
  --top-k 5 \
  --confirm-sandbox
```

Requires `--confirm-sandbox`, local Postgres, and `OPENAI_API_KEY` only when the gate **allows** execution. Output is a safe retrieval state snapshot (`query_hash` only; no transcripts/vectors/hits).

```bash
PYTHONPATH=. python3.11 scripts/run_sandbox_retrieval_tool.py \
  --query "settlement payment status" \
  --namespace vendor_ticket_real_pilot_balanced \
  --index-version pilot_balanced_v1 \
  --profile semantic_pgvector \
  --top-k 5 \
  --ticket-label fund \
  --confirm-sandbox
```

Requires `OPENAI_API_KEY` (query embedding only), local Postgres, and `--confirm-sandbox`. Output is safe JSON (`query_hash` only; no transcripts/vectors).

**Pilot corpus integrity check** (offline, aggregate output only):

```bash
PYTHONPATH=. python3.11 scripts/check_pilot_corpus_integrity.py \
  corpus/vendor_ticket_real_pilot
```

**Pilot corpus repository policy:** [`docs/operations/pilot_corpus_repository_policy.md`](docs/operations/pilot_corpus_repository_policy.md) — **`corpus/vendor_ticket_real_pilot/` is local-only and gitignored by default**; do not commit real corpus artifacts until explicit governance approval. Commit code, docs, and tests only.

**Offline embedding generation plan:** [`docs/operations/offline_embedding_generation_plan.md`](docs/operations/offline_embedding_generation_plan.md) — planning only; derived vectors are **sensitive** and stay under gitignored `artifacts/embeddings/`; corpus `indexing_status` remains **`not_started`**.

**Mock embedding dry-run** (`mock` provider only — no OpenAI, no pgvector):

```bash
PYTHONPATH=. python3.11 scripts/build_pilot_corpus_embeddings.py \
  corpus/vendor_ticket_real_pilot \
  --output-dir artifacts/embeddings/vendor_ticket_real_pilot \
  --provider mock \
  --model mock-embedding-1536 \
  --dimensions 1536
```

**Real OpenAI embeddings (local only)** — requires `OPENAI_API_KEY`, `--provider openai`, and `--confirm-real-openai`:

```bash
PYTHONPATH=. python3.11 scripts/build_pilot_corpus_embeddings.py \
  corpus/vendor_ticket_real_pilot \
  --output-dir artifacts/embeddings/vendor_ticket_real_pilot_openai \
  --provider openai \
  --model text-embedding-3-small \
  --dimensions 1536 \
  --confirm-real-openai
```

Then run `check_embedding_artifact_integrity.py` on the OpenAI output directory. **No pgvector indexing** in this step.

**Real embedding integrity report:** [`docs/operations/real_embedding_artifact_integrity_report.md`](docs/operations/real_embedding_artifact_integrity_report.md) — sanitized record of local OpenAI run (25 records, `real_generated`, integrity passed).

**PgVector sandbox indexing plan:** [`docs/operations/pgvector_sandbox_indexing_plan.md`](docs/operations/pgvector_sandbox_indexing_plan.md) — sandbox/local pgvector indexing for 1536-D pilot embeddings; **does not activate retrieval**; eval gates required before production retrieval.

**PgVector sandbox indexing (local only)** — requires local Postgres (`make pg-up` / `make pg-init`), real OpenAI artifacts, `--confirm-sandbox`, and profile **`semantic_pgvector`** only (not `semantic_pgvector_16`):

```bash
PYTHONPATH=. python3.11 scripts/index_pilot_embeddings_pgvector.py \
  artifacts/embeddings/vendor_ticket_real_pilot_openai \
  --namespace vendor_ticket_real_pilot \
  --index-version pilot_v1 \
  --profile semantic_pgvector \
  --confirm-sandbox
```

Uses `PGVECTOR_DATABASE_URL` (default local `127.0.0.1`). Writes aggregate summary to gitignored `reports/pgvector_sandbox_indexing_pilot_v1.json`. **No LangGraph / `RAG_PROFILE` changes**.

**Pilot retrieval evaluation (local only)** — after sandbox indexing; requires `OPENAI_API_KEY` for query embeddings (same model as index); **does not activate retrieval**:

```bash
PYTHONPATH=. python3.11 scripts/eval_pilot_retrieval.py \
  --cases evals/pilot_retrieval/vendor_ticket_real_pilot_cases.json \
  --namespace vendor_ticket_real_pilot \
  --index-version pilot_v1 \
  --profile semantic_pgvector \
  --top-k 5 \
  --output reports/pilot_retrieval_eval_pilot_v1.json \
  --overwrite

# Compare vector-only vs metadata-filtered (fund/finance cases with metadata_filter)
PYTHONPATH=. python3.11 scripts/eval_pilot_retrieval.py \
  --cases evals/pilot_retrieval/vendor_ticket_real_pilot_cases.json \
  --namespace vendor_ticket_real_pilot \
  --index-version pilot_v1 \
  --profile semantic_pgvector \
  --compare-modes \
  --output reports/pilot_retrieval_eval_pilot_v1.json \
  --overwrite
```

Eval cases: `evals/pilot_retrieval/vendor_ticket_real_pilot_cases.json` (v4 — English + Persian finance). **Metadata filter calibration:** use `ticket_label` / `route_label` only; do **not** pin `metadata_filter.namespace` or `index_version` (pilot scope from CLI `--namespace` / `--index-version`). Do **not** use `department` in filters unless inventory shows explicit `metadata.department`. `--compare-modes` runs `vector_only` vs `metadata_filtered` with `delta_pass_rate` / `delta_wrong_label_return_count`.

**Pilot pgvector metadata inventory** (diagnose filter/schema mismatches; local sandbox only):

```bash
PYTHONPATH=. python3.11 scripts/inspect_pilot_pgvector_metadata.py \
  --namespace vendor_ticket_real_pilot \
  --index-version pilot_v1 \
  --profile semantic_pgvector \
  --output reports/pilot_pgvector_metadata_inventory_pilot_v1.json \
  --overwrite
```

Aggregate counts only (`ticket_label_counts`, `route_label_counts`, `missing_field_counts`) — no content, vectors, or transcripts.

**Pilot retrieval evaluation report:** [`docs/operations/pilot_retrieval_evaluation_report.md`](docs/operations/pilot_retrieval_evaluation_report.md) — first sandbox run `pass_rate=0.6667` (imbalanced index); after [balanced rebuild](docs/operations/balanced_pilot_corpus_rebuild.md) + eval v4: **metadata_filtered fund subset 10/10**, `retrieval_activated=false`. **Decision (Step 124):** `retrieval_ready_for_sandbox_tooling_review` — sandbox tooling review may proceed; **does not** approve LangGraph, production `RAG_PROFILE`, or customer-facing retrieval. **Failure analysis:** [`docs/operations/pilot_retrieval_failure_analysis.md`](docs/operations/pilot_retrieval_failure_analysis.md).

**Embedding artifact integrity check** (aggregate output only; no vectors or transcripts):

```bash
# Mock artifacts
PYTHONPATH=. python3.11 scripts/check_embedding_artifact_integrity.py \
  artifacts/embeddings/vendor_ticket_real_pilot

# Real OpenAI artifacts
PYTHONPATH=. python3.11 scripts/check_embedding_artifact_integrity.py \
  artifacts/embeddings/vendor_ticket_real_pilot_openai
```

Reports: [mock](docs/operations/mock_embedding_artifact_integrity_report.md) · [real OpenAI](docs/operations/real_embedding_artifact_integrity_report.md)

**Real OpenAI embedding generation plan:** [`docs/operations/real_openai_embedding_generation_plan.md`](docs/operations/real_openai_embedding_generation_plan.md) — **planning only**; requires mock dry-run + artifact integrity first; future output under gitignored `artifacts/embeddings/vendor_ticket_real_pilot_openai/`; **no OpenAI calls in CI**; pgvector indexing remains blocked.

### Reviewer Sign-off Workflow

Human reviewers must explicitly approve any pilot corpus scope **before** a corpus builder exists. This is governance metadata only — not production moderation and not automatic corpus generation.

- **Doc:** [`docs/operations/reviewer_signoff_workflow.md`](docs/operations/reviewer_signoff_workflow.md)
- **Contracts:** `app/corpus_planning/reviewer_models.py`, `app/corpus_planning/reviewer_builders.py`
- **Local execution:** `scripts/create_reviewer_signoff.py`, `scripts/select_approved_room_ids.py` (`--balance-pilot` for label-balanced ~25 rooms), `scripts/validate_approved_room_ids.py` → outputs under `data/private/`
- **Checklist:** `no_raw_pii_visible`, `anonymization_verified`, `retrieval_safe`, `governance_approved`, `corpus_scope_validated` — all must pass for `decision=approved` (each via `--check`)
- **Gate:** `corpus_ready_after_signoff()` requires replay + privacy review complete, `approved` decision, full checklist pass
- **Principle:** AI cannot self-approve; room selection suggests candidates — human confirms before `build_pilot_corpus.py`

**`ticket_label`**, **`ticket_subtype`**, and **`room_id`** from the chat room are promoted into `CommerceAIState` during `normalize_request` for department-aware review routing.

## Vector Store Provider Factory

**`app/rag/vector_store_factory.py`** builds a **`VectorStore`** from configuration:

| Provider | Implementation |
|----------|----------------|
| `memory` (default) | `InMemoryVectorStore` |
| `pgvector` | `PgVectorStore` (requires `PGVECTOR_DATABASE_URL`) |

Environment: `VECTOR_STORE_PROVIDER`, `PGVECTOR_DATABASE_URL`, `PGVECTOR_TABLE`, `PGVECTOR_DIMENSIONS` (see `.env.example`).

- **Default remains `memory`**; normal **`make ci`** does not connect to Postgres.
- **Pgvector** is used only for **`semantic_pgvector_16`** or **`semantic_pgvector`** (and matching **`VECTOR_STORE_*`** / **`PGVECTOR_*`** env); all other profiles stay in-memory.

## Semantic RAG Retriever

**`app/rag/semantic_retriever.py`** wires the first **end-to-end semantic retrieval** path: **query text → `generate_embedding` → `VectorStore.search` → `RAGResult`**, using **`vector_record_to_rag_document`** for scored `RAGDocument` rows.

- **Defaults:** **`embedding_provider="mock"`** and **`InMemoryVectorStore`** (via **`build_in_memory_store_from_documents`**) keep runs **local and deterministic**; cosine similarity in the in-memory store drives ranking.
- **Interfaces:** retrieval depends on **`VectorStore`** and the embedding factory, **not** on pgvector, Pinecone, Qdrant, or vendor-specific vector SDKs.
- **`PgVectorStore`** is used when **`RAG_PROFILE`** selects a pgvector preset; the default graph path stays in-memory. **`semantic_retrieve`** stays storage-agnostic via **`VectorStore`**.
- **Tests** use **mock embeddings only** and do not call OpenAI or write to any database.

## RAG Context Injection

**`build_vendor_ticket_prompt`** in **`app/prompts/vendor_ticket.py`** appends a Persian **«اسناد و سیاست‌های بازیابی‌شده»** section built from **`RAGDocument`** rows (title, source type, optional similarity score, truncated content). The **`vendor_ticket_node`** reads **`retrieved_context["rag_documents"]`** (dicts from state), coerces them to **`RAGDocument`**, and passes them into the prompt builder so the **LLM sees policy snippets and approved response patterns** alongside ticket fields.

- **Retrieval stays provider-agnostic:** **`retrieve_context`** calls **`retrieve_for_workflow`** (default **`mock`** catalog; **`semantic`** and pgvector profiles swap store/backend without changing LangGraph topology).
- **Safety:** long document bodies are **truncated** per document in the prompt. Default CI/tests use **mock** only (no OpenAI, no Postgres). Pgvector prompt injection requires an explicit pgvector profile and local/staging setup.
- **Human approval:** drafts are still **operator-facing only** until reviewed; nothing is sent to a vendor without **human approval**.

## Retrieval Strategy Layer

**`app/rag/strategy.py`** exposes **`retrieve_for_workflow`** and **`RetrievalStrategyName`**. Workflow code (for example **`retrieve_context`**) calls **`retrieve_for_workflow`** instead of hardcoding **`retrieve_documents`** so orchestration stays decoupled from how hits are produced.

- **Strategies:** **`mock`** (default, same catalog as before), **`policy_only`** and **`approved_examples`** (filter the mock catalog with **`provider="strategy"`** metadata), and **`semantic`**, which runs **`semantic_retrieve`** when the caller passes an **explicit `VectorStore`** (typically **`InMemoryVectorStore`** built offline for tests or demos). There is **no global vector store** inside the strategy layer.
- **Default graph path:** **`retrieve_context`** reads **`RAG_STRATEGY`** / **`RAG_PROFILE`** from **`AppSettings`** (default **`mock`**). **`semantic_local`** / **`RAG_STRATEGY=semantic`** use the bootstrap **`InMemoryVectorStore`**; **`semantic_pgvector`** / **`semantic_pgvector_16`** use **`PgVectorStore`** when configured. Invalid strategy values fall back to **mock** with a **`ToolError`**.
- **Why:** swap **mock**, **filtered**, **semantic**, or future **hybrid** retrieval without editing node topology or FastAPI.
- **Observability:** **`tool_results["retrieve_for_workflow"]`** records **`strategy`**, **`count`**, and **`provider`**; the legacy **`retrieve_documents`** summary remains for compatibility.

## Runtime RAG Store Bootstrap

**`app/rag/bootstrap.py`** provides a **small, deterministic Persian corpus** (`default_vendor_ticket_documents`) and helpers to build a **fresh `InMemoryVectorStore`** (`build_default_vendor_ticket_vector_store`) and run **semantic retrieval** in one call (`retrieve_semantic_vendor_ticket_context`) using **mock embeddings** only.

- **Purpose:** local demos and scripts that need **semantic-style** ranking **without pgvector**, **without Postgres**, and **without a process-wide singleton store**—each helper builds or queries an explicit store.
- **Graph default:** **`RAG_STRATEGY`** defaults to **`mock`** so CI and local runs match earlier behavior unless you opt into **`semantic`**, **`policy_only`**, or **`approved_examples`** in **`.env`**.
- **No hidden globals:** each **`semantic`** run in the graph builds a **fresh** default corpus store (see bootstrap module); for custom corpora, callers can still build a **`VectorStore`** elsewhere and call **`retrieve_for_workflow`** directly.

## Versioned Corpus Manifest Foundation

The default vendor-ticket semantic corpus lives under **`corpus/vendor_ticket/`**: a **`manifest.json`** plus small **UTF-8 Persian** text files in **`policies/`**, **`approved_patterns/`**, and **`style_guides/`**. **`app/rag/corpus_manifest.py`** defines **`CorpusManifest`** / **`CorpusManifestDocument`** and loads them into **`RAGDocument`** rows with **deterministic list order**—no globbing, no DB, no background workers.

- **Why leave Python:** manifests and bodies are **easier to review, diff, and version** than long embedded strings, and they foreshadow **audit-friendly ingestion** without building a pipeline yet.
- **Scope today:** **filesystem only**; **`default_vendor_ticket_documents()`** reads **`manifest.json`** at runtime (same public bootstrap API as before).
- **Indexing:** offline **`make pg-index`** / **`make pg-index-16`** materialize the manifest into Postgres; the manifest remains the **source of truth** for corpus content.

## Retrieval Evaluation Foundation

**`app/rag/evaluation.py`** compares **`RAGResult`** rows to expectations. **Labeled cases** live in **`corpus/vendor_ticket/eval_cases.json`** (UTF-8 JSON: **`eval_version`**, **`workflow_type`**, **`locale`**, ordered **`cases`**). **`load_retrieval_eval_cases`** / **`load_vendor_ticket_eval_cases_from_file`** validate that file; **`default_vendor_ticket_eval_cases()`** reads the default path next to the corpus manifest—**Python is the engine, not the source of truth** for case definitions.

- **Eval engine:** no LLM calls in **`evaluation.py`**; default **`run_default_vendor_ticket_retrieval_eval()`** uses in-memory semantic retrieval (CI-safe). **`make pg-eval`** / **`make pg-compare`** exercise pgvector separately (manual/staging).
- **`eval_cases.json`** is intentionally broader than the original three-case smoke set: **15** labeled cases with short queries, conversational Persian, ambiguous phrasing, multi-document expectations, source-type mixes, and near-miss wording aligned to the vendor-ticket corpus. Staging **`pg-eval`** / **`pg-compare`** quality depends on this coverage—not on case count alone.
- **`run_default_vendor_ticket_retrieval_eval()`** still runs the default file-backed suite over **mock** semantic retrieval (CI-safe); use **`pg-eval`** for ranking-sensitive validation.
- **Ranking metrics** (per case and report averages): **Recall@K** (fraction of expected document ids found in top K), **Hit Rate** (1.0 if any expected id appears), **MRR** (reciprocal rank of the first expected hit). **`pass_rate`** remains strict case-level success (all expected ids + required source types).
- **Near-miss ranking guard** (metadata-driven): selected cases set **`near_miss_document_ids`** in **`eval_cases.json`**. A violation is recorded when a plausible-but-wrong document appears **before** the first expected hit (or at any rank if no expected hit). **`passed`** is unchanged; reports and **`pg-eval`** / **`pg-compare`** surface **`near_miss_violation_count`** and offending case IDs. Optional staging gates **`RETRIEVAL_MAX_NEAR_MISS_VIOLATIONS`** / **`RETRIEVAL_MAX_NEAR_MISS_VIOLATION_REGRESSION`** can fail promotion runs when violations exceed thresholds (see [Retrieval Quality Threshold Gates](#retrieval-quality-threshold-gates)).
- **Use case:** compare **in-memory vs pgvector** (`make pg-compare`) and future hybrid/reranked retrieval using metrics beyond binary pass/fail.
- **Use case:** evolve **`eval_version`** and cases alongside **`manifest_version`** before packaging or production **`VectorStore`** work.

## Corpus/Eval Consistency Guard

**`app/rag/consistency.py`** cross-checks **`corpus/vendor_ticket/eval_cases.json`** against **`corpus/vendor_ticket/manifest.json`**:

- every **`expected_document_id`** must exist in the manifest’s **`documents`**
- every **`required_source_type`** must be represented by the **`source_type`** of at least one of that case’s **expected** documents (not merely any row elsewhere in the manifest)

**`check_default_vendor_ticket_corpus_eval_consistency()`** loads both defaults offline; **`assert_corpus_eval_consistency`** is a strict helper for tests or CI.

- **Why:** stops **silent drift** when corpus rows are renamed, removed, or mis-typed relative to eval expectations.
- **Scope:** **deterministic, filesystem-only**—no vector DB, no OpenAI, no graph or API changes.
- **Typical use:** run (or assert) in **CI** before **packaging** the corpus or promoting pgvector staging.

## Corpus Packaging + Hash Verification

**`corpus/vendor_ticket/corpus.lock.json`** records **expected SHA-256 hashes and file sizes** for corpus assets (`manifest.json`, **`eval_cases.json`**, and **`.txt`** bodies). **`verify_corpus_against_lockfile`** compares on-disk files to that lockfile; changing corpus content requires **regenerating the lockfile intentionally** via **`write_corpus_lockfile`**.

- **`verify_corpus_integrity`**: builds a local inventory (excludes **`corpus.lock.json`** from the hashed set).
- **`verify_default_vendor_ticket_corpus_lockfile`**: fails on missing files, unexpected files, hash mismatch, or size mismatch.
- **`scripts/check_corpus_integrity.py`** runs three checks and exits **0** only when all pass:
  1. corpus integrity inventory
  2. corpus/eval consistency (`manifest.json` vs **`eval_cases.json`**)
  3. corpus lockfile verification
- **CI:** run **`python3.11 scripts/check_corpus_integrity.py`** before packaging or deploy.

Example (from repo root, with `PYTHONPATH=.` or after `pip install -e .`):

```bash
python3.11 scripts/check_corpus_integrity.py
```

To regenerate the lockfile after an approved corpus change:

```bash
PYTHONPATH=. python3.11 -c "
from app.rag.corpus_integrity import write_corpus_lockfile, default_vendor_ticket_corpus_lockfile_path
write_corpus_lockfile(
    base_dir='corpus/vendor_ticket',
    lockfile_path=default_vendor_ticket_corpus_lockfile_path(),
    corpus_name='vendor_ticket',
)
"
```

## Runtime Retrieval Strategy Configuration

**`retrieve_context`** builds a typed **`RetrievalConfig`** from **`AppSettings`** via **`build_retrieval_config_from_settings`** (see **`app/rag/config.py`**). Defaults remain **`mock`** strategy and **`top_k=5`**.

### Profile presets (optional)

Set **`RAG_PROFILE`** to select a named preset instead of tuning each field manually:

| Profile | Strategy | Embeddings |
|---------|----------|------------|
| **`mock`** (preset) | `mock` | mock |
| **`policy_only`** | `policy_only` | mock |
| **`approved_examples`** | `approved_examples` | mock |
| **`semantic_local`** | `semantic` (in-memory bootstrap store) | mock |
| **`semantic_pgvector_16`** | `semantic` via **`PgVectorStore`** (`rag_vector_records_16`, mock 16-D) | mock (fixed) |
| **`semantic_pgvector`** | `semantic` via **`PgVectorStore`** (`rag_vector_records`, 1536-D) | from **`EMBEDDING_*`** settings |
| **`custom`** | uses **`RAG_STRATEGY`**, **`RAG_TOP_K`**, **`EMBEDDING_*`** |

**`semantic_pgvector_16`** — local mock-only smoke ([PgVector Retrieval Profile Smoke Test](#pgvector-retrieval-profile-smoke-test)). **`semantic_pgvector`** — staging 1536-D ([1536-D PgVector Staging Profile](#1536-d-pgvector-staging-profile)). Neither indexes during requests; **`database_url`** is never in **`retrieval_summary`**.

```env
# Local 16-D mock
RAG_PROFILE=semantic_pgvector_16
PGVECTOR_TABLE=rag_vector_records_16
PGVECTOR_DIMENSIONS=16

# Staging 1536-D (index + retrieve with same EMBEDDING_* )
RAG_PROFILE=semantic_pgvector
PGVECTOR_TABLE=rag_vector_records
PGVECTOR_DIMENSIONS=1536
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
```

Example:

```env
RAG_PROFILE=semantic_local
```

When **`RAG_PROFILE`** is empty, individual env vars below apply (unchanged behavior).

**Validation:** **`RAG_PROFILE`** is checked when **`AppSettings`** loads (startup / first **`get_settings()`**). Unknown profile names raise a **Pydantic validation error** immediately. **`RAG_STRATEGY`** is **not** validated at settings load—invalid values still produce a **`ToolError`** in **`retrieve_context`** and fall back to **`mock`** (useful with **`RAG_PROFILE=custom`** for manual tuning).

**Recommended use:**

- Presets: set **`RAG_PROFILE`** (`mock`, `policy_only`, `approved_examples`, `semantic_local`, `semantic_pgvector_16`, `semantic_pgvector` for pgvector smoke/staging).
- Manual tuning: **`RAG_PROFILE=custom`** plus **`RAG_STRATEGY`**, **`RAG_TOP_K`**, and **`EMBEDDING_*`**.

Environment variables (mapped to **`AppSettings`**):

- **`RAG_PROFILE`** → **`rag_profile`**: optional preset (see table above); validated at settings load.
- **`RAG_STRATEGY`** → **`rag_strategy`**: controls how **`retrieve_context`** loads **`rag_documents`** (used when no profile, or with **`custom`**); runtime fallback only.
- **`RAG_TOP_K`** → **`rag_top_k`**: number of documents requested during workflow retrieval (default **5**; used when no profile, or with **`custom`**).
- **`EMBEDDING_PROVIDER`** / **`EMBEDDING_MODEL`**: passed through to semantic retrieval and embedding calls.

Strategy values:

- **`mock`** (default): deterministic mock catalog (**unchanged** from earlier MVP steps).
- **`semantic`**: cosine search over a **new in-memory store** built from **`default_vendor_ticket_documents`**, using **`embedding_provider`** / **`embedding_model`** (keep **`mock`** for no network).
- **`policy_only`** / **`approved_examples`**: filter strategies over the mock catalog (**`provider="strategy"`** in **`RAGResult`**).
- **Unknown values:** a **`ToolError`** is appended and retrieval **falls back to `mock`** so the node does not raise.
- **Pgvector:** use **`RAG_PROFILE=semantic_pgvector`** or **`semantic_pgvector_16`** (not the default). Validate with **`make pg-eval`** and **`make pg-compare`** before wider rollout—see [Staging Retrieval Evaluation Runbook](#staging-retrieval-evaluation-runbook).

## Retrieval Config Observability

Each workflow run records **safe** retrieval metadata (no API keys or secrets):

- **`POST /run-vendor-ticket`** responses include **`retrieval_summary`**: requested/effective strategy, provider, document count, **`top_k`**, embedding provider/model, and optional **`rag_profile`**.
- **`audit_log`** entries for **`retrieve_context`** include **`requested_rag_strategy`**, **`effective_rag_strategy`**, **`rag_provider`**, **`rag_top_k`**, embedding fields, and **`rag_document_count`**.
- **`tool_results.retrieve_for_workflow`** mirrors the same fields (legacy **`strategy`** / **`count`** / **`provider`** keys remain).

Use this to debug **mock vs semantic** runs and **invalid-strategy fallbacks** (requested strategy shows the env value; effective strategy shows **`mock`** after fallback). Full RAG document bodies are **not** exposed in the API response.

## Manual Smoke Test: Semantic RAG Vendor Ticket

This smoke test verifies that the **vendor ticket** workflow uses **semantic RAG** through runtime configuration:

**FastAPI → LangGraph → `retrieve_context` → `RAG_STRATEGY=semantic` → runtime in-memory vector store (bootstrap corpus) → prompt injection → LLM → human approval.**

This section exercises **in-memory semantic** retrieval (**`RAG_STRATEGY=semantic`** or **`RAG_PROFILE=semantic_local`**): no Postgres. For **pgvector** smoke, use [PgVector Retrieval Profile Smoke Test](#pgvector-retrieval-profile-smoke-test) instead. Pinecone/Qdrant/Weaviate are out of scope.

Recommended order: **0 → 1 → 2 → 3 → 4 → 5 → 6** (optional LangSmith: step 3).

### 0. Preflight configuration check

From the project root, validate **local** settings **before** installing or starting the server:

```bash
make config-check
```

This loads **`AppSettings`** from your **`.env`** (offline): catches invalid **`RAG_PROFILE`** early, does **not** call OpenAI, and does **not** print secrets.

If **`config-check` fails:** fix **`.env`**, rerun **`make config-check`**, then continue—do **not** start **`uvicorn`** until it passes.

### 1. Purpose

Confirm end-to-end wiring: **`retrieve_context`** builds a fresh default **`InMemoryVectorStore`**, runs **`retrieve_for_workflow`** with **`SEMANTIC`**, injects scored **`rag_documents`** into **`build_vendor_ticket_prompt`**, and still ends in **awaiting approval** with **no outbound send**.

### 2. Install and configure

Install dependencies:

```bash
cd inchand_ai
pip install -e ".[dev]"
```

Ensure **`.env`** includes (at minimum for semantic RAG with mock embeddings):

  ```env
  RAG_STRATEGY=semantic
  RAG_TOP_K=5
  EMBEDDING_PROVIDER=mock
  EMBEDDING_MODEL=mock-embedding-small
  ```

- **LLM** can be either:

  ```env
  LLM_PROVIDER=mock
  LLM_MODEL=mock-vendor-ticket-drafter
  ```

  or, if you are manually testing **real** generation (optional; requires a key in the environment, never in git):

  ```env
  LLM_PROVIDER=openai
  LLM_MODEL=gpt-4.1-mini
  OPENAI_API_KEY=your_key
  ```

Re-run preflight after editing **`.env`**:

```bash
make config-check
```

### 3. Optional LangSmith

```env
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com
LANGSMITH_API_KEY=your_langsmith_key
LANGSMITH_PROJECT=inchand-ai-commerce-mvp
```

### 4. Export environment and start FastAPI

From the project root:

```bash
set -a && source .env && set +a && PYTHONPATH=. python3.11 -m uvicorn app.api.main:app --reload --host 127.0.0.1 --port 8000
```

### 5. Trigger the workflow

```bash
curl -s -X POST "http://127.0.0.1:8000/run-vendor-ticket" \
  -H "Content-Type: application/json" \
  -d '{"user_input":"سلام، تسویه من با فاکتور فروش هم‌خوان نیست و نیاز به بررسی مالی دارم.","ticket_id":"t-semantic-rag-smoke-001"}' \
  | python3.11 -m json.tool
```

**Optional helper:** with the server running and **`RAG_STRATEGY=semantic`** already exported (e.g. after `set -a && source .env && set +a` in the same shell as the server):

```bash
make smoke-semantic
# or: ./scripts/smoke_semantic_rag_vendor_ticket.sh
```

The script runs **`make config-check`**-equivalent preflight (**`scripts/check_config.py`**) before **`curl`**—no API keys printed, no **`.env`** auto-sourced. **`make config-check`** is still recommended before **`uvicorn`**. The script **fails fast** if preflight or **`RAG_STRATEGY`** checks fail. Override the base URL with **`BASE_URL`** if needed.

### 6. Inspect the response

Parse the JSON and confirm:

- **`workflow_type`** is **`"vendor_ticket"`**
- **`workflow_status`** is **`"awaiting_approval"`** on the successful path
- **`approval_status`** is **`"required"`**
- **`human_approval_required`** is **`true`**
- **`errors`** is **`[]`**
- **`tool_results.retrieve_for_workflow.strategy`** is **`"semantic"`**
- **`tool_results.retrieve_for_workflow.provider`** is **`"semantic"`**
- **`specialist_output.evidence`** contains a line starting with **`rag_document_count=`**
- **`specialist_output.evidence`** contains a line starting with **`rag_sources=`**
- **`retrieved_context.rag_documents`** (or **`rag_sources`**) should include **semantically relevant** support/policy snippets from the bootstrap corpus (titles and `source_type` such as **`policy`**, **`approved_pattern`**, **`style_guide`**)
- When **`LLM_PROVIDER=openai`**, the injected RAG block in the prompt should **influence draft quality** versus running without that context; with **`mock`**, the draft remains deterministic placeholder text but the retrieval path is still validated

### 7. LangSmith checks (if enabled)

- In the LangSmith UI, open the project from **`LANGSMITH_PROJECT`**.
- Find a run named **`run_vendor_ticket_demo`**; confirm there is **no crash** and the trace completes.
- Cross-check HTTP JSON **`tool_results.retrieve_for_workflow`** for **`strategy`** / **`provider`** **`semantic`** and **`specialist_output.evidence`** for RAG counts/sources so the run reflects the **semantic RAG** path.

### 8. Safety

- Do **not** use raw **production** ticket exports until **anonymization** and policy sign-off.
- Do **not** send the generated draft to a **real vendor** inbox or ticket system from this smoke test.
- **Human approval remains required** before any real send in product flows.

## Manual Smoke Test: OpenAI Vendor Ticket Draft

This is a **manual, local-only** check that the FastAPI → LangGraph → `generate_text` OpenAI path returns a real draft while **human approval** still gates anything outbound. **Do not** run against raw production ticket exports; **do not** send the model output to a real vendor from this smoke path.

Recommended order: **0 → 1 → 2 → 3 → 4 → 5** (optional LangSmith: step 6).

### 0. Preflight configuration check

From the project root:

```bash
make config-check
```

Validates **local** **`.env`** / **`AppSettings`** before startup (invalid **`RAG_PROFILE`** fails fast; no OpenAI calls; no secrets printed).

If **`config-check` fails:** fix **`.env`**, rerun **`make config-check`**, then continue—only start **`uvicorn`** after it passes.

### 1. Preconditions

- You have a **valid OpenAI API key** (never commit it; keep it in `.env` or your shell only).
- Your **`.env`** (or exported environment) includes at least:

  ```env
  LLM_PROVIDER=openai
  LLM_MODEL=gpt-4.1-mini
  OPENAI_API_KEY=your_key
  ```

- **LangSmith** (optional) can be enabled for the same run, for example:

  ```env
  LANGSMITH_TRACING=true
  LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com
  LANGSMITH_API_KEY=your_langsmith_key
  LANGSMITH_PROJECT=inchand-ai-commerce-mvp
  ```

### 2. Install dependencies

```bash
cd inchand_ai
pip install -e ".[dev]"
```

Re-run **`make config-check`** after changing **`.env`**.

### 3. Export environment and start FastAPI

From the project root (so `app` imports resolve):

```bash
set -a && source .env && set +a && PYTHONPATH=. python3.11 -m uvicorn app.api.main:app --reload --host 127.0.0.1 --port 8000
```

### 4. Trigger the workflow

```bash
curl -s -X POST "http://127.0.0.1:8000/run-vendor-ticket" \
  -H "Content-Type: application/json" \
  -d '{"user_input":"سلام، وضعیت تسویه من با فاکتور هم‌خوان نیست. لطفاً بررسی کنید.","ticket_id":"t-openai-smoke-001"}' | python3.11 -m json.tool
```

**Optional helper:** with the server already running and **`OPENAI_API_KEY` exported** in your shell (after sourcing `.env` in that same shell), you can run:

```bash
make smoke-openai
# or: ./scripts/smoke_openai_vendor_ticket.sh
```

The script enforces the same offline config preflight before **`curl`** (see semantic smoke above). **`make config-check`** before **`uvicorn`** is still recommended. The script **does not** embed keys; it fails fast if preflight fails or **`OPENAI_API_KEY`** is unset. Override the base URL with **`BASE_URL`** if needed.

### 5. Inspect the response

Parse the JSON and confirm:

- `workflow_type` is **`"vendor_ticket"`**
- `workflow_status` is **`"awaiting_approval"`**
- `approval_status` is **`"required"`**
- `human_approval_required` is **`true`**
- `specialist_output.draft_response` reads like a **real Persian support draft** (not the mock bracket line that starts with **`[خروجی آزمایشی قطعی`** when `LLM_PROVIDER=mock`)
- `specialist_output.llm_provider` is **`"openai"`**
- `specialist_output.llm_model` matches your **`LLM_MODEL`** (e.g. `gpt-4.1-mini`)
- `errors` is **`[]`**

### 6. LangSmith check (if enabled)

- In the LangSmith UI, open the project from **`LANGSMITH_PROJECT`**.
- Find a run named **`run_vendor_ticket_demo`**; confirm tags/metadata as in the [LangSmith Observability](#langsmith-observability) section.
- In the HTTP JSON body, confirm **`specialist_output.llm_provider`** is **`openai`** so you know the request used the OpenAI adapter (not mock).

### 7. Safety notes

- Do **not** use raw production ticket exports until **anonymization** and policy sign-off.
- Do **not** post the generated draft to a real vendor inbox or ticket system from this smoke test.
- This path is for **local operator verification** only; **human approval remains required** before any real send in product flows.

## Principles (MVP)

- Mock tools and fixtures before real integrations.
- LLM calls are opt-in via `LLM_PROVIDER` (`mock` by default); use OpenAI only with approved keys and data handling.
- Default path: mock tools, in-memory/mock RAG, no Postgres in CI. Pgvector RAG is opt-in, staging-oriented, and manually evaluated—not the production default.
- No ticket reply sending or other destructive side effects in the MVP path.
