# Operational Actions Registry

## Purpose

The operational actions registry is the central catalog of **read-only external tools**
used by the operator console and manual sandbox. It records what each tool does, when it
may run, how risky it is, which inputs it needs, and which safe fields may appear in UI or
draft-adjacent flows.

This layer is **architecture only**. It does not:

- add new external integrations
- auto-run tools in live production mode
- mutate orders, tickets, or products
- send customer messages
- enable production automation
- replace shipment/delivery decision business rules

Implementation: `app/tools/operational_actions_registry.py`.

## Tool definitions

Each tool is an `OperationalToolDefinition` with:

| Field | Meaning |
|-------|---------|
| `tool_id` | Stable identifier (`OperationalToolId`) |
| `read_only` | No writes to Inchand or third parties |
| `risk_level` | `low` / `medium` / `high` |
| `execution_modes` | Allowed operator execution patterns |
| `capabilities` | What the tool can read or verify |
| `required_inputs` | Minimum inputs (e.g. `order_id`, `tracking_code`) |
| `safe_output_fields` | Fields allowed in session/UI/debug |
| `pii_excluded_fields` | Fields that must never be persisted in safe payloads |
| `can_affect_draft_generation` | Whether grounded replies may use tool output |

### Active tools (Step 234)

#### `inchand_order_lookup`

- **Risk:** low (internal read-only API)
- **Capabilities:** order status, parcel tracking, delivery state, provider status
- **Required input:** `order_id`
- **Safe outputs:** `order_status`, `provider_status`, `parcel_tracking_code`, `parcel_status_name`, `delivered_at`, `is_delivered_in_inchand`
- **PII excluded:** receiver/sender names, `user_id`, address, phone

#### `iran_post_tracking_verification`

- **Risk:** medium (external API, rate limits, third-party dependency)
- **Capabilities:** verify tracking code, carrier events, last tracking status
- **Required input:** `tracking_code`
- **Safe outputs:** `verified`, `status_description`, `last_event_*`, `event_count`
- **PII excluded:** receiver/sender names and zips, mail carrier/person names

### Reserved tool IDs (not registered yet)

- `sheba_verification`
- `settlement_status_lookup`
- `seller_panel_status_lookup`
- `product_review_lookup`
- `ticket_status_lookup`
- `carrier_tracking_generic`

## Execution modes

| Mode | Meaning |
|------|---------|
| `manual_only` | Operator button only |
| `sandbox_auto_allowed` | Auto-run permitted in **manual sandbox chat** when config + eligibility pass |
| `live_manual_allowed` | Manual button in live API feed / replay |
| `live_auto_disallowed` | Auto-run is never allowed in live feed (policy) |
| `future_production_auto_candidate` | Reserved for later graduation review |

Current policy: **no production auto execution**. Live feed may expose manual tool buttons;
orchestration must not auto-call APIs outside `manual_sandbox_chat`.

## Eligibility

`evaluate_tool_eligibility(tool_id, context)` returns:

- `eligible` — manual and/or sandbox auto path allowed
- `blocked_reason` — semicolon-separated codes (no secrets)
- `manual_allowed` / `sandbox_auto_allowed` / `live_auto_allowed`
- `tool_execution_mode` / `tool_risk_level`

Context (`OperationalToolEligibilityInput`) includes:

- `source_mode` — `manual_sandbox_chat`, `live_api_feed`, `historical_replay`
- `order_id_present`, `tracking_code_present`, `carrier_candidate`
- `order_delivered_in_inchand` — blocks Iran Post when delivery already confirmed in Inchand
- `manual_trigger`, `sandbox_auto_enabled`, `live_auto_enabled`
- `tool_enabled`, `token_present`
- `scenario_auto_eligible` — Inchand sandbox auto still requires shipment/delivery scenario gates

### Inchand order lookup

Eligible when:

- `order_id_present` and `tool_enabled` and `token_present`
- Manual: `manual_trigger=true` (all operator modes with live manual allowed)
- Sandbox auto: `source_mode=manual_sandbox_chat`, `sandbox_auto_enabled`, `scenario_auto_eligible`
- Live auto: always **blocked**

### Iran Post tracking verification

Eligible when:

- `tracking_code_present`, `carrier_candidate` is Iran Post, `tool_enabled`, `token_present`
- `order_delivered_in_inchand=false`
- Manual / sandbox auto: same pattern as Inchand (sandbox auto only in manual sandbox)
- Live auto: always **blocked**

## Integration points

- **Manual sandbox orchestration** — `should_trigger_manual_sandbox_auto_order_lookup` and
  `should_run_manual_sandbox_auto_tracking` consult the registry before auto-running.
- **Agentic graph read-only execution (Step 235)** — graph nodes
  `plan_read_only_tools`, `execute_order_lookup`, and `execute_iran_post_tracking`
  evaluate eligibility through this registry before any tool call. Graph auto execution
  is allowed only when:
  - `source_mode == manual_sandbox_chat`
  - `AGENTIC_GRAPH_READ_ONLY_TOOLS_ENABLED=true`
  - source mode is included in `AGENTIC_GRAPH_TOOL_EXECUTION_SOURCE_MODES`
  - per-tool eligibility passes (`tool_enabled`, token present, required inputs, scenario rules)
- **Operator panels** — Inchand / Iran Post panels show FA captions for execution mode,
  risk, and block reasons via `tool_registry_metadata_captions_fa`.
- **Orchestration debug** — `store_orchestration_meta` records `eligible_tools`,
  `blocked_tools`, `blocked_reason`, `tool_execution_mode`, `tool_risk_level` (safe only).

### Step 235 graph flags

- `AGENTIC_GRAPH_READ_ONLY_TOOLS_ENABLED` (default `false`)
- `AGENTIC_GRAPH_TOOL_EXECUTION_SOURCE_MODES` (default `manual_sandbox_chat`)
- `AGENTIC_GRAPH_ORDER_LOOKUP_ENABLED` (default `true`, but inert unless graph tools enabled)
- `AGENTIC_GRAPH_IRAN_POST_VERIFY_ENABLED` (default `true`, but inert unless graph tools enabled)

Guardrails stay unchanged: no write tools, no order/ticket mutation, no send, no live auto execution.

## Debugging

Use orchestration metadata in the manual sandbox shipment panel, or evaluate eligibility
in a REPL:

```python
from app.tools.operational_actions_registry import (
    OperationalToolId,
    build_inchand_eligibility_context,
    evaluate_tool_eligibility,
)

result = evaluate_tool_eligibility(
    OperationalToolId.INCHAND_ORDER_LOOKUP,
    build_inchand_eligibility_context(
        settings,
        source_mode="manual_sandbox_chat",
        order_id_present=True,
        sandbox_auto_enabled=True,
        scenario_auto_eligible=True,
    ),
)
```

No raw API responses, tokens, or transcripts are stored in registry debug rows.
