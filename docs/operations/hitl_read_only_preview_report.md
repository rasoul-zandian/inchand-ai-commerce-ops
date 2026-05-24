# HITL Read-Only Preview Batch Review Report

**Status:** Governance reporting only (Step 153) — local mock preview validated on sample batch  
**Governance:** `recommended_decision = retrieval_ready_for_sandbox_tooling_review` (Step 124)  
**Audience:** HITL reviewers, vendor-ticket operators, retrieval governance, platform engineering

---

## Purpose

Record a **local read-only HITL panel preview batch** generated from safe AI assist shadow payloads (Steps 150–152). This report summarizes aggregate-safe preview metrics and governance boundaries for human qualitative review — **not** production UI, **not** workflow mutation, **not** customer-facing behavior.

It does **not** approve a production HITL panel, FastAPI routes, reviewer actions that persist state, or draft/final consumption of `ai_assist_*` / `retrieval_*`.

**Gitignored artifacts (local operator):** `reports/hitl_read_only_payload_sample.json`, `reports/hitl_read_only_panel_preview.md`

---

## Preview purpose

The mock preview (`scripts/render_hitl_read_only_panel_preview.py`) renders Markdown from payloads that pass `assert_hitl_payload_ready()`. It lets operators and governance reviewers **see the intended HITL read-only layout** (aggregate metadata only) before any real UI work.

| Goal | Status |
|------|--------|
| Validate allowlisted field presentation | **Recorded** (sample batch) |
| Confirm safety footer and read-only boundary in output | **Recorded** |
| Support human qualitative review of layout/copy | **Ready** |
| Replace or implement production HITL UI | **Out of scope** |

---

## Source and output files

| Role | Path |
|------|------|
| **Source replay (upstream)** | `reports/ai_assist_shadow_replay_v1.jsonl` (166 rows; Step 149 validated) |
| **Source payload file (this batch)** | `reports/hitl_read_only_payload_sample.json` |
| **Preview output file** | `reports/hitl_read_only_panel_preview.md` |
| **Payload builder CLI** | `scripts/build_hitl_read_only_payload_sample.py` |
| **Preview renderer CLI** | `scripts/render_hitl_read_only_panel_preview.py` |

**Batch workflow (local):**

```bash
PYTHONPATH=. python3.11 scripts/build_hitl_read_only_payload_sample.py \
  reports/ai_assist_shadow_replay_v1.jsonl --limit 5 --overwrite

PYTHONPATH=. python3.11 scripts/render_hitl_read_only_panel_preview.py \
  reports/hitl_read_only_payload_sample.json \
  --output reports/hitl_read_only_panel_preview.md --overwrite
```

Each payload is built via `build_hitl_read_only_payload_from_replay_row()` and validated with `assert_hitl_payload_ready()` before render. Preview output is scanned with `assert_hitl_preview_markdown_safe()`.

---

## Read-only scope

| In scope | Out of scope |
|----------|--------------|
| Aggregate ticket metadata (`room_id`, labels, department) | Raw messages / transcripts |
| Aggregate `ai_assist_*` summary fields | Draft / `final_response` text |
| Aggregate `retrieval_*` counts and gate metadata | Retrieved hit bodies / snippets |
| Human review note + safety footer in Markdown | `retrieval_query_hash`, raw query, vectors |
| Local file preview for governance review | FastAPI routes, web UI, auto-send |

**Repository runtime defaults unchanged:** `VENDOR_TICKET_AI_ASSIST_SHADOW_ENABLED=false`, `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=false`. `vendor_ticket_node` does **not** read `ai_assist_*` or `retrieval_*`.

---

## Sample size

| Item | Value |
|------|------:|
| Replay rows available (Step 149 batch) | 166 |
| **Sample size (this preview batch)** | **5** |
| Sample selection | First 5 replay rows via `--limit 5` on payload sample CLI |
| Rationale | Representative pilot slice for qualitative layout review without committing large Markdown artifacts |

---

## Visible preview sections

Each ticket in `reports/hitl_read_only_panel_preview.md` includes:

1. **Ticket metadata** — `room_id`, `ticket_label`, `route_label`, `review_priority`, `assigned_department`
2. **AI assist summary** — shadow-generated flag, suggested priority, escalation/duplicate flags, suggested action, confidence band, human review required, shadow-only
3. **Retrieval aggregate summary** — gate decision, scenario, result count, sanitized metadata filter (`ticket_label` + `route_label` only), sandbox-only, `retrieval_activated=false`
4. **Human review note** — operator guidance (aggregate only; no message or hit text)
5. **Safety footer** — *Read-only. No customer response generated. No auto-send.*

Document header states: local mock preview only; no customer-facing behavior.

---

## Aggregate-safe preview metrics

**Source:** `reports/hitl_read_only_payload_sample.json` + `reports/hitl_read_only_panel_preview.md` (Step 153 local batch)

| Metric | Value |
|--------|------:|
| `payload_count` | 5 |
| `rendered_count` | 5 |
| `rejected_count` | 0 |
| `safety_check_passed` | **true** |

### `suggested_action_counts` (sample)

| `ai_assist_suggested_action` | Count |
|------------------------------|------:|
| `monitor` | 3 |
| `billing_review` | 2 |

### `priority_counts` (sample)

| `ai_assist_suggested_priority` | Count |
|--------------------------------|------:|
| `medium` | 5 |

Counts reflect the first-five replay slice only — **not** the full 166-ticket distribution ([AI assist shadow metrics report](ai_assist_shadow_metrics_report.md): `monitor=109`, `escalate=37`, `billing_review=20`).

---

## Safety / governance status

| Control | Status |
|---------|--------|
| Input passes `assert_hitl_payload_ready()` | **Yes** (5/5) |
| Output passes `assert_hitl_preview_markdown_safe()` | **Yes** |
| Forbidden fields in preview output | **None detected** (no raw query/hash, hits, messages, draft/final) |
| `retrieval_activated` in payloads | **false** (5/5) |
| Safety footer present in preview | **Yes** |
| Production HITL UI / FastAPI route | **Not implemented** |
| Reviewer actions persist workflow state | **No** |
| Draft / final consumption of assist metadata | **No** |
| Customer-facing / auto-send | **Not enabled** |

---

## Governance conclusions

1. **Preview is local-only** — Markdown file under `reports/`; no deployed UI or API in this step.  
2. **No UI route implemented** — rendering is CLI + `app/hitl/hitl_read_only_panel_preview.py` only.  
3. **No reviewer action persisted** — preview is read-only; no approve/reject/send hooks.  
4. **No draft/final/customer behavior changed** — `vendor_ticket_node` and customer paths unchanged; shadow flags remain default **off**.  
5. **Ready for human qualitative review** — operators and governance may review layout, copy, and field coverage on the 5-ticket sample before any production HITL UI proposal.

**This step does not implement real HITL UI.** Reporting only.

---

## Approval status

| Decision | Status |
|----------|--------|
| HITL read-only contract + payload builder (Steps 150–151) | **Recorded** |
| Local mock preview renderer (Step 152) | **Recorded** |
| Preview batch governance report (Step 153) | **Recorded** (this document) |
| Production HITL panel / API | **Not approved** — separate gated step |
| Draft-assist consumption of `ai_assist_*` | **Blocked** |
| Customer-facing AI assist / auto-send | **Blocked** |

**Recommended next step:** Human qualitative review of `reports/hitl_read_only_panel_preview.md` against [HITL read-only visibility contract](hitl_read_only_visibility_contract.md). Optional future step: production read-only HITL UI behind new flags — still no draft/final linkage or customer send.

---

## Related documentation

- [HITL read-only visibility contract](hitl_read_only_visibility_contract.md) — Steps 150–152 (contract, payload, mock preview)  
- [AI assist shadow metrics report](ai_assist_shadow_metrics_report.md) — Step 149 (166-ticket batch)  
- [Vendor ticket AI assist shadow workflow](vendor_ticket_ai_assist_shadow_workflow.md) — Steps 145–148  
- [Non-shadow retrieval consumption governance plan](non_shadow_retrieval_consumption_governance_plan.md) — Step 144
