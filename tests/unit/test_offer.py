from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from catering_system.domain.offer import (
    AcceptanceEvidence,
    ConversionLink,
    Offer,
    OfferPosition,
    OfferVariant,
    OfferVersion,
    RejectionEvidence,
    SentEvidence,
    WithdrawalEvidence,
    derive_offer_state,
    offer_allows_acceptance,
    offer_allows_conversion,
    offer_blocks_direct_inquiry_conversion,
)

_OFFER_ID = "11111111-1111-1111-1111-111111111111"
_INQUIRY_ID = "22222222-2222-2222-2222-222222222222"
_V1_ID = "33333333-3333-3333-3333-333333333331"
_V2_ID = "33333333-3333-3333-3333-333333333332"
_A_ID = "44444444-4444-4444-4444-444444444441"
_B_ID = "44444444-4444-4444-4444-444444444442"
_C_ID = "44444444-4444-4444-4444-444444444443"
_ACCEPTANCE_ID = "55555555-5555-5555-5555-555555555555"
_ORDER_ID = "66666666-6666-6666-6666-666666666666"
_NOW = datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)
_HASH = "sha256:" + ("a" * 64)
_POS_A = "88888888-8888-8888-8888-888888888881"
_POS_B = "88888888-8888-8888-8888-888888888882"
_POS_C = "88888888-8888-8888-8888-888888888883"


def _position(position_id: str = _POS_A, *, kind: str = "catalog") -> OfferPosition:
    return OfferPosition(
        position_id=position_id,
        kind=kind,  # type: ignore[arg-type]
        name="Fingerfood Paket",
        unit_net_cents=290,
        net_total_cents=23200,
        vat_rate_percent=7,
        vat_amount_cents=1624,
        gross_total_cents=24824,
    )


def _variant(
    variant_id: str,
    version_id: str,
    label: str,
    *,
    position_id: str | None = None,
) -> OfferVariant:
    return OfferVariant(
        variant_id=variant_id,
        offer_version_id=version_id,
        label=label,
        positions=(_position(position_id or _POS_A),),
    )


def _version(
    number: int = 1,
    *,
    created_at: datetime | None = None,
    valid_until: date = date(2026, 7, 31),
) -> OfferVersion:
    version_id = _V1_ID if number == 1 else _V2_ID
    variant_ids = (_A_ID, _B_ID) if number == 1 else (_C_ID,)
    return OfferVersion(
        offer_version_id=version_id,
        offer_id=_OFFER_ID,
        version_number=number,
        created_at=created_at or (_NOW + timedelta(hours=number - 1)),
        valid_until=valid_until,
        snapshot_id=f"77777777-7777-7777-7777-77777777777{number}",
        snapshot_hash=_HASH,
        variants=tuple(
            _variant(variant_id, version_id, f"Variante {index}")
            for index, variant_id in enumerate(variant_ids, start=1)
        ),
    )


def _sent(version_id: str = _V1_ID, *, sent_at: datetime = _NOW) -> SentEvidence:
    return SentEvidence(
        offer_id=_OFFER_ID,
        offer_version_id=version_id,
        sent_at=sent_at,
        recorded_at=sent_at + timedelta(minutes=1),
        channel="email",
        recipient_reference="kunde@example.invalid",
        evidence_reference="mail-1",
        recorded_by="office",
    )


def _acceptance(
    *,
    version_id: str = _V1_ID,
    variant_id: str = _B_ID,
    accepted_at: datetime = _NOW + timedelta(days=1),
) -> AcceptanceEvidence:
    return AcceptanceEvidence(
        acceptance_id=_ACCEPTANCE_ID,
        offer_id=_OFFER_ID,
        accepted_offer_version_id=version_id,
        accepted_variant_id=variant_id,
        accepted_at=accepted_at,
        recorded_at=accepted_at + timedelta(minutes=5),
        channel="email",
        evidence_reference="reply-1",
        recorded_by="office",
    )


