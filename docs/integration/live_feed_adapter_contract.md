# Live feed adapter contract

Integration specification for feeding **live seller-support tickets** into the Inchand AI **read-only shadow intake** pipeline (operator console live mode, live first-turn shadow intake). This document is the handoff artifact for upstream platform teams.

## Purpose

- Define a **stable, auditable contract** between Inchand seller-support systems and the AI shadow stack.
- Enable **file-based pilot** ingestion now and **read-only API** ingestion later without changing shadow safety rules.
- Ensure all live data enters through the same **redaction, first-turn eligibility, and dedupe** gates as offline replay.

## Data ownership

| Party | Responsibility |
|-------|----------------|
| **Source platform** | Authoritative ticket state, message ordering, timestamps, and pre-export redaction (preferred). |
| **Inchand AI** | Validation, normalization, shadow graph execution, safe artifact storage. |
| **Operators** | Human review only; no automated customer send from this path. |

Source systems remain the system of record. The AI pipeline **never writes back** ticket status, labels, assignments, or messages.

## Read-only scope

The live feed adapter and downstream consumers **must not**:

- Send customer or vendor replies.
- Mutate tickets, orders, or products.
- Auto-update ticket state, labels, or routing in production.
- Trigger operational workflows or action APIs.
- Bypass redaction or HITL governance.
- Treat multi-turn escalations as first-turn assisted drafts.

Downstream shadow intake enforces:

- `execution_allowed=false`
- `customer_send_allowed=false`
- `human_review_required=true`

## Supported input modes

### A. File-based adapter (pilot — preferred)

- **Path:** `data/private/live_vendor_tickets.jsonl` (configurable via `LIVE_FEED_SOURCE_PATH`).
- **Format:** UTF-8 JSONL, one ticket object per line.
- **Delivery:** append-only tail, periodic full snapshot, or batch drop — all accepted; each shadow run **dedupes** processed tickets.
- **Properties:** simple, auditable, no production API dependency; suitable for first internal pilot.

### B. API-based adapter (future)

- **Direction:** read-only pull from Inchand support APIs.
- **Example:** `GET /support/live-tickets?updated_after=...&limit=...`
- **Constraints:** no write/action endpoints; no reply POST; credentials scoped to read-only ticket export.
- **Sync:** `updated_after`, `limit`, stable sort by `updated_at` ascending; optional pagination cursor.
- **Normalization:** API payloads must be mapped to the same ticket schema below before validation.

> **Note:** API mode is **not implemented** in the repository yet. This contract defines the target shape only.

## Ticket schema (JSONL row / API item)

```json
{
  "room_id": "7743",
  "ticket_label": "support",
  "status": "open",
  "created_at": "2026-05-19T09:00:00+00:00",
  "updated_at": "2026-05-19T10:15:00+00:00",
  "messages": [
    {
      "message_id": "m1",
      "sender_type": "seller",
      "text": "سلام، وضعیت سفارش [ORDER_ID] را لطفاً بررسی کنید.",
      "created_at": "2026-05-19T10:00:00+00:00"
    }
  ]
}
```

### Required fields

| Level | Field | Notes |
|-------|--------|------|
| Ticket | `room_id` | Stable unique room/ticket id (string). |
| Ticket | `status` | e.g. `open`, `new`, `pending`, `closed`. |
| Ticket | `created_at` | ISO-8601 UTC (with offset or `Z`). |
| Ticket | `updated_at` | ISO-8601; used for incremental sync ordering. |
| Ticket | `messages` | Non-empty array. |
| Message | `message_id` | Stable per message. |
| Message | `sender_type` | See normalization below. |
| Message | `text` | Non-empty after trim. |
| Message | `created_at` | ISO-8601 (alias `timestamp` accepted and normalized). |

### Optional fields

