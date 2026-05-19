"""Diagnose shadow replay zero-hit exports (aggregate-safe; no raw content)."""

from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.corpus_planning.pilot_pgvector_metadata_inventory import (
    PilotMetadataRow,
    build_pilot_metadata_inventory,
    fetch_pilot_metadata_rows,
)
from app.corpus_planning.pilot_retrieval_eval import (
    PilotMetadataFilter,
    record_matches_metadata_filter,
)
from app.corpus_planning.shadow_replay_jsonl_export import (
    _bounded_query_text,
    build_initial_state_from_snapshot,
    run_routing_pipeline,
)
from app.corpus_planning.shadow_replay_row_contract import (
    FORBIDDEN_SHADOW_REPLAY_SUBSTRINGS,
    assert_shadow_replay_row_safe,
)
from app.corpus_planning.shadow_retrieval_metrics_dashboard import load_shadow_retrieval_rows
from app.tickets.conversation_models import parse_conversation_ticket_snapshot

_FORBIDDEN_OUTPUT_KEYS = frozenset(
    {
        "query",
        "user_input",
        "content",
        "transcript",
        "messages",
        "vector",
        "embedding",
    }
)

_STANDARD_FILTER_CHECKS: tuple[tuple[str, PilotMetadataFilter], ...] = (
    (
        "ticket_label=support",
        PilotMetadataFilter(ticket_label="support"),
    ),
    (
        "ticket_label=complaint",
        PilotMetadataFilter(ticket_label="complaint"),
    ),
    (
        "ticket_label=fund",
        PilotMetadataFilter(ticket_label="fund"),
    ),
    (
        "ticket_label=support,route_label=general_vendor_support",
        PilotMetadataFilter(ticket_label="support", route_label="general_vendor_support"),
    ),
    (
        "ticket_label=complaint,route_label=escalation_review",
        PilotMetadataFilter(ticket_label="complaint", route_label="escalation_review"),
    ),
    (
        "ticket_label=fund,route_label=billing_review",
        PilotMetadataFilter(ticket_label="fund", route_label="billing_review"),
    ),
)


@dataclass
class ShadowReplayRowSummary:
    total_rows: int = 0
    ticket_label_counts: dict[str, int] = field(default_factory=dict)
    route_label_counts: dict[str, int] = field(default_factory=dict)
    review_priority_counts: dict[str, int] = field(default_factory=dict)
    retrieval_result_count_distribution: dict[str, int] = field(default_factory=dict)
    executor_called_count: int = 0
    distinct_query_hash_count: int = 0
    distinct_metadata_filter_patterns: int = 0
    metadata_filter_pattern_counts: dict[str, int] = field(default_factory=dict)
    gate_decision_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class QueryBuildDiagnosis:
    tickets_sampled: int = 0
    query_nonempty_count: int = 0
    query_empty_count: int = 0
    query_source_user_input_count: int = 0
    query_source_grounding_summary_count: int = 0
    distinct_query_hash_estimate: int = 0


@dataclass
class IndexFilterMatchDiagnosis:
    pgvector_available: bool = False
    pgvector_error: str | None = None
    namespace: str = ""
    index_version: str = ""
    index_row_count: int = 0
    index_ticket_label_counts: dict[str, int] = field(default_factory=dict)
    index_route_label_counts: dict[str, int] = field(default_factory=dict)
    index_review_priority_counts: dict[str, int] = field(default_factory=dict)
    standard_filter_match_counts: dict[str, int] = field(default_factory=dict)
    export_filter_pattern_match_counts: dict[str, int] = field(default_factory=dict)
    export_filter_patterns_all_zero_hits: bool = False


@dataclass
class ShadowReplayHitDiagnosis:
    shadow_replay_path: str
    replay_summary: ShadowReplayRowSummary
    query_diagnosis: QueryBuildDiagnosis | None = None
    index_diagnosis: IndexFilterMatchDiagnosis | None = None
    findings: list[str] = field(default_factory=list)


