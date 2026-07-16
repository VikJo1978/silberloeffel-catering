"""SQLite catalog repository tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from catering_system.domain.catalog import CatalogDish
from catering_system.repositories.sqlite_catalog_repository import SQLiteCatalogRepository

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
