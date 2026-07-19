"""Offer aggregate invariant and validation error paths."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from catering_system.domain.offer import (
    AcceptanceEvidence,
    ConversionLink,
    OfferPosition,
    OfferVariant,
    OfferVersion,
    RejectionEvidence,
    SentEvidence,
    WithdrawalEvidence,
    derive_offer_state,
    offer_allows_acceptance,
    offer_allows_sent_recording,
)
from tests.unit.test_offer import (
    _ACCEPTANCE_ID,
    _A_ID,
    _B_ID,
    _C_ID,
    _HASH,
    _NOW,
    _OFFER_ID,
    _ORDER_ID,
    _POS_A,
    _POS_B,
    _V1_ID,
    _V2_ID,
    _acceptance,
    _link,
    _offer,
    _position,
    _sent,
    _variant,
    _version,
    _version_facts,
)


def test_offer_position_rejects_invalid_kind() -> None:
    with pytest.raises(ValueError, match="invalid position kind"):
        OfferPosition(
            position_id=_POS_A,
            kind="unknown",  # type: ignore[arg-type]
            name="Item",
            unit_net_cents=100,
            net_total_cents=100,
            vat_rate_percent=7,
            vat_amount_cents=7,
            gross_total_cents=107,
        )


def test_offer_position_rejects_negative_cents() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        OfferPosition(
            position_id=_POS_A,
            kind="catalog",
            name="Item",
            unit_net_cents=-1,
            net_total_cents=100,
            vat_rate_percent=7,
            vat_amount_cents=7,
            gross_total_cents=107,
        )


def test_offer_position_surcharge_requires_related_position() -> None:
    with pytest.raises(ValueError, match="surcharge requires related_position_id"):
        OfferPosition(
            position_id=_POS_A,
            kind="surcharge",
            name="Fee",
            unit_net_cents=100,
            net_total_cents=100,
            vat_rate_percent=7,
            vat_amount_cents=7,
            gross_total_cents=107,
        )


def test_offer_variant_rejects_empty_positions() -> None:
    with pytest.raises(ValueError, match="at least one position"):
        OfferVariant(
            variant_id=_A_ID,
            offer_version_id=_V1_ID,
            label="Empty",
            positions=(),
        )


def test_offer_variant_rejects_duplicate_position_ids() -> None:
    pos = _position()
    with pytest.raises(ValueError, match="position_id must be unique"):
        OfferVariant(
            variant_id=_A_ID,
            offer_version_id=_V1_ID,
            label="Dup",
            positions=(pos, pos),
        )


def test_offer_version_rejects_naive_created_at() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        OfferVersion(
            offer_version_id=_V1_ID,
            offer_id=_OFFER_ID,
            version_number=1,
            created_at=datetime(2026, 7, 15, 10, 0),
            valid_until=date(2026, 7, 31),
            snapshot_id="77777777-7777-7777-7777-777777777771",
            snapshot_hash=_HASH,
            **_version_facts(),
            variants=(_variant(_A_ID, _V1_ID, "A"),),
        )


def test_offer_version_rejects_invalid_snapshot_hash() -> None:
    with pytest.raises(ValueError, match="snapshot_hash"):
        OfferVersion(
            offer_version_id=_V1_ID,
            offer_id=_OFFER_ID,
            version_number=1,
            created_at=_NOW,
            valid_until=date(2026, 7, 31),
            snapshot_id="77777777-7777-7777-7777-777777777771",
            snapshot_hash="bad",
            **_version_facts(),
            variants=(_variant(_A_ID, _V1_ID, "A"),),
        )


def test_sent_evidence_rejects_recorded_before_sent() -> None:
    with pytest.raises(ValueError, match="recorded_at cannot precede sent_at"):
        SentEvidence(
            offer_id=_OFFER_ID,
            offer_version_id=_V1_ID,
            sent_at=_NOW,
            recorded_at=_NOW - timedelta(minutes=1),
            channel="email",
            recipient_reference="x@example.invalid",
            evidence_reference="mail-1",
            recorded_by="office",
        )


def test_acceptance_evidence_rejects_invalid_channel() -> None:
    with pytest.raises(ValueError, match="invalid acceptance channel"):
        AcceptanceEvidence(
            acceptance_id=_ACCEPTANCE_ID,
            offer_id=_OFFER_ID,
            accepted_offer_version_id=_V1_ID,
            accepted_variant_id=_B_ID,
            accepted_at=_NOW,
            recorded_at=_NOW,
            channel="fax",  # type: ignore[arg-type]
            evidence_reference="reply-1",
            recorded_by="office",
        )


def test_rejection_evidence_rejects_recorded_before_rejected() -> None:
    with pytest.raises(ValueError, match="recorded_at cannot precede rejected_at"):
        RejectionEvidence(
            offer_id=_OFFER_ID,
            offer_version_id=_V1_ID,
            rejected_at=_NOW,
            recorded_at=_NOW - timedelta(minutes=1),
            recorded_by="office",
        )


def test_offer_rejects_duplicate_sent_evidence_for_same_version() -> None:
    sent = _sent()
    with pytest.raises(ValueError, match="SentEvidence must be unique"):
        _offer(sent=(sent, sent))


def test_offer_rejects_rejection_without_sent() -> None:
    rejected = RejectionEvidence(
        offer_id=_OFFER_ID,
        offer_version_id=_V1_ID,
        rejected_at=_NOW + timedelta(days=1),
        recorded_at=_NOW + timedelta(days=1, minutes=1),
        recorded_by="office",
    )
    with pytest.raises(ValueError, match="only a sent OfferVersion can be rejected"):
        _offer(sent=(), rejected=(rejected,))


def test_offer_rejects_withdrawal_before_version_created() -> None:
    withdrawn = WithdrawalEvidence(
        offer_id=_OFFER_ID,
        offer_version_id=_V1_ID,
        withdrawn_at=_NOW - timedelta(hours=1),
        recorded_by="office",
    )
    with pytest.raises(ValueError, match="WithdrawalEvidence predates"):
        _offer(withdrawn=(withdrawn,))


def test_offer_rejects_acceptance_after_later_sent_version() -> None:
    v1 = _version(1)
    v2 = _version(2, created_at=_NOW + timedelta(hours=2))
    acceptance = _acceptance(version_id=_V1_ID, accepted_at=_NOW + timedelta(hours=3))
    with pytest.raises(ValueError, match="superseded OfferVersion cannot be accepted"):
        _offer(
            versions=(v1, v2),
            sent=(
                _sent(_V1_ID, sent_at=_NOW + timedelta(hours=1)),
                _sent(_V2_ID, sent_at=_NOW + timedelta(hours=2)),
            ),
            acceptance=acceptance,
        )


def test_offer_rejects_conversion_without_acceptance() -> None:
    with pytest.raises(ValueError, match="conversion requires AcceptanceEvidence"):
        _offer(link=_link())


def test_offer_rejects_conversion_mismatch_with_acceptance() -> None:
    link = ConversionLink(
        offer_id=_OFFER_ID,
        offer_version_id=_V1_ID,
        variant_id=_A_ID,
        acceptance_id=_ACCEPTANCE_ID,
        order_id=_ORDER_ID,
        created_at=_NOW + timedelta(days=1, minutes=6),
    )
    acceptance = _acceptance(variant_id=_B_ID)
    with pytest.raises(
        ValueError, match="conversion does not match AcceptanceEvidence"
    ):
        _offer(sent=(_sent(),), acceptance=acceptance, link=link)


def test_offer_rejects_conversion_predating_acceptance_recorded_at() -> None:
    acceptance = _acceptance()
    link = ConversionLink(
        offer_id=_OFFER_ID,
        offer_version_id=_V1_ID,
        variant_id=_B_ID,
        acceptance_id=_ACCEPTANCE_ID,
        order_id=_ORDER_ID,
        created_at=acceptance.recorded_at - timedelta(minutes=1),
    )
    with pytest.raises(
        ValueError, match="ConversionLink cannot predate AcceptanceEvidence"
    ):
        _offer(sent=(_sent(),), acceptance=acceptance, link=link)


def test_offer_rejects_non_contiguous_version_numbers() -> None:
    v1 = _version(1)
    v3 = OfferVersion(
        offer_version_id="33333333-3333-3333-3333-333333333333",
        offer_id=_OFFER_ID,
        version_number=3,
        created_at=_NOW + timedelta(hours=2),
        valid_until=date(2026, 7, 31),
        snapshot_id="77777777-7777-7777-7777-777777777773",
        snapshot_hash=_HASH,
        **_version_facts(),
        variants=(_variant(_A_ID, "33333333-3333-3333-3333-333333333333", "C"),),
    )
    with pytest.raises(ValueError, match="contiguous"):
        _offer(versions=(v1, v3))


def test_offer_position_rejects_invalid_vat_rate() -> None:
    with pytest.raises(ValueError, match="vat_rate_percent must be 7 or 19"):
        OfferPosition(
            position_id=_POS_A,
            kind="catalog",
            name="Item",
            unit_net_cents=100,
            net_total_cents=100,
            vat_rate_percent=8,  # type: ignore[arg-type]
            vat_amount_cents=8,
            gross_total_cents=108,
        )


def test_offer_position_rejects_related_position_on_non_surcharge() -> None:
    with pytest.raises(
        ValueError, match="related_position_id is only valid for surcharges"
    ):
        OfferPosition(
            position_id=_POS_A,
            kind="catalog",
            name="Item",
            unit_net_cents=100,
            net_total_cents=100,
            vat_rate_percent=7,
            vat_amount_cents=7,
            gross_total_cents=107,
            related_position_id=_POS_B,
        )


def test_offer_variant_rejects_surcharge_without_base_in_variant() -> None:
    surcharge = OfferPosition(
        position_id=_POS_B,
        kind="surcharge",
        name="Fee",
        unit_net_cents=100,
        net_total_cents=100,
        vat_rate_percent=7,
        vat_amount_cents=7,
        gross_total_cents=107,
        related_position_id=_POS_A,
    )
    with pytest.raises(
        ValueError, match="surcharge must reference a position in the variant"
    ):
        OfferVariant(
            variant_id=_A_ID,
            offer_version_id=_V1_ID,
            label="Bad surcharge",
            positions=(surcharge,),
        )


def test_offer_rejects_duplicate_snapshot_ids() -> None:
    v1 = _version(1)
    v2 = OfferVersion(
        offer_version_id=_V2_ID,
        offer_id=_OFFER_ID,
        version_number=2,
        created_at=_NOW + timedelta(hours=1),
        valid_until=date(2026, 7, 31),
        snapshot_id=v1.snapshot_id,
        snapshot_hash="sha256:" + ("b" * 64),
        **_version_facts(),
        variants=(_variant(_C_ID, _V2_ID, "C"),),
    )
    with pytest.raises(ValueError, match="snapshot_id must be unique"):
        _offer(versions=(v1, v2))


def test_offer_rejects_rejection_and_withdrawal_for_same_version() -> None:
    sent = _sent()
    rejected = RejectionEvidence(
        offer_id=_OFFER_ID,
        offer_version_id=_V1_ID,
        rejected_at=_NOW + timedelta(days=1),
        recorded_at=_NOW + timedelta(days=1, minutes=1),
        recorded_by="office",
    )
    withdrawn = WithdrawalEvidence(
        offer_id=_OFFER_ID,
        offer_version_id=_V1_ID,
        withdrawn_at=_NOW + timedelta(days=1, hours=1),
        recorded_by="office",
    )
    with pytest.raises(ValueError, match="both rejected and withdrawn"):
        _offer(sent=(sent,), rejected=(rejected,), withdrawn=(withdrawn,))


def test_offer_rejects_acceptance_before_sent() -> None:
    acceptance = _acceptance(accepted_at=_NOW - timedelta(hours=1))
    with pytest.raises(
        ValueError, match="AcceptanceEvidence cannot predate SentEvidence"
    ):
        _offer(sent=(_sent(sent_at=_NOW),), acceptance=acceptance)


def test_sent_evidence_rejects_invalid_channel() -> None:
    with pytest.raises(ValueError, match="invalid sent channel"):
        SentEvidence(
            offer_id=_OFFER_ID,
            offer_version_id=_V1_ID,
            sent_at=_NOW,
            recorded_at=_NOW,
            channel="sms",  # type: ignore[arg-type]
            recipient_reference="x@example.invalid",
            evidence_reference="mail-1",
            recorded_by="office",
        )


def test_derive_offer_state_unknown_version_raises() -> None:
    offer = _offer()
    with pytest.raises(ValueError, match="unknown OfferVersion"):
        derive_offer_state(
            offer, "00000000-0000-4000-8000-000000000000", today=date(2026, 7, 15)
        )


def test_offer_allows_acceptance_returns_false_for_unknown_version() -> None:
    offer = _offer(sent=(_sent(),))
    assert not offer_allows_acceptance(
        offer, "00000000-0000-4000-8000-000000000000", _B_ID, today=date(2026, 7, 20)
    )


def test_offer_allows_sent_recording_returns_false_for_unknown_version() -> None:
    offer = _offer()
    assert not offer_allows_sent_recording(
        offer, "00000000-0000-4000-8000-000000000000", today=date(2026, 7, 15)
    )


def test_offer_rejects_evidence_for_unknown_version() -> None:
    sent = SentEvidence(
        offer_id=_OFFER_ID,
        offer_version_id="00000000-0000-4000-8000-000000000000",
        sent_at=_NOW,
        recorded_at=_NOW,
        channel="email",
        recipient_reference="x@example.invalid",
        evidence_reference="mail-1",
        recorded_by="office",
    )
    with pytest.raises(ValueError, match="evidence references an unknown OfferVersion"):
        _offer(sent=(sent,))


def test_offer_rejects_duplicate_rejection_evidence() -> None:
    sent = _sent()
    rejected = RejectionEvidence(
        offer_id=_OFFER_ID,
        offer_version_id=_V1_ID,
        rejected_at=_NOW + timedelta(days=1),
        recorded_at=_NOW + timedelta(days=1, minutes=1),
        recorded_by="office",
    )
    with pytest.raises(ValueError, match="RejectionEvidence must be unique"):
        _offer(sent=(sent,), rejected=(rejected, rejected))


def test_offer_position_rejects_excessive_fractional_quantity() -> None:
    from decimal import Decimal

    with pytest.raises(ValueError, match="quantity exceeds fractional precision"):
        OfferPosition(
            position_id=_POS_A,
            kind="catalog",
            name="Item",
            unit_net_cents=100,
            net_total_cents=100,
            vat_rate_percent=7,
            vat_amount_cents=7,
            gross_total_cents=107,
            quantity=Decimal("1.0001"),
        )
