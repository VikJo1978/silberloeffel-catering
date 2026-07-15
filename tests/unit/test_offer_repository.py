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
        variants=tuple(
            _variant(
                variant_id,
                version_id,
                f"Variante {index}",
                position_id=position_ids[min(index - 1, len(position_ids) - 1)],
            )
            for index, variant_id in enumerate(ids, start=1)
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
    ]
    conn = sqlite3.connect(db)
    apply_migrations(conn, "offers", _MIGRATIONS)
    rows_after = conn.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE component = 'offers'"
    ).fetchone()
    conn.close()
    assert rows_after == (3,)