def _offer(
    *,
    versions: tuple[OfferVersion, ...] | None = None,
    sent: tuple[SentEvidence, ...] = (),
    acceptance: AcceptanceEvidence | None = None,
    rejected: tuple[RejectionEvidence, ...] = (),
    withdrawn: tuple[WithdrawalEvidence, ...] = (),
    link: ConversionLink | None = None,
) -> Offer:
    return Offer(
        offer_id=_OFFER_ID,
        source_inquiry_id=_INQUIRY_ID,
        created_at=_NOW,
        versions=versions or (_version(),),
        sent_evidence=sent,
        acceptance_evidence=acceptance,
        rejection_evidence=rejected,
        withdrawal_evidence=withdrawn,
        conversion_link=link,
    )


def _link() -> ConversionLink:
    return ConversionLink(
        offer_id=_OFFER_ID,
        offer_version_id=_V1_ID,
        variant_id=_B_ID,
        acceptance_id=_ACCEPTANCE_ID,
        order_id=_ORDER_ID,
        created_at=_NOW + timedelta(days=1, minutes=6),
    )


def test_offer_starts_with_prepared_immutable_version_and_embedded_variants() -> None:
    version = _version()
    offer = _offer(versions=(version,))

    assert offer.source_inquiry_id == _INQUIRY_ID
    assert offer.versions == (version,)
    assert [variant.variant_id for variant in version.variants] == [_A_ID, _B_ID]
    assert derive_offer_state(offer, _V1_ID, today=date(2026, 7, 15)) == "Prepared"

    with pytest.raises(FrozenInstanceError):
        version.version_number = 2  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        version.variants[0].label = "Geändert"  # type: ignore[misc]


def test_variant_must_belong_to_its_exact_version() -> None:
    foreign = _variant(_A_ID, _V2_ID, "Fremd", position_id=_POS_B)
    with pytest.raises(ValueError, match="different OfferVersion"):
        OfferVersion(
            offer_version_id=_V1_ID,
            offer_id=_OFFER_ID,
            version_number=1,
            created_at=_NOW,
            valid_until=date(2026, 7, 31),
            snapshot_id="77777777-7777-7777-7777-777777777771",
            snapshot_hash=_HASH,
            variants=(foreign,),
        )


def test_offer_rejects_non_contiguous_version_history() -> None:
    with pytest.raises(ValueError, match="contiguous"):
        _offer(versions=(_version(2),))


def test_state_derivation_uses_facts_not_a_stored_status() -> None:
    sent = _sent()
    offer = _offer(sent=(sent,))

    assert "status" not in {field.name for field in fields(Offer)}
    assert "status" not in {field.name for field in fields(OfferVersion)}
    assert derive_offer_state(offer, _V1_ID, today=date(2026, 7, 20)) == "Sent"
    assert derive_offer_state(offer, _V1_ID, today=date(2026, 8, 1)) == "Expired"


def test_newer_sent_version_supersedes_only_the_older_sent_version() -> None:
    v1 = _version()
    v2 = _version(2)
    offer = _offer(
        versions=(v1, v2),
        sent=(_sent(_V1_ID), _sent(_V2_ID, sent_at=_NOW + timedelta(hours=2))),
    )

    assert derive_offer_state(offer, _V1_ID, today=date(2026, 7, 20)) == "Superseded"
    assert derive_offer_state(offer, _V2_ID, today=date(2026, 7, 20)) == "Sent"


def test_rejected_and_withdrawn_are_derived_from_append_only_facts() -> None:
    rejected = RejectionEvidence(
        offer_id=_OFFER_ID,
        offer_version_id=_V1_ID,
        rejected_at=_NOW + timedelta(days=1),
        recorded_at=_NOW + timedelta(days=1, minutes=1),
        recorded_by="office",
    )
    rejected_offer = _offer(sent=(_sent(),), rejected=(rejected,))
    assert (
        derive_offer_state(rejected_offer, _V1_ID, today=date(2026, 7, 20))
        == "Rejected"
    )

    withdrawn = WithdrawalEvidence(
        offer_id=_OFFER_ID,
        offer_version_id=_V1_ID,
        withdrawn_at=_NOW + timedelta(minutes=1),
        recorded_by="office",
    )
    withdrawn_offer = _offer(withdrawn=(withdrawn,))
    assert (
        derive_offer_state(withdrawn_offer, _V1_ID, today=date(2026, 7, 20))
        == "Withdrawn"
    )


