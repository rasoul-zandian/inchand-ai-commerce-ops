# Shipment / delivery decision layer (Step 232–236)

Read-only operational decision intelligence for shipment/delivery tickets. Combines seller message, optional Inchand order lookup, and optional Iran Post verification into a structured decision and recommended Persian reply.

**No mutations:** does not update orders, shipment status, or send messages. Does not auto-call tools in live/replay modes.

## Module

`app/workflows/shipment_delivery_decision.py`

## Decision types

| Type | Meaning |
|------|---------|
| `order_already_delivered_in_inchand` | Inchand marks order/parcel delivered — skip Iran Post |
| `delivery_completed_without_tracking_ack` | Seller reports delivery; order has no parcel code — ack only (no tracking ask) |
| `iran_post_tracking_valid` | Iran Post code verified |
| `iran_post_tracking_invalid` | Iran Post code rejected |
| `iran_post_tracking_unavailable` | Iran Post API error |
| `non_iran_post_tracking_present` | Parcel uses non–Iran Post carrier |
| `tracking_missing_request_required` | Shipment case: ask optional postal tracking (`روش ارسال … در صورت وجود`) |
| `seller_reply_no_post_tracking_ack` | Seller replied without Iran Post code — register only |
| `seller_provided_non_post_or_no_tracking_ack` | Non-post delivery (پیک، تیپاکس، …) — register only |
| `seller_provided_iran_post_tracking_valid` | Valid Iran Post code after optional ask |
| `seller_provided_iran_post_tracking_invalid` | Invalid Iran Post code — ask correct code if exists |
| `seller_provided_iran_post_tracking_needs_verification` | Plausible code; verification recommended |
| `seller_provided_tracking_needs_verification` | Recommend manual Iran Post verify |
| `seller_provided_non_iran_post_tracking_ack` | Seller gave non–Iran Post tracking |
| `order_lookup_failed` | Order API failed / not found |
| `insufficient_order_identifier` | No order id |
| `not_shipment_or_delivery_case` | Out of scope |

## Priority rules (summary)

1. No order id → request order id.
2. Not shipment/delivery → no override.
3. Order lookup failed → registered for review.
4. **Inchand delivered** → delivered reply, `skip_iran_post_verification=true` (wins over parcel tracking).
5. Parcel Iran Post + verification result → valid/invalid/needs verification.
6. Parcel non–Iran Post → carrier + tracking ack.
7. **Delivery-completed seller message + no parcel tracking** → `delivery_completed_without_tracking_ack` (never ask for tracking).
8. Shipment + no parcel tracking → optional postal tracking ask, then follow-up rules (پیک ack / Iran Post verify).

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SHIPMENT_DELIVERY_DECISION_ENABLED` | `true` | Enable decision computation |
| `MANUAL_SANDBOX_AUTO_ORDER_LOOKUP_ENABLED` | `false` | Controlled auto Inchand lookup in manual sandbox only |
| `MANUAL_SANDBOX_AUTO_TRACKING_VERIFY_ENABLED` | `false` | Auto Iran Post verify in manual sandbox only |
| `MULTI_ORDER_BATCH_ENABLED` | `true` | Enable multi-order batch handling in manual sandbox graph flow |
| `MULTI_ORDER_BATCH_MAX_AUTO_LOOKUP` | `5` | Max auto lookups in one multi-order batch |
| `MULTI_ORDER_BATCH_MAX_REPLY_ITEMS` | `5` | Max per-order rows included in compact reply/debug payload |

## Manual sandbox orchestration (Step 233)

On seller turns in **`source_mode=manual_sandbox_chat`** only:

1. Assisted package runs (HITL; no send).
2. When `is_manual_sandbox_auto_order_lookup_enabled()` and seller message is shipment/delivery-related with a plausible `INC-#######`:
   - Read-only `lookup_inchand_order()` runs once per order id (session cache).
   - Safe result stored in `manual_sandbox_order_lookup_results_by_order_id` (no raw API body).
3. `decide_shipment_delivery()` runs with lookup + optional Iran Post result from session.
4. If Iran Post auto-verify is enabled and decision does not skip verification, sandbox may verify then **re-run** decision for grounded reply.
5. Chat AI bubble prefers `shipment_delivery_decision` reply over generic assisted draft when `should_override_draft=true`.

### Auto lookup gates (all required)

