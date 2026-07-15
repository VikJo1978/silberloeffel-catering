"""SQLite Offer repository — persistence adapter for the commercial aggregate.

Stores immutable OfferVersion snapshots and append-only evidence facts.
No derived lifecycle status is persisted; load reconstructs domain objects
for ``derive_offer_state()`` on read.
"""

from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from datetime import date, datetime
from pathlib import Path

from catering_system.domain.inquiry import validate_planning_mode
from catering_system.domain.offer import (
    ACCEPTANCE_CHANNELS,
    POSITION_KINDS,
    SENT_CHANNELS,
    VAT_RATES,
    AcceptanceChannel,
    AcceptanceEvidence,
    ConversionLink,
    Offer,
    OfferPosition,
    OfferVariant,
    OfferVersion,
    PositionKind,
    RejectionEvidence,
    SentChannel,
    SentEvidence,
    VatRatePercent,
    WithdrawalEvidence,
)
from catering_system.domain.order_payment_reminder import validate_payment_method
from catering_system.repositories.sqlite_migrations import apply_migrations

_CREATE_OFFERS = """
CREATE TABLE IF NOT EXISTS offers (
    offer_id TEXT PRIMARY KEY,
    source_inquiry_id TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

_CREATE_OFFER_VERSIONS = """
CREATE TABLE IF NOT EXISTS offer_versions (
    offer_version_id TEXT PRIMARY KEY,
    offer_id TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    UNIQUE (offer_id, version_number),
    UNIQUE (offer_id, snapshot_id)
)
"""

_CREATE_OFFER_VARIANTS = """
CREATE TABLE IF NOT EXISTS offer_variants (
    variant_id TEXT PRIMARY KEY,
    offer_version_id TEXT NOT NULL,
    offer_id TEXT NOT NULL,
    label TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    UNIQUE (offer_version_id, variant_id)
)
"""

_CREATE_OFFER_POSITIONS = """
CREATE TABLE IF NOT EXISTS offer_positions (
    position_id TEXT PRIMARY KEY,
    variant_id TEXT NOT NULL,
    offer_version_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    unit_net_cents INTEGER NOT NULL,
    net_total_cents INTEGER NOT NULL,
    vat_rate_percent INTEGER NOT NULL,
    vat_amount_cents INTEGER NOT NULL,
    gross_total_cents INTEGER NOT NULL,
    related_position_id TEXT,
    sort_order INTEGER NOT NULL
)
"""

_CREATE_SENT_EVIDENCE = """
CREATE TABLE IF NOT EXISTS offer_sent_evidence (
    offer_version_id TEXT PRIMARY KEY,
    offer_id TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    channel TEXT NOT NULL,
    recipient_reference TEXT NOT NULL,
    evidence_reference TEXT NOT NULL,
    recorded_by TEXT NOT NULL
)
"""

_CREATE_REJECTION_EVIDENCE = """
CREATE TABLE IF NOT EXISTS offer_rejection_evidence (
    offer_version_id TEXT PRIMARY KEY,
    offer_id TEXT NOT NULL,
    rejected_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    recorded_by TEXT NOT NULL,
    evidence_reference TEXT
)
"""

_CREATE_WITHDRAWAL_EVIDENCE = """
CREATE TABLE IF NOT EXISTS offer_withdrawal_evidence (
    offer_version_id TEXT PRIMARY KEY,
    offer_id TEXT NOT NULL,
    withdrawn_at TEXT NOT NULL,
    recorded_by TEXT NOT NULL,
    reason TEXT
)
"""

_CREATE_ACCEPTANCE_EVIDENCE = """
CREATE TABLE IF NOT EXISTS offer_acceptance_evidence (
    acceptance_id TEXT PRIMARY KEY,
    offer_id TEXT NOT NULL UNIQUE,
    accepted_offer_version_id TEXT NOT NULL,
    accepted_variant_id TEXT NOT NULL,
    accepted_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    channel TEXT NOT NULL,
    evidence_reference TEXT NOT NULL,
    recorded_by TEXT NOT NULL,
    note TEXT
)
"""

_CREATE_CONVERSION_LINKS = """
CREATE TABLE IF NOT EXISTS offer_conversion_links (
    offer_id TEXT PRIMARY KEY,
    offer_version_id TEXT NOT NULL,
    variant_id TEXT NOT NULL,
    acceptance_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

_IMMUTABLE_TABLES = (
    "offer_versions",
    "offer_variants",
    "offer_positions",
    "offer_sent_evidence",
    "offer_rejection_evidence",
    "offer_withdrawal_evidence",
    "offer_acceptance_evidence",
    "offer_conversion_links",
)


def _migration_1_create_tables(connection: sqlite3.Connection) -> None:
    connection.execute(_CREATE_OFFERS)
    connection.execute(_CREATE_OFFER_VERSIONS)
    connection.execute(_CREATE_OFFER_VARIANTS)
    connection.execute(_CREATE_OFFER_POSITIONS)
    connection.execute(_CREATE_SENT_EVIDENCE)
    connection.execute(_CREATE_REJECTION_EVIDENCE)
    connection.execute(_CREATE_WITHDRAWAL_EVIDENCE)
    connection.execute(_CREATE_ACCEPTANCE_EVIDENCE)
    connection.execute(_CREATE_CONVERSION_LINKS)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_offer_versions_offer_id "
        "ON offer_versions (offer_id, version_number)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_offer_variants_version "
        "ON offer_variants (offer_version_id, sort_order)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_offer_positions_variant "
        "ON offer_positions (variant_id, sort_order)"
    )


