"""SQLite catalog repository tests."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from catering_system.domain.catalog import CatalogDish
from catering_system.repositories.sqlite_catalog_repository import (
    SQLiteCatalogRepository,
)

_NOW = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
_DISH_ID = "11111111-1111-4111-8111-111111111111"


def _dish(
    *,
    dish_id: str = _DISH_ID,
    name: str = "Schnitzel",
    active: bool = True,
) -> CatalogDish:
    return CatalogDish(
        dish_id=dish_id,
        name=name,
        description="Beschreibung",
        composition="Zusammensetzung",
        notes=None,
        current_unit_net_cents=850,
        allergens=("A", "C", "G"),
        active=active,
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_sqlite_catalog_read_roundtrip(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    repo = SQLiteCatalogRepository(db)
    try:
        assert repo.insert_dish_if_absent(_dish()) is True
        assert repo.insert_dish_if_absent(_dish()) is False
        loaded = repo.get_dish(_DISH_ID)
        assert loaded == _dish()
        assert repo.count_dishes() == 1
        rows = repo.list_dishes()
        assert len(rows) == 1
        assert rows[0].name == "Schnitzel"
    finally:
        repo.close()


def test_sqlite_catalog_price_history_empty_by_default(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    repo = SQLiteCatalogRepository(db)
    try:
        repo.insert_dish_if_absent(_dish())
        assert repo.list_price_history(_DISH_ID) == []
    finally:
        repo.close()


def test_sqlite_catalog_active_only_filter(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    repo = SQLiteCatalogRepository(db)
    try:
        repo.insert_dish_if_absent(_dish())
        inactive_id = "22222222-2222-4222-8222-222222222222"
        repo.insert_dish_if_absent(
            _dish(dish_id=inactive_id, name="Inaktiv", active=False)
        )
        active_rows = repo.list_dishes(active_only=True)
        assert [row.dish_id for row in active_rows] == [_DISH_ID]
    finally:
        repo.close()


def test_sqlite_catalog_update_and_price_history(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    repo = SQLiteCatalogRepository(db)
    later = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    try:
        repo.insert_dish_if_absent(_dish())
        updated = CatalogDish(
            dish_id=_DISH_ID,
            name="Schnitzel",
            description="Neu",
            composition="mit Rosmarinkartoffeln",
            notes=None,
            current_unit_net_cents=900,
            allergens=("A", "G"),
            active=True,
            created_at=_NOW,
            updated_at=later,
        )
        from catering_system.domain.catalog import CatalogPriceHistoryEntry

        repo.update_dish(
            updated,
            expected_updated_at=_NOW,
            price_history_entry=CatalogPriceHistoryEntry(
                entry_id="99999999-9999-4999-8999-999999999999",
                dish_id=_DISH_ID,
                old_unit_net_cents=850,
                new_unit_net_cents=900,
                changed_at=later,
                changed_by="office",
                effective_from=date(2026, 8, 1),
            ),
        )
        loaded = repo.get_dish(_DISH_ID)
        assert loaded is not None
        assert loaded.current_unit_net_cents == 900
        history = repo.list_price_history(_DISH_ID)
        assert len(history) == 1
        assert history[0].new_unit_net_cents == 900
    finally:
        repo.close()


# --- CATALOG_ADMIN_COMPLETION_V1A -------------------------------------------


def test_sqlite_catalog_create_read_list_roundtrip_with_new_fields(
    tmp_path: Path,
) -> None:
    db = tmp_path / "core.db"
    repo = SQLiteCatalogRepository(db)
    try:
        dish = CatalogDish(
            dish_id=_DISH_ID,
            name="Lachs-Canape",
            description="Frisch",
            composition="Lachs, Brot",
            notes=None,
            current_unit_net_cents=250,
            allergens=("D",),
            active=False,
            created_at=_NOW,
            updated_at=_NOW,
            category="fingerfood",
            pricing_unit="stueck",
            vat_rate_percent=7,
        )
        assert repo.insert_dish_if_absent(dish) is True
        fetched = repo.get_dish(_DISH_ID)
        assert fetched == dish
        listed = repo.list_dishes()
        assert len(listed) == 1
        assert listed[0] == dish
    finally:
        repo.close()


def test_sqlite_catalog_duplicate_dish_id_rejected_with_new_fields(
    tmp_path: Path,
) -> None:
    db = tmp_path / "core.db"
    repo = SQLiteCatalogRepository(db)
    try:
        dish = CatalogDish(
            dish_id=_DISH_ID,
            name="Lachs-Canape",
            description=None,
            composition=None,
            notes=None,
            current_unit_net_cents=250,
            allergens=(),
            active=False,
            created_at=_NOW,
            updated_at=_NOW,
            category="fingerfood",
            pricing_unit="stueck",
            vat_rate_percent=7,
        )
        assert repo.insert_dish_if_absent(dish) is True
        assert repo.insert_dish_if_absent(dish) is False
        assert repo.count_dishes() == 1
    finally:
        repo.close()


def _build_legacy_v1_db(db: Path, *, dish_id: str = _DISH_ID) -> None:
    """Builds a database that only ever saw migration 1 (pre
    CATALOG_ADMIN_COMPLETION_V1A) with one legacy row inserted directly
    against the old schema — no category/pricing_unit/vat_rate_percent
    columns exist yet."""
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE catalog_dishes (
            dish_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            composition TEXT,
            notes TEXT,
            current_unit_net_cents INTEGER NOT NULL,
            allergens_json TEXT NOT NULL,
            active INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE catalog_price_history (
            entry_id TEXT PRIMARY KEY,
            dish_id TEXT NOT NULL,
            old_unit_net_cents INTEGER,
            new_unit_net_cents INTEGER NOT NULL,
            changed_at TEXT NOT NULL,
            changed_by TEXT NOT NULL,
            effective_from TEXT,
            FOREIGN KEY (dish_id) REFERENCES catalog_dishes (dish_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE schema_migrations (
            component TEXT NOT NULL,
            version INTEGER NOT NULL,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            PRIMARY KEY (component, version)
        )
        """
    )
    conn.execute(
        "INSERT INTO schema_migrations (component, version, name, applied_at) "
        "VALUES ('catalog', 1, 'catalog_dishes_v1', '2026-01-01T00:00:00Z')"
    )
    conn.execute(
        """
        INSERT INTO catalog_dishes (
            dish_id, name, description, composition, notes,
            current_unit_net_cents, allergens_json, active,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            dish_id,
            "Legacy Schnitzel",
            "Alt",
            None,
            None,
            850,
            "[]",
            1,
            _NOW.isoformat(),
            _NOW.isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def test_sqlite_catalog_migration_preserves_legacy_row_and_adds_new_columns(
    tmp_path: Path,
) -> None:
    """Simulates a database that only ever saw migration 1 (pre this slice):
    a legacy row inserted directly against the old schema must still be
    readable — with NULL new fields, no fictitious backfill — once the
    repository (and therefore migration 2) runs against it."""
    db = tmp_path / "core.db"
    _build_legacy_v1_db(db)

    repo = SQLiteCatalogRepository(db)
    try:
        legacy = repo.get_dish(_DISH_ID)
        assert legacy is not None
        assert legacy.name == "Legacy Schnitzel"
        assert legacy.category is None
        assert legacy.pricing_unit is None
        assert legacy.vat_rate_percent is None

        new_id = "22222222-2222-4222-8222-222222222222"
        new_dish = CatalogDish(
            dish_id=new_id,
            name="Neues Gericht",
            description=None,
            composition=None,
            notes=None,
            current_unit_net_cents=300,
            allergens=(),
            active=False,
            created_at=_NOW,
            updated_at=_NOW,
            category="fingerfood",
            pricing_unit="pauschal",
            vat_rate_percent=19,
        )
        assert repo.insert_dish_if_absent(new_dish) is True
        fetched_new = repo.get_dish(new_id)
        assert fetched_new == new_dish
        assert repo.count_dishes() == 2
    finally:
        repo.close()

    verify_conn = sqlite3.connect(str(db))
    try:
        versions = {
            row[0]
            for row in verify_conn.execute(
                "SELECT version FROM schema_migrations WHERE component = 'catalog'"
            ).fetchall()
        }
        assert versions == {1, 2}
    finally:
        verify_conn.close()


def test_sqlite_catalog_migration_v2_idempotent_on_repeated_open(
    tmp_path: Path,
) -> None:
    """CATALOG_ADMIN_COMPLETION_V1A review fix: migration v2 must not be
    reapplied (and must not error, e.g. via a duplicate-column ALTER TABLE)
    the second time a process opens an already-migrated database — the
    normal shape of a service restart."""
    db = tmp_path / "core.db"
    _build_legacy_v1_db(db)

    first_open = SQLiteCatalogRepository(db)
    first_open.close()

    second_open = SQLiteCatalogRepository(db)
    try:
        legacy = second_open.get_dish(_DISH_ID)
        assert legacy is not None
        assert legacy.name == "Legacy Schnitzel"
        assert legacy.category is None
        assert legacy.pricing_unit is None
        assert legacy.vat_rate_percent is None
        assert second_open.count_dishes() == 1
    finally:
        second_open.close()

    # A third open, to be sure it's not just "twice happens to work".
    third_open = SQLiteCatalogRepository(db)
    try:
        assert third_open.count_dishes() == 1
    finally:
        third_open.close()

    verify_conn = sqlite3.connect(str(db))
    try:
        versions = {
            row[0]
            for row in verify_conn.execute(
                "SELECT version FROM schema_migrations WHERE component = 'catalog'"
            ).fetchall()
        }
        assert versions == {1, 2}
        columns = {
            row[1]
            for row in verify_conn.execute(
                "PRAGMA table_info(catalog_dishes)"
            ).fetchall()
        }
        assert {"category", "pricing_unit", "vat_rate_percent"} <= columns
    finally:
        verify_conn.close()