def test_acceptance_requires_exact_sent_version_and_its_variant() -> None:
    sent_offer = _offer(sent=(_sent(),))

    assert offer_allows_acceptance(sent_offer, _V1_ID, _B_ID, today=date(2026, 7, 20))
    assert not offer_allows_acceptance(
        sent_offer, _V1_ID, _C_ID, today=date(2026, 7, 20)
    )

    with pytest.raises(ValueError, match="does not belong"):
        _offer(sent=(_sent(),), acceptance=_acceptance(variant_id=_C_ID))


def test_expired_or_superseded_version_cannot_be_accepted() -> None:
    expired_acceptance = _acceptance(accepted_at=_NOW + timedelta(days=20))
    with pytest.raises(ValueError, match="expired"):
        _offer(
            versions=(_version(valid_until=date(2026, 7, 20)),),
            sent=(_sent(),),
            acceptance=expired_acceptance,
        )

    v1 = _version()
    v2 = _version(2)
    dual_sent = _offer(
        versions=(v1, v2),
        sent=(_sent(_V1_ID), _sent(_V2_ID, sent_at=_NOW + timedelta(hours=2))),
    )
    with pytest.raises(ValueError, match="superseded"):
        _offer(
            versions=(v1, v2),
            sent=(_sent(_V1_ID), _sent(_V2_ID, sent_at=_NOW + timedelta(hours=2))),
            acceptance=_acceptance(),
        )
    assert not offer_allows_acceptance(
        dual_sent, _V1_ID, _B_ID, today=date(2026, 7, 20)
    )
    assert offer_allows_acceptance(dual_sent, _V2_ID, _C_ID, today=date(2026, 7, 20))


def test_sent_then_expired_prefers_expired_over_sent() -> None:
    offer = _offer(
        versions=(_version(valid_until=date(2026, 7, 14)),),
        sent=(_sent(),),
    )
    assert derive_offer_state(offer, _V1_ID, today=date(2026, 7, 14)) == "Sent"
    assert derive_offer_state(offer, _V1_ID, today=date(2026, 7, 15)) == "Expired"
    assert not offer_allows_acceptance(offer, _V1_ID, _B_ID, today=date(2026, 7, 15))


def test_acceptance_closes_offer_against_later_versions() -> None:
    acceptance = _acceptance()
    later = _version(
        2,
        created_at=acceptance.accepted_at + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="after acceptance"):
        _offer(
            versions=(_version(), later),
            sent=(_sent(),),
            acceptance=acceptance,
        )


def test_conversion_requires_and_preserves_exact_acceptance_reference() -> None:
    assert not offer_allows_conversion(
        _offer(sent=(_sent(),)), _V1_ID, _B_ID, _ACCEPTANCE_ID
    )

    accepted = _offer(sent=(_sent(),), acceptance=_acceptance())
    assert derive_offer_state(accepted, _V1_ID, today=date(2026, 7, 20)) == "Accepted"
    assert offer_allows_conversion(accepted, _V1_ID, _B_ID, _ACCEPTANCE_ID)
    assert not offer_allows_conversion(accepted, _V1_ID, _A_ID, _ACCEPTANCE_ID)

    converted = _offer(
        sent=(_sent(),),
        acceptance=_acceptance(),
        link=_link(),
    )
    assert derive_offer_state(converted, _V1_ID, today=date(2026, 7, 20)) == "Converted"
    assert offer_allows_conversion(converted, _V1_ID, _B_ID, _ACCEPTANCE_ID)
    assert converted.conversion_link is not None
    assert converted.conversion_link.order_id == _ORDER_ID


def test_conversion_link_cannot_reference_another_variant() -> None:
    bad_link = ConversionLink(
        offer_id=_OFFER_ID,
        offer_version_id=_V1_ID,
        variant_id=_A_ID,
        acceptance_id=_ACCEPTANCE_ID,
        order_id=_ORDER_ID,
        created_at=_NOW + timedelta(days=1, minutes=6),
    )
    with pytest.raises(ValueError, match="does not match"):
        _offer(
            sent=(_sent(),),
            acceptance=_acceptance(),
            link=bad_link,
        )


