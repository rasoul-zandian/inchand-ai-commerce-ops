# Real Ticket Export Format — Conversation Snapshot

**Status:** Contract only (no import pipeline, no production DB access)  
**Schema:** `app/tickets/conversation_models.py` (`ConversationTicketSnapshot`, `ConversationMessage`)

---

## Recommended transport

| Property | Value |
|----------|--------|
| Encoding | **UTF-8** |
| Layout | **JSONL** — one anonymized ticket room per line |
| Ordering | Messages in **chronological** order (`timestamp` ascending when present; else export order) |
| Git | **Never** commit raw exports; only reviewed, anonymized derivatives after sign-off |

See also: [Real Data Pilot Plan](real_data_pilot_plan.md), [anonymization helpers](../../app/data_readiness/anonymization.py).

---

## Required fields (per line / room)

| Field | Type | Notes |
|-------|------|--------|
| `room_id` | string | Stable room identifier (placeholder ok after anonymization) |
| `ticket_label` | string | Topic label, e.g. `financial`, `support`, `complaint` |
| `messages` | array | At least one message |
| `messages[].message_id` | string | Unique within room |
| `messages[].sender_type` | string | `seller`, `support_agent`, `finance_agent`, `system`, `unknown` |
| `messages[].text` | string | Non-empty after strip |

## Optional fields

| Field | Type | Notes |
|-------|------|--------|
| `ticket_subtype` | string | Finer label, e.g. `settlement_discrepancy` |
| `status` | string | e.g. `closed`, `resolved` |
| `created_at` / `closed_at` | ISO-8601 datetime | Room lifecycle |
| `seller_id` | string | **Placeholder only** in git, e.g. `SELLER_ID_001` |
| `final_resolution` | object | Compact outcome metadata (no PII) |
| `messages[].timestamp` | ISO-8601 datetime | Per-message time |
| `metadata` | object | Exporter tags (no secrets) |

---

## Excluded from v1 exports (never in AI pipeline files)

- Raw phone numbers, emails, national IDs  
- Real seller / customer / agent personal names  
- Payment card numbers, IBANs, wallet IDs  
- Street addresses and precise geo  
- API keys, tokens, internal URLs  
- Attachment binaries (reference `attachment_ref` in metadata only if needed later)

---

## Anonymization placeholders

Use **stable placeholders** so eval and re-indexing stay consistent:

| Real (local export only) | Placeholder in git-safe files |
|--------------------------|-------------------------------|
| Vendor / seller id | `SELLER_ID_001` |
| Order id | `ORDER_ID_001` |
| Phone | `PHONE_001` |
| IBAN / Sheba | `IBAN_001` |
| Address | `ADDRESS_001` |
| Ticket id (if needed in text) | `TICKET_ID_001` |

Maintain a **local-only mapping table** (encrypted disk, **not** in the repository) from placeholder → internal id for pilot debugging only.

---

## Example JSON object (one JSONL line)

```json
{
  "room_id": "ROOM_001",
  "ticket_label": "financial",
  "ticket_subtype": "settlement_discrepancy",
  "status": "closed",
  "created_at": "2026-03-01T10:15:00+00:00",
  "closed_at": "2026-03-02T14:30:00+00:00",
  "seller_id": "SELLER_ID_001",
  "final_resolution": {"outcome": "clarification_requested"},
  "messages": [
    {
      "message_id": "msg-1",
      "sender_type": "seller",
      "timestamp": "2026-03-01T10:16:00+00:00",
      "text": "مبلغ تسویه با فاکتور مغایرت دارد."
    },
    {
      "message_id": "msg-2",
      "sender_type": "support_agent",
      "timestamp": "2026-03-01T11:02:00+00:00",
      "text": "لطفاً شماره فاکتور را ارسال کنید."
    }
  ],
  "metadata": {"export_version": "1", "source": "manual_review"}
}
```

Parse in Python:

```python
from app.tickets import parse_conversation_ticket_snapshot, conversation_to_plain_text

snapshot = parse_conversation_ticket_snapshot(line)
transcript = conversation_to_plain_text(snapshot)
```

---

## Plain-text transcript (prompting / eval)

`conversation_to_plain_text()` produces role-labeled lines without metadata:

```text
[seller] مبلغ تسویه با فاکتور مغایرت دارد.
[support_agent] لطفاً شماره فاکتور را ارسال کنید.
```

Do not paste raw exports into prompts; use anonymized snapshots only.

---

## Offline validation (before AI pipeline)

Validate an export **without** importing, indexing, or calling workflows:

```bash
PYTHONPATH=. python3.11 scripts/validate_ticket_export.py path/to/export.jsonl
```

| Exit code | Meaning |
|-----------|---------|
| `0` | All non-empty lines are valid `ConversationTicketSnapshot` rows |
| `1` | One or more invalid lines, missing file, or CLI error |

Optional machine-readable summary:

```bash
PYTHONPATH=. python3.11 scripts/validate_ticket_export.py path/to/export.jsonl --json
```

The validator reports line-level schema errors (no full message bodies), aggregate stats (labels, sender types, message counts), and **suspicious-pattern warning counts only** (email/phone/IBAN-like)—warnings do not fail validation. It does **not** write to corpus, pgvector, or Postgres.

---

## Workflow input mapping (offline)

After validation, map each snapshot to a workflow-ready dict (no runtime execution, no import):

```python
from app.tickets import parse_conversation_ticket_snapshot, conversation_snapshot_to_workflow_input

snapshot = parse_conversation_ticket_snapshot(line)
workflow_input = conversation_snapshot_to_workflow_input(snapshot)
# workflow_input["user_input"] — transcript for vendor-ticket workflow
# workflow_input["workflow_metadata"] — compact room/label/sender summary
# workflow_input["workflow_state_snapshot"] — safe context for redraft/HITL contracts
```

Batch: `map_conversation_snapshots_to_workflow_inputs(snapshots)`. Excludes export `metadata`, per-message metadata, attachments, and secrets by default.

**Workflow state:** mapped `ticket_label` / `room_id` / `ticket_subtype` are applied to `CommerceAIState` at graph normalization (`apply_ticket_context_to_state`) for department-aware review routing. Optional on `POST /run-vendor-ticket` as additive fields. No corpus import or indexing in this step.

---

## Offline replay harness (observation only)

After validation, replay each ticket through the **mock** vendor-ticket workflow and write a local JSONL report (no OpenAI, Postgres, corpus import, or production execution):

```bash
# 1) Validate export (exit 0 required for clean replay)
PYTHONPATH=. python3.11 scripts/validate_ticket_export.py path/to/export.jsonl

# 2) Replay with mock LLM/RAG (operator-chosen output path)
PYTHONPATH=. python3.11 scripts/replay_ticket_export.py path/to/export.jsonl \
  --output reports/replay_report.jsonl
```

Optional machine-readable summary: add `--summary-json`.

| Artifact | Commit to git? |
|----------|----------------|
| Anonymized export JSONL | **No** (unless explicitly approved pilot sample) |
| `reports/*.jsonl` replay output | **No** — local observation only (`reports/` is gitignored) |

Each report row includes compact routing/QA fields (`route_label`, `review_priority`, `assigned_department`, etc.) and **excludes** draft/final responses, transcripts, and raw message text. The harness prints aggregate stats (label/route/department counts, label-vs-department mismatch observations). Mismatches are **observation only** — nothing is auto-corrected.
