"""Post-index retrieval smoke tests for operational knowledge (sandbox only)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.knowledge.knowledge_embedding_index import (
    assert_safe_knowledge_output,
    query_knowledge_pgvector,
)
from app.knowledge.knowledge_models import KnowledgeDocumentType

DEFAULT_SMOKE_SUMMARY_JSON = Path("reports/knowledge_retrieval_smoke_summary.json")
DEFAULT_SMOKE_REPORT_MD = Path("reports/knowledge_retrieval_smoke_report.md")

SETTLEMENT_QUERY = "بعد از خرید کالا توسط مشتری چند روز بعد می‌توانم تسویه کنم؟"
SETTLEMENT_BANK_QUERY = "برای تسویه حساب شماره حساب یا شبا باید مربوط به کدام بانک باشد؟"

_PRODUCT_QUERY = "زمان تایید و انتشار محصول چقدر است؟"
_RETURN_QUERY = "شرایط مرجوعی و بازگشت وجه چیست؟"


@dataclass(frozen=True)
class KnowledgeSmokeCaseResult:
    name: str
    query: str
    passed: bool
    required_document_types: tuple[str, ...]
    matched_document_types: tuple[str, ...]
    top_section_titles: tuple[str, ...]
    errors: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "query": self.query,
            "passed": self.passed,
            "required_document_types": list(self.required_document_types),
            "matched_document_types": list(self.matched_document_types),
            "top_section_titles": list(self.top_section_titles),
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class KnowledgeRetrievalSmokeResult:
    status: str
    cases: tuple[KnowledgeSmokeCaseResult, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "case_count": len(self.cases),
            "passed_count": sum(1 for case in self.cases if case.passed),
            "cases": [case.to_json_dict() for case in self.cases],
        }


def _document_types(hits: list[dict[str, Any]]) -> set[str]:
    return {str(hit.get("document_type") or "") for hit in hits if hit.get("document_type")}


def _combined_snippet_text(hits: list[dict[str, Any]]) -> str:
    return "\n".join(str(hit.get("text_snippet") or "") for hit in hits)


def evaluate_settlement_bank_smoke(hits: list[dict[str, Any]]) -> KnowledgeSmokeCaseResult:
    errors: list[str] = []
    doc_types = _document_types(hits)
    if KnowledgeDocumentType.SETTLEMENT_RULES.value not in doc_types:
        errors.append("missing_document_type:settlement_rules")

    combined = _combined_snippet_text(hits)
    if "بانک سامان" not in combined:
        errors.append("missing_marker:saman_bank")
    if "بانک مرکزی" not in combined:
        errors.append("missing_marker:central_bank")
    if "تسویه" not in combined and "تسویه‌حساب" not in combined:
        errors.append("missing_marker:settlement_accounts")

    sections = tuple(str(hit.get("section_title") or "") for hit in hits[:5])
    return KnowledgeSmokeCaseResult(
        name="settlement_bank",
        query=SETTLEMENT_BANK_QUERY,
        passed=not errors,
        required_document_types=(KnowledgeDocumentType.SETTLEMENT_RULES.value,),
        matched_document_types=tuple(sorted(doc_types)),
        top_section_titles=sections,
        errors=tuple(errors),
    )


def evaluate_settlement_smoke(hits: list[dict[str, Any]]) -> KnowledgeSmokeCaseResult:
    errors: list[str] = []
    doc_types = _document_types(hits)
    if KnowledgeDocumentType.SETTLEMENT_RULES.value not in doc_types:
        errors.append("missing_document_type:settlement_rules")

    combined = _combined_snippet_text(hits)
    if "کیف پول" not in combined and "بلاک" not in combined:
        errors.append("missing_marker:wallet_block")
    if "۳ روز" not in combined and "3 روز" not in combined:
        errors.append("missing_marker:three_days_after_finalization")
    if "اولین" not in combined and "بازه" not in combined:
        errors.append("missing_marker:first_settlement_window")

    sections = tuple(str(hit.get("section_title") or "") for hit in hits[:5])
    return KnowledgeSmokeCaseResult(
        name="settlement_timing",
        query=SETTLEMENT_QUERY,
        passed=not errors,
        required_document_types=(KnowledgeDocumentType.SETTLEMENT_RULES.value,),
        matched_document_types=tuple(sorted(doc_types)),
        top_section_titles=sections,
        errors=tuple(errors),
    )


def evaluate_document_type_smoke(
    *,
    name: str,
    query: str,
    hits: list[dict[str, Any]],
    required_any: tuple[str, ...],
) -> KnowledgeSmokeCaseResult:
    doc_types = _document_types(hits)
    matched = tuple(sorted(doc_types & set(required_any)))
    errors: list[str] = []
    if not matched:
        errors.append(f"missing_any_of:{','.join(required_any)}")
    sections = tuple(str(hit.get("section_title") or "") for hit in hits[:5])
    return KnowledgeSmokeCaseResult(
        name=name,
        query=query,
        passed=not errors,
        required_document_types=required_any,
        matched_document_types=matched,
        top_section_titles=sections,
        errors=tuple(errors),
    )


def run_knowledge_retrieval_smoke(
    *,
    namespace: str,
    index_version: str,
    database_url: str,
    table_name: str = "rag_vector_records",
    provider: str = "mock",
    confirm_real_openai: bool = False,
    top_k: int = 5,
    query_fn: Any | None = None,
) -> KnowledgeRetrievalSmokeResult:
    """Run required retrieval smoke queries against sandbox knowledge index."""
    _query = query_fn or query_knowledge_pgvector

    settlement_hits = _query(
        SETTLEMENT_QUERY,
        namespace=namespace,
        index_version=index_version,
        database_url=database_url,
        table_name=table_name,
        provider=provider,
        confirm_real_openai=confirm_real_openai,
        top_k=top_k,
    )
    settlement_case = evaluate_settlement_smoke(settlement_hits)

    bank_hits = _query(
        SETTLEMENT_BANK_QUERY,
        namespace=namespace,
        index_version=index_version,
        database_url=database_url,
        table_name=table_name,
        provider=provider,
        confirm_real_openai=confirm_real_openai,
        top_k=top_k,
    )
    settlement_bank_case = evaluate_settlement_bank_smoke(bank_hits)

    product_hits = _query(
        _PRODUCT_QUERY,
        namespace=namespace,
        index_version=index_version,
        database_url=database_url,
        table_name=table_name,
        provider=provider,
        confirm_real_openai=confirm_real_openai,
        top_k=top_k,
    )
    product_case = evaluate_document_type_smoke(
        name="product_publishing",
        query=_PRODUCT_QUERY,
        hits=product_hits,
        required_any=(
            KnowledgeDocumentType.PRODUCT_PUBLISHING_RULES.value,
            KnowledgeDocumentType.SUPPORT_FAQ.value,
        ),
    )

    return_hits = _query(
        _RETURN_QUERY,
        namespace=namespace,
        index_version=index_version,
        database_url=database_url,
        table_name=table_name,
        provider=provider,
        confirm_real_openai=confirm_real_openai,
        top_k=top_k,
    )
    return_case = evaluate_document_type_smoke(
        name="refund_return",
        query=_RETURN_QUERY,
        hits=return_hits,
        required_any=(KnowledgeDocumentType.REFUND_RETURN_RULES.value,),
    )

    cases = (settlement_case, settlement_bank_case, product_case, return_case)
    if not settlement_case.passed or not settlement_bank_case.passed:
        status = "failed"
    elif all(case.passed for case in cases):
        status = "passed"
    else:
        status = "partial"
    return KnowledgeRetrievalSmokeResult(status=status, cases=cases)


def render_smoke_report_markdown(result: KnowledgeRetrievalSmokeResult) -> str:
    lines = [
        "# Knowledge retrieval smoke report",
        "",
        f"**Status:** {result.status}",
        "",
    ]
    for case in result.cases:
        lines.append(f"## {case.name}")
        lines.append("")
        lines.append(f"- **passed:** {case.passed}")
        lines.append(f"- **query:** {case.query}")
        matched = ", ".join(case.matched_document_types) or "—"
        lines.append(f"- **matched_document_types:** {matched}")
        if case.errors:
            lines.append(f"- **errors:** {', '.join(case.errors)}")
        lines.append("")
    lines.append("_Aggregate counts/snippets only — no raw private docs._")
    lines.append("")
    return "\n".join(lines)


def write_knowledge_retrieval_smoke_reports(
    result: KnowledgeRetrievalSmokeResult,
    *,
    summary_json: Path = DEFAULT_SMOKE_SUMMARY_JSON,
    report_md: Path = DEFAULT_SMOKE_REPORT_MD,
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
    markdown = render_smoke_report_markdown(result)
    assert_safe_knowledge_output(markdown)
    report_md.write_text(markdown, encoding="utf-8")
