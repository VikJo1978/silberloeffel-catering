"""Pure office inquiry-state derivation for truthful queues and actions."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from catering_system.domain.inquiry import (
    CrmStage,
    Inquiry,
    derive_inquiry_office_state,
    inquiry_allows_convert_accepted_command,
    inquiry_crm_stage_is_compatible_with_active_order,
    inquiry_shows_convert_accepted_button,
)
from catering_system.domain.offer import (
    AcceptanceEvidence,
    ConversionLink,
    Offer,
    OfferPosition,
    OfferVariant,
    OfferVersion,
    SentEvidence,
)
from catering_system.domain.inquiry_customer_snapshot import (
    InquiryCustomerSnapshot as _CCSnapshot,
)

_CONTACT_COMPLETE_SNAPSHOT = _CCSnapshot(
    email="kunde@example.com", phone="+49301234567"
)

_TODAY = date(2026, 7, 15)
_OFFER_ID = "11111111-1111-1111-1111-111111111111"
_INQUIRY_ID = "22222222-2222-2222-2222-222222222222"
_V1_ID = "33333333-3333-3333-3333-333333333331"
_A_ID = "44444444-4444-4444-4444-444444444441"
_B_ID = "44444444-4444-4444-4444-444444444442"
_ACCEPTANCE_ID = "55555555-5555-5555-5555-555555555555"
_ORDER_ID = "66666666-6666-6666-6666-666666666666"
_NOW = datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)
_HASH = "sha256:" + ("a" * 64)
_POS_A = "88888888-8888-8888-8888-888888888881"


def _inquiry(**overrides: object) -> Inquiry:
    now = datetime(2026, 7, 14, 10, 0, tzinfo=timezone.utc)
    values: dict[str, object] = {
        "inquiry_id": _INQUIRY_ID,
        "event_date": date(2026, 10, 1),
        "created_at": now,
        "updated_at": now,
        "inquiry_source": "manual",
        "crm_stage": "Neue Anfrage",
        "customer_linkage": {},
        "time_window_text": "mittags",
        "location_text": "Hamburg",
        "guest_count_estimate": 25,
        "planning_mode": "caterer_suggestion",
        "call_verification_required": False,
        "call_verification_status": "not_required",
        "customer_snapshot": _CONTACT_COMPLETE_SNAPSHOT,
    }
    values.update(overrides)
    return Inquiry(**values)  # type: ignore[arg-type]


def _version(*, sent: bool = False) -> OfferVersion:
    return OfferVersion(
        offer_version_id=_V1_ID,
        offer_id=_OFFER_ID,
        version_number=1,
        created_at=_NOW,
        valid_until=date(2026, 7, 31),
        snapshot_id="77777777-7777-7777-7777-777777777771",
        snapshot_hash=_HASH,
        event_date=date(2026, 8, 20),
        time_window_text="18:00–22:00",
        location_text="Hamburg",
        guest_count=80,
        planning_mode="caterer_suggestion",
        payment_method="RECHNUNG",
        payment_customer_visible_text="Zahlung per Rechnung",
        variants=(
            OfferVariant(
                variant_id=_A_ID,
                offer_version_id=_V1_ID,
                label="Variante A",
                positions=(
                    OfferPosition(
                        position_id=_POS_A,
                        kind="catalog",
                        name="Fingerfood Paket",
                        unit_net_cents=290,
                        net_total_cents=23200,
                        vat_rate_percent=7,
                        vat_amount_cents=1624,
                        gross_total_cents=24824,
                    ),
                ),
            ),
        ),
    )


def _offer(
    *,
    sent: bool = False,
    acceptance: AcceptanceEvidence | None = None,
    link: ConversionLink | None = None,
) -> Offer:
    sent_evidence = (
        (
            SentEvidence(
                offer_id=_OFFER_ID,
                offer_version_id=_V1_ID,
                sent_at=_NOW,
                recorded_at=_NOW + timedelta(minutes=1),
                channel="email",
                recipient_reference="kunde@example.invalid",
                evidence_reference="mail-1",
                recorded_by="office",
            ),
        )
        if sent
        else ()
    )
    return Offer(
        offer_id=_OFFER_ID,
        source_inquiry_id=_INQUIRY_ID,
        created_at=_NOW,
        versions=(_version(),),
        sent_evidence=sent_evidence,
        acceptance_evidence=acceptance,
        rejection_evidence=(),
        withdrawal_evidence=(),
        conversion_link=link,
    )


def _acceptance() -> AcceptanceEvidence:
    return AcceptanceEvidence(
        acceptance_id=_ACCEPTANCE_ID,
        offer_id=_OFFER_ID,
        accepted_offer_version_id=_V1_ID,
        accepted_variant_id=_A_ID,
        accepted_at=_NOW + timedelta(days=1),
        recorded_at=_NOW + timedelta(days=1, minutes=5),
        channel="email",
        evidence_reference="reply-1",
        recorded_by="office",
    )


def _link() -> ConversionLink:
    return ConversionLink(
        offer_id=_OFFER_ID,
        offer_version_id=_V1_ID,
        variant_id=_A_ID,
        acceptance_id=_ACCEPTANCE_ID,
        order_id=_ORDER_ID,
        created_at=_NOW + timedelta(days=1, minutes=6),
    )


def test_open_inquiry_derives_convert_action() -> None:
    state = derive_inquiry_office_state(
        _inquiry(),
        has_order=False,
        has_active_order=False,
        today=_TODAY,
    )
    assert state.is_open is True
    assert state.next_action == "convert"
    assert state.offer is None


def test_required_unverified_call_derives_verify_only() -> None:
    state = derive_inquiry_office_state(
        _inquiry(
            call_verification_required=True,
            call_verification_status="pending",
        ),
        has_order=False,
        has_active_order=False,
        today=_TODAY,
    )
    assert state.is_open is True
    assert state.next_action == "verify"


def test_rejected_inquiry_is_closed_without_action() -> None:
    state = derive_inquiry_office_state(
        _inquiry(crm_stage="Abgelehnt / verloren"),
        has_order=False,
        has_active_order=False,
        today=_TODAY,
    )
    assert state.is_open is False
    assert state.next_action is None


def test_converted_inquiry_is_closed_and_active_order_blocks_action() -> None:
    state = derive_inquiry_office_state(
        _inquiry(crm_stage="Bestätigt / Auftrag"),
        has_order=True,
        has_active_order=True,
        today=_TODAY,
    )
    assert state.is_open is False
    assert state.next_action is None


def test_cancelled_order_stays_out_of_queue_and_blocks_reconversion() -> None:
    state = derive_inquiry_office_state(
        _inquiry(crm_stage="Bestätigt / Auftrag"),
        has_order=True,
        has_active_order=False,
        today=_TODAY,
    )
    assert state.is_open is False
    assert state.next_action is None


def test_prepared_offer_projects_offer_pending_not_legacy_convert() -> None:
    state = derive_inquiry_office_state(
        _inquiry(),
        has_order=False,
        has_active_order=False,
        offer=_offer(),
        today=_TODAY,
    )
    assert state.is_open is True
    assert state.next_action == "offer-pending"
    assert state.offer is not None
    assert state.offer.commercial_state == "Prepared"


def test_sent_offer_projects_offer_pending_not_legacy_convert() -> None:
    state = derive_inquiry_office_state(
        _inquiry(),
        has_order=False,
        has_active_order=False,
        offer=_offer(sent=True),
        today=_TODAY,
    )
    assert state.next_action == "offer-pending"
    assert state.offer is not None
    assert state.offer.commercial_state == "Sent"


def test_accepted_offer_projects_convert_accepted() -> None:
    state = derive_inquiry_office_state(
        _inquiry(),
        has_order=False,
        has_active_order=False,
        offer=_offer(sent=True, acceptance=_acceptance()),
        today=_TODAY,
    )
    assert state.next_action == "convert-accepted"
    assert state.offer is not None
    assert state.offer.acceptance_id == _ACCEPTANCE_ID


def test_converted_offer_after_storno_has_no_new_conversion_action() -> None:
    state = derive_inquiry_office_state(
        _inquiry(crm_stage="Bestätigt / Auftrag"),
        has_order=True,
        has_active_order=False,
        offer=_offer(
            sent=True,
            acceptance=_acceptance(),
            link=_link(),
        ),
        today=_TODAY,
    )
    assert state.is_open is False
    assert state.next_action is None


def test_convert_accepted_button_only_for_accepted_not_converted() -> None:
    accepted = derive_inquiry_office_state(
        _inquiry(),
        has_order=False,
        has_active_order=False,
        offer=_offer(sent=True, acceptance=_acceptance()),
        today=_TODAY,
    )
    converted = derive_inquiry_office_state(
        _inquiry(crm_stage="Bestätigt / Auftrag"),
        has_order=True,
        has_active_order=False,
        offer=_offer(
            sent=True,
            acceptance=_acceptance(),
            link=_link(),
        ),
        today=_TODAY,
    )
    assert inquiry_shows_convert_accepted_button(accepted) is True
    assert inquiry_shows_convert_accepted_button(converted) is False
    assert inquiry_allows_convert_accepted_command(converted) is False
    assert converted.next_action is None


def test_verify_still_wins_over_offer_pending() -> None:
    state = derive_inquiry_office_state(
        _inquiry(
            call_verification_required=True,
            call_verification_status="pending",
        ),
        has_order=False,
        has_active_order=False,
        offer=_offer(sent=True),
        today=_TODAY,
    )
    assert state.next_action == "verify"


def test_active_order_requires_existing_order_fact() -> None:
    with pytest.raises(ValueError, match="active order"):
        derive_inquiry_office_state(
            replace(_inquiry(), crm_stage="In Prüfung"),
            has_order=False,
            has_active_order=True,
            today=_TODAY,
        )


@pytest.mark.parametrize(
    ("stage", "compatible"),
    [
        ("Bestätigt / Auftrag", True),
        ("Neue Anfrage", False),
        ("Abgelehnt / verloren", False),
    ],
)
def test_active_order_crm_stage_compatibility(
    stage: CrmStage, compatible: bool
) -> None:
    assert inquiry_crm_stage_is_compatible_with_active_order(stage) is compatible
