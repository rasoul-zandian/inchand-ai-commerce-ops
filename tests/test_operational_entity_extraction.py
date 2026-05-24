"""Tests for deterministic operational entity extraction."""

from __future__ import annotations

import pytest
from app.workflows.operational_entity_extraction import (
    EntityType,
    TrackingCarrier,
    dedupe_entities_by_type_and_normalized_value_preserve_order,
    extract_operational_entities,
    extract_order_ids,
    extract_product_ids,
    extract_tracking_codes,
    mask_sensitive_entity,
    normalize_digits,
)

_SHEBA_24 = "123456789012345678901234"


def test_inc_prefix_order_id() -> None:
    result = extract_operational_entities("لطفا سفارش INC-8484683 را بررسی کنید")
    orders = [e for e in result.entities if e.entity_type == EntityType.ORDER_ID]
    assert len(orders) == 1
    assert orders[0].normalized_value == "8484683"
    assert orders[0].value.upper().startswith("INC")


def test_seven_digits_near_order_keyword() -> None:
    result = extract_operational_entities("سفارش 8484683 هنوز تحویل نشده")
    assert result.order_ids == ("8484683",)


def test_persian_digits_normalized() -> None:
    text = "سفارش ۸۴۸۴۶۸۳"
    assert extract_order_ids(text) == ("8484683",)
    assert normalize_digits("۸۴۸۴۶۸۳") == "8484683"


def test_incomplete_six_digit_order_near_safaresh() -> None:
    result = extract_operational_entities("سفارش 123456 لغو شد")
    incomplete = [
        e for e in result.entities if e.entity_type == EntityType.INCOMPLETE_ORDER_ID_CANDIDATE
    ]
    assert len(incomplete) == 1
    assert incomplete[0].normalized_value == "123456"
    assert incomplete[0].warning == "شماره سفارش ناقص احتمالی"


def test_product_id_eight_digits() -> None:
    text = "شناسه کالا 12345678 تایید نشده"
    assert extract_product_ids(text) == ("12345678",)
    products = [
        e
        for e in extract_operational_entities(text).entities
        if e.entity_type == EntityType.PRODUCT_ID
    ]
    assert products[0].normalized_value == "12345678"


def test_iran_post_tracking_24_digits() -> None:
    code = "1" * 24
    tracking = extract_tracking_codes(f"کد رهگیری {code} برای پست")
    assert len(tracking) == 1
    assert tracking[0].normalized_value == code
    assert tracking[0].carrier == TrackingCarrier.IRAN_POST


def test_chapar_seventeen_digits() -> None:
    code = "2" * 17
    result = extract_operational_entities(f"چاپار {code}")
    tracking = [e for e in result.entities if e.entity_type == EntityType.TRACKING_CODE]
    assert tracking[0].carrier == TrackingCarrier.CHAPAR


def test_tipax_fifteen_to_twenty_five_digits() -> None:
    code = "3" * 20
    result = extract_operational_entities(f"تیپاکس {code}")
    tracking = [e for e in result.entities if e.entity_type == EntityType.TRACKING_CODE]
    assert tracking[0].carrier == TrackingCarrier.TIPAX


def test_irrelevant_long_number_without_context_ignored() -> None:
    code = "9" * 20
    result = extract_operational_entities(code)
    assert result.entities == ()


def test_multiple_order_ids() -> None:
    text = "سفارش‌های 1111111 و 2222222 را بررسی کنید"
    assert extract_order_ids(text) == ("1111111", "2222222")


def test_seven_digit_near_product_keyword_is_order_not_product() -> None:
    result = extract_operational_entities("شناسه کالا 1234567")
    assert result.order_ids == ("1234567",)
    assert result.product_ids == ()


def test_complaint_number_without_safaresh_keyword() -> None:
    text = "سلام در مورد شکایت شماره 8201241 با ایشون تماس گرفتم"
    result = extract_operational_entities(text)
    assert result.order_ids == ("8201241",)
    orders = [e for e in result.entities if e.entity_type == EntityType.ORDER_ID]
    assert orders[0].confidence_band == "high"
    assert orders[0].context_keyword == "شکایت"


