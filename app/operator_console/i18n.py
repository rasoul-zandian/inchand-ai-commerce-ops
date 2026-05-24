"""Operator console UI translations (FA/EN) and RTL layout helpers."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any

CONSOLE_LANG_SESSION_KEY = "operator_console_lang"
LANG_FA = "fa"
LANG_EN = "en"
DEFAULT_CONSOLE_LANG = LANG_FA

_TRANSLATIONS: dict[str, dict[str, str]] = {
    "page_title": {
        "fa": "کنسول اپراتور تیکت فروشنده",
        "en": "Vendor ticket operator console",
    },
    "page_disclaimer": {
        "fa": (
            "**کنسول داخلی اپراتور (فقط محلی).** متادیتای تجمیعی به‌همراه حالت گفتگوی کامل "
            "(رداکت‌شده، فقط سندباکس). بدون پاسخ به مشتری، بدون ارسال خودکار، "
            "بدون تغییر تیکت/سفارش."
        ),
        "en": (
            "**Internal operator console (local only).** Aggregate metadata plus optional "
            "full conversation mode (redacted, sandbox-only). No customer responses, "
            "no auto-send, no ticket mutation."
        ),
    },
    "language_label": {"fa": "زبان رابط", "en": "UI language"},
    "sidebar_data_source": {"fa": "منبع داده", "en": "Data source"},
    "sidebar_feedback_log": {"fa": "**گزارش بازخورد**", "en": "**Feedback log**"},
    "sidebar_sandbox_reviews": {
        "fa": "**بازبینی پیش‌نمایش سندباکس**",
        "en": "**Sandbox preview reviews**",
    },
    "select_ticket": {"fa": "انتخاب تیکت", "en": "Select ticket"},
    "agentic_sandbox_preview": {
        "fa": "پیش‌نمایش سندباکس عامل",
        "en": "Agentic sandbox preview",
    },
    "agentic_sandbox_preview_caption": {
        "fa": (
            "تفسیر فقط‌خواندنی LangGraph سندباکس (فقط نوبت اول). "
            "فقط در جلسه — ارسال/ذخیره در DB نمی‌شود. "
            "جدا از پیش‌نمایش پیش‌نویس آفلاین."
        ),
        "en": (
            "Read-only LangGraph sandbox interpretation (first-turn only). "
            "Session-only — not sent, not persisted to DB. Distinct from offline draft preview."
        ),
    },
    "run_sandbox_graph": {"fa": "اجرای گراف سندباکس", "en": "Run sandbox graph"},
    "no_sandbox_preview": {
        "fa": "پیش‌نمایش سندباکسی در این جلسه نیست. **اجرای گراف سندباکس** را بزنید.",
        "en": "No sandbox preview in this session. Click **Run sandbox graph**.",
    },
    "sandbox_graph_done": {
        "fa": "گراف سندباکس تکمیل شد (فقط جلسه).",
        "en": "Sandbox graph completed (session-only).",
    },
    "operator_assisted_mode": {
        "fa": "حالت کمکی عامل برای اپراتور",
        "en": "Operator-assisted agentic mode",
    },
    "operator_assisted_caption": {
        "fa": (
            "بسته کاری HITL ساختاریافته از گراف سندباکس (فقط نوبت اول). "
            "فقط جلسه — بدون ارسال، بدون تغییر تیکت. "
            "جدا از **پیش‌نمایش سندباکس عامل** (نمای تشخیصی)."
        ),
        "en": (
            "Structured HITL work package from the sandbox LangGraph (first-turn only). "
            "Session-only — not sent, not persisted to DB, no ticket mutation. "
            "Distinct from **Agentic sandbox preview** (diagnostic graph view)."
        ),
    },
    "run_assisted_package": {"fa": "اجرای بسته کمکی", "en": "Run assisted package"},
    "refresh_assisted_package": {
        "fa": "بروزرسانی بسته کمکی",
        "en": "Refresh assisted package",
    },
    "no_assisted_package": {
        "fa": (
            "بسته کمکی در این جلسه نیست. پس از آماده بودن فارغ‌التحصیلی "
            "**اجرای بسته کمکی** را بزنید."
        ),
        "en": (
            "No assisted package in this session. Click **Run assisted package** "
            "after graduation is ready."
        ),
    },
    "assisted_package_ready": {
        "fa": "بسته کمکی آماده است (فقط جلسه).",
        "en": "Assisted package ready (session-only).",
    },
    "internal_draft_suggestion": {
        "fa": "پیش‌نویس پیشنهادی داخلی",
        "en": "Internal draft suggestion",
    },
    "internal_draft_caption": {
        "fa": "این متن فقط برای بررسی اپراتور است و به فروشنده ارسال نمی‌شود.",
        "en": "Internal review only — not sent to the vendor.",
    },
    "internal_draft_section": {
        "fa": "پیش‌نویس داخلی (گراف سندباکس)",
        "en": "Internal draft (sandbox graph)",
    },
    "draft_mock_label": {
        "fa": "(پیش‌نویس mock — فقط برای بررسی داخلی)",
        "en": "(mock draft — internal review only)",
    },
    "draft_source_mock_template": {
        "fa": "منبع پیش‌نویس: الگوی mock",
        "en": "Draft source: mock template",
    },
    "draft_source_openai": {
        "fa": "منبع پیش‌نویس: OpenAI",
        "en": "Draft source: OpenAI",
    },
    "assisted_section_vendor_summary": {
        "fa": "خلاصه درخواست فروشنده",
        "en": "Seller request summary",
    },
    "assisted_section_suggested_action": {
        "fa": "اقدام پیشنهادی",
        "en": "Suggested action",
    },
    "assisted_section_information_status": {
        "fa": "وضعیت اطلاعات",
        "en": "Information status",
    },
    "assisted_section_extracted_entities": {
        "fa": "شناسه‌های استخراج‌شده",
        "en": "Extracted identifiers",
    },
    "assisted_section_internal_draft": {
        "fa": "پاسخ پیشنهادی داخلی",
        "en": "Internal suggested reply",
    },
    "assisted_section_safety": {
        "fa": "وضعیت ایمنی",
        "en": "Safety status",
    },
    "assisted_debug_expander": {
        "fa": "جزئیات فنی / تشخیصی (گراف)",
        "en": "Technical / diagnostic details (graph)",
    },
    "assisted_draft_review_box": {
        "fa": "متن پیش‌نویس (فقط مشاهده)",
        "en": "Draft text (read-only)",
    },
    "assisted_action_reason": {"fa": "توضیح کوتاه", "en": "Short explanation"},
    "assisted_missing_identifiers": {
        "fa": "شناسه‌های موردنیاز (در صورت نبود)",
        "en": "Required identifiers (if missing)",
    },
    "assisted_validation_reason": {"fa": "دلیل اعتبارسنجی", "en": "Validation reason"},
    "assisted_none_missing": {"fa": "موردی ثبت نشده", "en": "None noted"},
    "assisted_orders": {"fa": "شماره سفارش", "en": "Order IDs"},
    "assisted_products": {"fa": "شناسه کالا", "en": "Product IDs"},
    "assisted_tracking": {"fa": "کد رهگیری", "en": "Tracking code"},
    "assisted_iban": {"fa": "شبا (نمایش امن)", "en": "IBAN (masked)"},
    "assisted_no_entities": {
        "fa": "شناسه‌ای استخراج نشده است.",
        "en": "No identifiers extracted.",
    },
    "assisted_actionable_yes": {"fa": "قابل اقدام", "en": "Actionable"},
    "assisted_actionable_no": {
        "fa": "نیازمند شناسه / غیرقابل اقدام",
        "en": "Needs identifier / not actionable",
    },
    "assisted_draft_unavailable": {
        "fa": "پیش‌نویس امن برای نمایش موجود نیست.",
        "en": "No safe draft available for display.",
    },
    "assisted_human_review_required": {
        "fa": "نیاز به بازبینی انسان",
        "en": "Human review required",
    },
    "assisted_execution_disabled": {
        "fa": "اجرای خودکار غیرفعال",
        "en": "Execution disabled",
    },
    "assisted_customer_send_disabled": {
        "fa": "ارسال به فروشنده غیرفعال",
        "en": "Customer send disabled",
    },
    "draft_char_count": {"fa": "طول پیش‌نویس", "en": "Draft length"},
    "draft_style": {"fa": "سبک پیش‌نویس", "en": "Draft style"},
    "safety_status": {"fa": "وضعیت ایمنی", "en": "Safety status"},
    "sandbox_preview_review": {
        "fa": "بازبینی پیش‌نمایش سندباکس",
        "en": "Sandbox preview review",
    },
    "sandbox_preview_review_caption": {
        "fa": (
            "ارزیابی HITL سطح گراف — ذخیره در "
            "`reports/agentic_preview_review_feedback.jsonl`. "
            "بدون یادگیری خودکار یا ارسال."
        ),
        "en": (
            "Graph-level HITL evaluation — saved to "
            "`reports/agentic_preview_review_feedback.jsonl`. "
            "Not used for auto-tuning, mapping changes, or customer send."
        ),
    },
    "submit_sandbox_review": {"fa": "ثبت بازبینی سندباکس", "en": "Submit sandbox review"},
    "review_unnecessary_additional_details": {
        "fa": "درخواست اطلاعات اضافه غیرضروری داشت",
        "en": "Asked for unnecessary additional details",
    },
    "draft_review": {"fa": "بازبینی پیش‌نویس", "en": "Draft review"},
    "submit_review": {"fa": "ثبت بازبینی", "en": "Submit review"},
    "suggested_action": {"fa": "اقدام پیشنهادی", "en": "Suggested action"},
    "actionability": {"fa": "قابلیت اجرا", "en": "Actionability"},
    "extracted_entities": {"fa": "موجودیت‌های استخراج‌شده", "en": "Extracted entities"},
    "knowledge_hints": {"fa": "راهنمای دانش", "en": "Knowledge hints"},
    "graph_status": {"fa": "وضعیت گراف", "en": "Graph status"},
    "detected_intent": {"fa": "نیت تشخیص‌داده‌شده", "en": "Detected intent"},
    "useful_label": {"fa": "مفید", "en": "Useful"},
    "helpful_label": {"fa": "مفید", "en": "Helpful"},
    "assisted_checklist_1": {
        "fa": "نیت تشخیص‌داده‌شده را با پیام اول فروشنده تطبیق دهید.",
        "en": "Verify detected intent matches the first seller message.",
    },
    "assisted_checklist_2": {
        "fa": "موجودیت‌های استخراج‌شده (شناسه سفارش/محصول، رهگیری، شبا) را بررسی کنید.",
        "en": "Verify extracted entities (order/product IDs, tracking, masked IBAN).",
    },
    "assisted_checklist_3": {
        "fa": "قابلیت اجرا و شناسه‌های جاافتاده را قبل از هر اقدام عملیاتی بررسی کنید.",
        "en": "Verify actionability and any missing identifiers before operational steps.",
    },
    "assisted_checklist_4": {
        "fa": "متن پیش‌نویس زیر را قبل از استفاده بررسی کنید.",
        "en": "Verify draft text below before use.",
    },
    "assisted_checklist_5": {
        "fa": "از این حالت پاسخ به فروشنده ارسال نکنید؛ اجرا و ارسال غیرفعال است.",
        "en": "Do not send customer replies from this mode; execution and send remain disabled.",
    },
    "operator_checklist_heading": {
        "fa": "**چک‌لیست اپراتور**",
        "en": "**Operator checklist**",
    },
    "structured_assistance_heading": {
        "fa": "**کمک ساختاریافته (گراف سندباکس)**",
        "en": "**Structured assistance (sandbox graph)**",
    },
    "assisted_feedback_note": {
        "fa": (
            "این خروجی گراف را با **بازبینی پیش‌نمایش سندباکس** پایین صفحه "
            "ارزیابی کنید (همان schema بازخورد)."
        ),
        "en": (
            "Review this graph output using **Sandbox preview review** below "
            "(same `agentic_preview_review_feedback.jsonl` schema)."
        ),
    },
}

_ASSISTED_CHECKLIST_KEYS: tuple[str, ...] = (
    "assisted_checklist_1",
    "assisted_checklist_2",
    "assisted_checklist_3",
    "assisted_checklist_4",
    "assisted_checklist_5",
)


def normalize_console_lang(lang: str | None) -> str:
    if lang in (LANG_FA, LANG_EN):
        return lang
    return DEFAULT_CONSOLE_LANG


def get_console_language(session_state: Mapping[str, Any] | None = None) -> str:
    if session_state is None:
        return DEFAULT_CONSOLE_LANG
    return normalize_console_lang(session_state.get(CONSOLE_LANG_SESSION_KEY))


def set_console_language(session_state: MutableMapping[str, Any], lang: str) -> None:
    session_state[CONSOLE_LANG_SESSION_KEY] = normalize_console_lang(lang)


def is_fa(lang: str) -> bool:
    return normalize_console_lang(lang) == LANG_FA


def t(key: str, lang: str | None = None) -> str:
    entry = _TRANSLATIONS.get(key)
    if entry is None:
        return key
    resolved = normalize_console_lang(lang)
    return entry.get(resolved) or entry.get(LANG_EN) or key


def assisted_checklist_for_lang(lang: str) -> tuple[str, ...]:
    return tuple(t(item_key, lang) for item_key in _ASSISTED_CHECKLIST_KEYS)


def apply_console_direction_css(lang: str) -> str:
    """Return global CSS for FA RTL layout (sidebar right) or empty string for EN."""
    if not is_fa(lang):
        return ""
    return """
