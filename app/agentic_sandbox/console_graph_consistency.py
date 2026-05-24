"""Console vs agentic sandbox graph interpretation consistency (diagnostics only)."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.agentic_sandbox.agentic_batch_report import load_first_vendor_room_ids
from app.agentic_sandbox.agentic_graph import resolve_ticket_for_sandbox
from app.config import AppSettings, get_settings
from app.evals.actionability_validation import actionability_metadata_row, validate_actionability
from app.evals.first_turn_draft_context import (
    ENTITY_SOURCE_FULL_FIRST_VENDOR,
    ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE,
    build_first_turn_draft_context_from_ticket,
    resolve_first_turn_text_sources_from_ticket,
)
from app.operator_console.agentic_sandbox_preview import (
    AgenticSandboxPreviewResult,
    run_agentic_preview_for_ticket,
)
from app.operator_console.console_loader import DEFAULT_REDACTED_TICKETS_PATH, DEFAULT_REPLAY_PATH
from app.operator_console.console_models import OperatorTicket
from app.operator_console.draft_review_feedback import _FORBIDDEN_TEXT_SUBSTRINGS
from app.operator_console.intent_display import _OPEN_SNAPSHOT_ENTITY_SOURCE

DEFAULT_BATCH_JSONL = Path("reports/console_graph_consistency_batch.jsonl")
DEFAULT_BATCH_SUMMARY_JSON = Path("reports/console_graph_consistency_summary.json")
DEFAULT_BATCH_REPORT_MD = Path("reports/console_graph_consistency_report.md")

_CONSOLE_AI_ASSIST_ENTITY_SOURCE = _OPEN_SNAPSHOT_ENTITY_SOURCE

_FORBIDDEN_OUTPUT_TOKENS = (
    "conversation transcript",
    "gold_reference_reply",
    '"messages"',
    "raw_prompt",
    "retrieved_context",
    "conversation_transcript",
    '"snippet":',
)

_FORBIDDEN_OUTPUT_KEYS = frozenset(
    {
        "full_first_vendor_message_text",
        "first_turn_extraction_text",
        "first_turn_full_text",
        "full_first_turn_text",
        "raw_first_turn_text",
        "messages",
        "transcript",
        "conversation_transcript",
        "raw_prompt",
        "retrieval_results",
        "raw_snippets",
        "draft_reply",
    },
)


class ComparedFieldStatus(StrEnum):
    MATCH = "match"
    EXPLAINABLE = "explainable"
    MISMATCH = "mismatch"


class ConsistencyStatus(StrEnum):
    CONSISTENT = "consistent"
    EXPLAINABLE_DIFFERENCE = "explainable_difference"
    MISMATCH = "mismatch"


@dataclass(frozen=True)
class ComparedField:
    """Single field comparison between console and graph interpretations."""

    field_name: str
    console_value: str | None
    graph_value: str | None
    status: str
    reason: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "console_value": self.console_value,
            "graph_value": self.graph_value,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ConsoleGraphConsistencyResult:
    """Per-room console vs graph consistency diagnostic."""

    room_id: str
    consistency_status: str
    compared_fields: tuple[ComparedField, ...]
    mismatches: tuple[str, ...]
    explanation_notes: tuple[str, ...]
    safe_metadata: dict[str, Any]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "room_id": self.room_id,
            "consistency_status": self.consistency_status,
            "compared_fields": [field.to_json_dict() for field in self.compared_fields],
            "mismatches": list(self.mismatches),
            "explanation_notes": list(self.explanation_notes),
            "safe_metadata": dict(self.safe_metadata),
        }


@dataclass(frozen=True)
class ConsoleGraphConsistencyBatchSummary:
    """Aggregate batch consistency output."""

    generated_at_utc: str
    source_replay_path: str
    source_redacted_path: str | None
    provider: str
    knowledge_hints_enabled: bool
    room_count: int
    status_counts: dict[str, int]
    results: tuple[ConsoleGraphConsistencyResult, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "source_replay_path": self.source_replay_path,
            "source_redacted_path": self.source_redacted_path,
            "provider": self.provider,
            "knowledge_hints_enabled": self.knowledge_hints_enabled,
            "room_count": self.room_count,
            "status_counts": dict(self.status_counts),
            "results": [item.to_json_dict() for item in self.results],
        }


def room_report_paths(room_id: str) -> tuple[Path, Path]:
    """Default JSON and markdown paths for one room."""
    return (
        Path(f"reports/console_graph_consistency_{room_id}.json"),
        Path(f"reports/console_graph_consistency_{room_id}.md"),
    )


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_bool(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip().lower() or None


def _normalize_csv_ids(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        parts = [str(item).strip() for item in value if str(item).strip()]
    else:
        text = str(value).strip()
        if not text or text in {"()", "[]"}:
            return None
        parts = [part.strip() for part in text.split(",") if part.strip()]
    if not parts:
        return None
    return ",".join(sorted(dict.fromkeys(parts)))


def _id_set(value: str | None) -> set[str]:
    if not value:
        return set()
    return {part.strip() for part in value.split(",") if part.strip()}


def _values_equal(left: str | None, right: str | None) -> bool:
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    return left == right


@dataclass(frozen=True)
class _InterpretationSnapshot:
    """Normalized safe fields for one interpretation path."""

    detected_intent: str | None
    conceptual_intent_fa: str | None
    suggested_action: str | None
    suggested_action_reason: str | None
    actionability_actionable: str | None
    missing_required_entities: str | None
    entity_source: str | None
    order_ids: str | None
    product_ids: str | None
    tracking_code: str | None
    knowledge_hint_count: str | None
    knowledge_hint_document_types: str | None
    safety_status: str | None
    metadata: dict[str, Any]


def build_console_interpretation_snapshot(
    ticket: OperatorTicket,
    *,
    settings: AppSettings | None = None,
) -> _InterpretationSnapshot:
    """Console path: internal first-turn draft context (+ AI assist metadata)."""
    cfg = settings or get_settings()
    sources = resolve_first_turn_text_sources_from_ticket(ticket)
    ctx = build_first_turn_draft_context_from_ticket(ticket, settings=cfg)
    validation = validate_actionability(
        suggested_action=ctx.suggested_action,
        entities=ctx.first_turn_intent,
        seller_text=ctx.first_turn_text,
        detected_intent=ctx.first_turn_intent.detected_intent,
    )
    actionability = actionability_metadata_row(validation)
    hint_types = sorted({hint.document_type for hint in ctx.first_turn_policy_hints})
    return _InterpretationSnapshot(
        detected_intent=_optional_str(ctx.first_turn_intent.detected_intent),
        conceptual_intent_fa=None,
        suggested_action=_optional_str(ctx.suggested_action),
        suggested_action_reason=_optional_str(ctx.suggested_action_reason),
        actionability_actionable=_normalize_bool(actionability.get("actionability_actionable")),
        missing_required_entities=_optional_str(
            actionability.get("actionability_missing_entities"),
        ),
        entity_source=_optional_str(ctx.entity_extraction_source),
        order_ids=_normalize_csv_ids(ctx.first_turn_entities.order_ids),
        product_ids=_normalize_csv_ids(ctx.first_turn_entities.product_ids),
        tracking_code=_optional_str(ctx.first_turn_entities.primary_tracking_code),
        knowledge_hint_count=str(len(ctx.first_turn_policy_hints)),
        knowledge_hint_document_types=_normalize_csv_ids(hint_types) if hint_types else None,
        safety_status=None,
        metadata={
            "console_path": "first_turn_draft_context",
            "console_ai_assist_entity_source": _CONSOLE_AI_ASSIST_ENTITY_SOURCE,
            "console_entity_extraction_source": ctx.entity_extraction_source,
            "console_display_preview_char_count": sources.display_preview_char_count,
            "console_entity_extraction_source_char_count": (
                sources.entity_extraction_source_char_count
            ),
            "ai_assist_detected_intent": _optional_str(ticket.detected_intent),
            "ai_assist_suggested_action": _optional_str(ticket.suggested_action),
            "ai_assist_suggested_action_reason": _optional_str(ticket.suggested_action_reason),
            "ai_assist_order_ids": _normalize_csv_ids(
                ticket.extracted_order_ids or ticket.extracted_order_id
            ),
            "ai_assist_product_ids": _normalize_csv_ids(ticket.extracted_product_ids),
            "ai_assist_tracking_code": _optional_str(ticket.extracted_tracking_code),
            "knowledge_hints_enabled": cfg.knowledge_hints_enabled,
            "operator_agentic_sandbox_knowledge_hints_enabled": (
                cfg.operator_agentic_sandbox_knowledge_hints_enabled
            ),
        },
    )


def build_graph_interpretation_snapshot(
    preview: AgenticSandboxPreviewResult,
    *,
    settings: AppSettings | None = None,
) -> _InterpretationSnapshot:
    """Graph path: sanitized agentic sandbox preview result."""
    cfg = settings or get_settings()
    return _InterpretationSnapshot(
        detected_intent=_optional_str(preview.detected_intent),
        conceptual_intent_fa=_optional_str(preview.conceptual_intent_fa),
        suggested_action=_optional_str(preview.suggested_action),
        suggested_action_reason=_optional_str(preview.suggested_action_reason),
        actionability_actionable=_normalize_bool(preview.actionability_actionable),
        missing_required_entities=_optional_str(preview.missing_required_entities),
        entity_source=_optional_str(preview.entity_extraction_source or preview.entity_source),
        order_ids=_normalize_csv_ids(preview.extracted_order_ids),
        product_ids=_normalize_csv_ids(preview.extracted_product_ids),
        tracking_code=_optional_str(preview.extracted_tracking_code),
        knowledge_hint_count=str(preview.knowledge_hint_count),
        knowledge_hint_document_types=_normalize_csv_ids(preview.knowledge_hint_document_types),
        safety_status=_optional_str(preview.safety_status),
        metadata={
            "graph_path": "agentic_sandbox_preview",
            "graph_entity_extraction_source": preview.entity_extraction_source,
            "graph_entity_extraction_source_char_count": (
                preview.entity_extraction_source_char_count
            ),
            "graph_display_preview_char_count": preview.display_preview_char_count,
            "graph_status": preview.graph_status,
            "knowledge_hints_enabled": cfg.operator_agentic_sandbox_knowledge_hints_enabled,
        },
    )


def _explainable_entity_field(
    field_name: str,
    console_value: str | None,
    graph_value: str | None,
    *,
    console: _InterpretationSnapshot,
    graph: _InterpretationSnapshot,
) -> tuple[str, str | None]:
    graph_source = graph.metadata.get("graph_entity_extraction_source")
    console_source = console.metadata.get("console_entity_extraction_source")
    ai_assist_orders = console.metadata.get("ai_assist_order_ids")
    console_ids = _id_set(console_value)
    graph_ids = _id_set(graph_value)
    ai_ids = _id_set(ai_assist_orders if isinstance(ai_assist_orders, str) else None)

    if field_name == "entity_source":
        if graph_source == ENTITY_SOURCE_FULL_FIRST_VENDOR and console_source in {
            ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE,
            ENTITY_SOURCE_FULL_FIRST_VENDOR,
        }:
            return (
                ComparedFieldStatus.EXPLAINABLE.value,
                "graph uses full_first_vendor_message_text; console draft may label preview source",
            )
        if ai_assist_orders and console_source == _CONSOLE_AI_ASSIST_ENTITY_SOURCE:
            return (
                ComparedFieldStatus.EXPLAINABLE.value,
                "console AI assist uses open snapshot; graph uses first-turn extraction path",
            )

    if field_name in {"order_ids", "product_ids", "tracking_code"}:
        if (
            graph_source == ENTITY_SOURCE_FULL_FIRST_VENDOR
            and graph_ids
            and graph_ids != console_ids
        ):
            if console_ids and graph_ids.issuperset(console_ids):
                return (
                    ComparedFieldStatus.EXPLAINABLE.value,
                    "graph extracted from full first seller message beyond truncated preview",
                )
        if ai_ids and ai_ids != graph_ids and console_ids == graph_ids:
            return (
                ComparedFieldStatus.EXPLAINABLE.value,
                "AI assist open snapshot differs; internal first-turn draft matches graph",
            )
        if ai_ids and graph_ids and not console_ids and graph_ids == ai_ids:
            return (
                ComparedFieldStatus.EXPLAINABLE.value,
                "console draft empty; graph matches AI assist snapshot entities",
            )

    return ComparedFieldStatus.MISMATCH.value, None


def _explainable_field(
    field_name: str,
    console_value: str | None,
    graph_value: str | None,
    *,
    console: _InterpretationSnapshot,
    graph: _InterpretationSnapshot,
) -> tuple[str, str | None]:
    if field_name in {"order_ids", "product_ids", "tracking_code", "entity_source"}:
        status, reason = _explainable_entity_field(
            field_name,
            console_value,
            graph_value,
            console=console,
            graph=graph,
        )
        if status == ComparedFieldStatus.EXPLAINABLE.value:
            return status, reason

    if field_name == "detected_intent":
        ai_intent = console.metadata.get("ai_assist_detected_intent")
        if ai_intent and ai_intent != graph_value and console_value == graph_value:
            return (
                ComparedFieldStatus.EXPLAINABLE.value,
                "AI assist replay intent differs; first-turn draft matches graph",
            )

    if field_name in {"suggested_action", "suggested_action_reason"}:
        ai_key = f"ai_assist_{field_name}"
        ai_val = console.metadata.get(ai_key)
        if ai_val and ai_val != graph_value and console_value == graph_value:
            return (
                ComparedFieldStatus.EXPLAINABLE.value,
                "AI assist replay action differs; first-turn draft matches graph",
            )

    if field_name in {"knowledge_hint_count", "knowledge_hint_document_types"}:
        console_hints = console.metadata.get("knowledge_hints_enabled")
        graph_hints = graph.metadata.get("knowledge_hints_enabled")
        if console_hints is not graph_hints:
            return (
                ComparedFieldStatus.EXPLAINABLE.value,
                "knowledge hint enablement differs between console and sandbox config",
            )

    if field_name == "conceptual_intent_fa" and console_value is None and graph_value:
        return (
            ComparedFieldStatus.EXPLAINABLE.value,
            "conceptual_intent_fa only produced by fresh sandbox graph draft run",
        )

    if field_name == "safety_status" and console_value is None and graph_value:
        return (
            ComparedFieldStatus.EXPLAINABLE.value,
            "safety_status only evaluated in agentic sandbox graph",
        )

    return ComparedFieldStatus.MISMATCH.value, None


def _compare_field(
    field_name: str,
    console_value: str | None,
    graph_value: str | None,
    *,
    console: _InterpretationSnapshot,
    graph: _InterpretationSnapshot,
) -> ComparedField:
    if _values_equal(console_value, graph_value):
        return ComparedField(
            field_name=field_name,
            console_value=console_value,
            graph_value=graph_value,
            status=ComparedFieldStatus.MATCH.value,
        )
    status, reason = _explainable_field(
        field_name,
        console_value,
        graph_value,
        console=console,
        graph=graph,
    )
    if status == ComparedFieldStatus.EXPLAINABLE.value:
        return ComparedField(
            field_name=field_name,
            console_value=console_value,
            graph_value=graph_value,
            status=status,
            reason=reason,
        )
    return ComparedField(
        field_name=field_name,
        console_value=console_value,
        graph_value=graph_value,
        status=ComparedFieldStatus.MISMATCH.value,
        reason="values differ with no recognized explainable pattern",
    )


def _aggregate_consistency_status(
    fields: Sequence[ComparedField],
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    mismatches = tuple(
        field.field_name for field in fields if field.status == ComparedFieldStatus.MISMATCH.value
    )
    explainable = [
        field for field in fields if field.status == ComparedFieldStatus.EXPLAINABLE.value
    ]
    if mismatches:
        status = ConsistencyStatus.MISMATCH.value
    elif explainable:
        status = ConsistencyStatus.EXPLAINABLE_DIFFERENCE.value
    else:
        status = ConsistencyStatus.CONSISTENT.value
    notes: list[str] = []
    for field in explainable:
        notes.append(f"{field.field_name}: {field.reason or 'explainable difference'}")
    if mismatches:
        notes.append(f"mismatch_fields={','.join(mismatches)}")
    return status, mismatches, tuple(notes)


def compare_console_graph_consistency(
    ticket: OperatorTicket,
    *,
    settings: AppSettings | None = None,
    graph_preview: AgenticSandboxPreviewResult | None = None,
) -> ConsoleGraphConsistencyResult:
    """Compare console first-turn draft interpretation with agentic sandbox preview."""
    cfg = settings or get_settings()
    console = build_console_interpretation_snapshot(ticket, settings=cfg)
    preview = graph_preview or run_agentic_preview_for_ticket(ticket, settings=cfg)
    graph = build_graph_interpretation_snapshot(preview, settings=cfg)

    field_specs = (
        ("detected_intent", console.detected_intent, graph.detected_intent),
        ("conceptual_intent_fa", console.conceptual_intent_fa, graph.conceptual_intent_fa),
        ("suggested_action", console.suggested_action, graph.suggested_action),
        ("suggested_action_reason", console.suggested_action_reason, graph.suggested_action_reason),
        (
            "actionability_actionable",
            console.actionability_actionable,
            graph.actionability_actionable,
        ),
        (
            "missing_required_entities",
            console.missing_required_entities,
            graph.missing_required_entities,
        ),
        ("entity_source", console.entity_source, graph.entity_source),
        ("order_ids", console.order_ids, graph.order_ids),
        ("product_ids", console.product_ids, graph.product_ids),
        ("tracking_code", console.tracking_code, graph.tracking_code),
        ("knowledge_hint_count", console.knowledge_hint_count, graph.knowledge_hint_count),
        (
            "knowledge_hint_document_types",
            console.knowledge_hint_document_types,
            graph.knowledge_hint_document_types,
        ),
        ("safety_status", console.safety_status, graph.safety_status),
    )
    compared = tuple(
        _compare_field(name, console_val, graph_val, console=console, graph=graph)
        for name, console_val, graph_val in field_specs
    )
    status, mismatches, notes = _aggregate_consistency_status(compared)
    safe_metadata = {
        "console_path": console.metadata.get("console_path"),
        "graph_path": graph.metadata.get("graph_path"),
        "console_entity_extraction_source": console.metadata.get(
            "console_entity_extraction_source"
        ),
        "graph_entity_extraction_source": graph.metadata.get("graph_entity_extraction_source"),
        "console_ai_assist_entity_source": console.metadata.get("console_ai_assist_entity_source"),
        "ai_assist_detected_intent": console.metadata.get("ai_assist_detected_intent"),
        "ai_assist_suggested_action": console.metadata.get("ai_assist_suggested_action"),
        "ai_assist_order_ids": console.metadata.get("ai_assist_order_ids"),
        "knowledge_hints_enabled": console.metadata.get("knowledge_hints_enabled"),
        "operator_agentic_sandbox_knowledge_hints_enabled": console.metadata.get(
            "operator_agentic_sandbox_knowledge_hints_enabled",
        ),
        "graph_status": graph.metadata.get("graph_status"),
        "graph_entity_extraction_source_char_count": graph.metadata.get(
            "graph_entity_extraction_source_char_count",
        ),
        "display_preview_char_count": graph.metadata.get("graph_display_preview_char_count"),
    }
    return ConsoleGraphConsistencyResult(
        room_id=ticket.room_id,
        consistency_status=status,
        compared_fields=compared,
        mismatches=mismatches,
        explanation_notes=notes,
        safe_metadata=safe_metadata,
    )


def summarize_console_graph_consistency_batch(
    results: Sequence[ConsoleGraphConsistencyResult],
    *,
    source_replay_path: str,
    source_redacted_path: str | None,
    provider: str,
    knowledge_hints_enabled: bool,
    generated_at_utc: str | None = None,
) -> ConsoleGraphConsistencyBatchSummary:
    counts: dict[str, int] = {}
    for item in results:
        counts[item.consistency_status] = counts.get(item.consistency_status, 0) + 1
    return ConsoleGraphConsistencyBatchSummary(
        generated_at_utc=generated_at_utc or _utc_now_iso(),
        source_replay_path=source_replay_path,
        source_redacted_path=source_redacted_path,
        provider=provider,
        knowledge_hints_enabled=knowledge_hints_enabled,
        room_count=len(results),
        status_counts=counts,
        results=tuple(results),
    )


def _collect_json_keys(obj: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            keys.add(str(key))
            keys |= _collect_json_keys(value)
    elif isinstance(obj, list):
        for item in obj:
            keys |= _collect_json_keys(item)
    return keys


def assert_console_graph_consistency_output_safe(content: str) -> None:
    """Fail closed if report output contains forbidden transcript/prompt patterns."""
    lowered = content.lower()
    for token in _FORBIDDEN_TEXT_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(
                f"console graph consistency output must not contain forbidden token: {token}",
            )
    for token in _FORBIDDEN_OUTPUT_TOKENS:
        if token.lower() in lowered:
            raise ValueError(
                f"console graph consistency output must not contain forbidden token: {token}",
            )
    if re.search(r"sk-[a-z0-9]{8,}", content, flags=re.IGNORECASE):
        raise ValueError("consistency output must not contain API key patterns")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = None
    if parsed is not None:
        for key in _collect_json_keys(parsed):
            if key in _FORBIDDEN_OUTPUT_KEYS:
                raise ValueError(
                    f"console graph consistency output must not contain forbidden key: {key}",
                )


def render_console_graph_consistency_markdown(result: ConsoleGraphConsistencyResult) -> str:
    """Markdown report for one room (safe fields only)."""
    lines = [
        f"# Console vs graph consistency — room {result.room_id}",
        "",
        f"- **consistency_status:** {result.consistency_status}",
        f"- **mismatches:** {', '.join(result.mismatches) if result.mismatches else 'none'}",
        "",
        "## Compared fields",
        "",
        "| Field | Console | Graph | Status | Reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    for field in result.compared_fields:
        lines.append(
            f"| {field.field_name} | {field.console_value or '—'} | "
            f"{field.graph_value or '—'} | {field.status} | {field.reason or '—'} |",
        )
    if result.explanation_notes:
        lines.extend(["", "## Notes", ""])
        for note in result.explanation_notes:
            lines.append(f"- {note}")
    if result.safe_metadata:
        lines.extend(["", "## Safe metadata", ""])
        for key, value in sorted(result.safe_metadata.items()):
            lines.append(f"- **{key}:** {value}")
    lines.extend(
        [
            "",
            "## Governance",
            "",
            "- Diagnostics only — does not modify console, graph, or mappings.",
            "- No prompts, transcripts, retrieval snippets, or full first-turn message text.",
            "",
        ],
    )
    return "\n".join(lines)


def render_console_graph_consistency_batch_markdown(
    summary: ConsoleGraphConsistencyBatchSummary,
) -> str:
    lines = [
        "# Console vs graph consistency — batch",
        "",
        f"- **generated_at_utc:** {summary.generated_at_utc}",
        f"- **room_count:** {summary.room_count}",
        f"- **provider:** {summary.provider}",
        f"- **knowledge_hints_enabled:** {summary.knowledge_hints_enabled}",
        "",
        "## Status counts",
        "",
    ]
    for status, count in sorted(summary.status_counts.items()):
        lines.append(f"- **{status}:** {count}")
    lines.extend(["", "## Rooms", ""])
    for item in summary.results:
        lines.append(
            f"- `{item.room_id}`: {item.consistency_status}"
            + (f" (mismatches: {', '.join(item.mismatches)})" if item.mismatches else ""),
        )
    lines.extend(
        [
            "",
            "## Governance",
            "",
            "- Diagnostics only — no behavior changes.",
            "",
        ],
    )
    return "\n".join(lines)


def write_console_graph_consistency_outputs(
    result: ConsoleGraphConsistencyResult,
    *,
    json_path: Path,
    markdown_path: Path,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(result.to_json_dict(), ensure_ascii=False, indent=2) + "\n"
    markdown = render_console_graph_consistency_markdown(result)
    assert_console_graph_consistency_output_safe(json_text)
    assert_console_graph_consistency_output_safe(markdown)
    json_path.write_text(json_text, encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")


def write_console_graph_consistency_batch_outputs(
    summary: ConsoleGraphConsistencyBatchSummary,
    *,
    jsonl_path: Path = DEFAULT_BATCH_JSONL,
    summary_json_path: Path = DEFAULT_BATCH_SUMMARY_JSON,
    markdown_path: Path = DEFAULT_BATCH_REPORT_MD,
) -> None:
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    summary_json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(item.to_json_dict(), ensure_ascii=False) for item in summary.results]
    jsonl_text = "\n".join(lines) + ("\n" if lines else "")
    summary_text = json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2) + "\n"
    markdown = render_console_graph_consistency_batch_markdown(summary)
    assert_console_graph_consistency_output_safe(jsonl_text)
    assert_console_graph_consistency_output_safe(summary_text)
    assert_console_graph_consistency_output_safe(markdown)
    jsonl_path.write_text(jsonl_text, encoding="utf-8")
    summary_json_path.write_text(summary_text, encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")


def _consistency_check_settings(
    settings: AppSettings | None,
    *,
    provider: str,
    knowledge_hints_enabled: bool,
) -> AppSettings:
    """Align sandbox/console settings for offline diagnostics (mock provider = no network)."""
    cfg = (settings or get_settings()).model_copy(
        update={
            "operator_agentic_sandbox_provider": provider.strip().lower(),
            "operator_agentic_sandbox_knowledge_hints_enabled": knowledge_hints_enabled,
            "knowledge_hints_enabled": knowledge_hints_enabled,
        },
    )
    if cfg.operator_agentic_sandbox_provider == "mock":
        return cfg.model_copy(
            update={
                "embedding_provider": "mock",
                "embedding_model": "mock-embedding-small",
                "rag_strategy": "mock",
                "knowledge_retrieval_index_version": "knowledge_v1_mock",
            },
        )
    return cfg


def run_console_graph_consistency_check(
    *,
    room_id: str | None,
    replay_path: Path | str = DEFAULT_REPLAY_PATH,
    redacted_path: Path | str | None = DEFAULT_REDACTED_TICKETS_PATH,
    provider: str = "mock",
    knowledge_hints_enabled: bool = False,
    limit: int | None = None,
    settings: AppSettings | None = None,
) -> ConsoleGraphConsistencyResult | ConsoleGraphConsistencyBatchSummary:
    """Run single-room or batch consistency diagnostics."""
    cfg = _consistency_check_settings(
        settings,
        provider=provider,
        knowledge_hints_enabled=knowledge_hints_enabled,
    )
    replay = Path(replay_path)
    redacted = Path(redacted_path) if redacted_path is not None else None

    if room_id:
        ticket = resolve_ticket_for_sandbox(
            str(room_id).strip(),
            replay_jsonl=replay,
            redacted_jsonl=redacted,
        )
        return compare_console_graph_consistency(ticket, settings=cfg)

    selection = load_first_vendor_room_ids(replay, redacted_jsonl=redacted, limit=limit)
    results: list[ConsoleGraphConsistencyResult] = []
    for rid in selection.room_ids:
        ticket = resolve_ticket_for_sandbox(rid, replay_jsonl=replay, redacted_jsonl=redacted)
        results.append(compare_console_graph_consistency(ticket, settings=cfg))
    return summarize_console_graph_consistency_batch(
        results,
        source_replay_path=str(replay),
        source_redacted_path=str(redacted) if redacted else None,
        provider=provider,
        knowledge_hints_enabled=knowledge_hints_enabled,
    )