| Field | Notes |
|-------|--------|
| `ticket_label` | `support`, `fund`, `complaint`, etc. Defaults to `unknown` if omitted. |
| `route_label` | Routing hint for analytics only. |
| `vendor_id_hash` / `seller_id_hash` | Hashed identifiers (preferred for external handoff). |
| `seller_id` | Raw seller id allowed **internal pilot only** when needed for debugging. |
| `source_system` | Provenance label (e.g. `seller_support_v2`). |
| `priority` | Opaque priority enum/string. |
| `attachments` | **Metadata only** (filename, mime, size, redacted url token) — no binary bodies. |
| `closed_at` | When set, ticket treated as closed for eligibility. |

### Forbidden content

Do **not** include in feed rows:

- Auth tokens, API keys, passwords, JWTs, session cookies, or `user_input` transcript blobs.
- Full internal staff private notes unless explicitly approved for AI shadow.
- Binary attachment payloads or presigned URLs with secrets.

### Internal pilot identifiers (allowed in feed inputs)

PII fields such as phone numbers, IBANs, emails, and card numbers **may be included**
in the **INTERNAL-ONLY** pilot feed for extraction evaluation and operator review.

**Why:** operators and evaluators need real identifiers during the pilot to:

- validate entity extraction quality
- verify IBAN extraction
- inspect order / tracking / product identifiers
- debug extraction edge cases

**Constraints:**

- The feed remains **internal-only** (no customer send, no external sharing).
- No prompts or full transcripts may be exported outside governed artifacts.
- **Reports and validation summaries** still prefer sanitized metadata (counts only).
- **UI / operator review** may display identifiers internally for HITL evaluation.
- Future production deployments may require stricter redaction (`ALLOW_RAW_PII_INTERNAL_PILOT=false`).

Raw identifiers are allowed **in feed inputs**. Downstream shadow JSONL and governance
reports should still avoid echoing full message bodies.

Forbidden **keys** (rejected at validation): `api_key`, `auth_token`, `password`, `secret`, `user_input`, `raw_prompt`, `draft_reply`, `messages_raw`, etc. See `app/live_shadow/live_feed_contract.py`.

## Sender type normalization

### Allowed values (after normalization)

`seller`, `support_agent`, `finance_agent`, `system`, `unknown`

(`vendor` is normalized to `seller`; `internal` is normalized to `system`.)

### Alias map (inbound → normalized)

| Inbound | Normalized |
|---------|------------|
| `vendor` | `seller` |
| `admin`, `support`, `operator` | `support_agent` |
| `finance`, `accounting` | `finance_agent` |
| `internal` | `system` |

Unknown aliases fail validation unless they already match an allowed value.

## Shadow intake eligibility (downstream)

Validation **does not** guarantee shadow processing. After contract validation, `live_first_turn_shadow_intake` applies:

| Process | Condition |
|---------|-----------|
| **Process** | First meaningful sender is `seller`; no `support_agent` / `finance_agent` reply yet; status open/new/pending; first seller message text present; not deduped. |
| **Skip** | Support-started or finance-started rooms; multi-turn with prior support; closed tickets; system-only threads; empty text; duplicate `room_id` + `first_turn_signature`. |

Multi-turn operational conversations are **out of scope** for assisted/shadow draft generation in the pilot.

## Redaction expectations

### Internal pilot (default)

- **Feed inputs:** raw phone, IBAN, email, and card values are **allowed** when
  `ALLOW_RAW_PII_INTERNAL_PILOT=true` (default).
- **Validator:** records `raw_identifiers_detected` as **informational only** — not a
  validation failure.
- **Open-ticket / graph path:** may still apply `app/privacy_review/redaction.py` for
  specific export surfaces; operator console may show identifiers when configured for
  internal review.

### Production / strict mode (future)

Set `ALLOW_RAW_PII_INTERNAL_PILOT=false` to **reject** raw identifier patterns in feed
validation (stricter handoff for non-pilot environments).

### Accepted placeholders (optional in feeds; preferred in external reports)

| Placeholder | Meaning |
|-------------|---------|
| `[PHONE_NUMBER]` | Redacted phone |
| `[IBAN]` | Redacted IBAN |
| `[EMAIL]` | Redacted email |
| `[CARD_NUMBER]` | Redacted card |
| `[ADDRESS]` | Redacted address |

