"""Node-level readiness analysis for agentic sandbox batch runs (analytics only)."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.agentic_sandbox.agentic_graph import NODE_ORDER
from app.agentic_sandbox.report_paths import (
    DEFAULT_BATCH_RUNS_JSONL,
    DEFAULT_READINESS_REPORT_PATH,
    DEFAULT_READINESS_SUMMARY_PATH,
)
from app.config import AppSettings, get_settings
from app.operator_console.draft_review_feedback import _FORBIDDEN_TEXT_SUBSTRINGS

BUCKET_READY_FOR_HUMAN_REVIEW = "ready_for_human_review"
BUCKET_NEEDS_MISSING_IDENTIFIER = "needs_missing_identifier"
BUCKET_NEEDS_KNOWLEDGE_REVIEW = "needs_knowledge_review"
BUCKET_NODE_ERROR = "node_error"
BUCKET_SAFETY_FAILED = "safety_failed"
BUCKET_DRAFT_MISSING_OR_INVALID = "draft_missing_or_invalid"

READINESS_BUCKETS = (
    BUCKET_READY_FOR_HUMAN_REVIEW,
    BUCKET_NEEDS_MISSING_IDENTIFIER,
    BUCKET_NEEDS_KNOWLEDGE_REVIEW,
    BUCKET_NODE_ERROR,
    BUCKET_SAFETY_FAILED,
    BUCKET_DRAFT_MISSING_OR_INVALID,
)

_POLICY_INTENTS = frozenset(
    {
        "settlement_status_inquiry",
        "settlement_panel_access_issue",
        "product_publishing_question",
        "prohibited_goods_question",
        "product_approval_review",
    },
)
_POLICY_ACTIONS = frozenset(
    {
        "check_settlement_status",
        "billing_review",
        "answer_policy_question",
        "check_product_approval",
        "check_return_request",
        "review_product_edit",
    },
)
_POLICY_KEYWORDS = (
    "settlement",
    "publish",
    "prohibited",
    "approval",
    "return",
    "refund",
    "تسویه",
    "انتشار",
    "مرجوع",
)


@dataclass(frozen=True)
class BatchRunRecord:
    """Parsed safe row from agentic sandbox batch JSONL."""

    room_id: str
    ticket_label: str | None
    route_label: str | None
    node_statuses: dict[str, str]
    safety_status: str | None
    detected_intent: str | None
    conceptual_intent_fa: str | None
    suggested_action: str | None
    actionability_actionable: bool | None
    missing_required_entities: str | None
    order_id_count: int
    product_id_count: int
    has_tracking_code: bool
    knowledge_hint_count: int
    draft_char_count: int
    human_review_required: bool
    execution_allowed: bool
    customer_send_allowed: bool
    success: bool
    errors: tuple[str, ...]

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> BatchRunRecord | None:
        room_id = data.get("room_id")
        if not isinstance(room_id, str) or not room_id.strip():
            return None
        node_statuses_raw = data.get("node_statuses") or {}
        node_statuses: dict[str, str] = {}
        if isinstance(node_statuses_raw, dict):
            node_statuses = {str(k): str(v) for k, v in node_statuses_raw.items()}
        errors_raw = data.get("errors") or []
        if isinstance(errors_raw, list):
            errors = tuple(str(e) for e in errors_raw if str(e).strip())
        else:
            errors = ()
        return cls(
            room_id=room_id.strip(),
            ticket_label=_optional_str(data.get("ticket_label")),
            route_label=_optional_str(data.get("route_label")),
            node_statuses=node_statuses,
            safety_status=_optional_str(data.get("safety_status")),
            detected_intent=_optional_str(data.get("detected_intent")),
            conceptual_intent_fa=_optional_str(data.get("conceptual_intent_fa")),
            suggested_action=_optional_str(data.get("suggested_action")),
            actionability_actionable=_optional_bool(data.get("actionability_actionable")),
            missing_required_entities=_optional_str(data.get("missing_required_entities")),
            order_id_count=int(data.get("order_id_count") or 0),
            product_id_count=int(data.get("product_id_count") or 0),
            has_tracking_code=bool(data.get("has_tracking_code")),
            knowledge_hint_count=int(data.get("knowledge_hint_count") or 0),
            draft_char_count=int(data.get("draft_char_count") or 0),
            human_review_required=bool(data.get("human_review_required", True)),
            execution_allowed=bool(data.get("execution_allowed")),
            customer_send_allowed=bool(data.get("customer_send_allowed")),
            success=bool(data.get("success")),
            errors=errors,
        )


@dataclass(frozen=True)
class ReadinessBucketAssignment:
    """Primary readiness bucket for one batch run."""

    room_id: str
    bucket: str
    reason: str
    detected_intent: str | None
    suggested_action: str | None


@dataclass
class AgenticReadinessSummary:
    """Aggregate node-level readiness metrics."""

    generated_at_utc: str
    source_batch_runs_path: str
    total_runs: int
    successful_runs: int
    failed_runs: int
    safety_passed_rate: float
    human_review_ready_rate: float
    execution_allowed_true_count: int
    customer_send_allowed_true_count: int
    missing_identifier_count: int
    knowledge_hint_missing_count: int
    average_draft_char_count: float
    draft_char_min: int
    draft_char_max: int
    draft_over_hard_max_count: int
    draft_hard_max_chars: int
    node_success_rates: dict[str, float]
    node_error_counts: dict[str, int]
    readiness_buckets: dict[str, int]
    readiness_by_detected_intent: dict[str, dict[str, int]] = field(default_factory=dict)
    readiness_by_suggested_action: dict[str, dict[str, int]] = field(default_factory=dict)
    missing_identifier_by_entity: dict[str, int] = field(default_factory=dict)
    knowledge_missing_by_intent: dict[str, int] = field(default_factory=dict)
    knowledge_missing_by_action: dict[str, int] = field(default_factory=dict)
    inspection_targets: tuple[ReadinessBucketAssignment, ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "source_batch_runs_path": self.source_batch_runs_path,
            "total_runs": self.total_runs,
            "successful_runs": self.successful_runs,
            "failed_runs": self.failed_runs,
            "safety_passed_rate": self.safety_passed_rate,
            "human_review_ready_rate": self.human_review_ready_rate,
            "execution_allowed_true_count": self.execution_allowed_true_count,
            "customer_send_allowed_true_count": self.customer_send_allowed_true_count,
            "missing_identifier_count": self.missing_identifier_count,
            "knowledge_hint_missing_count": self.knowledge_hint_missing_count,
            "average_draft_char_count": self.average_draft_char_count,
            "draft_char_min": self.draft_char_min,
            "draft_char_max": self.draft_char_max,
            "draft_over_hard_max_count": self.draft_over_hard_max_count,
            "draft_hard_max_chars": self.draft_hard_max_chars,
            "node_success_rates": dict(self.node_success_rates),
            "node_error_counts": dict(self.node_error_counts),
            "readiness_buckets": dict(self.readiness_buckets),
            "readiness_by_detected_intent": self.readiness_by_detected_intent,
            "readiness_by_suggested_action": self.readiness_by_suggested_action,
            "missing_identifier_by_entity": dict(self.missing_identifier_by_entity),
            "knowledge_missing_by_intent": dict(self.knowledge_missing_by_intent),
            "knowledge_missing_by_action": dict(self.knowledge_missing_by_action),
            "inspection_targets": [
                {
                    "room_id": item.room_id,
                    "bucket": item.bucket,
                    "reason": item.reason,
                    "detected_intent": item.detected_intent,
                    "suggested_action": item.suggested_action,
                }
                for item in self.inspection_targets
            ],
        }


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return None


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def load_batch_run_records(path: Path | str) -> list[BatchRunRecord]:
    """Load safe batch run rows from JSONL."""
    file_path = Path(path)
    if not file_path.is_file():
        return []
    records: list[BatchRunRecord] = []
    for line_no, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON at {file_path}:{line_no}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"line {line_no} must be a JSON object")
        record = BatchRunRecord.from_json_dict(data)
        if record is not None:
            records.append(record)
    return records


def _all_nodes_ok(row: BatchRunRecord) -> bool:
    for node in NODE_ORDER:
        status = row.node_statuses.get(node, "pending")
        if status != "ok":
            return False
    return True


def _has_node_error(row: BatchRunRecord) -> bool:
    for node in NODE_ORDER:
        if row.node_statuses.get(node) == "failed":
            return True
    return any(status == "failed" for status in row.node_statuses.values())


def _requires_identifier_request(row: BatchRunRecord) -> bool:
    if row.actionability_actionable is False:
        return bool(row.missing_required_entities and row.missing_required_entities.strip())
    return False


def _has_missing_identifier(row: BatchRunRecord) -> bool:
    return _requires_identifier_request(row)


def _policy_knowledge_relevant(row: BatchRunRecord) -> bool:
    intent = (row.detected_intent or "").strip().lower()
    action = (row.suggested_action or "").strip().lower()
    if intent in _POLICY_INTENTS or action in _POLICY_ACTIONS:
        return True
    blob = " ".join(
        part for part in (intent, action, row.conceptual_intent_fa or "") if part
    ).lower()
    return any(keyword in blob for keyword in _POLICY_KEYWORDS)


def _needs_knowledge_review(row: BatchRunRecord) -> bool:
    return row.knowledge_hint_count == 0 and _policy_knowledge_relevant(row)


def _draft_missing_or_invalid(row: BatchRunRecord) -> bool:
    generate_status = row.node_statuses.get("generate_draft", "pending")
    if generate_status == "failed":
        return True
    if row.draft_char_count <= 0:
        return True
    return False


def is_ready_for_human_review(row: BatchRunRecord) -> bool:
    """True when run meets HITL-ready sandbox criteria."""
    if not _all_nodes_ok(row):
        return False
    if row.safety_status != "passed":
        return False
    if not row.human_review_required:
        return False
    if row.execution_allowed or row.customer_send_allowed:
        return False
    if row.errors:
        return False
    if row.draft_char_count <= 0:
        return False
    return True


def classify_readiness_bucket(row: BatchRunRecord) -> ReadinessBucketAssignment:
    """Assign primary readiness bucket (priority-ordered)."""
    if row.safety_status != "passed":
        return ReadinessBucketAssignment(
            room_id=row.room_id,
            bucket=BUCKET_SAFETY_FAILED,
            reason=f"safety_status={row.safety_status or 'none'}",
            detected_intent=row.detected_intent,
            suggested_action=row.suggested_action,
        )
    if _has_node_error(row):
        failed_nodes = [node for node in NODE_ORDER if row.node_statuses.get(node) == "failed"]
        return ReadinessBucketAssignment(
            room_id=row.room_id,
            bucket=BUCKET_NODE_ERROR,
            reason=f"failed_nodes={','.join(failed_nodes) or 'unknown'}",
            detected_intent=row.detected_intent,
            suggested_action=row.suggested_action,
        )
    if _draft_missing_or_invalid(row):
        return ReadinessBucketAssignment(
            room_id=row.room_id,
            bucket=BUCKET_DRAFT_MISSING_OR_INVALID,
            reason=f"draft_char_count={row.draft_char_count}",
            detected_intent=row.detected_intent,
            suggested_action=row.suggested_action,
        )
    if is_ready_for_human_review(row):
        if _has_missing_identifier(row):
            reason = "identifier_request_draft_ready"
        else:
            reason = "all_nodes_ok"
        return ReadinessBucketAssignment(
            room_id=row.room_id,
            bucket=BUCKET_READY_FOR_HUMAN_REVIEW,
            reason=reason,
            detected_intent=row.detected_intent,
            suggested_action=row.suggested_action,
        )
    if _has_missing_identifier(row):
        return ReadinessBucketAssignment(
            room_id=row.room_id,
            bucket=BUCKET_NEEDS_MISSING_IDENTIFIER,
            reason=f"missing={row.missing_required_entities}",
            detected_intent=row.detected_intent,
            suggested_action=row.suggested_action,
        )
    if _needs_knowledge_review(row):
        return ReadinessBucketAssignment(
            room_id=row.room_id,
            bucket=BUCKET_NEEDS_KNOWLEDGE_REVIEW,
            reason="policy_relevant_no_hints",
            detected_intent=row.detected_intent,
            suggested_action=row.suggested_action,
        )
    return ReadinessBucketAssignment(
        room_id=row.room_id,
        bucket=BUCKET_NEEDS_MISSING_IDENTIFIER,
        reason="unclassified_needs_inspection",
        detected_intent=row.detected_intent,
        suggested_action=row.suggested_action,
    )


def summarize_agentic_readiness(
    records: list[BatchRunRecord],
    *,
    source_batch_runs_path: str = "",
    settings: AppSettings | None = None,
    generated_at_utc: str | None = None,
) -> AgenticReadinessSummary:
    """Compute node-level readiness summary from batch run records."""
    cfg = settings or get_settings()
    hard_max = cfg.draft_hard_max_chars
    total = len(records)
    successful = sum(1 for row in records if row.success)
    failed = total - successful
    safety_passed = sum(1 for row in records if row.safety_status == "passed")
    ready_count = sum(1 for row in records if is_ready_for_human_review(row))

    node_ok_counts: Counter[str] = Counter()
    node_error_counts: Counter[str] = Counter()
    bucket_counts: Counter[str] = Counter()
    intent_buckets: dict[str, Counter[str]] = defaultdict(Counter)
    action_buckets: dict[str, Counter[str]] = defaultdict(Counter)
    missing_entity_counts: Counter[str] = Counter()
    knowledge_missing_intent: Counter[str] = Counter()
    knowledge_missing_action: Counter[str] = Counter()
    inspection: list[ReadinessBucketAssignment] = []

    draft_chars = [row.draft_char_count for row in records if row.draft_char_count > 0]
    over_hard_max = sum(1 for count in draft_chars if count > hard_max)

    missing_identifier_count = 0
    knowledge_hint_missing_count = 0
    execution_true = 0
    customer_send_true = 0

    for row in records:
        if row.execution_allowed:
            execution_true += 1
        if row.customer_send_allowed:
            customer_send_true += 1
        if _has_missing_identifier(row):
            missing_identifier_count += 1
            for entity in _split_entities(row.missing_required_entities):
                missing_entity_counts[entity] += 1
        if _needs_knowledge_review(row):
            knowledge_hint_missing_count += 1
            if row.detected_intent:
                knowledge_missing_intent[row.detected_intent] += 1
            if row.suggested_action:
                knowledge_missing_action[row.suggested_action] += 1

        for node in NODE_ORDER:
            status = row.node_statuses.get(node, "pending")
            if status == "ok":
                node_ok_counts[node] += 1
            elif status == "failed":
                node_error_counts[node] += 1

        assignment = classify_readiness_bucket(row)
        bucket_counts[assignment.bucket] += 1
        if row.detected_intent:
            intent_buckets[row.detected_intent][assignment.bucket] += 1
        if row.suggested_action:
            action_buckets[row.suggested_action][assignment.bucket] += 1
        if assignment.bucket != BUCKET_READY_FOR_HUMAN_REVIEW:
            inspection.append(assignment)

    node_success_rates = {node: _rate(node_ok_counts[node], total) for node in NODE_ORDER}

    inspection_sorted = sorted(
        inspection,
        key=lambda item: (
            0
            if item.bucket == BUCKET_SAFETY_FAILED
            else 1
            if item.bucket == BUCKET_NODE_ERROR
            else 2
            if item.bucket == BUCKET_DRAFT_MISSING_OR_INVALID
            else 3,
            item.room_id,
        ),
    )[:25]

    return AgenticReadinessSummary(
        generated_at_utc=generated_at_utc or _utc_now_iso(),
        source_batch_runs_path=source_batch_runs_path,
        total_runs=total,
        successful_runs=successful,
        failed_runs=failed,
        safety_passed_rate=_rate(safety_passed, total),
        human_review_ready_rate=_rate(ready_count, total),
        execution_allowed_true_count=execution_true,
        customer_send_allowed_true_count=customer_send_true,
        missing_identifier_count=missing_identifier_count,
        knowledge_hint_missing_count=knowledge_hint_missing_count,
        average_draft_char_count=(
            round(sum(draft_chars) / len(draft_chars), 1) if draft_chars else 0.0
        ),
        draft_char_min=min(draft_chars) if draft_chars else 0,
        draft_char_max=max(draft_chars) if draft_chars else 0,
        draft_over_hard_max_count=over_hard_max,
        draft_hard_max_chars=hard_max,
        node_success_rates=node_success_rates,
        node_error_counts=dict(node_error_counts),
        readiness_buckets={bucket: bucket_counts.get(bucket, 0) for bucket in READINESS_BUCKETS},
        readiness_by_detected_intent={
            intent: dict(counter) for intent, counter in sorted(intent_buckets.items())
        },
        readiness_by_suggested_action={
            action: dict(counter) for action, counter in sorted(action_buckets.items())
        },
        missing_identifier_by_entity=dict(sorted(missing_entity_counts.items())),
        knowledge_missing_by_intent=dict(sorted(knowledge_missing_intent.items())),
        knowledge_missing_by_action=dict(sorted(knowledge_missing_action.items())),
        inspection_targets=tuple(inspection_sorted),
    )


def _split_entities(value: str | None) -> list[str]:
    if not value or not str(value).strip():
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def render_agentic_readiness_markdown(summary: AgenticReadinessSummary) -> str:
    """Render readiness markdown report (metrics only)."""
    lines = [
        "# Agentic Sandbox Readiness Report",
        "",
        f"**Generated (UTC):** {summary.generated_at_utc}  ",
        f"**Source:** `{summary.source_batch_runs_path}`  ",
        "**Scope:** Node-level readiness analytics — no graph/draft behavior changes.",
        "",
        "## Boundaries",
        "",
        "- Analytics/readiness only — does not mutate tickets or execute actions.",
        "- No full draft text, prompts, transcripts, or retrieval snippets.",
        "- `execution_allowed` and `customer_send_allowed` must remain **false**.",
        "",
        "## Overall readiness",
        "",
        f"- **total_runs:** {summary.total_runs}",
        f"- **successful_runs:** {summary.successful_runs}",
        f"- **failed_runs:** {summary.failed_runs}",
        f"- **human_review_ready_rate:** {summary.human_review_ready_rate:.1%}",
        f"- **safety_passed_rate:** {summary.safety_passed_rate:.1%}",
        "",
        "## Safety status",
        "",
        f"- **execution_allowed_true_count:** {summary.execution_allowed_true_count}",
        f"- **customer_send_allowed_true_count:** {summary.customer_send_allowed_true_count}",
        "",
        "## Node health",
        "",
        "| Node | Success rate | Error count |",
        "|------|-------------:|------------:|",
    ]
    for node in NODE_ORDER:
        rate = summary.node_success_rates.get(node, 0.0)
        errors = summary.node_error_counts.get(node, 0)
        lines.append(f"| `{node}` | {rate:.1%} | {errors} |")
    lines.extend(["", "## Readiness buckets", "", "| Bucket | Count |", "|--------|------:|"])
    for bucket in READINESS_BUCKETS:
        lines.append(f"| {bucket} | {summary.readiness_buckets.get(bucket, 0)} |")
    lines.extend(
        [
            "",
            "## Missing identifier analysis",
            "",
            f"- **missing_identifier_count:** {summary.missing_identifier_count}",
            "",
            "| Entity | Count |",
            "|--------|------:|",
        ],
    )
    if summary.missing_identifier_by_entity:
        for entity, count in summary.missing_identifier_by_entity.items():
            lines.append(f"| `{entity}` | {count} |")
    else:
        lines.append("| *(none)* | 0 |")
    lines.extend(
        [
            "",
            "## Knowledge hint coverage",
            "",
            f"- **knowledge_hint_missing_count (policy-relevant):** "
            f"{summary.knowledge_hint_missing_count}",
            "",
            "### By detected_intent",
            "",
            "| Intent | Missing hints |",
            "|--------|-------------:|",
        ],
    )
    if summary.knowledge_missing_by_intent:
        for intent, count in sorted(
            summary.knowledge_missing_by_intent.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            lines.append(f"| `{intent}` | {count} |")
    else:
        lines.append("| *(none)* | 0 |")
    lines.extend(
        [
            "",
            "### By suggested_action",
            "",
            "| Action | Missing hints |",
            "|--------|-------------:|",
        ],
    )
    if summary.knowledge_missing_by_action:
        for action, count in sorted(
            summary.knowledge_missing_by_action.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            lines.append(f"| `{action}` | {count} |")
    else:
        lines.append("| *(none)* | 0 |")
    lines.extend(
        [
            "",
            "## Draft health",
            "",
            f"- **average_draft_char_count:** {summary.average_draft_char_count}",
            f"- **draft_char_min:** {summary.draft_char_min}",
            f"- **draft_char_max:** {summary.draft_char_max}",
            f"- **draft_hard_max_chars:** {summary.draft_hard_max_chars}",
            f"- **draft_over_hard_max_count:** {summary.draft_over_hard_max_count}",
            "",
            "## Top inspection targets",
            "",
        ],
    )
    if summary.inspection_targets:
        lines.extend(
            [
                "| room_id | bucket | reason | intent | action |",
                "|---------|--------|--------|--------|--------|",
            ],
        )
        for item in summary.inspection_targets[:20]:
            lines.append(
                f"| `{item.room_id}` | {item.bucket} | {item.reason[:48]} | "
                f"`{item.detected_intent or '—'}` | `{item.suggested_action or '—'}` |",
            )
    else:
        lines.append("*(All runs ready for human review at sandbox level.)*")
    lines.extend(
        [
            "",
            "## Governance",
            "",
            "- Run after `run_agentic_sandbox_batch_report.py` to validate workflow readiness.",
            "- Not wired to operator console or production LangGraph.",
            "",
        ],
    )
    return "\n".join(lines)


def assert_readiness_output_safe(content: str) -> None:
    lowered = content.lower()
    for token in _FORBIDDEN_TEXT_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(f"readiness output must not contain forbidden token: {token}")
    for token in ("conversation transcript", "gold_reference_reply", '"messages"'):
        if token in lowered:
            raise ValueError(f"readiness output must not contain forbidden token: {token}")


def build_agentic_readiness_report(
    batch_runs_path: Path | str = DEFAULT_BATCH_RUNS_JSONL,
    *,
    summary_output: Path = DEFAULT_READINESS_SUMMARY_PATH,
    markdown_output: Path = DEFAULT_READINESS_REPORT_PATH,
    settings: AppSettings | None = None,
    generated_at_utc: str | None = None,
) -> AgenticReadinessSummary:
    """Load batch JSONL and write readiness JSON + markdown reports."""
    source = Path(batch_runs_path)
    records = load_batch_run_records(source)
    summary = summarize_agentic_readiness(
        records,
        source_batch_runs_path=str(source),
        settings=settings,
        generated_at_utc=generated_at_utc,
    )

    summary_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)

    json_text = json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2) + "\n"
    markdown = render_agentic_readiness_markdown(summary)

    assert_readiness_output_safe(json_text)
    assert_readiness_output_safe(markdown)

    summary_output.write_text(json_text, encoding="utf-8")
    markdown_output.write_text(markdown, encoding="utf-8")
    return summary