- `source_mode == manual_sandbox_chat`
- Plausible Inchand order id in seller/graph context
- Shipment/delivery scenario (`delivery_completed`, `shipment_reshipment`, `seller_notification` + shipment text, tracking intents, etc.)
- `INCHAND_ORDER_LOOKUP_ENABLED=true`
- `MANUAL_SANDBOX_AUTO_ORDER_LOOKUP_ENABLED=true`
- Valid API token

### Session cache

| Key | Purpose |
|-----|---------|
| `manual_sandbox_order_lookup_results_by_order_id` | Safe lookup payload keyed by normalized order id |
| `inchand_order_lookup_result_{room_id}` | Latest lookup for room (backward compatible) |
| `manual_sandbox_orchestration_meta` | `order_lookup_auto_triggered`, `order_lookup_cache_hit`, `reply_origin`, etc. |

Manual **دریافت اطلاعات سفارش** button still works and refreshes cache (`force_refresh` on auto path when implemented via button).

### Orchestration panel (manual sandbox)

Shows auto lookup triggered, cache hit/miss, Iran Post auto status, decision type, and recommended reply.

## Live / historical replay

- **No** auto order lookup.
- **No** auto Iran Post verification.
- Decision panel appears when order lookup exists in session (manual button only).

## Agentic graph integration (Step 235)

Read-only shipment/delivery decision is now part of the agentic graph pipeline:

`plan_read_only_tools -> execute_order_lookup -> shipment_delivery_decision ->
execute_iran_post_tracking (optional) -> shipment_delivery_decision_after_tracking ->
generate_draft -> grounded_reply`

Execution guardrails:

- graph tools run only in `manual_sandbox_chat`
- requires `AGENTIC_GRAPH_READ_ONLY_TOOLS_ENABLED=true`
- every tool call must pass `evaluate_tool_eligibility()`
- live feed / historical replay graph auto execution remains blocked
- no send / no mutation / no shipment-status writes

Decision precedence remains unchanged:

- Inchand delivered -> skip Iran Post, delivered ack
- delivery-completed + no tracking -> delivery ack only
- shipment + no tracking -> optional tracking request
- optional tracking already asked and seller has no postal code -> register ack
- Iran Post valid/invalid -> status+ack or ask for corrected code

Workflow diagram: `docs/architecture/agentic_graph_read_only_tools_workflow.svg`.

## Multi-order batch handling (Step 236)

For seller messages containing multiple order IDs in shipment/delivery context:

- extract all order IDs with order-preserving dedupe (`extract_all_inchand_order_ids`)
- run read-only lookup per order (manual sandbox graph path only; registry-eligible only)
- run shipment/delivery decision per order
- aggregate to compact seller-facing grounded reply
- expose safe per-order debug rows in operator preview

Batch thresholds:

- 1 order: existing single-order flow
- 2..`MULTI_ORDER_BATCH_MAX_AUTO_LOOKUP`: batch lookup + aggregate decision
- over limit: no mass lookup; compact registration reply and `batch_limit_exceeded=true`

Aggregate decision metadata:

- `multi_order_decision_type`
- `multi_order_summary` (`batch_count`, `executed_count`, `skipped_count`, `limit_exceeded`)
- `multi_order_reply_used`

Per-order safe debug fields (PII-free):

- `order_id`, `found`, `order_status`, `provider_status`, `parcel_status`
- `has_tracking`, `delivered_in_inchand`, `decision_type`, `lookup_error_type`

## Reflection

Protected decision replies (including `delivery_completed_without_tracking_ack`) are not replaced by reflection rewrites that re-ask for tracking or generic troubleshooting.

Metadata may include `shipment_delivery_decision_type`, `order_delivered_in_inchand`, `tracking_verification_status`.

### Platform rule: runtime identifiers

When runtime/operator metadata already identifies the seller/shop (for example `shop_id` in operator context or manual sandbox session), final-draft reflection suppresses unnecessary requests for:

- `شناسه فروشگاه` / `shop id` / `کد فروشگاه`
- `شناسه فروشنده` / `seller id`

In operationally complete requests, these are rewritten to:

`درخواست شما ثبت شد و در دست بررسی قرار گرفت.`

## Tests

- `tests/test_shipment_delivery_decision.py`
- `tests/test_shipment_delivery_decision_scenarios.py`
- `tests/test_manual_sandbox_auto_order_lookup.py` — Step 233 orchestration

## Related

- Step 231: `docs/integration/inchand_order_lookup_api.md`
- Step 229: `docs/integration/iran_post_tracking_api.md`