def assert_safe_diagnosis_output(text: str) -> None:
    lowered = text.lower()
    for key in _FORBIDDEN_OUTPUT_KEYS:
        if f'"{key}"' in lowered:
            raise ValueError(f"diagnosis output must not reference forbidden key: {key}")
    for token in FORBIDDEN_SHADOW_REPLAY_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(f"diagnosis output must not contain forbidden token: {token}")


def _filter_pattern_key(metadata_filter: Any) -> str:
    if not isinstance(metadata_filter, dict):
        return "(none)"
    parts = [f"{key}={metadata_filter[key]}" for key in sorted(metadata_filter)]
    return ",".join(parts) if parts else "(empty)"


def summarize_shadow_replay_rows(rows: list[dict[str, Any]]) -> ShadowReplayRowSummary:
    """Aggregate-safe counts from shadow replay JSONL rows."""
    ticket_labels: Counter[str] = Counter()
    route_labels: Counter[str] = Counter()
    review_priorities: Counter[str] = Counter()
    result_counts: Counter[str] = Counter()
    gate_decisions: Counter[str] = Counter()
    filter_patterns: Counter[str] = Counter()
    query_hashes: set[str] = set()
    executor_called = 0

    for row in rows:
        assert_shadow_replay_row_safe(row)
        ticket_labels[str(row.get("ticket_label") or "(none)")] += 1
        route_labels[str(row.get("route_label") or "(none)")] += 1
        review_priorities[str(row.get("review_priority") or "(none)")] += 1
        rc = row.get("retrieval_result_count")
        result_counts["(null)" if rc is None else str(int(rc))] += 1
        gate_decisions[str(row.get("retrieval_gate_decision") or "(none)")] += 1
        filter_patterns[_filter_pattern_key(row.get("retrieval_metadata_filter"))] += 1
        qh = row.get("retrieval_query_hash")
        if isinstance(qh, str) and qh.strip():
            query_hashes.add(qh.strip())
        if row.get("executor_called"):
            executor_called += 1

    return ShadowReplayRowSummary(
        total_rows=len(rows),
        ticket_label_counts=dict(ticket_labels),
        route_label_counts=dict(route_labels),
        review_priority_counts=dict(review_priorities),
        retrieval_result_count_distribution=dict(result_counts),
        executor_called_count=executor_called,
        distinct_query_hash_count=len(query_hashes),
        distinct_metadata_filter_patterns=len(filter_patterns),
        metadata_filter_pattern_counts=dict(filter_patterns),
        gate_decision_counts=dict(gate_decisions),
    )


def diagnose_query_build_from_ticket_export(
    ticket_export_path: Path,
    *,
    sample_limit: int | None = None,
) -> QueryBuildDiagnosis:
    """Simulate export query construction without logging raw query text."""
    lines = ticket_export_path.read_text(encoding="utf-8").splitlines()
    nonempty = 0
    empty = 0
    from_user_input = 0
    from_grounding = 0
    hashes: set[str] = set()
    sampled = 0

    for raw_line in lines:
        if not raw_line.strip():
            continue
        if sample_limit is not None and sampled >= sample_limit:
            break
        try:
            snapshot = parse_conversation_ticket_snapshot(raw_line)
        except (json.JSONDecodeError, ValueError):
            continue
        sampled += 1
        state = build_initial_state_from_snapshot(snapshot)
        try:
            state = run_routing_pipeline(state)
        except Exception:
            pass
        user_text = (state.get("user_input") or "").strip()
        grounding = (state.get("grounding_summary") or "").strip()
        query = _bounded_query_text(state)
        if query:
            nonempty += 1
        else:
            empty += 1
        if user_text:
            from_user_input += 1
        elif grounding:
            from_grounding += 1
        from app.corpus_planning.retrieval_tool_models import query_hash

        if query:
            hashes.add(query_hash(query))

    return QueryBuildDiagnosis(
        tickets_sampled=sampled,
        query_nonempty_count=nonempty,
        query_empty_count=empty,
        query_source_user_input_count=from_user_input,
        query_source_grounding_summary_count=from_grounding,
        distinct_query_hash_estimate=len(hashes),
    )