Display layers may render Persian labels for operators; **governance reports and
validation summaries** should remain aggregate-only without message bodies.

## Incremental sync

### File adapter

- Append-only or full snapshot files are both supported.
- Shadow intake loads recent rows (configurable `since_hours`, `limit`).
- **Dedupe key:** `room_id` + `first_turn_signature` (hash of first seller message id/time/text prefix).
- Re-exporting the same first turn does not re-run the graph when `--dedupe` is enabled.

### API adapter (future)

- Query: `updated_after`, `limit`.
- Sort: `updated_at` ascending.
- Return `next_cursor` when more pages exist.
- Map each item to the ticket schema and run `validate_live_ticket_row` before append to local staging JSONL (recommended).

## Error handling

| Situation | Behavior |
|-----------|----------|
| Invalid JSON line | Line fails validation; reported in validation summary; not passed to shadow intake. |
| Missing required field | Fail row; include `room_id` (if parseable) in report. |
| Forbidden key / secret pattern | Fail row. |
| Raw identifiers (phone/IBAN/email/card) | Informational only in internal pilot mode; fail in strict mode. |
| Valid row, ineligible for shadow | Pass contract validation; skipped later with reason counters in shadow summary. |
| Graph/runtime errors | Safe error strings in shadow JSONL (`workflow_error_redacted` for credential-like text). |

Validation reports **must not** echo full message bodies, prompts, or secrets.

## Security boundaries

- Feed files live under `data/private/` (gitignored in production deployments).
- No production graph, send, or mutation endpoints from this adapter.
- Operator console live mode uses the same HITL-safe payload builder as replay shadow export.
- Validation CLI writes only aggregate summaries under `reports/`.

## Sample payloads

### Valid first-turn seller ticket (minimal)

```json
{
  "room_id": "90001",
  "ticket_label": "support",
  "status": "open",
  "created_at": "2026-05-20T08:00:00+00:00",
  "updated_at": "2026-05-20T08:05:00+00:00",
  "messages": [
    {
      "message_id": "90001-m1",
      "sender_type": "seller",
      "text": "لطفاً وضعیت تسویه را بررسی کنید.",
      "created_at": "2026-05-20T08:05:00+00:00"
    }
  ]
}
```

### Support-started (valid contract, skipped by shadow)

```json
{
  "room_id": "90002",
  "status": "open",
  "created_at": "2026-05-20T08:00:00+00:00",
  "updated_at": "2026-05-20T08:10:00+00:00",
  "messages": [
    {
      "message_id": "90002-m1",
      "sender_type": "support_agent",
      "text": "لطفاً شماره سفارش را ارسال کنید.",
      "created_at": "2026-05-20T08:10:00+00:00"
    }
  ]
}
```

### Redacted seller message

```json
{
  "message_id": "90003-m1",
  "sender_type": "vendor",
  "text": "شماره تماس: [PHONE_NUMBER] — پیگیری سفارش",
  "created_at": "2026-05-20T09:00:00+00:00"
}
```

(`vendor` normalizes to `seller`.)

## Validation tooling

```bash
PYTHONPATH=. python3.11 scripts/validate_live_feed_contract.py \
  data/private/live_vendor_tickets.jsonl
```

Outputs:

- `reports/live_feed_contract_validation_summary.json`
- `reports/live_feed_contract_validation_report.md`

Implementation: `app/live_shadow/live_feed_contract.py`.

## Related components

| Component | Role |
|-----------|------|
| `app/live_feed/ticket_feed_adapter.py` | Load/normalize live JSONL for operator console |
| `app/live_shadow/live_first_turn_shadow_intake.py` | First-turn shadow graph batch |
| `app/live_feed/open_ticket_snapshot.py` | Redacted open-ticket previews |
| `app/tickets/conversation_models.py` | Parsed snapshot types |

## Versioning

- **Contract version:** `live_feed_adapter_v1` (Step 213).
- Breaking changes require a new contract version and coordinated validator update.
