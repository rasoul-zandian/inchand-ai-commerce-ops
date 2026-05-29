"""Post-generation calibration for grounded policy_explanation drafts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.evals.draft_style import DRAFT_STYLE_POLICY_EXPLANATION
from app.knowledge.policy_fact_extraction import (
    build_sheba_issue_draft_response,
    calibrate_settlement_policy_draft,
    calibrate_sheba_issue_draft,
    draft_has_settlement_grounding,
    is_settlement_account_operational_request,
    is_settlement_bank_policy_question,
    is_settlement_timing_policy_question,
    is_vague_settlement_policy_draft,
)
from app.operator_console.knowledge_hints import KnowledgeHint


@dataclass(frozen=True)
class PolicyGroundingCalibrationResult:
    """Outcome of policy grounding calibration."""

    draft_reply: str
    policy_grounding_calibrated: bool
    settlement_grounding_calibrated: bool


def apply_policy_grounding_calibration(
    draft: str,
    *,
    seller_text: str,
    detected_intent: str | None,
    suggested_action: str | None,
    draft_style: str,
    hints: Sequence[KnowledgeHint | Mapping[str, Any]] = (),
    conceptual_intent_fa: str | None = None,
    extracted_iban: str | None = None,
    has_incomplete_iban_entity: bool = False,
    entity_warnings_summary: str | None = None,
) -> PolicyGroundingCalibrationResult:
    """Ground policy_explanation drafts using safe policy facts when needed."""
    cleaned = draft.strip()

    settlement_policy = is_settlement_bank_policy_question(
        seller_text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    ) or is_settlement_timing_policy_question(
        seller_text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    )
    if settlement_policy and (
        draft_style == DRAFT_STYLE_POLICY_EXPLANATION
        or is_settlement_bank_policy_question(
            seller_text,
            detected_intent=detected_intent,
            conceptual_intent_fa=conceptual_intent_fa,
            suggested_action=suggested_action,
        )
    ):
        calibrated, settlement_changed = calibrate_settlement_policy_draft(
            cleaned,
            seller_text=seller_text,
            detected_intent=detected_intent,
            suggested_action=suggested_action,
            hints=hints,
            conceptual_intent_fa=conceptual_intent_fa,
            draft_style=DRAFT_STYLE_POLICY_EXPLANATION,
        )
        return PolicyGroundingCalibrationResult(
            draft_reply=calibrated,
            policy_grounding_calibrated=settlement_changed,
            settlement_grounding_calibrated=settlement_changed,
        )

    if is_settlement_account_operational_request(
        seller_text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    ):
        calibrated, sheba_changed = calibrate_sheba_issue_draft(
            cleaned,
            seller_text=seller_text,
            detected_intent=detected_intent,
            conceptual_intent_fa=conceptual_intent_fa,
            suggested_action=suggested_action,
            extracted_iban=extracted_iban,
            has_incomplete_iban_entity=has_incomplete_iban_entity,
            entity_warnings_summary=entity_warnings_summary,
        )
        if draft_has_settlement_grounding(cleaned) or is_vague_settlement_policy_draft(cleaned):
            return PolicyGroundingCalibrationResult(
                draft_reply=build_sheba_issue_draft_response(
                    seller_text,
                    extracted_iban=extracted_iban,
                    has_incomplete_iban_entity=has_incomplete_iban_entity,
                    entity_warnings_summary=entity_warnings_summary,
                ),
                policy_grounding_calibrated=True,
                settlement_grounding_calibrated=False,
            )
        if sheba_changed:
            return PolicyGroundingCalibrationResult(
                draft_reply=calibrated,
                policy_grounding_calibrated=True,
                settlement_grounding_calibrated=False,
            )
        return PolicyGroundingCalibrationResult(
            draft_reply=cleaned,
            policy_grounding_calibrated=False,
            settlement_grounding_calibrated=False,
        )

    if draft_style != DRAFT_STYLE_POLICY_EXPLANATION:
        return PolicyGroundingCalibrationResult(
            draft_reply=cleaned,
            policy_grounding_calibrated=False,
            settlement_grounding_calibrated=False,
        )

    if not is_settlement_timing_policy_question(
        seller_text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    ):
        return PolicyGroundingCalibrationResult(
            draft_reply=cleaned,
            policy_grounding_calibrated=False,
            settlement_grounding_calibrated=False,
        )

    calibrated, settlement_changed = calibrate_settlement_policy_draft(
        cleaned,
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        hints=hints,
        conceptual_intent_fa=conceptual_intent_fa,
        draft_style=draft_style,
    )
    return PolicyGroundingCalibrationResult(
        draft_reply=calibrated,
        policy_grounding_calibrated=settlement_changed,
        settlement_grounding_calibrated=settlement_changed,
    )


def policy_grounding_metadata_row(result: PolicyGroundingCalibrationResult) -> dict[str, Any]:
    """Serialize policy grounding calibration for metrics rows."""
    return {
        "policy_grounding_calibrated": result.policy_grounding_calibrated,
        "settlement_grounding_calibrated": result.settlement_grounding_calibrated,
    }


def draft_is_ungrounded_settlement_reply(draft: str) -> bool:
    """True when a settlement policy draft is vague or referral-only."""
    return is_vague_settlement_policy_draft(draft)