def _export_filter_to_pilot(metadata_filter: dict[str, Any]) -> PilotMetadataFilter:
    return PilotMetadataFilter(
        ticket_label=str(metadata_filter["ticket_label"]).strip().lower()
        if metadata_filter.get("ticket_label")
        else None,
        route_label=str(metadata_filter["route_label"]).strip()
        if metadata_filter.get("route_label")
        else None,
        review_priority=str(metadata_filter["review_priority"]).strip()
        if metadata_filter.get("review_priority")
        else None,
    )


def _count_filter_matches(rows: list[PilotMetadataRow], filt: PilotMetadataFilter) -> int:
    return sum(1 for row in rows if record_matches_metadata_filter(row.metadata, filt))


def diagnose_index_filter_matches(
    *,
    namespace: str,
    index_version: str,
    database_url: str | None,
    table_name: str = "rag_vector_records",
    export_filter_patterns: dict[str, int] | None = None,
    profile: str = "semantic_pgvector",
) -> IndexFilterMatchDiagnosis:
    """Compare pgvector index metadata against standard and export filter patterns."""
    diagnosis = IndexFilterMatchDiagnosis(namespace=namespace, index_version=index_version)
    url = (database_url or "").strip() or os.environ.get("PGVECTOR_DATABASE_URL", "").strip()
    if not url:
        diagnosis.pgvector_error = "PGVECTOR_DATABASE_URL not configured"
        return diagnosis

    try:
        index_rows = fetch_pilot_metadata_rows(
            url,
            table_name=table_name,
            namespace=namespace,
            index_version=index_version,
        )
    except Exception as exc:  # noqa: BLE001 — diagnosis reports connectivity errors
        diagnosis.pgvector_error = str(exc)
        return diagnosis

    diagnosis.pgvector_available = True
    inventory = build_pilot_metadata_inventory(
        index_rows,
        namespace=namespace,
        index_version=index_version,
        profile=profile,
    )
    diagnosis.index_row_count = inventory.row_count
    diagnosis.index_ticket_label_counts = dict(inventory.ticket_label_counts)
    diagnosis.index_route_label_counts = dict(inventory.route_label_counts)
    diagnosis.index_review_priority_counts = dict(inventory.review_priority_counts)

    for label, filt in _STANDARD_FILTER_CHECKS:
        diagnosis.standard_filter_match_counts[label] = _count_filter_matches(index_rows, filt)

    if export_filter_patterns:
        for pattern, _replay_count in export_filter_patterns.items():
            if pattern in {"(none)", "(empty)"}:
                diagnosis.export_filter_pattern_match_counts[pattern] = 0
                continue
            parts = dict(item.split("=", 1) for item in pattern.split(",") if "=" in item)
            filt = _export_filter_to_pilot(parts)
            diagnosis.export_filter_pattern_match_counts[pattern] = _count_filter_matches(
                index_rows,
                filt,
            )

    match_counts = list(diagnosis.export_filter_pattern_match_counts.values())
    diagnosis.export_filter_patterns_all_zero_hits = bool(match_counts) and all(
        count == 0 for count in match_counts
    )
    return diagnosis