def test_standalone_seven_digit_medium_confidence() -> None:
    result = extract_operational_entities("8201241")
    assert result.order_ids == ("8201241",)
    orders = [e for e in result.entities if e.entity_type == EntityType.ORDER_ID]
    assert orders[0].confidence_band == "medium"
    assert orders[0].context_keyword is None


def test_persian_digits_complaint_order_id() -> None:
    text = "شکایت شماره ۸۲۰۱۲۴۱"
    assert extract_order_ids(text) == ("8201241",)


def test_24_digit_tracking_does_not_emit_seven_digit_orders() -> None:
    code = "1" * 24
    result = extract_operational_entities(f"کد رهگیری {code} برای پست")
    assert result.order_ids == ()
    tracking = [e for e in result.entities if e.entity_type == EntityType.TRACKING_CODE]
    assert len(tracking) == 1
    assert tracking[0].normalized_value == code


def test_eight_digit_product_not_seven_digit_order() -> None:
    text = "شناسه کالا 12345678 تایید نشده"
    result = extract_operational_entities(text)
    assert result.product_ids == ("12345678",)
    assert result.order_ids == ()


def test_ir_prefix_iban_extracted() -> None:
    iban = f"IR{_SHEBA_24}"
    result = extract_operational_entities(f"شماره شبا {iban}")
    ibans = [e for e in result.entities if e.entity_type == EntityType.IBAN]
    assert len(ibans) == 1
    assert ibans[0].normalized_value == iban
    assert result.order_ids == ()


def test_sheba_keyword_24_digits_without_ir_prefix() -> None:
    result = extract_operational_entities(f"شماره شبا {_SHEBA_24}")
    ibans = [e for e in result.entities if e.entity_type == EntityType.IBAN]
    assert len(ibans) == 1
    assert ibans[0].normalized_value == _SHEBA_24


def test_persian_digits_sheba_extracted() -> None:
    persian = "۱۲۳۴۵۶۷۸۹۰۱۲۳۴۵۶۷۸۹۰۱۲۳۴"
    result = extract_operational_entities(f"شبا {persian}")
    assert result.primary_iban == _SHEBA_24


def test_post_tracking_24_digits_not_iban() -> None:
    result = extract_operational_entities(f"کد رهگیری پست {_SHEBA_24}")
    assert result.primary_iban is None
    tracking = [e for e in result.entities if e.entity_type == EntityType.TRACKING_CODE]
    assert len(tracking) == 1
    assert tracking[0].carrier == TrackingCarrier.IRAN_POST


def test_incomplete_iban_23_digits_near_sheba() -> None:
    digits = "1" * 23
    result = extract_operational_entities(f"شماره شبا {digits}")
    incomplete = [
        e for e in result.entities if e.entity_type == EntityType.INCOMPLETE_IBAN_CANDIDATE
    ]
    assert len(incomplete) == 1
    assert incomplete[0].warning == "شماره شبا ناقص احتمالی"


def test_incomplete_iban_25_digits_near_sheba() -> None:
    digits = "2" * 25
    result = extract_operational_entities(f"حساب بانکی {digits}")
    incomplete = [
        e for e in result.entities if e.entity_type == EntityType.INCOMPLETE_IBAN_CANDIDATE
    ]
    assert len(incomplete) == 1


def test_iban_and_tracking_do_not_emit_order_submatches() -> None:
    result = extract_operational_entities(
        f"شبا IR{_SHEBA_24} و کد رهگیری پست {'3' * 24}",
    )
    assert result.order_ids == ()
    assert result.primary_iban is not None


def test_mask_sensitive_entity_iban() -> None:
    masked = mask_sensitive_entity(f"IR{_SHEBA_24}")
    assert _SHEBA_24 not in masked
    assert masked.startswith("IR")
    assert masked.endswith(_SHEBA_24[-4:])
    assert "*" in masked


