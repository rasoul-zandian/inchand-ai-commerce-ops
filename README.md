# Inchand AI — Commerce Operations Copilot (MVP)

Production-oriented skeleton for the **Vendor Ticket Assistant** workflow: a controlled LangGraph pipeline with shared state, mock tools first, and no destructive or outbound actions in early phases.

This repository is built **step by step**. Each step adds only the agreed files; graph code, nodes, tools, and the FastAPI application come in later steps.

## Tech stack (target)

- Python 3.11+
- LangGraph / LangChain
- Pydantic v2
- FastAPI
- pytest

Planned integrations (not wired in the skeleton steps yet): LangSmith, PostgreSQL, pgvector.

## Layout

- `app/graph`, `app/nodes`, `app/tools` — workflow and orchestration (added incrementally).
- `app/state`, `app/schemas` — shared state and validation.
- `app/services`, `app/prompts`, `app/rag`, `app/memory` — services and retrieval/memory placeholders.
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

## Manual Smoke Test: OpenAI Vendor Ticket Draft

This is a **manual, local-only** check that the FastAPI → LangGraph → `generate_text` OpenAI path returns a real draft while **human approval** still gates anything outbound. **Do not** run against raw production ticket exports; **do not** send the model output to a real vendor from this smoke path.

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

### 3. Run FastAPI

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
./scripts/smoke_openai_vendor_ticket.sh
```

The script **does not** embed keys; it fails fast if `OPENAI_API_KEY` is unset and calls the same `curl` + `json.tool` pipeline. Override the base URL with `BASE_URL` if needed.

### 5. Expected response checks

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
- No real database or RAG until explicitly introduced.
- No ticket reply sending or other destructive side effects in the MVP path.
