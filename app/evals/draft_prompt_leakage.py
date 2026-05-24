"""Draft prompt leakage guards — first-turn isolation and benchmark gold protection."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.evals.draft_generation_mode import DraftGenerationMode
from app.evals.first_turn_draft_context import (
    first_turn_text_from_case,
    first_turn_text_from_ticket,
)
from app.llm.types import LLMMessage
from app.operator_console.console_models import OperatorTicket
from app.operator_console.knowledge_hints import KnowledgeHint
from app.workflows.operational_entity_extraction import (
    EntityType,
    extract_operational_entities,
    normalize_digits,
)
from app.workflows.seller_notification_detection import normalize_persian_arabic_digits

_STABLE_LEAK_ENTITY_TYPES = frozenset(
    {
        EntityType.ORDER_ID,
        EntityType.PRODUCT_ID,
        EntityType.TRACKING_CODE,
    },
)
_MIN_ENTITY_LEAK_CHECK_LEN = 6
_INC_ORDER_PREFIX_RE = re.compile(r"^INC[-_]?(\d{7})$", re.IGNORECASE)

ALLOWED_SNAPSHOT_KEYS = frozenset(
    {
        "original_vendor_issue_preview",
        "latest_vendor_message",
        "recent_context_preview",
    },
)

FIRST_TURN_SNAPSHOT_KEYS = frozenset({"original_vendor_issue_preview"})

FIRST_TURN_EXCLUDED_FIELD_NAMES = (
    "snapshot_before_reply.latest_vendor_message",
    "snapshot_before_reply.recent_context_preview",
    "open_ticket_preview",
    "ticket_text_preview",
    "latest_vendor_message",
    "recent_context_preview",
)

_FIRST_TURN_FORBIDDEN_PROMPT_LABELS = (
    "latest_vendor_message",
    "recent_context_preview",
    "open_ticket_preview",
    "ticket_text_preview",
    "آخرین پیام فروشنده",
    "زمینه اخیر",
)

_FORBIDDEN_PROMPT_MARKERS = (
    "gold_reference_reply",
    "gold reference",
    "human reply to copy",
    "پاسخ مرجع",
    "future_support_reply",
    "conversation transcript",
    "conversation_transcript",
    '"messages"',
    "draft_response",
    "final_response",
    "responder_reply_text",
)

_MIN_FORBIDDEN_SUBSTRING_LEN = 16


def prompt_text_from_messages(messages: Sequence[LLMMessage]) -> str:
    return "\n".join(message.content for message in messages)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def safe_snapshot_before_reply(
    snap: Mapping[str, Any] | None,
    *,
    mode: DraftGenerationMode = DraftGenerationMode.FIRST_TURN_ONLY,
) -> dict[str, str | None]:
    """Extract snapshot fields allowed for the active draft generation mode."""
    if not isinstance(snap, Mapping):
        if mode == DraftGenerationMode.FIRST_TURN_ONLY:
            keys = FIRST_TURN_SNAPSHOT_KEYS
        else:
            keys = ALLOWED_SNAPSHOT_KEYS
        return {key: None for key in keys}
    if mode == DraftGenerationMode.FIRST_TURN_ONLY:
        return {key: _optional_str(snap.get(key)) for key in FIRST_TURN_SNAPSHOT_KEYS}
    return {key: _optional_str(snap.get(key)) for key in ALLOWED_SNAPSHOT_KEYS}


def list_excluded_prompt_fields(
    mode: DraftGenerationMode = DraftGenerationMode.FIRST_TURN_ONLY,
) -> list[str]:
    """Field names intentionally omitted from prompts for the given mode."""
    if mode == DraftGenerationMode.FIRST_TURN_ONLY:
        return list(FIRST_TURN_EXCLUDED_FIELD_NAMES)
    return []


def list_included_prompt_fields(
    case: Mapping[str, Any],
    *,
    intent_result: Any,
    suggested_action: str,
    policy_hints: Sequence[KnowledgeHint],
    mode: DraftGenerationMode = DraftGenerationMode.FIRST_TURN_ONLY,
) -> list[str]:
    """Allowlisted field names included in offline/operator draft prompts."""
    snap = safe_snapshot_before_reply(case.get("snapshot_before_reply"), mode=mode)  # type: ignore[arg-type]
    fields: list[str] = []
    for key, value in snap.items():
        if value:
            fields.append(f"snapshot_before_reply.{key}")
    if case.get("ticket_label") is not None:
        fields.append("ticket_label")
    if case.get("route_label") is not None:
        fields.append("route_label")
    if case.get("seller_intent_type"):
        fields.append("seller_intent_type")
    if case.get("seller_operational_request_type"):
        fields.append("seller_operational_request_type")
    fields.append("detected_intent")
    fields.append("suggested_action")
    if getattr(intent_result, "extracted_order_ids", None):
        fields.append("extracted_order_ids")
    if getattr(intent_result, "extracted_tracking_code", None):
        fields.append("extracted_tracking_code")
    if policy_hints:
        fields.append("policy_hints")
    return fields


def _normalize_allowed_values(allowed_values: Sequence[str] | None) -> tuple[str, ...]:
    if not allowed_values:
        return ()
    return tuple(value.strip() for value in allowed_values if value and str(value).strip())


def _forbidden_fragment_allowed(
    forbidden_fragment: str,
    allowed_values: Sequence[str],
) -> bool:
    """True when a forbidden substring/prefix is part of allowed first-turn source text."""
    fragment = forbidden_fragment.strip()
    if not fragment:
        return False
    for allowed in allowed_values:
        if fragment in allowed:
            return True
    return False


def _thread_forbidden_values_excluding_original(
    thread_values: Sequence[str],
    original: str | None,
) -> list[str]:
    """Keep only thread preview values that differ from the allowed first seller message."""
    orig = (original or "").strip()
    excluded: list[str] = []
    for value in thread_values:
        text = value.strip()
        if not text:
            continue
        if orig and text == orig:
            continue
        excluded.append(text)
    return excluded


def _snapshot_thread_values_for_forbidden_check(
    case: Mapping[str, Any],
    *,
    ticket: OperatorTicket | None = None,
) -> list[str]:
    """Collect latest-thread snapshot text that must not appear in first_turn_only prompts."""
    values: list[str] = []
    snap = case.get("snapshot_before_reply")
    if isinstance(snap, Mapping):
        for key in ("latest_vendor_message", "recent_context_preview"):
            raw = snap.get(key)
            if isinstance(raw, str) and raw.strip():
                values.append(raw.strip())
    if ticket is not None:
        for value in (
            ticket.latest_vendor_message,
            ticket.recent_context_preview,
            ticket.open_ticket_preview,
            ticket.ticket_text_preview,
        ):
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
    open_preview = case.get("open_ticket_preview")
    if isinstance(open_preview, str) and open_preview.strip():
        values.append(open_preview.strip())
    return values


def extract_forbidden_values_from_benchmark_case(
    case: Mapping[str, Any],
    *,
    mode: DraftGenerationMode = DraftGenerationMode.FIRST_TURN_ONLY,
) -> list[str]:
    """Collect benchmark-only text that must never appear in draft prompts."""
    forbidden: list[str] = []

    def _add(text: str | None) -> None:
        if text and text not in forbidden:
            forbidden.append(text)

    gold = case.get("gold_reference_reply")
    if isinstance(gold, str):
        _add(gold.strip())

    snap_for_original = case.get("snapshot_before_reply")
    original_for_case: str | None = None
    if isinstance(snap_for_original, Mapping):
        original_for_case = _optional_str(snap_for_original.get("original_vendor_issue_preview"))
    if not original_for_case:
        original_for_case = first_turn_text_from_case(case) or None

    for key in (
        "future_support_reply",
        "responder_reply_text",
        "conversation_transcript",
        "transcript",
        "user_input",
        "draft_response",
        "final_response",
        "retrieved_context",
        "query",
        "open_ticket_preview",
        "ticket_text_preview",
    ):
        value = case.get(key)
        if isinstance(value, str):
            text = value.strip()
            if (
                mode == DraftGenerationMode.FIRST_TURN_ONLY
                and original_for_case
                and text == original_for_case
            ):
                continue
            _add(text)

    messages = case.get("messages")
    if isinstance(messages, list):
        for item in messages:
            if isinstance(item, str):
                _add(item.strip())
                continue
            if not isinstance(item, Mapping):
                continue
            for msg_key in ("text", "content", "body", "message"):
                raw = item.get(msg_key)
                if isinstance(raw, str):
                    _add(raw.strip())

    snap = case.get("snapshot_before_reply")
    original_preview: str | None = None
    if isinstance(snap, Mapping):
        original_preview = _optional_str(snap.get("original_vendor_issue_preview"))
        for key, value in snap.items():
            if key not in ALLOWED_SNAPSHOT_KEYS and isinstance(value, str):
                _add(value.strip())
        if mode == DraftGenerationMode.FIRST_TURN_ONLY:
            thread_values = _snapshot_thread_values_for_forbidden_check(case)
            for value in _thread_forbidden_values_excluding_original(
                thread_values,
                original_preview,
            ):
                _add(value)

    sequence = case.get("sequence")
    if isinstance(sequence, Mapping):
        for key in ("responder_reply_preview", "future_support_reply"):
            raw = sequence.get(key)
            if isinstance(raw, str):
                _add(raw.strip())

    return forbidden


def _csv_entity_tokens(value: str | None) -> list[str]:
    if not value or not str(value).strip():
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _ticket_precomputed_entity_tokens(ticket: OperatorTicket) -> list[str]:
    tokens: list[str] = []
    for value in (
        ticket.extracted_order_id,
        ticket.extracted_order_ids,
        ticket.extracted_product_ids,
        ticket.extracted_tracking_code,
    ):
        tokens.extend(_csv_entity_tokens(value if isinstance(value, str) else None))
    return tokens


def extract_forbidden_values_from_operator_ticket(
    ticket: OperatorTicket,
    *,
    mode: DraftGenerationMode = DraftGenerationMode.FIRST_TURN_ONLY,
) -> list[str]:
    """Fields on OperatorTicket that must not leak into draft prompts."""
    forbidden: list[str] = []

    def _add(text: str | None) -> None:
        if text and text not in forbidden:
            forbidden.append(text)

    first_turn = (
        first_turn_text_from_ticket(ticket) if mode == DraftGenerationMode.FIRST_TURN_ONLY else None
    )

    for value in (
        ticket.ticket_text_preview,
        ticket.open_ticket_preview,
    ):
        if isinstance(value, str):
            text = value.strip()
            if first_turn and text == first_turn:
                continue
            _add(text)

    if mode == DraftGenerationMode.FIRST_TURN_ONLY:
        full_first = (ticket.full_first_vendor_message_text or "").strip()
        if full_first and full_first != (first_turn or ""):
            _add(full_first)
        for value in (
            ticket.latest_vendor_message,
            ticket.recent_context_preview,
        ):
            if isinstance(value, str):
                text = value.strip()
                if first_turn and text == first_turn:
                    continue
                if full_first and text == full_first:
                    continue
                _add(text)
        allowed = _allowed_values_from_first_turn(
            first_turn or "",
            full_first_turn_text=full_first or None,
        )
        for token in _ticket_precomputed_entity_tokens(ticket):
            is_allowed, _ = _is_allowed_first_turn_entity_value(
                token,
                display_text=first_turn or "",
                full_first_turn_text=full_first or None,
                allowed=allowed,
            )
            if not is_allowed:
                _add(token)

    return forbidden


def assert_first_turn_thread_fields_absent(prompt: str) -> None:
    """Fail if first-turn-only prompt includes thread-context field labels or markers."""
    lowered = prompt.lower()
    for label in _FIRST_TURN_FORBIDDEN_PROMPT_LABELS:
        if label.lower() in lowered:
            raise ValueError(
                f"first_turn_only prompt must not reference thread field: {label}",
            )


def assert_no_prompt_leakage(
    prompt: str,
    forbidden_values: Sequence[str],
    *,
    forbidden_markers: Sequence[str] = _FORBIDDEN_PROMPT_MARKERS,
    mode: DraftGenerationMode = DraftGenerationMode.FIRST_TURN_ONLY,
    allowed_values: Sequence[str] | None = None,
) -> None:
    """Fail closed if prompt text may contain gold, future replies, or thread context."""
    if not prompt.strip():
        raise ValueError("prompt must be non-empty")
    lowered = prompt.lower()
    for marker in forbidden_markers:
        if marker in lowered:
            raise ValueError(f"prompt must not contain forbidden marker: {marker}")

    if mode == DraftGenerationMode.FIRST_TURN_ONLY:
        assert_first_turn_thread_fields_absent(prompt)

    allowed = _normalize_allowed_values(allowed_values)

    for value in forbidden_values:
        text = value.strip()
        if not text:
            continue
        if text in prompt:
            if allowed and _forbidden_fragment_allowed(text, allowed):
                continue
            raise ValueError("prompt must not contain forbidden benchmark/reference text")
        if len(text) >= _MIN_FORBIDDEN_SUBSTRING_LEN:
            prefix = text[:_MIN_FORBIDDEN_SUBSTRING_LEN]
            if prefix in prompt:
                if allowed and _forbidden_fragment_allowed(prefix, allowed):
                    continue
                raise ValueError("prompt must not contain forbidden text prefix")


def _entity_values_from_text(text: str) -> set[str]:
    """Normalized stable entity values (order/product/tracking) from preview text."""
    if not text.strip():
        return set()
    result = extract_operational_entities(text)
    values: set[str] = set()
    for entity in result.entities:
        if entity.entity_type not in _STABLE_LEAK_ENTITY_TYPES:
            continue
        if entity.normalized_value:
            values.add(entity.normalized_value)
    return values


def _equivalent_forms(value: str) -> set[str]:
    """Normalized equivalence classes for order IDs (INC-1234567 == 1234567)."""
    raw = value.strip()
    if not raw:
        return set()
    digits_only = normalize_digits(raw)
    forms: set[str] = {digits_only}
    if digits_only.isdigit():
        forms.add(digits_only)
        if len(digits_only) == 7:
            forms.add(f"INC-{digits_only}")
            forms.add(f"INC_{digits_only}")
    match = _INC_ORDER_PREFIX_RE.match(digits_only.upper().replace(" ", ""))
    if match:
        forms.add(match.group(1))
        forms.add(f"INC-{match.group(1)}")
    return {normalize_digits(item) for item in forms if item}


def _normalize_for_entity_match(text: str) -> str:
    return normalize_persian_arabic_digits(normalize_digits(text))


def _digit_tokens_in_text(text: str, *, min_length: int = _MIN_ENTITY_LEAK_CHECK_LEN) -> set[str]:
    if not text.strip():
        return set()
    normalized = _normalize_for_entity_match(text)
    return {token for token in re.findall(r"\d+", normalized) if len(token) >= min_length}


def _allowed_values_from_first_turn(
    first_turn_text: str,
    *,
    full_first_turn_text: str | None = None,
) -> set[str]:
    """Values permitted when they appear in first-turn display or full extraction source."""
    allowed: set[str] = set()
    for text in (first_turn_text, full_first_turn_text or ""):
        if not text.strip():
            continue
        allowed |= _entity_values_from_text(text)
        allowed |= _digit_tokens_in_text(text)
    expanded: set[str] = set()
    for value in allowed:
        expanded |= _equivalent_forms(value)
    return {item for item in expanded if item}


def _is_allowed_first_turn_entity_value(
    value: str,
    *,
    display_text: str,
    full_first_turn_text: str | None,
    allowed: set[str],
) -> tuple[bool, bool]:
    """Return (allowed, allowed_by_full_first_turn_source_only)."""
    if value in allowed or any(form in allowed for form in _equivalent_forms(value)):
        in_display = _value_literal_in_text(value, display_text)
        in_full = bool(full_first_turn_text) and _value_literal_in_text(
            value,
            full_first_turn_text,
        )
        return True, bool(in_full and not in_display)
    return False, False


def _value_literal_in_text(value: str, text: str) -> bool:
    if not value or not text.strip():
        return False
    norm_text = _normalize_for_entity_match(text)
    for form in _equivalent_forms(value):
        if len(form) >= _MIN_ENTITY_LEAK_CHECK_LEN and form in norm_text:
            return True
    return False


def _prompt_contains_entity_value(prompt: str, value: str) -> bool:
    return _value_literal_in_text(value, prompt)


def _iter_labeled_thread_sources(
    thread_texts: Sequence[str],
    *,
    ticket: OperatorTicket | None = None,
) -> list[tuple[str, str]]:
    """Thread/open fields that may contain later-only entities (labeled for diagnostics)."""
    labeled: list[tuple[str, str]] = []
    seen: set[str] = set()
    if ticket is not None:
        for field in (
            "latest_vendor_message",
            "recent_context_preview",
            "open_ticket_preview",
            "ticket_text_preview",
        ):
            raw = getattr(ticket, field, None)
            if isinstance(raw, str) and raw.strip():
                text = raw.strip()
                if text not in seen:
                    labeled.append((field, text))
                    seen.add(text)
    for index, raw in enumerate(thread_texts):
        if not isinstance(raw, str) or not raw.strip():
            continue
        text = raw.strip()
        if text in seen:
            continue
        labeled.append((f"thread_text[{index}]", text))
        seen.add(text)
    return labeled


def analyze_first_turn_entity_leakage(
    prompt: str,
    *,
    first_turn_text: str,
    thread_texts: Sequence[str],
    ticket: OperatorTicket | None = None,
    full_first_turn_text: str | None = None,
) -> dict[str, Any]:
    """Safe diagnostics for first-turn entity isolation (no full prompt/transcript echo)."""
    full_text = (full_first_turn_text or "").strip()
    if not full_text and ticket is not None:
        full_text = (ticket.full_first_vendor_message_text or "").strip()
    allowed = _allowed_values_from_first_turn(first_turn_text, full_first_turn_text=full_text)
    later_only_by_field: dict[str, list[str]] = {}
    forbidden_later_only: list[str] = []
    prompt_hits: list[str] = []
    leak_rows: list[dict[str, Any]] = []

    for source_field, text in _iter_labeled_thread_sources(thread_texts, ticket=ticket):
        field_values = _entity_values_from_text(text)
        later_for_field: list[str] = []
        for value in sorted(field_values):
            is_allowed, _ = _is_allowed_first_turn_entity_value(
                value,
                display_text=first_turn_text,
                full_first_turn_text=full_text or None,
                allowed=allowed,
            )
            if is_allowed:
                continue
            later_for_field.append(value)
            if value not in forbidden_later_only:
                forbidden_later_only.append(value)
            if _prompt_contains_entity_value(prompt, value):
                if value not in prompt_hits:
                    prompt_hits.append(value)
                _, full_only = _is_allowed_first_turn_entity_value(
                    value,
                    display_text=first_turn_text,
                    full_first_turn_text=full_text or None,
                    allowed=allowed,
                )
                leak_rows.append(
                    {
                        "leaked_value": value,
                        "leaked_value_normalized": normalize_digits(value),
                        "source_field": source_field,
                        "in_original_vendor_issue_preview": _value_literal_in_text(
                            value,
                            first_turn_text,
                        ),
                        "allowed_by_full_first_turn_source": full_only,
                        "in_prompt": True,
                    },
                )
        if later_for_field:
            later_only_by_field[source_field] = later_for_field

    if ticket is not None:
        for token in _ticket_precomputed_entity_tokens(ticket):
            is_allowed, _ = _is_allowed_first_turn_entity_value(
                token,
                display_text=first_turn_text,
                full_first_turn_text=full_text or None,
                allowed=allowed,
            )
            if is_allowed:
                continue
            source_field = "operator_ticket.extracted_order_ids"
            later_only_by_field.setdefault(source_field, [])
            if token not in later_only_by_field[source_field]:
                later_only_by_field[source_field].append(token)
            if token not in forbidden_later_only:
                forbidden_later_only.append(token)
            if _prompt_contains_entity_value(prompt, token):
                if token not in prompt_hits:
                    prompt_hits.append(token)
                leak_rows.append(
                    {
                        "leaked_value": token,
                        "leaked_value_normalized": normalize_digits(token),
                        "source_field": source_field,
                        "in_original_vendor_issue_preview": False,
                        "in_prompt": True,
                    },
                )

    return {
        "allowed_values_from_original": sorted(allowed),
        "later_only_by_field": later_only_by_field,
        "forbidden_later_only_values": forbidden_later_only,
        "prompt_contains_forbidden_later_only_values": prompt_hits,
        "would_fail": bool(leak_rows),
        "leak_diagnostics": leak_rows,
    }


def assert_first_turn_entity_isolation(
    prompt: str,
    *,
    first_turn_text: str,
    thread_texts: Sequence[str],
    ticket: OperatorTicket | None = None,
    full_first_turn_text: str | None = None,
) -> None:
    """Fail if a later-thread entity is absent from first-turn sources but in the prompt."""
    analysis = analyze_first_turn_entity_leakage(
        prompt,
        first_turn_text=first_turn_text,
        thread_texts=thread_texts,
        ticket=ticket,
        full_first_turn_text=full_first_turn_text,
    )
    if not analysis["would_fail"]:
        return
    row = analysis["leak_diagnostics"][0]
    value = str(row["leaked_value"])
    source = str(row["source_field"])
    in_original = bool(row["in_original_vendor_issue_preview"])
    raise ValueError(
        "first_turn_only prompt contains latest-only entity: "
        f"{value} from {source}; "
        f"{'also' if in_original else 'not'} present in original_vendor_issue_preview",
    )


def assert_prompt_messages_safe(
    messages: Sequence[LLMMessage],
    *,
    forbidden_values: Sequence[str],
    mode: DraftGenerationMode = DraftGenerationMode.FIRST_TURN_ONLY,
    first_turn_text: str | None = None,
    thread_texts: Sequence[str] | None = None,
    allowed_values: Sequence[str] | None = None,
    ticket: OperatorTicket | None = None,
) -> None:
    """Run leakage checks on assembled LLM messages."""
    prompt = prompt_text_from_messages(messages)
    allowed = _normalize_allowed_values(allowed_values)
    if not allowed and first_turn_text and first_turn_text.strip():
        allowed = (first_turn_text.strip(),)
    assert_no_prompt_leakage(
        prompt,
        forbidden_values,
        mode=mode,
        allowed_values=allowed,
    )
    if mode == DraftGenerationMode.FIRST_TURN_ONLY and first_turn_text is not None:
        full_text = (ticket.full_first_vendor_message_text if ticket is not None else None) or None
        assert_first_turn_entity_isolation(
            prompt,
            first_turn_text=first_turn_text,
            thread_texts=thread_texts or (),
            ticket=ticket,
            full_first_turn_text=full_text,
        )


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def build_prompt_audit_record(
    *,
    case_id: str,
    messages: Sequence[LLMMessage],
    included_fields: Sequence[str],
    case: Mapping[str, Any],
    mode: DraftGenerationMode = DraftGenerationMode.FIRST_TURN_ONLY,
) -> dict[str, Any]:
    """Safe audit row (no full prompt body)."""
    prompt = prompt_text_from_messages(messages)
    forbidden = extract_forbidden_values_from_benchmark_case(case, mode=mode)
    gold = case.get("gold_reference_reply")
    contains_gold_reference = False
    if isinstance(gold, str) and gold.strip():
        contains_gold_reference = gold.strip() in prompt
    contains_forbidden_markers = False
    lowered = prompt.lower()
    for marker in _FORBIDDEN_PROMPT_MARKERS:
        if marker in lowered:
            contains_forbidden_markers = True
            break
    allowed: tuple[str, ...] = ()
    if mode == DraftGenerationMode.FIRST_TURN_ONLY:
        allowed = _normalize_allowed_values((first_turn_text_from_case(case),))
    try:
        assert_no_prompt_leakage(prompt, forbidden, mode=mode, allowed_values=allowed)
        leakage_check_passed = True
    except ValueError:
        leakage_check_passed = False

    return {
        "case_id": case_id,
        "draft_generation_mode": mode.value,
        "included_fields": list(included_fields),
        "excluded_fields": list_excluded_prompt_fields(mode),
        "prompt_hash": prompt_hash(prompt),
        "prompt_char_count": len(prompt),
        "contains_gold_reference": contains_gold_reference,
        "contains_forbidden_markers": contains_forbidden_markers,
        "leakage_check_passed": leakage_check_passed,
    }


def write_prompt_audit_jsonl(
    rows: Sequence[Mapping[str, Any]],
    path: Any,
) -> None:
    """Append-safe write of prompt audit rows (gitignored reports/ only)."""
    from pathlib import Path

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False) + "\n")


def assert_audit_record_safe(row: Mapping[str, Any]) -> None:
    """Audit JSONL must not contain full prompts or gold text."""
    forbidden_keys = frozenset(
        {
            "prompt",
            "prompt_body",
            "gold_reference_reply",
            "messages",
            "snapshot_before_reply",
        },
    )
    keys = {str(k).lower() for k in row.keys()}
    bad = keys.intersection(forbidden_keys)
    if bad:
        joined = ", ".join(sorted(bad))
        raise ValueError(f"prompt audit row contains forbidden keys: {joined}")
    serialized = json.dumps(row, ensure_ascii=False)
    if re.search(r"sk-[a-zA-Z0-9]{10,}", serialized):
        raise ValueError("prompt audit row must not contain API key patterns")