def test_order_id_in_sentence_without_keyword() -> None:
    assert extract_order_ids("لطفا سفارش 7654321 را بررسی کنید") == ("7654321",)


def test_inc_with_space_separator() -> None:
    result = extract_operational_entities("لطفا INC 7654321 را بررسی کنید")
    assert result.order_ids == ("7654321",)


def test_inc_underscore_lowercase() -> None:
    result = extract_operational_entities("inc_7654321")
    assert result.order_ids == ("7654321",)


def test_safaresh_colon_order_id() -> None:
    result = extract_operational_entities("سفارش: 7654321")
    assert result.order_ids == ("7654321",)


def test_multiple_order_ids_in_one_message() -> None:
    text = "سفارش 1111111 و 2222222 و INC-3333333"
    assert set(extract_order_ids(text)) == {"1111111", "2222222", "3333333"}


def test_repeated_inc_codes_extract_both_unique_order_ids() -> None:
    text = "INC-7452190\nINC-7447698\nINC-7452190\nINC-7447698"
    assert extract_order_ids(text) == ("7452190", "7447698")


def test_concatenated_inc_codes_without_separator() -> None:
    assert extract_order_ids("INC-7452190INC-7447698") == ("7452190", "7447698")


def test_bare_repeated_seven_digit_order_ids() -> None:
    text = "7452190 7452190 7447698 7447698"
    assert extract_order_ids(text) == ("7452190", "7447698")


def test_mixed_persian_digits_with_inc() -> None:
    text = "INC-۷۴۵۲۱۹۰ INC-۷۴۴۷۶۹۸"
    assert extract_order_ids(text) == ("7452190", "7447698")


@pytest.mark.parametrize(
    "fragment",
    [
        "INC-7452190",
        "INC 7452190",
        "inc_7452190",
        "INC:7452190",
    ],
)
def test_inc_separator_variants(fragment: str) -> None:
    text = f"{fragment} و INC-7447698"
    assert extract_order_ids(text) == ("7452190", "7447698")


def test_tracking_24_digits_does_not_emit_order_submatches() -> None:
    code = "1" * 24
    text = f"کد رهگیری پست {code} INC-7452190 INC-7447698"
    assert extract_order_ids(text) == ("7452190", "7447698")
    result = extract_operational_entities(text)
    tracking = [e for e in result.entities if e.entity_type == EntityType.TRACKING_CODE]
    assert len(tracking) == 1
    assert tracking[0].normalized_value == code


def test_eight_digit_product_id_not_extracted_as_order() -> None:
    text = "شناسه کالا 12345678 INC-7452190 INC-7447698"
    result = extract_operational_entities(text)
    assert result.product_ids == ("12345678",)
    assert result.order_ids == ("7452190", "7447698")


def test_dedupe_entities_by_type_and_normalized_value_preserve_order() -> None:
    first = extract_operational_entities("INC-7452190 INC-7447698").entities
    duplicated = list(first) + list(first)
    deduped = dedupe_entities_by_type_and_normalized_value_preserve_order(list(duplicated))
    assert deduped == list(first)


def test_first_turn_draft_context_sees_both_order_ids() -> None:
    from app.evals.first_turn_draft_context import (
        build_first_turn_draft_context_from_case,
        draft_entity_preview_fields,
    )

    case = {
        "room_id": "ROOM_MULTI_INC",
        "ticket_label": "support",
        "route_label": "general_vendor_support",
        "snapshot_before_reply": {
            "original_vendor_issue_preview": ("INC-7452190\nINC-7447698\nINC-7452190\nINC-7447698"),
            "latest_vendor_message": "پیام بعدی",
        },
    }
    ctx = build_first_turn_draft_context_from_case(case)
    assert ctx.first_turn_entities.order_ids == ("7452190", "7447698")
    assert ctx.first_turn_intent.extracted_order_ids == ["7452190", "7447698"]
    fields = draft_entity_preview_fields(ctx.first_turn_entities, context=ctx)
    assert fields["draft_extracted_order_ids"] == "7452190,7447698"
