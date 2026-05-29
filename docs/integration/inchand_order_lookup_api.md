# Inchand internal order lookup API (Step 231)

Read-only adapter for the Inchand internal **orders** endpoint. Used for manual operator lookup and CLI verification only — **no order mutation**, no shipment updates, no seller/customer messages, and **no automatic graph execution**.

## Endpoint

```
GET {INCHAND_API_BASE_URL}/orders/{order_id}
```

Example:

```
GET https://app.inchand.com/api/v1/internal/orders/INC-7358954
```

### Headers

| Header | Value |
|--------|--------|
| `Authorization` | API token (configurable header name) |
| `Content-Type` | `application/json` |
| `X-Requested-With` | `XMLHttpRequest` |

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `INCHAND_API_BASE_URL` | `https://app.inchand.com/api/v1/internal` | API base URL |
| `INCHAND_API_KEY_NAME` | `Authorization` | Header name for token |
| `INCHAND_API_KEY_VALUE` | (empty) | Primary token (never commit) |
| `INCHAND_ORDER_LOOKUP_ENABLED` | `false` | Enable manual/CLI lookup |
| `INCHAND_ORDER_LOOKUP_TIMEOUT_SECONDS` | `20` | HTTP timeout |

**Token resolution:** `INCHAND_API_KEY_VALUE` first, then `LIVE_ROOMS_API_TOKEN`.

## Order id normalization

Inputs such as `7358954`, `INC-7358954`, `inc-7358954`, or `سفارش INC-7358954` normalize to `INC-7358954`.

- Extracts 7-digit Inchand order ids and adds the `INC-` prefix.
- Rejects bare long numeric strings (e.g. 24-digit Iran Post parcel codes) as order ids.
- Sets `code_validation_warning` when multiple order ids appear in one string.

**Important:** `data.tracking_code` in the API response is the **Inchand order code** (e.g. `INC-7358954`). The **parcel** tracking code is `data.providers[0].parcel.tracking_code`.

## Observed response shape (abbreviated)

The internal orders API has been observed to return **either** of these shapes:

- Wrapped: `{"data": {...order...}}`
- Direct: `{...order...}` (same order fields at top level, no `data` wrapper)

```json
{
  "data": {
    "order_status": "تحویل شده",
    "payment_status": "موفق",
    "tracking_code": "INC-7358954",
    "providers": [
      {
        "shop_name": "...",
        "status": "تحویل شده",
        "delivered_at": "2026-05-26 09:33:15",
        "parcel": {
          "tracking_code": "195370506501166594474111",
          "status_detail": { "name": "تحویل مشتری", "code": 1 },
          "status": 1
        },
        "items": [{ "product_id": 238981, "product_name": "...", "quantity": 1 }]
      }
    ],
    "created_at": "2026-05-22T10:34:09.000000Z"
  }
}
```

## Normalized safe output

The tool returns operational metadata only (see `InchandOrderLookupResult.to_safe_dict()`):

- `order_id`, `order_status`, `payment_status`, `created_at`
- Per-provider: `shop_name`, `provider_status`, `delivered_at`, delivery window, parcel `tracking_code` / `status` / `status_name`
- `items_summary`: `product_id` and `quantity` only (no product names)
- `has_parcel_tracking_code`, `primary_parcel_tracking_code`
- `is_delivered_in_inchand`, `delivery_source`, `safe_summary_fa`

### PII exclusions (default)

Not included in safe output or operator UI:

- `user_id`
- `receiver_name`, `sender_name`
- Customer phone / address
- Full `product_name`
- Raw API body

Raw archives are allowed **only** under `data/private/` when explicitly requested via CLI.

## Delivered-state detection

`is_delivered_order_state()` is true when Inchand reports delivery via:

- `order_status` containing «تحویل شده»
- Provider `status` containing «تحویل شده»
- Parcel `status_detail.name` in {تحویل مشتری, تحویل گیرنده, تحویل شده}
- Parcel `status == 1` (when confirmed by API data)

This boolean is advisory for future shipment/delivery orchestration; **Iran Post verification is not required** when Inchand already marks delivered.

## Advisory metadata (no auto-call)

When an order id is extracted in multi-turn context:

```json
{
  "inchand_order_lookup_recommended": true,
  "inchand_order_id_candidate": "INC-7358954"
}
```

The LangGraph agentic sandbox **does not** call `lookup_inchand_order` automatically.

## Manual CLI

```bash
export INCHAND_ORDER_LOOKUP_ENABLED=true
export INCHAND_API_KEY_VALUE=...

PYTHONPATH=. python3.11 scripts/lookup_inchand_order.py \
  --order-id 7358954 \
  --overwrite
```

Options:

- `--summary-output reports/inchand_order_lookup_summary.json` (safe summary; default)
- `--raw-private-output data/private/inchand_order_INC-7358954_raw.json` (optional; must be under `data/private/`)
- `--no-raw` — skip raw write even if `--raw-private-output` is set

## Operator console (manual only)

In assisted / manual sandbox / live ticket detail, when an order id is present:

- Section: **اطلاعات سفارش اینچند** / “Inchand order lookup”
- Button: **دریافت اطلاعات سفارش** / “Lookup order”
- On click: `lookup_inchand_order(order_id)`; result stored in **session only**
- Displays safe fields only (statuses, parcel tracking code, delivered flags)

## Module

`app/tools/inchand/order_lookup.py`

## Constraints

- Read-only GET
- No ticket/order mutation
- No draft changes
- No automatic Iran Post verification from order lookup (Step 232+)
