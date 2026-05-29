"""Check policy fact extraction against sandbox knowledge retrieval (prep only)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.knowledge.knowledge_embedding_index import assert_safe_knowledge_output
from app.knowledge.knowledge_retrieval_smoke import SETTLEMENT_QUERY
from app.knowledge.policy_fact_extraction import (
    SETTLEMENT_CANONICAL_DRAFT_ANSWER,
    build_policy_facts_prompt_block,
    is_settlement_timing_policy_question,
    select_policy_facts_for_draft,
    settlement_fact_present,
)
from app.operator_console.knowledge_hints import KnowledgeHint

DEFAULT_POLICY_CHECK_SUMMARY_JSON = Path("reports/policy_fact_extraction_check_summary.json")
DEFAULT_POLICY_CHECK_REPORT_MD = Path("reports/policy_fact_extraction_check_report.md")


@dataclass(frozen=True)
class PolicyFactExtractionCheckResult:
    status: str
    settlement_query: str
    facts_count: int
    settlement_fact_present: bool
    canonical_fact_reachable: bool
    prompt_block_chars: int
    document_types: tuple[str, ...]
    section_titles: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "settlement_query": self.settlement_query,
            "facts_count": self.facts_count,
            "settlement_fact_present": self.settlement_fact_present,
            "canonical_fact_reachable": self.canonical_fact_reachable,
            "prompt_block_chars": self.prompt_block_chars,
            "document_types": list(self.document_types),
            "section_titles": list(self.section_titles),
        }


def retrieval_hits_to_hints(hits: list[dict[str, Any]]) -> list[KnowledgeHint]:
    hints: list[KnowledgeHint] = []
    for hit in hits:
        snippet = str(hit.get("text_snippet") or "").strip()
        if not snippet:
            continue
        hints.append(
            KnowledgeHint(
                document_type=str(hit.get("document_type") or ""),
                section_title=str(hit.get("section_title") or ""),
                source_lane=str(hit.get("source_lane") or "official_policy"),
                priority_rank=int(hit.get("priority_rank") or 0),
                snippet=snippet,
                score=float(hit.get("score") or 0.0),
            ),
        )
    return hints


def run_policy_fact_extraction_check(
    *,
    namespace: str,
    index_version: str,
    database_url: str,
    table_name: str = "rag_vector_records",
    provider: str = "mock",
    confirm_real_openai: bool = False,
    query_fn: Any | None = None,
) -> PolicyFactExtractionCheckResult:
    """Retrieve settlement hints and verify policy facts for draft prompts."""
    from app.knowledge.knowledge_embedding_index import query_knowledge_pgvector

    _query = query_fn or query_knowledge_pgvector
    hits = _query(
        SETTLEMENT_QUERY,
        namespace=namespace,
        index_version=index_version,
        database_url=database_url,
        table_name=table_name,
        provider=provider,
        confirm_real_openai=confirm_real_openai,
        top_k=5,
    )
    hints = retrieval_hits_to_hints(hits)
    selected = select_policy_facts_for_draft(
        detected_intent="settlement_timing",
        suggested_action=None,
        seller_text=SETTLEMENT_QUERY,
        hints=hints,
    )
    prompt_block = build_policy_facts_prompt_block(
        detected_intent="settlement_timing",
        suggested_action=None,
        seller_text=SETTLEMENT_QUERY,
        hints=hints,
        conceptual_intent_fa="سوال زمان تسویه",
    )
    has_settlement = settlement_fact_present(selected)
    canonical_ok = SETTLEMENT_CANONICAL_DRAFT_ANSWER[:40] in prompt_block or has_settlement
    timing_question = is_settlement_timing_policy_question(SETTLEMENT_QUERY)
    status = "passed" if has_settlement and timing_question and canonical_ok else "failed"
    return PolicyFactExtractionCheckResult(
        status=status,
        settlement_query=SETTLEMENT_QUERY,
        facts_count=len(selected),
        settlement_fact_present=has_settlement,
        canonical_fact_reachable=canonical_ok,
        prompt_block_chars=len(prompt_block),
        document_types=tuple(sorted({fact.document_type for fact in selected})),
        section_titles=tuple(fact.section_title for fact in selected),
    )


def render_policy_check_report_markdown(result: PolicyFactExtractionCheckResult) -> str:
    return "\n".join(
        [
            "# Policy fact extraction check",
            "",
            f"**Status:** {result.status}",
            "",
            f"- **settlement_query:** {result.settlement_query}",
            f"- **facts_count:** {result.facts_count}",
            f"- **settlement_fact_present:** {result.settlement_fact_present}",
            f"- **canonical_fact_reachable:** {result.canonical_fact_reachable}",
            f"- **prompt_block_chars:** {result.prompt_block_chars}",
            f"- **document_types:** {', '.join(result.document_types) or '—'}",
            "",
            "_Prompt block text is not written to this report (counts/metadata only)._",
            "",
        ],
    )


def write_policy_fact_extraction_check_reports(
    result: PolicyFactExtractionCheckResult,
    *,
    summary_json: Path = DEFAULT_POLICY_CHECK_SUMMARY_JSON,
    report_md: Path = DEFAULT_POLICY_CHECK_REPORT_MD,
    overwrite: bool = False,
) -> None:
    for path in (summary_json, report_md):
        if path.exists() and not overwrite:
            raise FileExistsError(f"output exists: {path} (use --overwrite)")
    payload = result.to_json_dict()
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    assert_safe_knowledge_output(text)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(text + "\n", encoding="utf-8")
    markdown = render_policy_check_report_markdown(result)
    assert_safe_knowledge_output(markdown)
    report_md.write_text(markdown, encoding="utf-8")