def test_offer_domain_has_no_repository_api_or_ui_dependency() -> None:
    import catering_system.domain.offer as offer_module

    source = Path(offer_module.__file__).read_text(encoding="utf-8")
    assert "sqlite" not in source.lower()
    assert "catering_system.repositories" not in source
    assert "catering_system.ui" not in source
    assert "catering_system.services" not in source


def test_one_version_can_present_three_selectable_variants_with_positions() -> None:
    version = OfferVersion(
        offer_version_id=_V1_ID,
        offer_id=_OFFER_ID,
        version_number=1,
        created_at=_NOW,
        valid_until=date(2026, 7, 31),
        snapshot_id="77777777-7777-7777-7777-777777777771",
        snapshot_hash=_HASH,
        variants=(
            _variant(_A_ID, _V1_ID, "Variante A", position_id=_POS_A),
            _variant(_B_ID, _V1_ID, "Variante B", position_id=_POS_B),
            _variant(_C_ID, _V1_ID, "Variante C", position_id=_POS_C),
        ),
    )
    offer = _offer(versions=(version,), sent=(_sent(),))

    assert len(version.variants) == 3
    assert version.variants[1].positions[0].unit_net_cents == 290
    assert offer_allows_acceptance(offer, _V1_ID, _B_ID, today=date(2026, 7, 20))


def test_active_offer_blocks_direct_inquiry_conversion() -> None:
    prepared = _offer()
    sent = _offer(sent=(_sent(),))
    rejected = _offer(
        sent=(_sent(),),
        rejected=(
            RejectionEvidence(
                offer_id=_OFFER_ID,
                offer_version_id=_V1_ID,
                rejected_at=_NOW + timedelta(days=1),
                recorded_at=_NOW + timedelta(days=1, minutes=1),
                recorded_by="office",
            ),
        ),
    )
    v1 = _version()
    v2 = _version(2)
    superseded_with_active_sent = _offer(
        versions=(v1, v2),
        sent=(_sent(_V1_ID), _sent(_V2_ID, sent_at=_NOW + timedelta(hours=2))),
    )
    superseded_with_expired_latest = _offer(
        versions=(v1, _version(2, valid_until=date(2026, 7, 14))),
        sent=(_sent(_V1_ID), _sent(_V2_ID, sent_at=_NOW + timedelta(hours=2))),
    )
    expired_only = _offer(
        versions=(_version(valid_until=date(2026, 7, 14)),),
        sent=(_sent(),),
    )
    withdrawn_only = _offer(
        withdrawn=(
            WithdrawalEvidence(
                offer_id=_OFFER_ID,
                offer_version_id=_V1_ID,
                withdrawn_at=_NOW + timedelta(minutes=1),
                recorded_by="office",
            ),
        ),
    )

    assert offer_blocks_direct_inquiry_conversion(prepared, today=date(2026, 7, 20))
    assert offer_blocks_direct_inquiry_conversion(sent, today=date(2026, 7, 20))
    assert offer_blocks_direct_inquiry_conversion(
        superseded_with_active_sent, today=date(2026, 7, 20)
    )
    assert not offer_blocks_direct_inquiry_conversion(rejected, today=date(2026, 7, 20))
    assert not offer_blocks_direct_inquiry_conversion(
        superseded_with_expired_latest, today=date(2026, 7, 15)
    )
    assert not offer_blocks_direct_inquiry_conversion(
        expired_only, today=date(2026, 7, 15)
    )
    assert not offer_blocks_direct_inquiry_conversion(
        withdrawn_only, today=date(2026, 7, 20)
    )


def test_accepted_or_converted_offer_stays_closed_after_order_storno() -> None:
    accepted = _offer(sent=(_sent(),), acceptance=_acceptance())
    converted = _offer(
        sent=(_sent(),),
        acceptance=_acceptance(),
        link=_link(),
    )

    for offer in (accepted, converted):
        assert derive_offer_state(offer, _V1_ID, today=date(2026, 7, 20)) in (
            "Accepted",
            "Converted",
        )
        assert not offer_allows_acceptance(
            offer, _V1_ID, _B_ID, today=date(2026, 7, 20)
        )
        assert offer_blocks_direct_inquiry_conversion(offer, today=date(2026, 7, 20))
        assert not offer_allows_conversion(offer, _V1_ID, _B_ID, "other-acceptance-id")