def build_shadow_replay_hit_findings(
    replay: ShadowReplayRowSummary,
    *,
    query: QueryBuildDiagnosis | None,
    index: IndexFilterMatchDiagnosis | None,
) -> list[str]:
    """Derive human-readable diagnosis findings (no raw content)."""
    findings: list[str] = []

    zero_result_rows = replay.retrieval_result_count_distribution.get("0", 0)
    if replay.total_rows and zero_result_rows == replay.total_rows:
        findings.append(
            f"All {replay.total_rows} shadow replay rows recorded retrieval_result_count=0.",
        )
    if replay.executor_called_count == replay.total_rows and replay.total_rows:
        findings.append(
            "executor_called=true on every row — zero hits are not from gate skip/deny.",
        )

    if query is not None:
        if query.query_empty_count:
            findings.append(
                f"query_empty_count={query.query_empty_count} "
                f"of {query.tickets_sampled} sampled tickets "
                "(export uses user_input/grounding_summary).",
            )
        elif query.tickets_sampled:
            findings.append(
                f"query_nonempty_count={query.query_nonempty_count} "
                f"of {query.tickets_sampled} sampled tickets; distinct_query_hash_estimate="
                f"{query.distinct_query_hash_estimate}.",
            )

    if index is not None and index.pgvector_available:
        findings.append(
            f"pgvector index row_count={index.index_row_count} for "
            f"{index.namespace}/{index.index_version}.",
        )
        if index.export_filter_patterns_all_zero_hits:
            findings.append(
                "Every export metadata_filter pattern matches 0 index rows — "
                "filters are over-constrained vs indexed metadata.",
            )
        fund_route_only = index.standard_filter_match_counts.get(
            "ticket_label=fund,route_label=billing_review",
            0,
        )
        fund_full = next(
            (
                count
                for pattern, count in index.export_filter_pattern_match_counts.items()
                if "ticket_label=fund" in pattern and "review_priority=LOW" in pattern
            ),
            0,
        )
        if fund_route_only > 0 and fund_full == 0:
            findings.append(
                "fund rows match ticket_label+route_label in index, but adding "
                "review_priority=LOW (export default) matches 0 rows — "
                "index uses review_priority values like 'high'/'normal', not 'LOW'/'MEDIUM'.",
            )
        support_route = index.standard_filter_match_counts.get(
            "ticket_label=support,route_label=general_vendor_support",
            0,
        )
        support_with_low = next(
            (
                count
                for pattern, count in index.export_filter_pattern_match_counts.items()
                if "ticket_label=support" in pattern and "review_priority=LOW" in pattern
            ),
            0,
        )
        if support_route > 0 and support_with_low == 0:
            findings.append(
                "support+route_label matches index rows, but export filter including "
                "review_priority=LOW matches none — vocabulary mismatch with index.",
            )
        findings.append(
            "Standalone smoke test typically omits review_priority on CLI; pre-Step-142 "
            "export included review_priority from build_review_queue_metadata — "
            "explained 5 hits vs 0. Step 142 omits review_priority from export filters.",
        )
    elif index is not None and index.pgvector_error:
        findings.append(f"pgvector index check skipped: {index.pgvector_error}")

    if replay.distinct_query_hash_count <= 3 and replay.total_rows > 10:
        findings.append(
            f"Only {replay.distinct_query_hash_count} distinct retrieval_query_hash values "
            "across replay rows — hashes are expected to vary when queries differ.",
        )

    return findings


def run_shadow_replay_hit_diagnosis(
    shadow_replay_path: Path,
    *,
    namespace: str | None = None,
    index_version: str | None = None,
    database_url: str | None = None,
    table_name: str = "rag_vector_records",
    ticket_export_path: Path | None = None,
    query_sample_limit: int | None = 166,
) -> ShadowReplayHitDiagnosis:
    """Run full shadow replay hit-count diagnosis."""
    rows = load_shadow_retrieval_rows(shadow_replay_path)
    replay_summary = summarize_shadow_replay_rows(rows)

    query_diagnosis = None
    if ticket_export_path is not None and ticket_export_path.is_file():
        query_diagnosis = diagnose_query_build_from_ticket_export(
            ticket_export_path,
            sample_limit=query_sample_limit,
        )

    ns = namespace or "vendor_ticket_real_pilot_balanced"
    version = index_version or "pilot_balanced_v1"
    index_diagnosis = diagnose_index_filter_matches(
        namespace=ns,
        index_version=version,
        database_url=database_url,
        table_name=table_name,
        export_filter_patterns=replay_summary.metadata_filter_pattern_counts,
    )

    findings = build_shadow_replay_hit_findings(
        replay_summary,
        query=query_diagnosis,
        index=index_diagnosis,
    )

    return ShadowReplayHitDiagnosis(
        shadow_replay_path=str(shadow_replay_path),
        replay_summary=replay_summary,
        query_diagnosis=query_diagnosis,
        index_diagnosis=index_diagnosis,
        findings=findings,
    )


