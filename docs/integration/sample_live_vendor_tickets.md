# Sample live vendor tickets (JSONL)

Copy-ready example for the **Step 213** live feed adapter contract (`live_feed_adapter_v1`).

Full specification: [live_feed_adapter_contract.md](live_feed_adapter_contract.md)

## JSONL format

**JSONL** (JSON Lines) means **one JSON object per line**. Each line is a complete ticket record. Do not wrap the file in a JSON array.

Example file in this repo:

```text
docs/integration/sample_live_vendor_tickets.jsonl
```

Production / pilot intake path (gitignored, internal only):

```text
data/private/live_vendor_tickets.jsonl
```

Copy the sample lines into that path, or append new rows in the same shape.

## Required fields

### Ticket (each JSONL row)

| Field | Description |
|-------|-------------|
| `room_id` | Stable unique room/ticket id (string). |
| `status` | e.g. `open`, `new`, `pending`, `closed`. |
| `created_at` | ISO-8601 timestamp (UTC with offset or `Z`). |
| `updated_at` | ISO-8601; used for incremental sync ordering. |
| `messages` | Non-empty array of message objects. |

Optional but recommended: `ticket_label` (`support`, `fund`, `complaint`, etc.).

### Message (each item in `messages[]`)

| Field | Description |
|-------|-------------|
| `message_id` | Stable id per message. |
| `sender_type` | See allowed values below. |
| `text` | Non-empty message body after trim. |
| `created_at` | ISO-8601 (`timestamp` is accepted as an alias). |

Use **redacted placeholders** in sample or external handoff text when possible: `[ORDER_ID]`, `[PHONE_NUMBER]`, `[IBAN]`, `[EMAIL]`.

## `sender_type` allowed values

After normalization, only these values are valid:

- `seller`
- `support_agent`
- `finance_agent`
- `system`
- `unknown`

Common inbound aliases (normalized automatically):

| Inbound | Normalized |
|---------|------------|
| `vendor` | `seller` |
| `admin`, `support`, `operator` | `support_agent` |
| `finance`, `accounting` | `finance_agent` |
| `internal` | `system` |

## Sample rows: eligibility vs skip

Contract validation checks schema and safety. **Shadow first-turn intake** applies separate eligibility rules.

| Row | `room_id` | First sender | Support reply? | Contract | Shadow intake |
|-----|-----------|--------------|----------------|----------|---------------|
| ERS | `LIVE-90001` | `seller` | No | Valid | **Eligible** — seller-first, open, first-turn |
| 2 | `LIVE-90002` | `support_agent` | N/A (support started) | Valid | **Skipped** — support-started room |
| 3 | `LIVE-90003` | `seller` | Yes (`support_agent` reply) | Valid | **Skipped** — multi-turn with prior support reply |

Row 1 is the pattern to follow for assisted/shadow draft generation in the pilot.

Rows 2 and 3 pass contract validation but are intentionally **not** processed as first-turn shadow tickets.

## Validate before intake

```bash
PYTHONPATH=. python3.11 scripts/validate_live_feed_contract.py \
  docs/integration/sample_live_vendor_tickets.jsonl \
  --overwrite
```

For the live pilot file:

```bash
PYTHONPATH=. python3.11 scripts/validate_live_feed_contract.py \
  data/private/live_vendor_tickets.jsonl \
  --overwrite
```

Reports (aggregate only, no message bodies):

- `reports/live_feed_contract_validation_summary.json`
- `reports/live_feed_contract_validation_report.md`

## Read-only reminder

The live feed adapter is **read-only** for the AI stack: no customer send, no ticket mutation, no production write-back. See the contract doc for full boundaries.
