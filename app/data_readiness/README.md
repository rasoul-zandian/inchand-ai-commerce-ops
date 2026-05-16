# Data readiness — vendor tickets (offline)

## Purpose

Real vendor ticket data improves the copilot when used **offline** for:

- Higher-quality support draft patterns and tone
- Retrieval (RAG) examples grounded in real cases
- Evaluation datasets and regression checks
- Intent taxonomy and routing labels
- Future API contract design with product and backend teams

Nothing in this package connects to production systems. Step 8 is **schema design, anonymization rules, and documentation** only.

## Not live yet

Do **not** wire ticket exports directly into the running graph, FastAPI handlers, or LangSmith until security review, DPA/consent, and retention policies are in place. Use local files outside git and explicit import pipelines later.

## Recommended export sample

For first iterations, aim for **500–2000 closed vendor tickets** that include support replies (and approval / escalation metadata when available). Closed tickets reduce ongoing consent churn and stabilize labels.

## Required fields (export contract)

Exports should include at least:

| Field | Notes |
|--------|--------|
| `ticket_id` | Stable unique id |
| `created_at` | ISO-8601 string recommended |
| `vendor_id` **or** `vendor_id_hash` | Raw vendor id must be hashed before sharing widely |
| `subject` | Short line; will be masked for PII |
| `body` | Main message; will be masked |
| `category` | Product / ops taxonomy when available |
| `status` | e.g. closed, resolved |
| `support_reply` | Human agent reply text |
| `reply_approved` | Whether reply was approved for send |
| `escalated` | Escalation flag |
| `resolution_time_hours` | Optional SLA analytics |

Map exports into `VendorTicketRecord` in `app/schemas/ticket_data.py` during a future import step.

**Multi-message chat rooms:** use `ConversationTicketSnapshot` in `app/tickets/conversation_models.py` and [`docs/data_governance/real_ticket_export_format.md`](../../docs/data_governance/real_ticket_export_format.md) (UTF-8 JSONL, one room per line, anonymized placeholders only).

## Sensitive data (must be masked or removed)

Before any commit, sharing, or indexing:

- Phone numbers (including Iranian `09…` mobiles)
- Email addresses
- National IDs
- Bank card numbers
- IBAN / Sheba (`IR…`)
- Street addresses and free-text locations
- Personal names when feasible (harder in Persian free text; combine masking with manual review)

Use `app/data_readiness/anonymization.py` for deterministic local masking of common patterns; extend regexes as you learn failure modes from real samples.

## Outputs to derive later

1. **Anonymized ticket dataset** — JSONL/Parquet of `VendorTicketRecord` with `metadata.anonymized=true`
2. **RAG ticket examples** — `RAGTicketExample` documents (title + content + intent), only **approved** content
3. **Evaluation golden set** — `VendorTicketEvaluationExample` rows for automated scoring
4. **API contract** — align the internal ticket service with the shapes below

## Future API contract (draft)

These are **not implemented** in the MVP; they describe how a real ticket backend might look:

- `GET /internal/vendor-tickets/{ticket_id}` — single ticket with messages summary
- `GET /internal/vendors/{vendor_id}` — vendor profile for context (hashed ids in logs)
- `GET /internal/vendor-tickets?status=closed&limit=1000` — bounded export for batch jobs
- `GET /internal/vendor-tickets/{ticket_id}/messages` — thread for RAG / model context

Versioning, authn/z, pagination (`cursor`), and rate limits belong in a proper API design doc.

## Security rule

**Never commit raw real ticket exports into git.** Store them in encrypted local disks or approved object storage; only anonymized derivatives may enter the repository after review.