def diagnosis_to_dict(diagnosis: ShadowReplayHitDiagnosis) -> dict[str, Any]:
    """Serialize diagnosis for JSON report."""
    payload: dict[str, Any] = {
        "shadow_replay_path": diagnosis.shadow_replay_path,
        "replay_summary": {
            "total_rows": diagnosis.replay_summary.total_rows,
            "ticket_label_counts": diagnosis.replay_summary.ticket_label_counts,
            "route_label_counts": diagnosis.replay_summary.route_label_counts,
            "review_priority_counts": diagnosis.replay_summary.review_priority_counts,
            "retrieval_result_count_distribution": (
                diagnosis.replay_summary.retrieval_result_count_distribution
            ),
            "executor_called_count": diagnosis.replay_summary.executor_called_count,
            "distinct_query_hash_count": diagnosis.replay_summary.distinct_query_hash_count,
            "distinct_metadata_filter_patterns": (
                diagnosis.replay_summary.distinct_metadata_filter_patterns
            ),
            "metadata_filter_pattern_counts": (
                diagnosis.replay_summary.metadata_filter_pattern_counts
            ),
            "gate_decision_counts": diagnosis.replay_summary.gate_decision_counts,
        },
        "findings": diagnosis.findings,
    }
    if diagnosis.query_diagnosis is not None:
        q = diagnosis.query_diagnosis
        payload["query_diagnosis"] = {
            "tickets_sampled": q.tickets_sampled,
            "query_nonempty_count": q.query_nonempty_count,
            "query_empty_count": q.query_empty_count,
            "query_source_user_input_count": q.query_source_user_input_count,
            "query_source_grounding_summary_count": q.query_source_grounding_summary_count,
            "distinct_query_hash_estimate": q.distinct_query_hash_estimate,
        }
    if diagnosis.index_diagnosis is not None:
        idx = diagnosis.index_diagnosis
        payload["index_diagnosis"] = {
            "pgvector_available": idx.pgvector_available,
            "pgvector_error": idx.pgvector_error,
            "namespace": idx.namespace,
            "index_version": idx.index_version,
            "index_row_count": idx.index_row_count,
            "index_ticket_label_counts": idx.index_ticket_label_counts,
            "index_route_label_counts": idx.index_route_label_counts,
            "index_review_priority_counts": idx.index_review_priority_counts,
            "standard_filter_match_counts": idx.standard_filter_match_counts,
            "export_filter_pattern_match_counts": idx.export_filter_pattern_match_counts,
            "export_filter_patterns_all_zero_hits": idx.export_filter_patterns_all_zero_hits,
        }
    return payload


