"""Unit tests — Offer repository roundtrip and immutability."""

from __future__ import annotations

import sqlite3
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
)
from catering_system.domain.offer_budget_definition import OfferBudgetDefinition
from catering_system.domain.offer_charges import (
    BuffetChargeDefinition,
    DeliveryChargeDefinition,
    DishwareAdditionalLineDefinition,
    DishwareChargeDefinition,
    OfferChargesDefinition,
)
from catering_system.repositories.in_memory_offer_repository import (
    InMemoryOfferRepository,
)
from catering_system.repositories.sqlite_migrations import apply_migrations
from catering_system.repositories.sqlite_offer_repository import (
    SQLiteOfferRepository,
    _MIGRATIONS,
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
_HASH_V1 = "sha256:" + ("a" * 64)
_HASH_V2 = "sha256:" + ("b" * 64)
_POS_A = "88888888-8888-8888-8888-888888888881"
_POS_B = "88888888-8888-8888-8888-888888888882"
_POS_C = "88888888-8888-8888-8888-888888888883"
_EVENT_DATE = date(2026, 8, 20)


def _version_facts(**overrides: object) -> dict[str, object]:
    facts: dict[str, object] = {
        "event_date": _EVENT_DATE,
        "time_window_text": "18:00–22:00",
        "location_text": "Hamburg",
        "guest_count": 80,
        "planning_mode": "caterer_suggestion",
        "payment_method": "RECHNUNG",
        "payment_customer_visible_text": "Zahlung per Rechnung",
    }
    facts.update(overrides)
    return facts


def _position(position_id: str = _POS_A) -> OfferPosition:
    return OfferPosition(
        position_id=position_id,
        kind="catalog",
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
    position_id: str,
) -> OfferVariant:
    return OfferVariant(
        variant_id=variant_id,
        offer_version_id=version_id,
        label=label,
        positions=(_position(position_id),),
    )


def _version(
    number: int = 1,
    *,
    valid_until: date = date(2026, 7, 31),
    snapshot_hash: str = _HASH_V1,
    variant_ids: tuple[str, ...] | None = None,
    budget_definition: OfferBudgetDefinition | None = None,
    charges_definition: OfferChargesDefinition | None = None,
) -> OfferVersion:
    version_id = _V1_ID if number == 1 else _V2_ID
    ids = variant_ids or ((_A_ID, _B_ID) if number == 1 else (_C_ID,))
    position_ids = (_POS_A, _POS_B) if len(ids) == 2 else (_POS_C,)
    return OfferVersion(
        offer_version_id=version_id,
        offer_id=_OFFER_ID,
        version_number=number,
        created_at=_NOW + timedelta(hours=number - 1),
        valid_until=valid_until,
        snapshot_id=f"77777777-7777-7777-7777-77777777777{number}",
        snapshot_hash=snapshot_hash,
        **_version_facts(),
        variants=tuple(
            _variant(
                variant_id,
                version_id,
                f"Variante {index}",
                position_id=position_ids[min(index - 1, len(position_ids) - 1)],
            )
            for index, variant_id in enumerate(ids, start=1)
        ),
        budget_definition=budget_definition,
        charges_definition=charges_definition,
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


def _acceptance() -> AcceptanceEvidence:
    return AcceptanceEvidence(
        acceptance_id=_ACCEPTANCE_ID,
        offer_id=_OFFER_ID,
        accepted_offer_version_id=_V1_ID,
        accepted_variant_id=_B_ID,
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
        variant_id=_B_ID,
        acceptance_id=_ACCEPTANCE_ID,
        order_id=_ORDER_ID,
        created_at=_NOW + timedelta(days=1, minutes=6),
    )


def _rejection() -> RejectionEvidence:
    return RejectionEvidence(
        offer_id=_OFFER_ID,
        offer_version_id=_V1_ID,
        rejected_at=_NOW + timedelta(days=1),
        recorded_at=_NOW + timedelta(days=1, minutes=1),
        recorded_by="office",
        evidence_reference="phone-decline",
    )


def _withdrawal() -> WithdrawalEvidence:
    return WithdrawalEvidence(
        offer_id=_OFFER_ID,
        offer_version_id=_V1_ID,
        withdrawn_at=_NOW + timedelta(minutes=1),
        recorded_by="office",
        reason="Kunde nicht erreichbar",
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


def test_in_memory_offer_repository_roundtrip_preserves_prepared_offer() -> None:
    repo = InMemoryOfferRepository()
    offer = _offer()
    repo.save(offer)
    loaded = repo.get(_OFFER_ID)
    assert loaded == offer
    assert repo.exists(_OFFER_ID)


def test_sqlite_offer_repository_roundtrip_preserves_prepared_offer(
    tmp_path: Path,
) -> None:
    repo = SQLiteOfferRepository(tmp_path / "offer.db")
    offer = _offer()
    repo.save(offer)
    loaded = repo.get(_OFFER_ID)
    assert loaded == offer
    assert repo.exists(_OFFER_ID)
    assert derive_offer_state(loaded, _V1_ID, today=date(2026, 7, 20)) == "Prepared"


def test_sqlite_offer_roundtrip_preserves_multiple_versions_and_hashes(
    tmp_path: Path,
) -> None:
    v1 = _version(1, snapshot_hash=_HASH_V1)
    v2 = _version(2, snapshot_hash=_HASH_V2)
    offer = _offer(
        versions=(v1, v2),
        sent=(_sent(_V1_ID), _sent(_V2_ID, sent_at=_NOW + timedelta(hours=2))),
    )
    repo = SQLiteOfferRepository(tmp_path / "offer.db")
    repo.save(offer)
    loaded = repo.get(_OFFER_ID)
    assert loaded == offer
    assert loaded is not None
    assert loaded.versions[0].snapshot_hash == _HASH_V1
    assert loaded.versions[1].snapshot_hash == _HASH_V2
    assert derive_offer_state(loaded, _V1_ID, today=date(2026, 7, 20)) == "Superseded"
    assert derive_offer_state(loaded, _V2_ID, today=date(2026, 7, 20)) == "Sent"


def test_sqlite_offer_roundtrip_preserves_three_variants(tmp_path: Path) -> None:
    version = OfferVersion(
        offer_version_id=_V1_ID,
        offer_id=_OFFER_ID,
        version_number=1,
        created_at=_NOW,
        valid_until=date(2026, 7, 31),
        snapshot_id="77777777-7777-7777-7777-777777777771",
        snapshot_hash=_HASH_V1,
        **_version_facts(),
        variants=(
            _variant(_A_ID, _V1_ID, "Variante A", position_id=_POS_A),
            _variant(_B_ID, _V1_ID, "Variante B", position_id=_POS_B),
            _variant(_C_ID, _V1_ID, "Variante C", position_id=_POS_C),
        ),
    )
    offer = _offer(versions=(version,), sent=(_sent(),))
    repo = SQLiteOfferRepository(tmp_path / "offer.db")
    repo.save(offer)
    loaded = repo.get(_OFFER_ID)
    assert loaded == offer
    assert loaded is not None
    assert len(loaded.versions[0].variants) == 3


def test_sqlite_offer_roundtrip_preserves_acceptance_and_conversion_link(
    tmp_path: Path,
) -> None:
    offer = _offer(
        sent=(_sent(),),
        acceptance=_acceptance(),
        link=_link(),
    )
    repo = SQLiteOfferRepository(tmp_path / "offer.db")
    repo.save(offer)
    loaded = repo.get(_OFFER_ID)
    assert loaded == offer
    assert loaded is not None
    assert loaded.acceptance_evidence is not None
    assert loaded.conversion_link is not None
    assert loaded.conversion_link.order_id == _ORDER_ID
    assert derive_offer_state(loaded, _V1_ID, today=date(2026, 7, 20)) == "Converted"


def test_sqlite_offer_reconnect_preserves_aggregate(tmp_path: Path) -> None:
    offer = _offer(sent=(_sent(),), acceptance=_acceptance())
    db = tmp_path / "offer.db"
    SQLiteOfferRepository(db).save(offer)
    loaded = SQLiteOfferRepository(db).get(_OFFER_ID)
    assert loaded == offer


def test_sqlite_offer_duplicate_save_is_rejected(tmp_path: Path) -> None:
    repo = SQLiteOfferRepository(tmp_path / "offer.db")
    offer = _offer()
    repo.save(offer)
    with pytest.raises(sqlite3.IntegrityError):
        repo.save(offer)


def test_in_memory_offer_duplicate_save_raises_key_error() -> None:
    repo = InMemoryOfferRepository()
    offer = _offer()
    repo.save(offer)
    with pytest.raises(KeyError):
        repo.save(offer)


def test_append_sent_evidence_roundtrip_in_memory_and_sqlite(tmp_path: Path) -> None:
    evidence = _sent()
    for repo_factory in (
        lambda: InMemoryOfferRepository(),
        lambda: SQLiteOfferRepository(tmp_path / "append.db"),
    ):
        repo = repo_factory()
        repo.save(_offer())
        updated = repo.append_sent_evidence(evidence)
        assert len(updated.sent_evidence) == 1
        assert derive_offer_state(updated, _V1_ID, today=date(2026, 7, 20)) == "Sent"
        reloaded = repo.get(_OFFER_ID)
        assert reloaded == updated


def test_append_acceptance_evidence_roundtrip_in_memory_and_sqlite(
    tmp_path: Path,
) -> None:
    evidence = _acceptance()
    sent_offer = _offer(sent=(_sent(),))
    for repo_factory in (
        lambda: InMemoryOfferRepository(),
        lambda: SQLiteOfferRepository(tmp_path / "accept.db"),
    ):
        repo = repo_factory()
        repo.save(sent_offer)
        updated = repo.append_acceptance_evidence(evidence)
        assert updated.acceptance_evidence == evidence
        assert (
            derive_offer_state(updated, _V1_ID, today=date(2026, 7, 20)) == "Accepted"
        )
        reloaded = repo.get(_OFFER_ID)
        assert reloaded == updated


def test_append_acceptance_evidence_rejects_second_acceptance() -> None:
    repo = InMemoryOfferRepository()
    repo.save(_offer(sent=(_sent(),), acceptance=_acceptance()))
    with pytest.raises(ValueError, match="acceptance already exists"):
        repo.append_acceptance_evidence(_acceptance())


def test_append_rejection_evidence_roundtrip_in_memory_and_sqlite(
    tmp_path: Path,
) -> None:
    evidence = _rejection()
    sent_offer = _offer(sent=(_sent(),))
    for repo_factory in (
        lambda: InMemoryOfferRepository(),
        lambda: SQLiteOfferRepository(tmp_path / "reject.db"),
    ):
        repo = repo_factory()
        repo.save(sent_offer)
        updated = repo.append_rejection_evidence(evidence)
        assert len(updated.rejection_evidence) == 1
        assert (
            derive_offer_state(updated, _V1_ID, today=date(2026, 7, 20)) == "Rejected"
        )
        reloaded = repo.get(_OFFER_ID)
        assert reloaded == updated


def test_append_withdrawal_evidence_roundtrip_in_memory_and_sqlite(
    tmp_path: Path,
) -> None:
    evidence = _withdrawal()
    sent_offer = _offer(sent=(_sent(),))
    for repo_factory in (
        lambda: InMemoryOfferRepository(),
        lambda: SQLiteOfferRepository(tmp_path / "withdraw.db"),
    ):
        repo = repo_factory()
        repo.save(sent_offer)
        updated = repo.append_withdrawal_evidence(evidence)
        assert len(updated.withdrawal_evidence) == 1
        assert (
            derive_offer_state(updated, _V1_ID, today=date(2026, 7, 20)) == "Withdrawn"
        )
        reloaded = repo.get(_OFFER_ID)
        assert reloaded == updated


def test_append_conversion_link_roundtrip_in_memory_and_sqlite(tmp_path: Path) -> None:
    link = _link()
    accepted_offer = _offer(sent=(_sent(),), acceptance=_acceptance())
    for repo_factory in (
        lambda: InMemoryOfferRepository(),
        lambda: SQLiteOfferRepository(tmp_path / "convert.db"),
    ):
        repo = repo_factory()
        repo.save(accepted_offer)
        updated = repo.append_conversion_link(link)
        assert updated.conversion_link == link
        assert (
            derive_offer_state(updated, _V1_ID, today=date(2026, 7, 20)) == "Converted"
        )
        reloaded = repo.get(_OFFER_ID)
        assert reloaded == updated


def test_append_conversion_link_rejects_second_link() -> None:
    repo = InMemoryOfferRepository()
    repo.save(_offer(sent=(_sent(),), acceptance=_acceptance(), link=_link()))
    with pytest.raises(ValueError, match="conversion link already exists"):
        repo.append_conversion_link(_link())


def test_sqlite_offer_roundtrip_preserves_event_and_payment_facts(
    tmp_path: Path,
) -> None:
    v1 = _version(
        1,
        snapshot_hash=_HASH_V1,
        valid_until=date(2026, 7, 31),
    )
    v2 = _version(
        2,
        snapshot_hash=_HASH_V2,
        valid_until=date(2026, 8, 15),
    )
    v2 = OfferVersion(
        offer_version_id=v2.offer_version_id,
        offer_id=v2.offer_id,
        version_number=v2.version_number,
        created_at=v2.created_at,
        valid_until=v2.valid_until,
        snapshot_id=v2.snapshot_id,
        snapshot_hash=v2.snapshot_hash,
        **_version_facts(
            event_date=date(2026, 9, 1),
            location_text="Berlin",
            guest_count=120,
            payment_method="VORKASSE",
            payment_customer_visible_text="Zahlung per Vorkasse",
        ),
        variants=v2.variants,
    )
    offer = _offer(versions=(v1, v2))
    repo = SQLiteOfferRepository(tmp_path / "facts.db")
    repo.save(offer)
    loaded = repo.get(_OFFER_ID)
    assert loaded == offer
    assert loaded is not None
    assert loaded.versions[0].payment_method == "RECHNUNG"
    assert loaded.versions[1].guest_count == 120


def test_sqlite_offer_roundtrip_preserves_customer_narrative(
    tmp_path: Path,
) -> None:
    v1 = _version(1, snapshot_hash=_HASH_V1)
    v1 = OfferVersion(
        offer_version_id=v1.offer_version_id,
        offer_id=v1.offer_id,
        version_number=v1.version_number,
        created_at=v1.created_at,
        valid_until=v1.valid_until,
        snapshot_id=v1.snapshot_id,
        snapshot_hash=v1.snapshot_hash,
        **_version_facts(),
        variants=v1.variants,
        # Already normalized (outer-trimmed, internal newlines kept) — the
        # normalization step itself is OfferService's job (see
        # test_offer_service.py); this test only proves the SQLite
        # repository round-trips the resulting value byte-for-byte.
        customer_title="Sommerfest 2026",
        customer_introduction="Liebe Familie Muster,\n\nvielen Dank.",
        customer_notes="Bitte pünktlich liefern.",
    )
    offer = _offer(versions=(v1,))
    repo = SQLiteOfferRepository(tmp_path / "narrative.db")
    repo.save(offer)
    repo.close()

    reopened = SQLiteOfferRepository(tmp_path / "narrative.db")
    loaded = reopened.get(_OFFER_ID)
    reopened.close()
    assert loaded is not None
    loaded_v1 = loaded.versions[0]
    assert loaded_v1.customer_title == "Sommerfest 2026"
    # Internal newlines/text are preserved exactly through the round-trip.
    assert loaded_v1.customer_introduction == "Liebe Familie Muster,\n\nvielen Dank."
    assert loaded_v1.customer_notes == "Bitte pünktlich liefern."


def test_sqlite_offer_roundtrip_preserves_none_customer_narrative(
    tmp_path: Path,
) -> None:
    offer = _offer()  # default _version() carries no narrative fields (all None)
    repo = SQLiteOfferRepository(tmp_path / "narrative_none.db")
    repo.save(offer)
    loaded = repo.get(_OFFER_ID)
    assert loaded is not None
    v1 = loaded.versions[0]
    assert v1.customer_title is None
    assert v1.customer_introduction is None
    assert v1.customer_notes is None


def test_pre_migration_7_rows_load_with_narrative_fields_none(
    tmp_path: Path,
) -> None:
    db = tmp_path / "pre_migration.db"
    conn = sqlite3.connect(db)
    apply_migrations(conn, "offers", _MIGRATIONS[:6])
    conn.execute(
        "INSERT INTO offers (offer_id, source_inquiry_id, created_at) VALUES (?, ?, ?)",
        (_OFFER_ID, _INQUIRY_ID, _NOW.isoformat()),
    )
    conn.execute(
        """
        INSERT INTO offer_versions (
            offer_version_id, offer_id, version_number, created_at, valid_until,
            snapshot_id, snapshot_hash, event_date, time_window_text,
            location_text, guest_count, planning_mode, payment_method,
            payment_customer_visible_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _V1_ID,
            _OFFER_ID,
            1,
            _NOW.isoformat(),
            date(2026, 7, 31).isoformat(),
            "77777777-7777-7777-7777-777777777771",
            _HASH_V1,
            _EVENT_DATE.isoformat(),
            "18:00–22:00",
            "Hamburg",
            80,
            "caterer_suggestion",
            "RECHNUNG",
            "Zahlung per Rechnung",
        ),
    )
    conn.execute(
        "INSERT INTO offer_variants "
        "(variant_id, offer_version_id, offer_id, label, sort_order) "
        "VALUES (?, ?, ?, ?, ?)",
        (_A_ID, _V1_ID, _OFFER_ID, "Variante A", 0),
    )
    conn.execute(
        """
        INSERT INTO offer_positions (
            position_id, variant_id, offer_version_id, kind, name,
            unit_net_cents, net_total_cents, vat_rate_percent,
            vat_amount_cents, gross_total_cents, related_position_id,
            sort_order
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _POS_A,
            _A_ID,
            _V1_ID,
            "catalog",
            "Fingerfood Paket",
            290,
            23200,
            7,
            1624,
            24824,
            None,
            0,
        ),
    )
    conn.commit()
    conn.close()

    repo = SQLiteOfferRepository(db)  # migration 7 runs defensively on open
    loaded = repo.get(_OFFER_ID)
    repo.close()
    assert loaded is not None
    v1 = loaded.versions[0]
    assert v1.customer_title is None
    assert v1.customer_introduction is None
    assert v1.customer_notes is None


def test_sqlite_offer_roundtrip_preserves_budget_definition(tmp_path: Path) -> None:
    repo = SQLiteOfferRepository(tmp_path / "offer.db")
    budget = OfferBudgetDefinition(
        amount_cents=3500,
        type="PER_PERSON",
        tax_basis="GROSS",
        cost_scope="FULL_OFFER",
    )
    offer = _offer(versions=(_version(budget_definition=budget),))
    repo.save(offer)
    loaded = repo.get(_OFFER_ID)
    assert loaded is not None
    assert loaded.versions[0].budget_definition == budget
    assert loaded == offer


def test_sqlite_offer_roundtrip_preserves_absent_budget_definition(
    tmp_path: Path,
) -> None:
    repo = SQLiteOfferRepository(tmp_path / "offer.db")
    offer = _offer(versions=(_version(budget_definition=None),))
    repo.save(offer)
    loaded = repo.get(_OFFER_ID)
    assert loaded is not None
    assert loaded.versions[0].budget_definition is None


def test_pre_migration_8_rows_load_with_budget_definition_none(
    tmp_path: Path,
) -> None:
    """Migration/backward-compat: rows persisted before
    OFFER_BUDGET_DEFINITION_V1 load with budget_definition=None rather than
    failing or inventing a default."""
    db = tmp_path / "pre_migration.db"
    conn = sqlite3.connect(db)
    apply_migrations(conn, "offers", _MIGRATIONS[:7])
    conn.execute(
        "INSERT INTO offers (offer_id, source_inquiry_id, created_at) VALUES (?, ?, ?)",
        (_OFFER_ID, _INQUIRY_ID, _NOW.isoformat()),
    )
    conn.execute(
        """
        INSERT INTO offer_versions (
            offer_version_id, offer_id, version_number, created_at, valid_until,
            snapshot_id, snapshot_hash, event_date, time_window_text,
            location_text, guest_count, planning_mode, payment_method,
            payment_customer_visible_text, customer_title,
            customer_introduction, customer_notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _V1_ID,
            _OFFER_ID,
            1,
            _NOW.isoformat(),
            date(2026, 7, 31).isoformat(),
            "77777777-7777-7777-7777-777777777771",
            _HASH_V1,
            _EVENT_DATE.isoformat(),
            "18:00–22:00",
            "Hamburg",
            80,
            "caterer_suggestion",
            "RECHNUNG",
            "Zahlung per Rechnung",
            None,
            None,
            None,
        ),
    )
    conn.execute(
        "INSERT INTO offer_variants "
        "(variant_id, offer_version_id, offer_id, label, sort_order) "
        "VALUES (?, ?, ?, ?, ?)",
        (_A_ID, _V1_ID, _OFFER_ID, "Variante A", 0),
    )
    conn.execute(
        """
        INSERT INTO offer_positions (
            position_id, variant_id, offer_version_id, kind, name,
            unit_net_cents, net_total_cents, vat_rate_percent,
            vat_amount_cents, gross_total_cents, related_position_id,
            sort_order
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _POS_A,
            _A_ID,
            _V1_ID,
            "catalog",
            "Fingerfood Paket",
            290,
            23200,
            7,
            1624,
            24824,
            None,
            0,
        ),
    )
    conn.commit()
    conn.close()

    repo = SQLiteOfferRepository(db)  # migration 8 runs defensively on open
    loaded = repo.get(_OFFER_ID)
    repo.close()
    assert loaded is not None
    assert loaded.versions[0].budget_definition is None


def test_sqlite_offer_roundtrip_preserves_charges_definition(tmp_path: Path) -> None:
    repo = SQLiteOfferRepository(tmp_path / "offer.db")
    charges = OfferChargesDefinition(
        delivery=DeliveryChargeDefinition(amount_cents=3500),
        dishware=DishwareChargeDefinition(
            base_mode="PAUSCHALE",
            pauschale_per_person_cents=200,
            additional_lines=(
                DishwareAdditionalLineDefinition(
                    description="Weinglas", quantity=20, unit_net_cents=80
                ),
            ),
        ),
        buffet=BuffetChargeDefinition(base_mode="NONE", pauschale_per_person_cents=50),
    )
    offer = _offer(versions=(_version(charges_definition=charges),))
    repo.save(offer)
    loaded = repo.get(_OFFER_ID)
    assert loaded is not None
    assert loaded.versions[0].charges_definition == charges
    assert loaded == offer


def test_sqlite_offer_roundtrip_preserves_absent_charges_definition(
    tmp_path: Path,
) -> None:
    repo = SQLiteOfferRepository(tmp_path / "offer.db")
    offer = _offer(versions=(_version(charges_definition=None),))
    repo.save(offer)
    loaded = repo.get(_OFFER_ID)
    assert loaded is not None
    assert loaded.versions[0].charges_definition is None


def test_pre_migration_9_rows_load_with_charges_definition_none(
    tmp_path: Path,
) -> None:
    """Migration/backward-compat: rows persisted before
    CONFIGURABLE_OFFER_CHARGES_V1 load with charges_definition=None rather
    than failing or inventing a default."""
    db = tmp_path / "pre_migration.db"
    conn = sqlite3.connect(db)
    apply_migrations(conn, "offers", _MIGRATIONS[:8])
    conn.execute(
        "INSERT INTO offers (offer_id, source_inquiry_id, created_at) VALUES (?, ?, ?)",
        (_OFFER_ID, _INQUIRY_ID, _NOW.isoformat()),
    )
    conn.execute(
        """
        INSERT INTO offer_versions (
            offer_version_id, offer_id, version_number, created_at, valid_until,
            snapshot_id, snapshot_hash, event_date, time_window_text,
            location_text, guest_count, planning_mode, payment_method,
            payment_customer_visible_text, customer_title,
            customer_introduction, customer_notes, budget_definition_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _V1_ID,
            _OFFER_ID,
            1,
            _NOW.isoformat(),
            date(2026, 7, 31).isoformat(),
            "77777777-7777-7777-7777-777777777771",
            _HASH_V1,
            _EVENT_DATE.isoformat(),
            "18:00–22:00",
            "Hamburg",
            80,
            "caterer_suggestion",
            "RECHNUNG",
            "Zahlung per Rechnung",
            None,
            None,
            None,
            None,
        ),
    )
    conn.execute(
        "INSERT INTO offer_variants "
        "(variant_id, offer_version_id, offer_id, label, sort_order) "
        "VALUES (?, ?, ?, ?, ?)",
        (_A_ID, _V1_ID, _OFFER_ID, "Variante A", 0),
    )
    conn.execute(
        """
        INSERT INTO offer_positions (
            position_id, variant_id, offer_version_id, kind, name,
            unit_net_cents, net_total_cents, vat_rate_percent,
            vat_amount_cents, gross_total_cents, related_position_id,
            sort_order
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _POS_A,
            _A_ID,
            _V1_ID,
            "catalog",
            "Fingerfood Paket",
            290,
            23200,
            7,
            1624,
            24824,
            None,
            0,
        ),
    )
    conn.commit()
    conn.close()

    repo = SQLiteOfferRepository(db)  # migration 9 runs defensively on open
    loaded = repo.get(_OFFER_ID)
    repo.close()
    assert loaded is not None
    assert loaded.versions[0].charges_definition is None


def test_prepare_offer_document_after_sqlite_reload_gets_frozen_narrative(
    tmp_path: Path,
) -> None:
    from dataclasses import replace as _replace

    from catering_system.domain.customer_document_projection import CustomerAddress
    from catering_system.domain.inquiry_customer_snapshot import (
        InquiryCustomerSnapshot,
    )
    from catering_system.repositories.in_memory_inquiry_repository import (
        InMemoryInquiryRepository,
    )
    from catering_system.repositories.in_memory_order_repository import (
        InMemoryOrderRepository,
    )
    from catering_system.repositories.sqlite_offer_document_snapshot_repository import (
        SQLiteOfferDocumentSnapshotRepository,
    )
    from catering_system.services.offer_document_snapshot_service import (
        OfferDocumentSnapshotService,
    )
    from catering_system.services.offer_service import OfferService
    from tests.unit.test_offer_service import (
        _INQUIRY_ID as _SVC_INQUIRY_ID,
    )
    from tests.unit.test_offer_service import (
        _sample_inquiry,
        _valid_snapshot,
    )

    db = tmp_path / "narrative_prepare.db"
    invoice = CustomerAddress(
        street="Bürostraße 1", postal_code="20095", city="Hamburg", country="DE"
    )
    inquiries = InMemoryInquiryRepository()
    inquiry = _replace(
        _sample_inquiry(),
        customer_snapshot=InquiryCustomerSnapshot(
            company_name="ACME GmbH",
            contact_name="Anna",
            email="anna@example.invalid",
            phone="+49301234567",
            invoice_address=invoice,
            delivery_address=None,
            delivery_address_mode="SAME_AS_INVOICE",
        ),
        fulfillment_mode="DELIVERY",
    )
    inquiries.save(inquiry)

    offers = SQLiteOfferRepository(db)
    offer_service = OfferService(
        offers,
        inquiries,
        InMemoryOrderRepository(),
        today=lambda: date(2026, 7, 15),
    )
    # _valid_snapshot()'s customer_text carries fixed narrative values
    # ("Sommerfest" / "Customer-visible introduction" / "...notes").
    snapshot_in = _valid_snapshot()
    offer = offer_service.prepare_offer_version(_SVC_INQUIRY_ID, snapshot_in)
    version = offer.versions[0]
    offers.close()

    # Reopen a fresh repository/connection to force a real SQLite round-trip.
    offers = SQLiteOfferRepository(db)
    documents = SQLiteOfferDocumentSnapshotRepository(db)
    doc_service = OfferDocumentSnapshotService(offers, inquiries, documents)
    doc = doc_service.prepare_offer_document(
        offer.offer_id,
        version.offer_version_id,
        version.variants[0].variant_id,
        "office",
    )
    offers.close()
    documents.close()

    assert doc.customer_title == "Sommerfest"
    assert doc.customer_introduction == "Customer-visible introduction"
    assert doc.customer_notes == "Customer-visible conditions and notes"


def test_sqlite_offer_version_event_facts_are_immutable(tmp_path: Path) -> None:
    repo = SQLiteOfferRepository(tmp_path / "offer.db")
    repo.save(_offer())
    with pytest.raises(sqlite3.IntegrityError, match="offer_versions is immutable"):
        repo._conn.execute(
            "UPDATE offer_versions SET event_date = ? WHERE offer_version_id = ?",
            ("2026-09-01", _V1_ID),
        )


def test_sqlite_offer_version_rows_are_immutable(tmp_path: Path) -> None:
    repo = SQLiteOfferRepository(tmp_path / "offer.db")
    repo.save(_offer())
    with pytest.raises(sqlite3.IntegrityError, match="offer_versions is immutable"):
        repo._conn.execute(
            "UPDATE offer_versions SET snapshot_hash = ? WHERE offer_version_id = ?",
            ("sha256:" + ("c" * 64), _V1_ID),
        )


def test_offer_component_migrations_are_recorded_once(tmp_path: Path) -> None:
    db = tmp_path / "offer.db"
    SQLiteOfferRepository(db).close()
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT version, name FROM schema_migrations WHERE component = 'offers' "
        "ORDER BY version"
    ).fetchall()
    conn.close()
    assert rows == [
        (1, "create_offer_tables"),
        (2, "unique_source_inquiry"),
        (3, "offer_immutability_triggers"),
        (4, "offer_version_event_and_payment_facts"),
        (5, "offer_variant_and_position_print_fields"),
        (6, "offer_position_catalog_snapshot_fields"),
        (7, "offer_version_customer_narrative"),
        (8, "offer_version_budget_definition"),
        (9, "offer_version_charges_definition"),
        (10, "offer_version_logistics_timing"),
        (11, "offer_version_exact_timing"),
    ]
    conn = sqlite3.connect(db)
    apply_migrations(conn, "offers", _MIGRATIONS)
    rows_after = conn.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE component = 'offers'"
    ).fetchone()
    conn.close()
    assert rows_after == (11,)
