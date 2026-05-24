"""Application settings loaded from environment variables and optional `.env` file."""

from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.rag.config import RetrievalProfileName


class AppSettings(BaseSettings):
    """Runtime configuration; secrets must not be committed (use `.env` locally, never in git)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Inchand AI Commerce Operations Copilot"
    environment: str = "development"
    langsmith_tracing: bool = False
    langsmith_tracing_enabled: bool = Field(
        default=False,
        description=(
            "When true, agentic sandbox CLI may enable LangSmith tracing "
            "(LANGCHAIN_TRACING_V2). Default false; requires API key at runtime."
        ),
    )
    langsmith_api_key: str | None = None
    langsmith_project: str = Field(
        default="inchand-agentic-sandbox",
        description="LangSmith / LANGCHAIN_PROJECT name for sandbox and local tracing.",
    )
    llm_provider: str = "mock"
    llm_model: str = "mock-vendor-ticket-drafter"
    openai_api_key: str | None = None
    embedding_provider: str = "mock"
    embedding_model: str = "mock-embedding-small"
    rag_strategy: str = Field(
        default="mock",
        description=(
            "RAG retrieval strategy for workflow context loading. "
            "Valid values: mock (default catalog), semantic (local in-memory bootstrap store), "
            "policy_only, approved_examples. Unknown values fall back to mock at runtime."
        ),
    )
    rag_top_k: int = Field(
        default=5,
        ge=1,
        description="Maximum RAG documents requested during workflow retrieval.",
    )
    rag_profile: str | None = Field(
        default=None,
        description=(
            "Optional retrieval profile preset (mock, policy_only, approved_examples, "
            "semantic_local, semantic_pgvector_16, semantic_pgvector, custom). "
            "When set, controls "
            "strategy/top_k/embedding fields; "
            "custom uses rag_strategy/rag_top_k/embedding_* overrides."
        ),
    )
    vector_store_provider: str = Field(
        default="memory",
        description=(
            "Vector store backend: memory (default) or pgvector "
            "(used when RAG_PROFILE is a pgvector preset)."
        ),
    )
    pgvector_database_url: str | None = Field(
        default=None,
        description="Postgres URL for PgVectorStore when vector_store_provider=pgvector.",
        repr=False,
    )
    pgvector_table: str = Field(
        default="rag_vector_records",
        description="Table name for PgVectorStore when vector_store_provider=pgvector.",
    )
    pgvector_dimensions: int = Field(
        default=1536,
        ge=1,
        description="Embedding dimensions for PgVectorStore (must match table VECTOR width).",
    )
    review_action_adapter: str = Field(
        default="noop",
        description=(
            "Operator review action persistence adapter: noop (default, no storage) "
            "or memory (in-process test/dev only)."
        ),
    )
    langgraph_sandbox_retrieval_enabled: bool = Field(
        default=False,
        description=(
            "When true, run sandbox_retrieve_pilot_shadow in the vendor ticket graph "
            "(shadow metadata only; does not change draft/final responses). Default false."
        ),
    )
    vendor_ticket_ai_assist_shadow_enabled: bool = Field(
        default=False,
        description=(
            "When true, run vendor_ticket_ai_assist_shadow after sandbox retrieval "
            "(HITL-only assist metadata; does not change draft/final responses). Default false."
        ),
    )
    live_feed_enabled: bool = Field(
        default=False,
        description=(
            "When true, operator console may use live JSONL feed polling "
            "(read-only; no production writes). Default false."
        ),
    )
    live_feed_poll_interval_seconds: int = Field(
        default=30,
        ge=5,
        description="Streamlit live mode auto-refresh interval in seconds.",
    )
    live_feed_max_batch: int = Field(
        default=20,
        ge=1,
        le=200,
        description="Maximum live tickets processed per poll/refresh.",
    )
    live_feed_source_path: str = Field(
        default="data/private/live_vendor_tickets.jsonl",
        description="UTF-8 JSONL path for incoming vendor tickets (append-only local feed).",
    )
    live_feed_checkpoint_path: str = Field(
        default="reports/live_feed_checkpoint.json",
        description="Local JSON checkpoint for incremental live feed polling.",
    )
    allow_raw_pii_internal_pilot: bool = Field(
        default=True,
        description=(
            "When true (default), live feed contract validation allows raw phone/IBAN/email/card "
            "identifiers in internal-only pilot feeds for extraction evaluation. "
            "Set false for strict redaction enforcement in future production feeds."
        ),
    )
    knowledge_hints_enabled: bool = Field(
        default=False,
        description=(
            "When true, operator console may fetch read-only official policy hints "
            "via sandbox knowledge retrieval (no draft/final use). Default false."
        ),
    )
    knowledge_retrieval_namespace: str = Field(
        default="knowledge_operations_sandbox",
        description="Sandbox namespace for operator knowledge hints only.",
    )
    knowledge_retrieval_index_version: str = Field(
        default="knowledge_v1_openai",
        description="Sandbox knowledge index version (must start with knowledge_v).",
    )
    knowledge_hints_top_k: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Max official policy hints shown per ticket in operator console.",
    )
    operator_first_vendor_only: bool = Field(
        default=True,
        description=(
            "When true, operator console lists only rooms where the first non-internal "
            "message is from seller/vendor (first-turn seller-initiated calibration)."
        ),
    )
    operator_draft_preview_enabled: bool = Field(
        default=False,
        description=(
            "When true, operator console may load offline draft suggestions JSONL "
            "for internal preview (not sent to customers)."
        ),
    )
    operator_draft_generation_enabled: bool = Field(
        default=False,
        description=(
            "When true, operator console may regenerate drafts via OpenAI into "
            "Streamlit session_state only (no DB/JSONL persistence)."
        ),
    )
    operator_agentic_sandbox_preview_enabled: bool = Field(
        default=False,
        description=(
            "When true, operator console may run the agentic sandbox LangGraph preview "
            "per ticket (session-only; no execution/send)."
        ),
    )
    operator_agentic_sandbox_provider: str = Field(
        default="mock",
        description="LLM provider for operator-console agentic sandbox preview (mock or openai).",
    )
    operator_agentic_sandbox_knowledge_hints_enabled: bool = Field(
        default=True,
        description=(
            "When true, agentic sandbox preview runs with sandbox knowledge hints enabled "
            "(metadata only in UI; no raw snippets)."
        ),
    )
    operator_agentic_assisted_mode_enabled: bool = Field(
        default=False,
        description=(
            "When true, operator console may run operator-assisted agentic mode "
            "(structured HITL review package; session-only; no execution/send)."
        ),
    )
    operator_agentic_assisted_provider: str = Field(
        default="mock",
        description="LLM provider for operator-assisted agentic mode (mock or openai).",
    )
    operator_agentic_assisted_knowledge_hints_enabled: bool = Field(
        default=True,
        description=(
            "When true, operator-assisted agentic mode runs with knowledge hints enabled "
            "(metadata only in UI; no raw snippets)."
        ),
    )
    operator_agentic_assisted_require_graduation_ready: bool = Field(
        default=True,
        description=(
            "When true, operator-assisted agentic mode requires graduation summary "
            "overall_status=ready_for_operator_assisted_phase before running."
        ),
    )
    operator_draft_suggestions_path: str = Field(
        default="reports/offline_draft_suggestions_first_turn_v1.jsonl",
        description="Offline draft suggestions JSONL for operator console preview.",
    )
    operator_draft_model: str = Field(
        default="gpt-4o-mini",
        description="OpenAI model for operator-console session draft regeneration.",
    )
    operator_draft_max_chars: int = Field(
        default=700,
        ge=100,
        le=1200,
        description="Max characters for operator-console regenerated drafts.",
    )
    openai_draft_model: str = Field(
        default="gpt-4o-mini",
        description="OpenAI model for agentic sandbox / assisted draft generation pilot.",
    )
    openai_draft_temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Sampling temperature for OpenAI draft generation (pilot).",
    )
    openai_draft_max_tokens: int = Field(
        default=256,
        ge=64,
        le=1024,
        description="Max completion tokens for OpenAI draft generation (pilot).",
    )
    show_gold_reply_in_console: bool = Field(
        default=False,
        description=(
            "When true, allow showing gold human replies in console (evaluation only). "
            "Default false."
        ),
    )
    show_full_iban_in_operator_console: bool = Field(
        default=True,
        description=(
            "When true, operator console shows full normalized Sheba/IBAN for internal "
            "calibration review. Set false to mask in UI (future production/HITL rollout)."
        ),
    )
    draft_generation_mode: str = Field(
        default="first_turn_only",
        description=(
            "Draft prompt isolation mode: first_turn_only (default; initial seller issue only) "
            "or live_thread_context (deferred; not used in production paths yet)."
        ),
    )
    draft_style: str = Field(
        default="operational_short",
        description="Draft reply style preset (operational_short: 1–2 short sentences).",
    )
    draft_max_sentences: int = Field(
        default=2,
        ge=1,
        le=4,
        description="Max sentences for operational_short draft validation.",
    )
    draft_target_max_chars: int = Field(
        default=180,
        ge=80,
        le=400,
        description="Target max characters for operational_short drafts.",
    )
    draft_hard_max_chars: int = Field(
        default=300,
        ge=120,
        le=600,
        description="Hard max characters for operational_short drafts.",
    )
    policy_draft_max_sentences: int = Field(
        default=4,
        ge=2,
        le=6,
        description="Max sentences for policy_explanation draft validation.",
    )
    policy_draft_target_max_chars: int = Field(
        default=600,
        ge=300,
        le=900,
        description="Target max characters for policy_explanation drafts.",
    )
    policy_draft_hard_max_chars: int = Field(
        default=700,
        ge=400,
        le=1000,
        description="Hard max characters for policy_explanation drafts.",
    )

    @field_validator("review_action_adapter", mode="before")
    @classmethod
    def _normalize_review_action_adapter(cls, value: Any) -> str:
        if value is None:
            return "noop"
        if not isinstance(value, str):
            return value
        return value.strip().lower() or "noop"

    @field_validator("pgvector_database_url", mode="before")
    @classmethod
    def _empty_pgvector_url_to_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("rag_profile", mode="before")
    @classmethod
    def normalize_and_validate_rag_profile(cls, value: Any) -> str | None:
        """Normalize empty profile to None; validate known presets at settings load."""
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower()
        if not normalized:
            return None
        try:
            RetrievalProfileName(normalized)
        except ValueError as exc:
            allowed = ", ".join(profile.value for profile in RetrievalProfileName)
            raise ValueError(f"Invalid RAG_PROFILE {value!r}; allowed values: {allowed}") from exc
        return normalized


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return cached settings.

    Call ``get_settings.cache_clear()`` in tests when overriding environment.
    """
    return AppSettings()