def _migration_2_unique_source_inquiry(connection: sqlite3.Connection) -> None:
    duplicate = connection.execute(
        "SELECT source_inquiry_id FROM offers "
        "GROUP BY source_inquiry_id HAVING COUNT(*) > 1 LIMIT 1"
    ).fetchone()
    if duplicate is not None:
        raise ValueError(
            "cannot enforce one offer per inquiry: inquiry "
            f"{duplicate[0]!r} has more than one offer; resolve manually before migrating"
        )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_offers_source_inquiry "
        "ON offers (source_inquiry_id)"
    )


def _migration_3_immutability_triggers(connection: sqlite3.Connection) -> None:
    for table in _IMMUTABLE_TABLES:
        connection.execute(
            f"""CREATE TRIGGER IF NOT EXISTS trg_{table}_immutable_update
            BEFORE UPDATE ON {table}
            BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END"""
        )
        connection.execute(
            f"""CREATE TRIGGER IF NOT EXISTS trg_{table}_immutable_delete
            BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END"""
        )


def _migration_4_offer_version_event_and_payment_facts(
    connection: sqlite3.Connection,
) -> None:
    existing = {
        row[1] for row in connection.execute("PRAGMA table_info(offer_versions)")
    }
    columns = (
        ("event_date", "TEXT"),
        ("time_window_text", "TEXT"),
        ("location_text", "TEXT"),
        ("guest_count", "INTEGER"),
        ("planning_mode", "TEXT"),
        ("payment_method", "TEXT"),
        ("payment_customer_visible_text", "TEXT"),
    )
    for name, column_type in columns:
        if name not in existing:
            connection.execute(
                f"ALTER TABLE offer_versions ADD COLUMN {name} {column_type}"
            )