def format_diagnosis_markdown(diagnosis: ShadowReplayHitDiagnosis) -> str:
    """Render Markdown diagnosis report."""
    r = diagnosis.replay_summary
    lines = [
        "# Shadow Replay Hit-Count Diagnosis",
        "",
        f"**Source:** `{diagnosis.shadow_replay_path}`  ",
        "**Scope:** Aggregate diagnostics only; no raw queries, content, or vectors.",
        "",
        "## Shadow replay row summary",
        "",
        f"- **total_rows:** {r.total_rows}",
        f"- **executor_called_count:** {r.executor_called_count}",
        f"- **distinct_query_hash_count:** {r.distinct_query_hash_count}",
        f"- **distinct_metadata_filter_patterns:** {r.distinct_metadata_filter_patterns}",
        "",
        "### Gate decision counts",
        "",
        "| Decision | Count |",
        "|----------|------:|",
    ]
    for decision, count in sorted(r.gate_decision_counts.items()):
        lines.append(f"| {decision} | {count} |")

    lines.extend(["", "### Retrieval result count distribution", ""])
    lines.extend(["| result_count | Count |", "|-------------|------:|"])
    for bucket, count in sorted(r.retrieval_result_count_distribution.items()):
        lines.append(f"| {bucket} | {count} |")

    lines.extend(["", "### Ticket label counts", ""])
    lines.extend(["| ticket_label | Count |", "|--------------|------:|"])
    for label, count in sorted(r.ticket_label_counts.items()):
        lines.append(f"| {label} | {count} |")

    lines.extend(["", "### Route label counts (export)", ""])
    lines.extend(["| route_label | Count |", "|-------------|------:|"])
    for label, count in sorted(r.route_label_counts.items()):
        lines.append(f"| {label} | {count} |")

    lines.extend(["", "### Export metadata_filter patterns", ""])
    lines.extend(["| pattern | replay_rows |", "|---------|------------:|"])
    for pattern, count in sorted(r.metadata_filter_pattern_counts.items()):
        lines.append(f"| `{pattern}` | {count} |")

    if diagnosis.query_diagnosis is not None:
        q = diagnosis.query_diagnosis
        lines.extend(
            [
                "",
                "## Query build diagnosis (ticket export sample)",
                "",
                f"- **tickets_sampled:** {q.tickets_sampled}",
                f"- **query_nonempty_count:** {q.query_nonempty_count}",
                f"- **query_empty_count:** {q.query_empty_count}",
                f"- **query_source_user_input_count:** {q.query_source_user_input_count}",
                "- **query_source_grounding_summary_count:** "
                f"{q.query_source_grounding_summary_count}",
                f"- **distinct_query_hash_estimate:** {q.distinct_query_hash_estimate}",
            ]
        )

    if diagnosis.index_diagnosis is not None:
        idx = diagnosis.index_diagnosis
        lines.extend(["", "## Pgvector index diagnosis", ""])
        if not idx.pgvector_available:
            lines.append(f"- **unavailable:** {idx.pgvector_error or 'unknown'}")
        else:
            lines.extend(
                [
                    f"- **namespace / index_version:** `{idx.namespace}` / `{idx.index_version}`",
                    f"- **index_row_count:** {idx.index_row_count}",
                    "",
                    "### Index ticket_label counts",
                    "",
                    "| ticket_label | Count |",
                    "|--------------|------:|",
                ]
            )
            for label, count in sorted(idx.index_ticket_label_counts.items()):
                lines.append(f"| {label} | {count} |")
            lines.extend(
                [
                    "",
                    "### Index route_label counts",
                    "",
                    "| route_label | Count |",
                    "|-------------|------:|",
                ]
            )
            for label, count in sorted(idx.index_route_label_counts.items()):
                lines.append(f"| {label} | {count} |")
            lines.extend(
                [
                    "",
                    "### Index review_priority counts",
                    "",
                    "| review_priority | Count |",
                    "|-----------------|------:|",
                ]
            )
            for label, count in sorted(idx.index_review_priority_counts.items()):
                lines.append(f"| {label} | {count} |")
            lines.extend(
                [
                    "",
                    "### Standard filter match counts (index rows)",
                    "",
                    "| filter | matching_rows |",
                    "|--------|--------------:|",
                ]
            )
            for label, count in sorted(idx.standard_filter_match_counts.items()):
                lines.append(f"| `{label}` | {count} |")
            lines.extend(
                [
                    "",
                    "### Export filter pattern match counts (index rows)",
                    "",
                    "| export_pattern | matching_rows |",
                    "|----------------|--------------:|",
                ]
            )
            for pattern, count in sorted(idx.export_filter_pattern_match_counts.items()):
                lines.append(f"| `{pattern}` | {count} |")

    lines.extend(["", "## Findings", ""])
    for item in diagnosis.findings:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Governance",
            "",
            "- Diagnosis only; does not enable retrieval consumption or change gate rules.",
            "- No raw ticket text, queries, hits, or vectors in this report.",
            "",
        ]
    )
    return "\n".join(lines)


def write_shadow_replay_hit_diagnosis_report(
    diagnosis: ShadowReplayHitDiagnosis,
    *,
    json_output: Path,
    markdown_output: Path,
) -> None:
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    payload = diagnosis_to_dict(diagnosis)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    assert_safe_diagnosis_output(json_text)
    json_output.write_text(json_text, encoding="utf-8")
    markdown = format_diagnosis_markdown(diagnosis)
    assert_safe_diagnosis_output(markdown)
    markdown_output.write_text(markdown, encoding="utf-8")
