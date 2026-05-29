# Iran Post tracking verification (Ayantech Core API)

Read-only adapter for operator/CLI manual verification. **No** order updates, ticket mutation, customer messages, or automatic graph execution.

## API

- **URL:** `https://core.inquiry.ayantech.ir/webservices/Core.svc/PostTrackingInquiry`
- **Method:** `POST` (`IRAN_POST_TRACKING_METHOD=POST`)
- **Provider label:** `ayantech`

### Request

Ayantech expects the tracking code in **`PackageNumber`** (not `TraceNumber`). Default config matches this.

```json
{
  "Identity": { "Token": "<from env only>" },
  "Parameters": {
    "PackageNumber": "<tracking_code>",
    "TraceNumber": ""
  }
}
```

Use `IRAN_POST_TRACKING_CODE_FIELD=TraceNumber` or `both` only for diagnostics when comparing API behavior.

### Response (abbreviated)

```json
{
  "Parameters": {
    "AcceptanceDateTime": "...",
    "Destination": "...",
    "PostPackageStatusDetail": [
      {
        "DateTime": "...",
        "EventNumber": "...",
        "ExtraInfo": "{\"شرح\":\"...\",\"نامه رسان\":\"...\"}",
        "Province": "..."
      }
    ],
    "ReceiverName": "...",
    "SenderName": "..."
  },
  "Status": { "Code": "G00000", "Description": "..." }
}
```

`ExtraInfo` JSON is parsed to the `شرح` field only. Mail carrier names (`نامه رسان`) are **not** shown in safe summaries or UI.

`ReceiverName`, `ReceiverZip`, `SenderName`, and `SenderZip` are **never** included in operator-safe summaries or default reports.

## Environment

| Variable | Default | Notes |
|----------|---------|--------|
| `IRAN_POST_TRACKING_ENABLED` | `false` | Must be `true` for CLI/console verify |
| `IRAN_POST_TRACKING_TOKEN` | — | **Required** for live calls; env only |
| `IRAN_POST_TRACKING_API_URL` | Ayantech URL above | |
| `IRAN_POST_TRACKING_TIMEOUT_SECONDS` | `20` | |
| `IRAN_POST_TRACKING_METHOD` | `POST` | |
| `IRAN_POST_TRACKING_PROVIDER` | `ayantech` | |
| `IRAN_POST_TRACKING_LOG_RAW` | `false` | Safe aggregate logs only |
| `IRAN_POST_TRACKING_CODE_FIELD` | `PackageNumber` | `PackageNumber`, `TraceNumber`, or `both` |

## Extraction

Seller text is parsed by `extract_iran_post_tracking_candidates()` (Persian/Arabic digits, separators, keyword proximity). The selected code is sent in `Parameters` per `IRAN_POST_TRACKING_CODE_FIELD`. Manual sandbox stores safe **Tracking extraction debug** / «دیباگ استخراج کد رهگیری» under **Input parity / debug**.

## Manual CLI

```bash
export IRAN_POST_TRACKING_ENABLED=true
export IRAN_POST_TRACKING_TOKEN=...

PYTHONPATH=. python3.11 scripts/verify_iran_post_tracking.py \
  --tracking-code 195370506501166594474111 \
  --debug-extraction \
  --overwrite
```

Diagnostic override (not default):

```bash
PYTHONPATH=. python3.11 scripts/verify_iran_post_tracking.py \
  --tracking-code 195370506501166594474111 \
  --debug-extraction \
  --code-field TraceNumber \
  --overwrite
```

- Prints safe summary JSON to stdout
- Writes `reports/iran_post_tracking_check_summary.json` by default
- Raw output only with `--raw-private-output data/private/iran_post_tracking_raw.json` (must stay under `data/private/`)

## Operator console

When a plausible Iran Post tracking code is present in the assisted package:

- Section: **Tracking verification** / «استعلام کد رهگیری»
- Button: **Verify with Iran Post** / «استعلام از پست ایران»
- **No auto-call** on page load; result stored in `session_state` only
- Advisory caption: result is not sent to the seller automatically

## Advisory metadata (no auto API call)

When multi-turn context has `pending_request_type=requested_tracking_code`, `pending_request_fulfilled=true`, and a plausible Iran Post code:

```json
{
  "tracking_verification_recommended": true,
  "tracking_verification_carrier_candidate": "iran_post"
}
```

The LangGraph workflow does **not** call the API automatically.

## CI

Tests use a mock HTTP client. Live Ayantech calls are manual/staging only.

## Module

- `app/tools/tracking/iran_post_tracking.py`
- `scripts/verify_iran_post_tracking.py`
- `app/operator_console/iran_post_tracking_panel.py`

## Future (not in this step)

- Draft calibration from verification
- Multi-carrier abstraction