<style>
/* Flip app shell so sidebar docks on the right */
[data-testid="stAppViewContainer"] {
  direction: rtl;
}
[data-testid="stAppViewContainer"] > .main {
  direction: rtl;
}
section[data-testid="stSidebar"] {
  right: 0 !important;
  left: auto !important;
  direction: rtl;
  text-align: right;
}
section[data-testid="stSidebar"] > div {
  direction: rtl;
  text-align: right;
}
[data-testid="stAppViewContainer"] .main .block-container {
  direction: rtl;
  text-align: right;
}
[data-testid="stMarkdownContainer"],
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stMetricValue"],
[data-testid="stMetricLabel"],
label[data-testid="stWidgetLabel"],
.stRadio label,
.stCheckbox label,
.stExpander summary,
.stAlert {
  direction: rtl;
  text-align: right;
}
div[data-baseweb="select"] > div,
div[data-baseweb="input"] > div,
.stSelectbox label,
.stTextInput label,
.stTextArea label,
.stNumberInput label {
  direction: rtl;
  text-align: right;
}
.stButton > button {
  direction: rtl;
}
[data-testid="stHorizontalBlock"] {
  direction: rtl;
  flex-direction: row-reverse;
}
[data-testid="column"] {
  direction: rtl;
}
.operator-console-ltr,
.operator-console-ltr pre,
.operator-console-ltr code,
.stCode,
.stCodeBlock,
pre,
code {
  direction: ltr !important;
  text-align: left !important;
  unicode-bidi: isolate;
}
</style>
"""