_MIGRATIONS = (
    (1, "create_offer_tables", _migration_1_create_tables),
    (2, "unique_source_inquiry", _migration_2_unique_source_inquiry),
    (3, "offer_immutability_triggers", _migration_3_immutability_triggers),
    (
        4,
        "offer_version_event_and_payment_facts",
        _migration_4_offer_version_event_and_payment_facts,
    ),
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _position_kind(value: str) -> PositionKind:
    if value not in POSITION_KINDS:
        raise ValueError("invalid position kind")
    return value


def _vat_rate(value: int) -> VatRatePercent:
    if value not in VAT_RATES:
        raise ValueError("vat_rate_percent must be 7 or 19")
    return value


def _sent_channel(value: str) -> SentChannel:
    if value not in SENT_CHANNELS:
        raise ValueError("invalid sent channel")
    return value


def _acceptance_channel(value: str) -> AcceptanceChannel:
    if value not in ACCEPTANCE_CHANNELS:
        raise ValueError("invalid acceptance channel")
    return value


class SQLiteOfferRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._manage_transactions = True
        try:
            apply_migrations(self._conn, "offers", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(cls, connection: sqlite3.Connection) -> SQLiteOfferRepository:
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._manage_transactions = False
        apply_migrations(connection, "offers", _MIGRATIONS)
        return repo

    def _write_scope(self):  # noqa: ANN202
        return self._conn if self._manage_transactions else nullcontext()

    def close(self) -> None:
        self._conn.close()

    def save(self, offer: Offer) -> None:
        with self._write_scope():
            self._conn.execute(
                "INSERT INTO offers VALUES (?, ?, ?)",
                (
                    offer.offer_id,
                    offer.source_inquiry_id,
                    offer.created_at.isoformat(),
                ),
            )
            for version in offer.versions:
                self._insert_version(offer.offer_id, version)
            for sent in offer.sent_evidence:
                self._insert_sent_evidence(sent)
            for rejection in offer.rejection_evidence:
                self._insert_rejection_evidence(rejection)
            for withdrawal in offer.withdrawal_evidence:
                self._insert_withdrawal_evidence(withdrawal)
            if offer.acceptance_evidence is not None:
                self._insert_acceptance_evidence(offer.acceptance_evidence)
            if offer.conversion_link is not None:
                self._insert_conversion_link(offer.conversion_link)

    def get(self, offer_id: str) -> Offer | None:
        row = self._conn.execute(
            "SELECT offer_id, source_inquiry_id, created_at FROM offers WHERE offer_id = ?",
            (offer_id,),
        ).fetchone()
        if row is None:
            return None
        versions = self._load_versions(offer_id)
        return Offer(
            offer_id=row[0],
            source_inquiry_id=row[1],
            created_at=_dt(row[2]),
            versions=versions,
            sent_evidence=self._load_sent_evidence(offer_id),
            acceptance_evidence=self._load_acceptance_evidence(offer_id),
            rejection_evidence=self._load_rejection_evidence(offer_id),
            withdrawal_evidence=self._load_withdrawal_evidence(offer_id),
            conversion_link=self._load_conversion_link(offer_id),
        )

    def exists(self, offer_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM offers WHERE offer_id = ? LIMIT 1", (offer_id,)
        ).fetchone()
        return row is not None

    def get_by_source_inquiry_id(self, inquiry_id: str) -> Offer | None:
        row = self._conn.execute(
            "SELECT offer_id FROM offers WHERE source_inquiry_id = ? LIMIT 1",
            (inquiry_id,),
        ).fetchone()
        if row is None:
            return None
        return self.get(row[0])

    def list_all(self) -> list[Offer]:
        rows = self._conn.execute(
            "SELECT offer_id FROM offers ORDER BY created_at, offer_id"
        ).fetchall()
        offers: list[Offer] = []
        for (offer_id,) in rows:
            offer = self.get(offer_id)
            if offer is not None:
                offers.append(offer)
        return offers

    def append_sent_evidence(self, evidence: SentEvidence) -> Offer:
        with self._write_scope():
            offer = self.get(evidence.offer_id)
            if offer is None:
                raise KeyError(evidence.offer_id)
            updated = Offer(
                offer_id=offer.offer_id,
                source_inquiry_id=offer.source_inquiry_id,
                created_at=offer.created_at,
                versions=offer.versions,
                sent_evidence=(*offer.sent_evidence, evidence),
                acceptance_evidence=offer.acceptance_evidence,
                rejection_evidence=offer.rejection_evidence,
                withdrawal_evidence=offer.withdrawal_evidence,
                conversion_link=offer.conversion_link,
            )
            self._insert_sent_evidence(evidence)
            return updated

    def append_acceptance_evidence(self, evidence: AcceptanceEvidence) -> Offer:
        with self._write_scope():
            offer = self.get(evidence.offer_id)
            if offer is None:
                raise KeyError(evidence.offer_id)
            if offer.acceptance_evidence is not None:
                raise ValueError(
                    f"acceptance already exists for offer_id={evidence.offer_id!r}"
                )
            updated = Offer(
                offer_id=offer.offer_id,
                source_inquiry_id=offer.source_inquiry_id,
                created_at=offer.created_at,
                versions=offer.versions,
                sent_evidence=offer.sent_evidence,
                acceptance_evidence=evidence,
                rejection_evidence=offer.rejection_evidence,
                withdrawal_evidence=offer.withdrawal_evidence,
                conversion_link=offer.conversion_link,
            )
            self._insert_acceptance_evidence(evidence)
            return updated

    def append_conversion_link(self, link: ConversionLink) -> Offer:
        with self._write_scope():
            offer = self.get(link.offer_id)
            if offer is None:
                raise KeyError(link.offer_id)
            if offer.conversion_link is not None:
                raise ValueError(
                    f"conversion link already exists for offer_id={link.offer_id!r}"
                )
            updated = Offer(
                offer_id=offer.offer_id,
                source_inquiry_id=offer.source_inquiry_id,
                created_at=offer.created_at,
                versions=offer.versions,
                sent_evidence=offer.sent_evidence,
                acceptance_evidence=offer.acceptance_evidence,
                rejection_evidence=offer.rejection_evidence,
                withdrawal_evidence=offer.withdrawal_evidence,
                conversion_link=link,
            )
            self._insert_conversion_link(link)
            return updated

    def _insert_version(self, offer_id: str, version: OfferVersion) -> None:
        self._conn.execute(
            """
            INSERT INTO offer_versions (
                offer_version_id, offer_id, version_number, created_at, valid_until,
                snapshot_id, snapshot_hash, event_date, time_window_text,
                location_text, guest_count, planning_mode, payment_method,
                payment_customer_visible_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version.offer_version_id,
                offer_id,
                version.version_number,
                version.created_at.isoformat(),
                version.valid_until.isoformat(),
                version.snapshot_id,
                version.snapshot_hash,
                version.event_date.isoformat(),
                version.time_window_text,
                version.location_text,
                version.guest_count,
                version.planning_mode,
                version.payment_method,
                version.payment_customer_visible_text,
            ),
        )
        for sort_order, variant in enumerate(version.variants):
            self._conn.execute(
                "INSERT INTO offer_variants VALUES (?, ?, ?, ?, ?)",
                (
                    variant.variant_id,
                    version.offer_version_id,
                    offer_id,
                    variant.label,
                    sort_order,
                ),
            )
            for position_order, position in enumerate(variant.positions):
                self._conn.execute(
                    """
                    INSERT INTO offer_positions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        position.position_id,
                        variant.variant_id,
                        version.offer_version_id,
                        position.kind,
                        position.name,
                        position.unit_net_cents,
                        position.net_total_cents,
                        position.vat_rate_percent,
                        position.vat_amount_cents,
                        position.gross_total_cents,
                        position.related_position_id,
                        position_order,
                    ),
                )

    def _insert_sent_evidence(self, evidence: SentEvidence) -> None:
        self._conn.execute(
            """
            INSERT INTO offer_sent_evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence.offer_version_id,
                evidence.offer_id,
                evidence.sent_at.isoformat(),
                evidence.recorded_at.isoformat(),
                evidence.channel,
                evidence.recipient_reference,
                evidence.evidence_reference,
                evidence.recorded_by,
            ),
        )

    def _insert_rejection_evidence(self, evidence: RejectionEvidence) -> None:
        self._conn.execute(
            """
            INSERT INTO offer_rejection_evidence VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                evidence.offer_version_id,
                evidence.offer_id,
                evidence.rejected_at.isoformat(),
                evidence.recorded_at.isoformat(),
                evidence.recorded_by,
                evidence.evidence_reference,
            ),
        )

    def _insert_withdrawal_evidence(self, evidence: WithdrawalEvidence) -> None:
        self._conn.execute(
            """
            INSERT INTO offer_withdrawal_evidence VALUES (?, ?, ?, ?, ?)
            """,
            (
                evidence.offer_version_id,
                evidence.offer_id,
                evidence.withdrawn_at.isoformat(),
                evidence.recorded_by,
                evidence.reason,
            ),
        )

    def _insert_acceptance_evidence(self, evidence: AcceptanceEvidence) -> None:
        self._conn.execute(
            """
            INSERT INTO offer_acceptance_evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence.acceptance_id,
                evidence.offer_id,
                evidence.accepted_offer_version_id,
                evidence.accepted_variant_id,
                evidence.accepted_at.isoformat(),
                evidence.recorded_at.isoformat(),
                evidence.channel,
                evidence.evidence_reference,
                evidence.recorded_by,
                evidence.note,
            ),
        )

    def _insert_conversion_link(self, link: ConversionLink) -> None:
        self._conn.execute(
            """
            INSERT INTO offer_conversion_links VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                link.offer_id,
                link.offer_version_id,
                link.variant_id,
                link.acceptance_id,
                link.order_id,
                link.created_at.isoformat(),
            ),
        )

    def _load_versions(self, offer_id: str) -> tuple[OfferVersion, ...]:
        version_rows = self._conn.execute(
            """
            SELECT offer_version_id, version_number, created_at, valid_until,
                   snapshot_id, snapshot_hash, event_date, time_window_text,
                   location_text, guest_count, planning_mode, payment_method,
                   payment_customer_visible_text
            FROM offer_versions
            WHERE offer_id = ?
            ORDER BY version_number
            """,
            (offer_id,),
        ).fetchall()
        variants_by_version = self._load_variants_by_version(offer_id)
        positions_by_variant = self._load_positions_by_variant(offer_id)
        versions: list[OfferVersion] = []
        for row in version_rows:
            version_id = row[0]
            if row[6] is None:
                raise ValueError(
                    f"offer_version_id {version_id!r} is missing persisted event facts"
                )
            variant_rows = variants_by_version.get(version_id, [])
            variants = tuple(
                OfferVariant(
                    variant_id=variant_row[0],
                    offer_version_id=version_id,
                    label=variant_row[1],
                    positions=positions_by_variant.get(variant_row[0], ()),
                )
                for variant_row in variant_rows
            )
            versions.append(
                OfferVersion(
                    offer_version_id=version_id,
                    offer_id=offer_id,
                    version_number=row[1],
                    created_at=_dt(row[2]),
                    valid_until=date.fromisoformat(row[3]),
                    snapshot_id=row[4],
                    snapshot_hash=row[5],
                    event_date=date.fromisoformat(row[6]),
                    time_window_text=row[7],
                    location_text=row[8],
                    guest_count=row[9],
                    planning_mode=validate_planning_mode(row[10]),
                    payment_method=validate_payment_method(row[11]),
                    payment_customer_visible_text=row[12],
                    variants=variants,
                )
            )
        return tuple(versions)

    def _load_variants_by_version(
        self, offer_id: str
    ) -> dict[str, list[tuple[str, str]]]:
        rows = self._conn.execute(
            """
            SELECT offer_version_id, variant_id, label
            FROM offer_variants
            WHERE offer_id = ?
            ORDER BY sort_order
            """,
            (offer_id,),
        ).fetchall()
        grouped: dict[str, list[tuple[str, str]]] = {}
        for version_id, variant_id, label in rows:
            grouped.setdefault(version_id, []).append((variant_id, label))
        return grouped

    def _load_positions_by_variant(
        self, offer_id: str
    ) -> dict[str, tuple[OfferPosition, ...]]:
        rows = self._conn.execute(
            """
            SELECT p.variant_id, p.position_id, p.kind, p.name, p.unit_net_cents,
                   p.net_total_cents, p.vat_rate_percent, p.vat_amount_cents,
                   p.gross_total_cents, p.related_position_id
            FROM offer_positions p
            JOIN offer_variants v ON v.variant_id = p.variant_id
            WHERE v.offer_id = ?
            ORDER BY p.sort_order
            """,
            (offer_id,),
        ).fetchall()
        grouped: dict[str, list[OfferPosition]] = {}
        for row in rows:
            grouped.setdefault(row[0], []).append(
                OfferPosition(
                    position_id=row[1],
                    kind=_position_kind(row[2]),
                    name=row[3],
                    unit_net_cents=row[4],
                    net_total_cents=row[5],
                    vat_rate_percent=_vat_rate(row[6]),
                    vat_amount_cents=row[7],
                    gross_total_cents=row[8],
                    related_position_id=row[9],
                )
            )
        return {
            variant_id: tuple(positions) for variant_id, positions in grouped.items()
        }

    def _load_sent_evidence(self, offer_id: str) -> tuple[SentEvidence, ...]:
        rows = self._conn.execute(
            """
            SELECT s.offer_version_id, s.sent_at, s.recorded_at, s.channel,
                   s.recipient_reference, s.evidence_reference, s.recorded_by
            FROM offer_sent_evidence s
            JOIN offer_versions v ON v.offer_version_id = s.offer_version_id
            WHERE s.offer_id = ?
            ORDER BY v.version_number
            """,
            (offer_id,),
        ).fetchall()
        return tuple(
            SentEvidence(
                offer_id=offer_id,
                offer_version_id=row[0],
                sent_at=_dt(row[1]),
                recorded_at=_dt(row[2]),
                channel=_sent_channel(row[3]),
                recipient_reference=row[4],
                evidence_reference=row[5],
                recorded_by=row[6],
            )
            for row in rows
        )

    def _load_rejection_evidence(self, offer_id: str) -> tuple[RejectionEvidence, ...]:
        rows = self._conn.execute(
            """
            SELECT r.offer_version_id, r.rejected_at, r.recorded_at, r.recorded_by,
                   r.evidence_reference
            FROM offer_rejection_evidence r
            JOIN offer_versions v ON v.offer_version_id = r.offer_version_id
            WHERE r.offer_id = ?
            ORDER BY v.version_number
            """,
            (offer_id,),
        ).fetchall()
        return tuple(
            RejectionEvidence(
                offer_id=offer_id,
                offer_version_id=row[0],
                rejected_at=_dt(row[1]),
                recorded_at=_dt(row[2]),
                recorded_by=row[3],
                evidence_reference=row[4],
            )
            for row in rows
        )

    def _load_withdrawal_evidence(
        self, offer_id: str
    ) -> tuple[WithdrawalEvidence, ...]:
        rows = self._conn.execute(
            """
            SELECT w.offer_version_id, w.withdrawn_at, w.recorded_by, w.reason
            FROM offer_withdrawal_evidence w
            JOIN offer_versions v ON v.offer_version_id = w.offer_version_id
            WHERE w.offer_id = ?
            ORDER BY v.version_number
            """,
            (offer_id,),
        ).fetchall()
        return tuple(
            WithdrawalEvidence(
                offer_id=offer_id,
                offer_version_id=row[0],
                withdrawn_at=_dt(row[1]),
                recorded_by=row[2],
                reason=row[3],
            )
            for row in rows
        )

    def _load_acceptance_evidence(self, offer_id: str) -> AcceptanceEvidence | None:
        row = self._conn.execute(
            """
            SELECT acceptance_id, accepted_offer_version_id, accepted_variant_id,
                   accepted_at, recorded_at, channel, evidence_reference,
                   recorded_by, note
            FROM offer_acceptance_evidence
            WHERE offer_id = ?
            """,
            (offer_id,),
        ).fetchone()
        if row is None:
            return None
        return AcceptanceEvidence(
            acceptance_id=row[0],
            offer_id=offer_id,
            accepted_offer_version_id=row[1],
            accepted_variant_id=row[2],
            accepted_at=_dt(row[3]),
            recorded_at=_dt(row[4]),
            channel=_acceptance_channel(row[5]),
            evidence_reference=row[6],
            recorded_by=row[7],
            note=row[8],
        )

    def _load_conversion_link(self, offer_id: str) -> ConversionLink | None:
        row = self._conn.execute(
            """
            SELECT offer_version_id, variant_id, acceptance_id, order_id, created_at
            FROM offer_conversion_links
            WHERE offer_id = ?
            """,
            (offer_id,),
        ).fetchone()
        if row is None:
            return None
        return ConversionLink(
            offer_id=offer_id,
            offer_version_id=row[0],
            variant_id=row[1],
            acceptance_id=row[2],
            order_id=row[3],
            created_at=_dt(row[4]),
        )
