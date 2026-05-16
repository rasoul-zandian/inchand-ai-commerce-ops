"""Deterministic mock RAG retrieval (no I/O, embeddings, or vector DB)."""

from __future__ import annotations

from app.rag.types import RAGDocument, RAGQuery, RAGResult

_MOCK_CATALOG: tuple[RAGDocument, ...] = (
    RAGDocument(
        document_id="rag-policy-seller-support-001",
        title="سیاست پاسخ‌گویی به تیکت فروشندگان",
        content=(
            "پاسخ‌ها باید محترمانه، شفاف و بدون تعهد مالی باشند. "
            "در صورت ابهام در تسویه، درخواست فاکتور و بازه زمانی مشخص شود."
        ),
        source_type="policy",
        score=0.92,
        metadata={"locale": "fa-IR", "domain": "seller_support"},
    ),
    RAGDocument(
        document_id="rag-policy-financial-adjustment-002",
        title="سیاست تعدیل مالی و بازپرداخت",
        content=(
            "هرگونه تعدیل مالی یا بازپرداخت نیازمند تأیید واحد مالی و مسیر رسمی است. "
            "به‌صورت خودکار مبلغ قطعی به فروشنده وعده داده نشود."
        ),
        source_type="policy",
        score=0.88,
        metadata={"locale": "fa-IR", "domain": "finance"},
    ),
    RAGDocument(
        document_id="rag-pattern-approved-reply-003",
        title="الگوی پاسخ تأییدشده برای ابهام تسویه",
        content=(
            "نمونهٔ تأییدشده: ابراز همدلی، درخواست مدارک تکمیلی، "
            "و اعلام پیگیری توسط تیم مالی بدون ذکر عدد نهایی تا زمان تأیید."
        ),
        source_type="approved_pattern",
        score=0.85,
        metadata={"locale": "fa-IR", "intent": "billing_discrepancy"},
    ),
    RAGDocument(
        document_id="rag-policy-escalation-004",
        title="زمان و شرایط تشدید (Escalation) تیکت",
        content=(
            "در صورت تکرار شکایت یا نبود پاسخ مناسب پس از SLA داخلی، "
            "تیکت به سطح بالاتر ارجاع می‌شود."
        ),
        source_type="policy",
        score=0.8,
        metadata={"locale": "fa-IR", "domain": "operations"},
    ),
    RAGDocument(
        document_id="rag-pattern-tone-005",
        title="لحن استاندارد ارتباط با فروشنده",
        content=(
            "از زبان رسمی و محترمانه استفاده شود؛ از اصطلاحات تهدیدآمیز یا تضمین قطعی پرهیز شود."
        ),
        source_type="style_guide",
        score=0.78,
        metadata={"locale": "fa-IR", "domain": "communications"},
    ),
)


def mock_retrieve(query: RAGQuery) -> RAGResult:
    """Return the first ``top_k`` catalog documents (fixed order, deterministic)."""
    top_k = max(0, query.top_k)
    selected = list(_MOCK_CATALOG[: min(top_k, len(_MOCK_CATALOG))])
    return RAGResult(
        documents=selected,
        provider="mock",
        metadata={
            "query": query.query,
            "top_k": query.top_k,
            "filters": dict(query.filters),
            "catalog_size": len(_MOCK_CATALOG),
        },
    )
