"""OpenAI-powered Persian draft generation for agentic sandbox (draft quality pilot only)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from app.agentic_sandbox.final_draft_reflection import (
    apply_final_draft_reflection_review,
    reflection_metadata_row,
)
from app.agentic_sandbox.mock_draft_templates import (
    MockOperationalDraftInput,
    generate_mock_operational_draft,
)
from app.config import AppSettings, get_settings
from app.evals.actionability_validation import (
    ActionabilityValidationResult,
    apply_actionability_to_draft,
    validate_actionability,
)
from app.evals.conceptual_intent_fa import (
    DraftWithConceptualIntent,
    fallback_conceptual_intent_fa,
    resolve_conceptual_intent_fa,
)
from app.evals.draft_completion_calibration import apply_draft_completion_calibration
from app.evals.draft_evidence_wording_calibration import (
    build_photo_evidence_wording_instruction,
    calibrate_photo_evidence_wording,
)
from app.evals.draft_policy_grounding_calibration import apply_policy_grounding_calibration
from app.evals.draft_product_wording_calibration import (
    apply_product_wording_calibration,
    build_product_wording_prompt_instruction,
)
from app.evals.draft_style import (
    DRAFT_STYLE_POLICY_EXPLANATION,
    apply_draft_style_checks,
    resolve_draft_style_limits,
    resolve_effective_draft_style,
    resolve_effective_draft_style_limits,
    validate_operational_short_draft,
    validate_policy_explanation_draft,
)
from app.evals.first_turn_draft_context import FirstTurnDraftContext
from app.evals.offline_draft_generation import assert_draft_reply_safe
from app.knowledge.policy_fact_extraction import (
    build_policy_facts_prompt_block,
    has_incomplete_iban_signal,
    has_valid_extracted_iban,
    is_settlement_account_operational_request,
    is_settlement_bank_policy_question,
)
from app.llm.types import LLMMessage
from app.workflows.operational_information_sufficiency import (
    apply_panel_issue_draft_calibration,
    build_operational_policy_prompt_hints,
    detect_operational_scenario,
    evaluate_operational_sufficiency,
    is_seller_panel_issue,
    minimum_required_operational_entities,
    resolve_operational_order_ids,
    shop_id_available,
)
from app.workflows.seller_notification_detection import (
    SellerIntentType,
    detect_seller_notification,
)

DRAFT_PROVIDER_MOCK = "mock"
DRAFT_PROVIDER_OPENAI = "openai"
DRAFT_PROVIDER_MOCK_FALLBACK = "mock_fallback"

_GENERIC_BOILERPLATE_PHRASES = (
    "مطابق اقدام پیشنهادی",
    "مطابق اقدام پیشنهادی سیستم",
    "درخواست شما دریافت شد",
    "درخواست شما با موفقیت ثبت شد",
    "در اسرع وقت",
    "نتیجه اطلاع‌رسانی خواهد شد",
    "از صبر و شکیبایی شما سپاسگزاریم",
    "طبق قوانین و مقررات",
    "کارشناسان مربوطه",
    "همراهی شما",
    "مطابق دستورالعمل",
)

_REPETITIVE_TEMPLATE_PATTERNS = (
    re.compile(r"درخواست شما دریافت شد"),
    re.compile(r"توسط تیم مربوطه بررسی"),
    re.compile(r"برای بررسی به تیم"),
)

_MARKDOWN_PATTERN = re.compile(r"[#*_`\[\]]")
_EMOJI_PATTERN = re.compile(
    r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF]",
)


@dataclass(frozen=True)
class OpenAIDraftPromptContext:
    """Safe first-turn context for OpenAI draft generation (no snippets/transcripts)."""

    room_id: str
    seller_text: str
    detected_intent: str
    conceptual_intent_fa: str | None
    suggested_action: str
    suggested_action_reason: str | None
    ticket_label: str | None
    route_label: str | None
    order_ids: tuple[str, ...]
    product_ids: tuple[str, ...]
    tracking_code: str | None
    knowledge_hint_document_types: tuple[str, ...]
    actionability: ActionabilityValidationResult
    target_max_chars: int
    hard_max_chars: int
    draft_style: str = "operational_short"
    max_sentences: int = 2
    policy_facts_prompt: str = ""
    operational_policy_hints: tuple[str, ...] = ()
    extracted_iban: str | None = None
    has_incomplete_iban_entity: bool = False
    entity_warnings_summary: str | None = None
    shop_id_available: bool = False
    panel_issue_detected: bool = False


@dataclass(frozen=True)
class OpenAIDraftQualityResult:
    """Post-generation quality signals for OpenAI drafts."""

    quality_ok: bool
    generic_reply: bool
    repetitive_template: bool
    concise_reply: bool
    openai_draft_quality_rate: float
    generic_reply_rate: float
    concise_reply_rate: float
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class OpenAIDraftGenerationResult:
    """Draft generation outcome including provider and fallback metadata."""

    draft: DraftWithConceptualIntent
    draft_provider: str
    used_mock_fallback: bool
    fallback_warning: str | None
    quality: OpenAIDraftQualityResult


def resolve_openai_draft_settings(
    settings: AppSettings | None = None,
) -> tuple[str, float, int, int]:
    """Return (model, temperature, max_tokens, hard_max_chars)."""
    cfg = settings or get_settings()
    model = (cfg.openai_draft_model or cfg.operator_draft_model or "gpt-4o-mini").strip()
    temperature = float(cfg.openai_draft_temperature)
    max_tokens = int(cfg.openai_draft_max_tokens)
    _style, _max_sent, _target, hard_max = resolve_draft_style_limits(cfg)
    hard_max = min(int(cfg.operator_draft_max_chars), hard_max)
    return model, temperature, max_tokens, hard_max


def build_openai_draft_prompt(context: OpenAIDraftPromptContext) -> list[LLMMessage]:
    """Build safe Persian draft prompt (metadata only; no retrieval snippets)."""
    entities_lines: list[str] = []
    if context.order_ids:
        entities_lines.append("شناسه سفارش (استخراج‌شده): " + ", ".join(context.order_ids))
    if context.product_ids:
        entities_lines.append("شناسه کالا (استخراج‌شده): " + ", ".join(context.product_ids))
    if context.tracking_code:
        entities_lines.append(f"کد رهگیری (استخراج‌شده): {context.tracking_code}")
    entities_block = "\n".join(entities_lines) if entities_lines else "(ندارد)"

    hint_types = (
        ", ".join(context.knowledge_hint_document_types)
        if context.knowledge_hint_document_types
        else "(ندارد)"
    )

    actionability = context.actionability
    if actionability.should_request_identifier:
        actionability_note = (
            "شناسه عملیاتی کافی نیست — فقط شناسه‌های واقعاً لازم را درخواست کن "
            f"({', '.join(actionability.missing_required_entities) or 'مطابق اقدام'})."
        )
    elif actionability.actionable:
        actionability_note = "اقدام از نظر شناسه‌ها قابل انجام است — پاسخ کوتاه و واقع‌بینانه بده."
    else:
        actionability_note = "در صورت ابهام، یک سؤال مشخص بپرس؛ وعده اجرا یا زمان قطعی نده."

    seller_intent = detect_seller_notification(context.seller_text)
    if (
        seller_intent.seller_intent == SellerIntentType.SELLER_NOTIFICATION.value
        and not context.operational_policy_hints
    ):
        scenario_note = (
            "پیام بیشتر شبیه اطلاع/اعلان فروشنده است — اگر جزئیات کافی نیست، "
            "محترمانه بخواهید موضوع را دقیق‌تر توضیح دهند."
        )
    elif context.operational_policy_hints:
        scenario_note = "راهنمای کفایت عملیاتی را رعایت کن."
    else:
        scenario_note = "پاسخ را متناسب با همان موضوع اولیه فروشنده بنویس."

    operational_block = ""
    if context.operational_policy_hints:
        operational_block = (
            "راهنمای کفایت عملیاتی (حداقل اطلاعات لازم):\n"
            + "\n".join(f"- {hint}" for hint in context.operational_policy_hints)
            + "\n\n"
        )

    conceptual = context.conceptual_intent_fa or fallback_conceptual_intent_fa(
        context.detected_intent,
        source_text=context.seller_text,
    )

    style_note = (
        "پاسخ را کامل و شفاف بده؛ متن قانون مرتبط را توضیح بده؛ "
        "خلاصه‌سازی بیش از حد یا ارجاع کلی نده."
        if context.draft_style == DRAFT_STYLE_POLICY_EXPLANATION
        else "پاسخ را بدون جمله پایانی عمومی مثل «تماس بگیرید» یا «اگر سوالی داشتید» تمام کن."
    )

    photo_instruction = build_photo_evidence_wording_instruction(
        seller_text=context.seller_text,
        detected_intent=context.detected_intent,
        conceptual_intent_fa=context.conceptual_intent_fa,
        suggested_action=context.suggested_action,
        missing_entities=context.actionability.missing_required_entities,
    )
    product_wording_instruction = build_product_wording_prompt_instruction(
        seller_text=context.seller_text,
        detected_intent=context.detected_intent,
        conceptual_intent_fa=context.conceptual_intent_fa,
        suggested_action=context.suggested_action,
        draft_style=context.draft_style,
    )
    draft_length_hint = (
        "یک پیش‌نویس پاسخ فارسی شفاف بنویس."
        if context.draft_style == DRAFT_STYLE_POLICY_EXPLANATION
        else "یک پیش‌نویس پاسخ فارسی کوتاه بنویس."
    )
    policy_facts_block = ""
    settlement_account_block = ""
    if is_settlement_bank_policy_question(
        context.seller_text,
        detected_intent=context.detected_intent,
        conceptual_intent_fa=context.conceptual_intent_fa,
        suggested_action=context.suggested_action,
    ):
        settlement_account_block = (
            "این سوال درباره قانون بانک قابل قبول برای تسویه است؛ از فروشنده شماره شبا نخواه.\n"
            "اگر فروشنده می‌پرسد شبا/حساب برای تسویه باید مربوط به کدام بانک باشد، "
            "پاسخ قانونی بده و درخواست ارسال شبا نکن.\n\n"
        )
    elif is_settlement_account_operational_request(
        context.seller_text,
        detected_intent=context.detected_intent,
        conceptual_intent_fa=context.conceptual_intent_fa,
        suggested_action=context.suggested_action,
    ):
        settlement_account_block = (
            "این درخواست عملیاتی مربوط به ثبت/اصلاح اطلاعات تسویه یا شماره شبا است؛ "
            "پاسخ درباره زمان‌بندی تسویه نده.\n"
        )
        if has_valid_extracted_iban(context.extracted_iban, context.seller_text):
            settlement_account_block += (
                "شماره شبا از پیام فروشنده استخراج شده است؛ "
                "دوباره شماره شبا نخواه و فقط ثبت/بررسی را تأیید کن.\n\n"
            )
        elif has_incomplete_iban_signal(
            has_incomplete_iban_entity=context.has_incomplete_iban_entity,
            entity_warnings_summary=context.entity_warnings_summary,
        ):
            settlement_account_block += (
                "شماره شبای ارسال‌شده ناقص یا نامعتبر است؛ فقط شماره شبای صحیح را بخواه.\n\n"
            )
        else:
            settlement_account_block += (
                "شماره شبای معتبر استخراج نشده است؛ فقط شماره شبای صحیح را بخواه.\n\n"
            )
    panel_issue_block = ""
    if context.panel_issue_detected:
        panel_issue_block = (
            "مشکل دسترسی/وضعیت پنل یا فروشگاه شناسایی شده است.\n"
            f"shop_id_available={'true' if context.shop_id_available else 'false'}\n"
            "برای مشکل پنل/دسترسی فروشگاه، شناسه پنل/فروشگاه/shop_id را از فروشنده "
            "نخواه — سیستم shop_id را دارد.\n"
            "علت بسته شدن پنل را حدس نزن و وعده فعال‌سازی مجدد نده.\n"
            "اگر علت بسته‌شدن در تاریخچه نیست، بگو پنل توسط ناظر بررسی می‌شود.\n\n"
        )

    elif context.draft_style == DRAFT_STYLE_POLICY_EXPLANATION and context.policy_facts_prompt:
        policy_facts_block = (
            "حقایق رسمی سیاست (مستقیم استفاده کن؛ زمان‌بندی دیگری اختراع نکن؛ "
            "اگر پاسخ در همین حقایق هست به قوانین ارجاع نده):\n"
            f"{context.policy_facts_prompt}\n\n"
        )
        style_note = (
            "از حقایق سیاست بالا مستقیم استفاده کن؛ زمان‌بندی دیگری اختراع نکن؛ "
            "اگر پاسخ موجود است به قوانین/راهنما ارجاع نده."
        )

    system = (
        "تو یک دستیار داخلی برای نگارش پیش‌نویس پاسخ پشتیبانی فروشندگان هستی. "
        "فقط یک پاسخ فارسی برای بررسی اپراتور تولید کن — نه برای ارسال خودکار.\n"
        "قوانین سخت:\n"
        f"- سبک: {context.draft_style}; حداکثر حدود {context.target_max_chars} کاراکتر "
        f"و حداکثر {context.max_sentences} جمله.\n"
        "- فقط فارسی؛ بدون markdown؛ بدون ایموجی.\n"
        "- بدون وعده قطعی، بدون زمان‌بندی ساختگی، بدون ادعای انجام کار سیستم.\n"
        "- عبارت «مطابق اقدام پیشنهادی» یا متن کلیشه‌ای «درخواست شما دریافت شد» ننویس.\n"
        "- شناسه‌ای که در متن فروشنده نیست اختراع نکن.\n"
        "- اگر فقط سلام/احوال‌پرسی است، محترمانه جزئیات درخواست را بخواه.\n"
        f"- {style_note}\n"
        f"{photo_instruction}\n"
        f"{product_wording_instruction}"
        "- chain-of-thought یا توضیح داخلی ننویس.\n"
        'خروجی فقط JSON: {"draft_reply": "..."}'
    )

    user = (
        f"room_id={context.room_id}\n"
        f"ticket_label={context.ticket_label or '—'}, route_label={context.route_label or '—'}\n"
        f"متن اولین پیام فروشنده:\n{context.seller_text}\n\n"
        f"قصد تشخیص‌داده‌شده: {context.detected_intent}\n"
        f"برچسب مفهومی: {conceptual}\n"
        f"اقدام پیشنهادی داخلی: {context.suggested_action}\n"
        f"دلیل اقدام: {context.suggested_action_reason or '—'}\n"
        f"موجودیت‌های استخراج‌شده:\n{entities_block}\n"
        f"انواع سند راهنما (فقط نوع — بدون متن سند): {hint_types}\n"
        f"راهنمای عملیاتی: {actionability_note}\n"
        f"راهنمای سناریو: {scenario_note}\n"
        f"{operational_block}"
        f"{panel_issue_block}"
        f"{settlement_account_block}"
        f"{policy_facts_block}"
        f"{draft_length_hint}"
    )

    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]


def _strip_json_fences(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def sanitize_openai_draft(
    raw: str,
    *,
    max_chars: int,
    detected_intent: str,
    source_text: str | None = None,
) -> str:
    """Normalize model output to a single safe Persian draft string."""
    stripped = _strip_json_fences(raw)
    draft_raw = stripped
    if stripped.startswith("{"):
        import json

        try:
            payload = json.loads(stripped)
            if isinstance(payload, dict) and isinstance(payload.get("draft_reply"), str):
                draft_raw = payload["draft_reply"]
        except json.JSONDecodeError:
            draft_raw = stripped

    draft = " ".join(str(draft_raw).split())
    draft = _MARKDOWN_PATTERN.sub("", draft)
    draft = _EMOJI_PATTERN.sub("", draft).strip()
    if len(draft) > max_chars:
        draft = draft[: max_chars - 1].rstrip() + "…"
    assert_draft_reply_safe(draft, max_chars=max_chars)
    _ = detected_intent, source_text
    return draft


def generic_response_detection(draft: str) -> bool:
    """True when draft matches low-information generic boilerplate."""
    text = draft.strip()
    if len(text) < 12:
        return True
    for phrase in _GENERIC_BOILERPLATE_PHRASES:
        if phrase in text:
            return True
    low_info_markers = ("درخواست شما", "بررسی خواهد شد", "بررسی می‌شود")
    if all(marker in text for marker in low_info_markers[:2]) and len(text) < 80:
        return True
    return False


def repetitive_template_detection(draft: str) -> bool:
    """True when draft reuses repetitive sandbox boilerplate patterns."""
    return any(pattern.search(draft) for pattern in _REPETITIVE_TEMPLATE_PATTERNS)


def validate_openai_draft_quality(
    draft: str,
    *,
    settings: AppSettings | None = None,
    seller_text: str = "",
    detected_intent: str | None = None,
    suggested_action: str | None = None,
    extracted_order_ids: tuple[str, ...] = (),
    extracted_product_ids: tuple[str, ...] = (),
    tracking_code: str | None = None,
    conceptual_intent_fa: str | None = None,
) -> OpenAIDraftQualityResult:
    """Run style, generic, and repetition checks on a draft."""
    cfg = settings or get_settings()
    style, max_sentences, target_chars, hard_max = resolve_effective_draft_style_limits(
        cfg,
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
    )
    if style == DRAFT_STYLE_POLICY_EXPLANATION:
        style_result = validate_policy_explanation_draft(
            draft,
            target_max_chars=target_chars,
            hard_max_chars=hard_max,
            max_sentences=max_sentences,
        )
    else:
        style_result = validate_operational_short_draft(
            draft,
            target_max_chars=target_chars,
            hard_max_chars=hard_max,
            max_sentences=max_sentences,
        )
    generic = generic_response_detection(draft)
    repetitive = repetitive_template_detection(draft)
    concise = (
        len(draft.strip()) <= target_chars and style_result.draft_sentence_count <= max_sentences
    )

    warnings = list(style_result.draft_style_warnings)
    if generic:
        warnings.append("generic_response_detected")
    if repetitive:
        warnings.append("repetitive_template_detected")
    sufficiency = evaluate_operational_sufficiency(
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        order_ids=extracted_order_ids,
        product_ids=extracted_product_ids,
        tracking_code=tracking_code,
        conceptual_intent_fa=conceptual_intent_fa,
        draft=draft,
    )
    if sufficiency.over_questioning:
        warnings.append("over_questioning_detected")
    if sufficiency.unnecessary_clarification:
        warnings.append("unnecessary_clarification_detected")
    warnings.extend(
        _hallucinated_entity_warnings(
            draft,
            seller_text=seller_text,
            order_ids=extracted_order_ids,
            product_ids=extracted_product_ids,
        )
    )

    quality_ok = (
        style_result.draft_style_ok
        and not generic
        and not repetitive
        and not sufficiency.over_questioning
        and not sufficiency.unnecessary_clarification
    )
    rate = 1.0 if quality_ok else 0.0
    return OpenAIDraftQualityResult(
        quality_ok=quality_ok,
        generic_reply=generic,
        repetitive_template=repetitive,
        concise_reply=concise,
        openai_draft_quality_rate=rate,
        generic_reply_rate=1.0 if generic else 0.0,
        concise_reply_rate=1.0 if concise else 0.0,
        warnings=tuple(warnings),
    )


def _hallucinated_entity_warnings(
    draft: str,
    *,
    seller_text: str,
    order_ids: tuple[str, ...],
    product_ids: tuple[str, ...],
) -> list[str]:
    """Flag order/product tokens in draft that are absent from seller text and extraction."""
    warnings: list[str] = []
    seller_norm = seller_text or ""
    for order_id in order_ids:
        if order_id in draft and order_id not in seller_norm:
            warnings.append(f"possible_hallucinated_order:{order_id}")
    for product_id in product_ids:
        if product_id in draft and product_id not in seller_norm:
            warnings.append(f"possible_hallucinated_product:{product_id}")
    return warnings


def _call_openai_chat(
    messages: list[LLMMessage],
    *,
    model: str,
    temperature: float,
    max_tokens: int,
) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": m.role, "content": m.content} for m in messages],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = response.choices[0].message.content if response.choices else None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("OpenAI returned empty draft content")
    return content


def generate_openai_draft(
    context: OpenAIDraftPromptContext,
    *,
    settings: AppSettings | None = None,
    generate_fn: Any | None = None,
) -> OpenAIDraftGenerationResult:
    """Generate draft via OpenAI; fall back to mock templates on failure."""
    cfg = settings or get_settings()
    model, temperature, max_tokens, hard_max = resolve_openai_draft_settings(cfg)
    _style, _max_sent, target_chars, _hard = resolve_draft_style_limits(cfg)

    try:
        if generate_fn is not None:
            response = generate_fn(
                build_openai_draft_prompt(context),
                provider="openai",
                model=model,
            )
            raw_content = getattr(response, "content", response)
        else:
            raw_content = _call_openai_chat(
                build_openai_draft_prompt(context),
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        draft_text = sanitize_openai_draft(
            str(raw_content),
            max_chars=hard_max,
            detected_intent=context.detected_intent,
            source_text=context.seller_text,
        )
        conceptual = resolve_conceptual_intent_fa(
            context.conceptual_intent_fa,
            detected_intent=context.detected_intent,
            source_text=context.seller_text,
        )
        quality = validate_openai_draft_quality(
            draft_text,
            settings=cfg,
            seller_text=context.seller_text,
            detected_intent=context.detected_intent,
            suggested_action=context.suggested_action,
            extracted_order_ids=context.order_ids,
            extracted_product_ids=context.product_ids,
            tracking_code=context.tracking_code,
            conceptual_intent_fa=conceptual,
        )
        return OpenAIDraftGenerationResult(
            draft=DraftWithConceptualIntent(
                draft_reply=draft_text,
                conceptual_intent_fa=conceptual,
            ),
            draft_provider=DRAFT_PROVIDER_OPENAI,
            used_mock_fallback=False,
            fallback_warning=None,
            quality=quality,
        )
    except Exception as exc:  # noqa: BLE001
        mock_draft = generate_mock_operational_draft(
            MockOperationalDraftInput(
                detected_intent=context.detected_intent,
                conceptual_intent_fa=context.conceptual_intent_fa,
                suggested_action=context.suggested_action,
                suggested_action_reason=context.suggested_action_reason,
                seller_text=context.seller_text,
                order_ids=context.order_ids,
                product_ids=context.product_ids,
                tracking_code=context.tracking_code,
                actionability={
                    "actionability_actionable": context.actionability.actionable,
                    "actionability_missing_entities": ",".join(
                        context.actionability.missing_required_entities,
                    ),
                    "requires_identifier_request": context.actionability.should_request_identifier,
                    "requested_action": context.actionability.requested_action,
                },
            ),
            max_chars=hard_max,
        )
        quality = validate_openai_draft_quality(
            mock_draft,
            settings=cfg,
            seller_text=context.seller_text,
            detected_intent=context.detected_intent,
            suggested_action=context.suggested_action,
            extracted_order_ids=context.order_ids,
            extracted_product_ids=context.product_ids,
            tracking_code=context.tracking_code,
            conceptual_intent_fa=context.conceptual_intent_fa,
        )
        return OpenAIDraftGenerationResult(
            draft=DraftWithConceptualIntent(
                draft_reply=mock_draft,
                conceptual_intent_fa=context.conceptual_intent_fa
                or fallback_conceptual_intent_fa(
                    context.detected_intent,
                    source_text=context.seller_text,
                ),
            ),
            draft_provider=DRAFT_PROVIDER_MOCK_FALLBACK,
            used_mock_fallback=True,
            fallback_warning=f"openai_draft_fallback: {exc}",
            quality=quality,
        )


def _override_actionability_for_operational_sufficiency(
    validation: ActionabilityValidationResult,
    *,
    seller_text: str,
    detected_intent: str,
    suggested_action: str,
    order_ids: tuple[str, ...],
    product_ids: tuple[str, ...],
    tracking_code: str | None,
    conceptual_intent_fa: str | None,
) -> ActionabilityValidationResult:
    """Align actionability prompt notes with operational sufficiency (not raw delivery action)."""
    scenario = detect_operational_scenario(
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        conceptual_intent_fa=conceptual_intent_fa,
    )
    if scenario not in {"cancellation_request", "delivery_completed", "shipment_reshipment"}:
        return validation

    effective_orders = resolve_operational_order_ids(
        seller_text,
        order_ids,
        scenario=scenario,
    )
    missing = minimum_required_operational_entities(
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        order_ids=effective_orders,
        product_ids=product_ids,
        tracking_code=tracking_code,
        conceptual_intent_fa=conceptual_intent_fa,
    )
    if not missing:
        return ActionabilityValidationResult(
            actionable=True,
            missing_required_entities=(),
            requested_action=validation.requested_action,
            validation_reason="operational_sufficiency_complete",
            should_request_identifier=False,
        )
    if scenario in {"cancellation_request", "delivery_completed"} and missing == ("order_id",):
        return ActionabilityValidationResult(
            actionable=False,
            missing_required_entities=("order_id",),
            requested_action=validation.requested_action,
            validation_reason="operational_sufficiency_missing_order_id",
            should_request_identifier=True,
        )
    if scenario == "shipment_reshipment":
        return ActionabilityValidationResult(
            actionable=not bool(missing),
            missing_required_entities=missing,
            requested_action=validation.requested_action,
            validation_reason="operational_sufficiency_shipment",
            should_request_identifier=bool(missing),
        )
    return validation


def build_openai_prompt_context_from_graph(
    state: dict[str, Any],
    ctx: FirstTurnDraftContext,
    *,
    settings: AppSettings | None = None,
) -> OpenAIDraftPromptContext:
    """Build prompt context from sandbox graph state (post intent/entity/action nodes)."""
    cfg = settings or get_settings()
    detected = str(state.get("detected_intent") or ctx.first_turn_intent.detected_intent)
    suggested = str(state.get("suggested_action") or ctx.suggested_action)
    conceptual = state.get("conceptual_intent_fa")
    draft_style, max_sentences, target_chars, hard_max = resolve_effective_draft_style_limits(
        cfg,
        seller_text=ctx.first_turn_text,
        detected_intent=detected,
        suggested_action=suggested,
        conceptual_intent_fa=conceptual,
    )
    entities = ctx.first_turn_entities
    order_ids = tuple(entities.order_ids) if entities and entities.order_ids else ()
    product_ids = tuple(entities.product_ids) if entities and entities.product_ids else ()
    tracking = getattr(entities, "primary_tracking_code", None) if entities else None
    extracted_iban = (
        entities.primary_iban
        if entities and entities.primary_iban
        else ctx.first_turn_intent.extracted_iban
    )
    has_incomplete_iban_entity = entities.has_incomplete_iban_candidate if entities else False
    entity_warnings_summary = (
        entities.entity_warnings_summary if entities else None
    ) or ctx.first_turn_intent.entity_warnings_summary

    actionability_raw = state.get("actionability") or {}
    validation = validate_actionability(
        suggested_action=ctx.suggested_action,
        entities=ctx.first_turn_intent,
        seller_text=ctx.first_turn_text,
        detected_intent=ctx.first_turn_intent.detected_intent,
    )
    if (
        isinstance(actionability_raw, dict)
        and actionability_raw.get("actionability_actionable") is not None
    ):
        missing = actionability_raw.get("actionability_missing_entities") or ""
        validation = ActionabilityValidationResult(
            actionable=bool(actionability_raw.get("actionability_actionable")),
            missing_required_entities=tuple(
                part.strip() for part in str(missing).replace(",", " ").split() if part.strip()
            ),
            requested_action=str(
                actionability_raw.get("requested_action") or ctx.suggested_action,
            ),
            validation_reason=str(
                actionability_raw.get("actionability_validation_reason")
                or validation.validation_reason,
            ),
            should_request_identifier=bool(
                actionability_raw.get(
                    "requires_identifier_request",
                    validation.should_request_identifier,
                ),
            ),
        )

    hint_types: list[str] = []
    for item in state.get("knowledge_hints") or []:
        if isinstance(item, dict) and item.get("document_type"):
            hint_types.append(str(item["document_type"]))

    ticket_shop_id = state.get("shop_id")
    policy_hints = build_operational_policy_prompt_hints(
        seller_text=ctx.first_turn_text,
        detected_intent=detected,
        suggested_action=suggested,
        order_ids=order_ids,
        product_ids=product_ids,
        tracking_code=tracking,
        conceptual_intent_fa=conceptual,
        extracted_iban=extracted_iban,
        has_incomplete_iban_entity=has_incomplete_iban_entity,
        entity_warnings_summary=entity_warnings_summary,
        shop_id=ticket_shop_id,
    )
    panel_detected = is_seller_panel_issue(
        ctx.first_turn_text,
        detected_intent=detected,
        suggested_action=suggested,
        conceptual_intent_fa=conceptual,
        order_ids=order_ids,
        product_ids=product_ids,
    )
    validation = _override_actionability_for_operational_sufficiency(
        validation,
        seller_text=ctx.first_turn_text,
        detected_intent=detected,
        suggested_action=suggested,
        order_ids=order_ids,
        product_ids=product_ids,
        tracking_code=tracking,
        conceptual_intent_fa=conceptual,
    )

    prompt_hints_raw = state.get("knowledge_hints_for_prompt") or []
    policy_hint_sources: list[Any] = list(prompt_hints_raw) if prompt_hints_raw else []
    if not policy_hint_sources and ctx.first_turn_policy_hints:
        policy_hint_sources = list(ctx.first_turn_policy_hints)
    policy_facts_prompt = ""
    if draft_style == DRAFT_STYLE_POLICY_EXPLANATION and policy_hint_sources:
        policy_facts_prompt = build_policy_facts_prompt_block(
            detected_intent=detected,
            suggested_action=suggested,
            seller_text=ctx.first_turn_text,
            document_types=tuple(dict.fromkeys(hint_types)),
            hints=policy_hint_sources,
            conceptual_intent_fa=conceptual,
        )

    return OpenAIDraftPromptContext(
        room_id=str(state.get("room_id") or ""),
        seller_text=ctx.first_turn_text,
        detected_intent=detected,
        conceptual_intent_fa=conceptual,
        suggested_action=suggested,
        suggested_action_reason=state.get("suggested_action_reason") or ctx.suggested_action_reason,
        ticket_label=state.get("ticket_label"),
        route_label=state.get("route_label"),
        order_ids=order_ids,
        product_ids=product_ids,
        tracking_code=tracking,
        knowledge_hint_document_types=tuple(dict.fromkeys(hint_types)),
        actionability=validation,
        target_max_chars=target_chars,
        hard_max_chars=hard_max,
        draft_style=draft_style,
        max_sentences=max_sentences,
        policy_facts_prompt=policy_facts_prompt,
        operational_policy_hints=policy_hints,
        extracted_iban=extracted_iban,
        has_incomplete_iban_entity=has_incomplete_iban_entity,
        entity_warnings_summary=entity_warnings_summary,
        shop_id_available=shop_id_available(shop_id=ticket_shop_id),
        panel_issue_detected=panel_detected,
    )


def generate_openai_draft_for_sandbox_state(
    state: dict[str, Any],
    ctx: FirstTurnDraftContext,
    *,
    settings: AppSettings | None = None,
    generate_fn: Any | None = None,
) -> tuple[DraftWithConceptualIntent, OpenAIDraftGenerationResult]:
    """Full OpenAI draft path with post-processing used by generate_draft_node."""
    cfg = settings or get_settings()
    prompt_ctx = build_openai_prompt_context_from_graph(state, ctx, settings=cfg)
    generation = generate_openai_draft(prompt_ctx, settings=cfg, generate_fn=generate_fn)
    draft_result = generation.draft

    completion = apply_draft_completion_calibration(
        draft_result.draft_reply,
        seller_text=ctx.first_turn_text,
        suggested_action=ctx.suggested_action,
        detected_intent=ctx.first_turn_intent.detected_intent,
        entity_warnings_summary=ctx.first_turn_intent.entity_warnings_summary,
    )
    validation = validate_actionability(
        suggested_action=ctx.suggested_action,
        entities=ctx.first_turn_intent,
        seller_text=ctx.first_turn_text,
        detected_intent=ctx.first_turn_intent.detected_intent,
    )
    draft_text, validation = apply_actionability_to_draft(
        completion.draft_reply,
        validation,
        seller_text=ctx.first_turn_text,
    )
    draft_text, _photo_calibrated, _unnecessary_photo = calibrate_photo_evidence_wording(
        draft_text,
        seller_text=ctx.first_turn_text,
        detected_intent=ctx.first_turn_intent.detected_intent,
        suggested_action=ctx.suggested_action,
        conceptual_intent_fa=prompt_ctx.conceptual_intent_fa,
        missing_entities=validation.missing_required_entities,
        product_ids=tuple(
            ctx.first_turn_entities.product_ids
            if ctx.first_turn_entities and ctx.first_turn_entities.product_ids
            else ()
        ),
        extracted_iban=prompt_ctx.extracted_iban,
        has_incomplete_iban_entity=prompt_ctx.has_incomplete_iban_entity,
        entity_warnings_summary=prompt_ctx.entity_warnings_summary,
    )
    effective_style = resolve_effective_draft_style(
        seller_text=ctx.first_turn_text,
        detected_intent=ctx.first_turn_intent.detected_intent,
        suggested_action=ctx.suggested_action,
        conceptual_intent_fa=prompt_ctx.conceptual_intent_fa,
    )
    prompt_hints = state.get("knowledge_hints_for_prompt") or ctx.first_turn_policy_hints
    grounding = apply_policy_grounding_calibration(
        draft_text,
        seller_text=ctx.first_turn_text,
        detected_intent=ctx.first_turn_intent.detected_intent,
        suggested_action=ctx.suggested_action,
        draft_style=effective_style,
        hints=tuple(prompt_hints),
        conceptual_intent_fa=prompt_ctx.conceptual_intent_fa,
        extracted_iban=prompt_ctx.extracted_iban,
        has_incomplete_iban_entity=prompt_ctx.has_incomplete_iban_entity,
        entity_warnings_summary=prompt_ctx.entity_warnings_summary,
    )
    draft_text = grounding.draft_reply
    draft_text, _panel_metrics = apply_panel_issue_draft_calibration(
        draft_text,
        seller_text=ctx.first_turn_text,
        detected_intent=ctx.first_turn_intent.detected_intent,
        suggested_action=ctx.suggested_action,
        conceptual_intent_fa=prompt_ctx.conceptual_intent_fa,
        order_ids=prompt_ctx.order_ids,
        product_ids=prompt_ctx.product_ids,
        shop_id=state.get("shop_id"),
    )
    draft_text, _product_wording = apply_product_wording_calibration(
        draft_text,
        seller_text=ctx.first_turn_text,
        detected_intent=ctx.first_turn_intent.detected_intent,
        suggested_action=ctx.suggested_action,
        conceptual_intent_fa=prompt_ctx.conceptual_intent_fa,
        draft_style=effective_style,
        product_ids=prompt_ctx.product_ids,
    )
    draft_text, reflection_result = apply_final_draft_reflection_review(
        draft_text,
        seller_text=ctx.first_turn_text,
        detected_intent=ctx.first_turn_intent.detected_intent,
        suggested_action=ctx.suggested_action,
        conceptual_intent_fa=prompt_ctx.conceptual_intent_fa,
        draft_style=effective_style,
        order_ids=prompt_ctx.order_ids,
        product_ids=prompt_ctx.product_ids,
        tracking_code=prompt_ctx.tracking_code,
        extracted_iban=prompt_ctx.extracted_iban,
        has_incomplete_iban_entity=prompt_ctx.has_incomplete_iban_entity,
        entity_warnings_summary=prompt_ctx.entity_warnings_summary,
        shop_id=state.get("shop_id"),
        policy_hints=tuple(prompt_hints),
        draft_provider=generation.draft_provider,
        runtime_shop_identity_available=bool(
            state.get("shop_identity_available")
            or state.get("shop_id")
            or state.get("seller_id")
            or state.get("shop_name")
        ),
        runtime_shop_id_present=bool(state.get("shop_id")),
        settings=cfg,
    )
    _ = reflection_metadata_row(reflection_result)
    apply_draft_style_checks(
        draft_text,
        cfg,
        seller_text=ctx.first_turn_text,
        detected_intent=ctx.first_turn_intent.detected_intent,
        suggested_action=ctx.suggested_action,
    )
    assert_draft_reply_safe(draft_text, max_chars=prompt_ctx.hard_max_chars)

    final = DraftWithConceptualIntent(
        draft_reply=draft_text,
        conceptual_intent_fa=draft_result.conceptual_intent_fa,
    )
    return final, generation


def openai_draft_metrics_row(generation: OpenAIDraftGenerationResult) -> dict[str, Any]:
    """Serialize provider/quality metrics for JSONL or session metadata."""
    return {
        "draft_provider": generation.draft_provider,
        "used_mock_fallback": generation.used_mock_fallback,
        "fallback_to_mock_rate": 1.0 if generation.used_mock_fallback else 0.0,
        "openai_draft_quality_rate": generation.quality.openai_draft_quality_rate,
        "generic_reply_rate": generation.quality.generic_reply_rate,
        "concise_reply_rate": generation.quality.concise_reply_rate,
        "draft_quality_ok": generation.quality.quality_ok,
        "draft_quality_warnings": list(generation.quality.warnings),
    }
