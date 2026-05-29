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
    "data_source_historical_replay": {
        "fa": "بازپخش تاریخی",
        "en": "Historical replay",
    },
    "data_source_live_api_feed": {
        "fa": "API زنده",
        "en": "Live API feed",
    },
    "data_source_manual_sandbox_chat": {
        "fa": "چت آزمایشی دستی",
        "en": "Manual sandbox chat",
    },
    "manual_sandbox_disclaimer": {
        "fa": (
            "«این یک شبیه‌سازی محلی است و هیچ پیامی به اینچند ارسال نمی‌شود.» "
            "بدون ارسال، بدون تغییر تیکت زنده، بدون API نوشتن."
        ),
        "en": (
            "This is a local sandbox simulation. Nothing is sent to Inchand. "
            "No send, no live ticket mutation, no write APIs."
        ),
    },
    "manual_sandbox_ticket_label": {"fa": "برچسب تیکت (اختیاری)", "en": "Ticket label (optional)"},
    "manual_sandbox_ticket_label_auto": {
        "fa": "خودکار / انتخاب نشده",
        "en": "auto / unset",
    },
    "manual_sandbox_ticket_label_complaint": {"fa": "شکایت", "en": "complaint"},
    "manual_sandbox_ticket_label_fund": {"fa": "مالی", "en": "fund"},
    "manual_sandbox_ticket_label_support": {"fa": "پشتیبانی", "en": "support"},
    "manual_sandbox_room_id": {"fa": "شناسه اتاق", "en": "Room ID"},
    "manual_sandbox_shop_id": {"fa": "شناسه فروشگاه (اختیاری)", "en": "Shop ID (optional)"},
    "manual_sandbox_role_seller": {"fa": "فروشنده", "en": "Seller"},
    "manual_sandbox_role_support": {"fa": "پشتیبانی", "en": "Support"},
    "manual_sandbox_add_message": {"fa": "افزودن پیام", "en": "Add message"},
    "manual_sandbox_clear_chat": {"fa": "پاک کردن گفتگو", "en": "Clear chat"},
    "manual_sandbox_load_sample": {"fa": "بارگذاری نمونه", "en": "Load sample"},
    "manual_sandbox_message_placeholder": {
        "fa": "متن پیام را بنویسید…",
        "en": "Type a message…",
    },
    "manual_sandbox_latest_support_skip": {
        "fa": "آخرین پیام از پشتیبانی است؛ پاسخ فروشنده لازم نیست.",
        "en": "Latest message is from support; no seller response needed.",
    },
    "manual_sandbox_no_messages": {
        "fa": "حداقل یک پیام فروشنده اضافه کنید تا پیش‌نویس تولید شود.",
        "en": "Add at least one seller message to generate a draft.",
    },
    "manual_sandbox_ai_reply_label": {
        "fa": "پاسخ پیشنهادی سیستم",
        "en": "AI suggested reply",
    },
    "manual_sandbox_regenerate_ai_reply": {
        "fa": "تولید مجدد پاسخ پیشنهادی",
        "en": "Regenerate latest AI reply",
    },
    "manual_sandbox_remove_last_ai_reply": {
        "fa": "حذف آخرین پاسخ پیشنهادی",
        "en": "Remove last AI reply",
    },
    "manual_sandbox_generation_error": {
        "fa": "تولید پاسخ پیشنهادی ناموفق بود",
        "en": "AI reply generation failed",
    },
    "live_api_feed_disclaimer": {
        "fa": (
            "**منبع داده: API زنده** — فقط خواندن JSONL محلی. بدون ارسال، بدون تغییر تیکت، "
            "بدون اجرای خودکار یا polling. دریافت تازه فقط با دکمه **دریافت تیکت‌های جدید از API**؛ "
            "بارگذاری مجدد فایل محلی با **بارگذاری مجدد**."
        ),
        "en": (
            "**Data source: Live API feed** — local JSONL read-only. No send, no ticket mutation, "
            "no auto-run or polling. Fetch fresh tickets via **Fetch latest tickets from API**; "
            "reload the local file with **Reload feed**."
        ),
    },
    "live_feed_fetch_button": {
        "fa": "دریافت تیکت‌های جدید از API",
        "en": "Fetch latest tickets from API",
    },
    "live_feed_fetch_spinner": {
        "fa": "در حال دریافت تیکت‌های جدید...",
        "en": "Fetching latest tickets...",
    },
    "live_feed_fetch_success": {
        "fa": "تیکت‌های جدید دریافت شد: {count}",
        "en": "Fetched latest tickets: {count}",
    },
    "live_feed_fetch_failed": {
        "fa": "دریافت تیکت‌های جدید ناموفق بود",
        "en": "Failed to fetch latest tickets",
    },
    "live_feed_fetch_last_time": {
        "fa": "آخرین دریافت از API",
        "en": "Last API fetch",
    },
    "live_feed_fetch_rooms_metric": {"fa": "اتاق‌های دریافت‌شده", "en": "Rooms fetched"},
    "live_feed_fetch_warnings_metric": {"fa": "هشدارها", "en": "Warnings"},
    "live_feed_fetch_validation_metric": {"fa": "اعتبارسنجی", "en": "Validation"},
    "live_feed_fetch_invalid_rows_metric": {
        "fa": "ردیف‌های نامعتبر",
        "en": "Invalid rows",
    },
    "live_feed_ticket_count": {"fa": "تعداد تیکت‌ها", "en": "Ticket count"},
    "live_feed_eligible_count": {"fa": "تیکت‌های قابل بررسی", "en": "Reviewable tickets"},
    "live_feed_last_refresh": {"fa": "آخرین بروزرسانی", "en": "Last refresh"},
    "live_feed_reload_button": {"fa": "بارگذاری مجدد", "en": "Reload feed"},
    "live_feed_jsonl_path": {"fa": "مسیر JSONL زنده", "en": "Live feed JSONL path"},
    "live_feed_file_missing": {
        "fa": "فایل JSONL زنده یافت نشد",
        "en": "Live feed JSONL file not found",
    },
    "live_feed_no_entries": {
        "fa": "تیکتی در فید زنده نیست. ابتدا API را واکشی کنید.",
        "en": "No tickets in live feed. Fetch from API first.",
    },
    "live_feed_badge_eligible": {"fa": "قابل بررسی", "en": "Eligible"},
    "live_feed_badge_skipped": {"fa": "رد شده", "en": "Skipped"},
    "live_feed_hitl_required": {"fa": "نیازمند بررسی انسانی", "en": "Human review required"},
    "live_feed_metadata_title": {"fa": "متادیتای تیکت زنده", "en": "Live ticket metadata"},
    "live_feed_source_system": {"fa": "منبع سیستم", "en": "Source system"},
    "live_feed_updated_at": {"fa": "زمان بروزرسانی", "en": "Updated at"},
    "live_feed_created_at": {"fa": "زمان ایجاد", "en": "Created at"},
    "live_feed_message_count": {"fa": "تعداد پیام", "en": "Message count"},
    "live_feed_first_sender": {"fa": "فرستنده اول", "en": "First sender"},
    "live_feed_eligibility_reason": {"fa": "دلیل وضعیت", "en": "Eligibility reason"},
    "live_feed_skip_support_replied": {
        "fa": "پاسخ پشتیبانی ثبت شده",
        "en": "Support replied",
    },
    "live_feed_skip_support_started": {
        "fa": "شروع توسط پشتیبانی",
        "en": "Support started",
    },
    "live_feed_skip_closed_ticket": {
        "fa": "تیکت بسته",
        "en": "Closed ticket",
    },
    "live_feed_skip_empty_first_turn": {
        "fa": "نوبت اول خالی",
        "en": "Empty first turn",
    },
    "live_feed_skip_malformed_ticket": {
        "fa": "تیکت ناقص / نامعتبر",
        "en": "Malformed ticket",
    },
    "live_feed_seller_preview": {"fa": "پیش‌نمایش فروشنده", "en": "Seller preview"},
    "live_feed_select_ticket": {"fa": "انتخاب تیکت زنده", "en": "Select live ticket"},
    "live_feed_filter_ticket_label": {"fa": "برچسب تیکت", "en": "Ticket label"},
    "live_feed_filter_eligibility": {"fa": "وضعیت صلاحیت", "en": "Eligibility"},
    "live_feed_filter_first_sender": {"fa": "فرستنده اول", "en": "First sender"},
    "live_feed_filtered_count": {"fa": "نمایش پس از فیلتر", "en": "Showing after filters"},
    "live_feed_ticket_card_title": {"fa": "کارت تیکت", "en": "Ticket card"},
    "live_feed_eligibility_eligible": {"fa": "قابل بررسی", "en": "Eligible"},
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
    "reflection_comparison_section_heading": {
        "fa": "مقایسه رفلکشن",
        "en": "Reflection comparison",
    },
    "reflection_comparison_expander": {
        "fa": "مقایسه قبل و بعد از رفلکشن",
        "en": "Reflection comparison",
    },
    "reflection_comparison_caption": {
        "fa": "فقط برای ارزیابی/عیب‌یابی — بدون نمایش استدلال پنهان یا پرامپت.",
        "en": "Evaluation/debug only — no hidden reasoning or prompts.",
    },
    "reflection_comparison_unavailable": {
        "fa": "پیش‌نویس برای مقایسه رفلکشن در دسترس نیست.",
        "en": "No draft available for reflection comparison.",
    },
    "reflection_no_change_caption": {
        "fa": "رفلکشن اجرا شد، اما تغییری لازم نبود.",
        "en": "Reflection ran; no change was required.",
    },
    "reflection_disabled_warning": {
        "fa": "رفلکشن نهایی پیش‌نویس غیرفعال است.",
        "en": "Final draft reflection is disabled.",
    },
    "reflection_disabled_technical_warning": {
        "fa": "Final draft reflection is disabled.",
        "en": "Final draft reflection is disabled.",
    },
    "reflection_enabled_label": {
        "fa": "رفلکشن فعال",
        "en": "Reflection enabled",
    },
    "reflection_provider_label": {
        "fa": "ارائه‌دهنده رفلکشن",
        "en": "Reflection provider",
    },
    "reflection_before_label": {
        "fa": "پیش‌نویس قبل از رفلکشن",
        "en": "Before reflection draft",
    },
    "reflection_after_label": {
        "fa": "پیش‌نویس بعد از رفلکشن",
        "en": "After reflection draft",
    },
    "reflection_metadata_heading": {
        "fa": "متادیتای رفلکشن",
        "en": "Reflection metadata",
    },
    "reflection_reviewed_label": {
        "fa": "بررسی شده",
        "en": "Reviewed",
    },
    "reflection_rewrite_label": {
        "fa": "بازنویسی اعمال شد",
        "en": "Rewrite applied",
    },
    "reflection_issue_types_label": {
        "fa": "انواع مسئله",
        "en": "Issue types",
    },
    "reflection_issue_count_label": {
        "fa": "تعداد مسئله",
        "en": "Issue count",
    },
    "reflection_raw_generated_label": {
        "fa": "پیش‌نویس خام اولیه (قبل از کالیبراسیون)",
        "en": "Initial raw generated draft (pre-calibration)",
    },
    "reflection_diff_heading": {
        "fa": "تغییرات جمله‌ای",
        "en": "Sentence-level changes",
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
    "tracking_verification_section": {
        "fa": "استعلام کد رهگیری",
        "en": "Tracking verification",
    },
    "tracking_verification_verify_button": {
        "fa": "استعلام از پست ایران",
        "en": "Verify with Iran Post",
    },
    "tracking_verification_advisory_caption": {
        "fa": ("نتیجه استعلام صرفاً مشاوره‌ای است و به‌صورت خودکار به فروشنده ارسال نمی‌شود."),
        "en": ("Verification result is advisory only and is not sent to the seller automatically."),
    },
    "tracking_verification_recommended_note": {
        "fa": "پس از دریافت کد رهگیری، استعلام دستی پست ایران توصیه می‌شود.",
        "en": "After tracking code fulfillment, manual Iran Post verification is recommended.",
    },
    "tracking_verification_disabled": {
        "fa": "استعلام پست ایران غیرفعال است (IRAN_POST_TRACKING_ENABLED=false).",
        "en": "Iran Post tracking is disabled (IRAN_POST_TRACKING_ENABLED=false).",
    },
    "tracking_verification_missing_token": {
        "fa": "توکن استعلام تنظیم نشده است (IRAN_POST_TRACKING_TOKEN).",
        "en": "Tracking token is not configured (IRAN_POST_TRACKING_TOKEN).",
    },
    "tracking_verification_result_heading": {
        "fa": "نتیجه استعلام",
        "en": "Verification result",
    },
    "tracking_verification_verified": {"fa": "تأیید شده", "en": "Verified"},
    "tracking_verification_status": {"fa": "وضعیت", "en": "Status"},
    "tracking_verification_last_event": {"fa": "آخرین رویداد", "en": "Last event"},
    "tracking_verification_province": {"fa": "استان", "en": "Province"},
    "tracking_verification_event_count": {"fa": "تعداد رویداد", "en": "Event count"},
    "tracking_verification_destination": {"fa": "مقصد", "en": "Destination"},
    "tracking_verification_source": {"fa": "مبدأ", "en": "Source"},
    "inchand_order_lookup_section": {
        "fa": "اطلاعات سفارش اینچند",
        "en": "Inchand order lookup",
    },
    "inchand_order_lookup_button": {
        "fa": "دریافت اطلاعات سفارش",
        "en": "Lookup order",
    },
    "inchand_order_lookup_advisory_caption": {
        "fa": ("نتیجه استعلام سفارش صرفاً مشاوره‌ای است و به‌صورت خودکار به فروشنده ارسال نمی‌شود."),
        "en": ("Order lookup result is advisory only and is not sent to the seller automatically."),
    },
    "inchand_order_lookup_recommended_note": {
        "fa": "پس از استخراج شماره سفارش، استعلام دستی اینچند توصیه می‌شود.",
        "en": "After order id extraction, manual Inchand lookup is recommended.",
    },
    "inchand_order_lookup_disabled": {
        "fa": "استعلام سفارش اینچند غیرفعال است (INCHAND_ORDER_LOOKUP_ENABLED=false).",
        "en": "Inchand order lookup is disabled (INCHAND_ORDER_LOOKUP_ENABLED=false).",
    },
    "inchand_order_lookup_missing_token": {
        "fa": "توکن API تنظیم نشده است (INCHAND_API_KEY_VALUE یا LIVE_ROOMS_API_TOKEN).",
        "en": "API token is not configured (INCHAND_API_KEY_VALUE or LIVE_ROOMS_API_TOKEN).",
    },
    "inchand_order_lookup_result_heading": {
        "fa": "نتیجه استعلام سفارش",
        "en": "Order lookup result",
    },
    "inchand_order_lookup_order_status": {"fa": "وضعیت سفارش", "en": "Order status"},
    "inchand_order_lookup_provider_status": {
        "fa": "وضعیت ارسال",
        "en": "Provider status",
    },
    "inchand_order_lookup_parcel_status": {
        "fa": "وضعیت مرسوله",
        "en": "Parcel status",
    },
    "inchand_order_lookup_parcel_tracking": {
        "fa": "کد رهگیری مرسوله",
        "en": "Parcel tracking code",
    },
    "inchand_order_lookup_delivered_at": {
        "fa": "زمان تحویل",
        "en": "Delivered at",
    },
    "inchand_order_lookup_has_tracking": {
        "fa": "کد رهگیری مرسوله موجود",
        "en": "Has parcel tracking code",
    },
    "inchand_order_lookup_is_delivered": {
        "fa": "تحویل‌شده در اینچند",
        "en": "Delivered in Inchand",
    },
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
