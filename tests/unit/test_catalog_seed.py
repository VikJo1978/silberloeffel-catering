"""Seed script tests for catalog import."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from catering_system.repositories.sqlite_catalog_repository import SQLiteCatalogRepository

_DISH_ID = "catalog-schnitzel-1"


def _load_seed_module():
    root = Path(__file__).resolve().parents[2]
    path = root / "scripts" / "seed_catalog_from_items.py"
    spec = importlib.util.spec_from_file_location("seed_catalog_from_items", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_import_idempotent(tmp_path: Path) -> None:
    seed_catalog = _load_seed_module().seed_catalog
    db = tmp_path / "core.db"
    items = tmp_path / "items.json"
    items.write_text(
        json.dumps(
            [
                {
                    "id": _DISH_ID,
                    "name": "Schnitzel",
                    "description": "Paniert",
                    "composition": "Schwein",
                    "price": "8.50",
                    "allergens": ["A", "C", "G"],
                    "active": True,
                }
            ]
        ),
        encoding="utf-8",
    )

    inserted, skipped = seed_catalog(db, items)
    assert inserted == 1
    assert skipped == 0

    inserted_again, skipped_again = seed_catalog(db, items)
    assert inserted_again == 0
    assert skipped_again == 1

    repo = SQLiteCatalogRepository(db)
    try:
        dish = repo.get_dish(repo.list_dishes()[0].dish_id)
        assert dish is not None
        assert dish.name == "Schnitzel"
        assert dish.current_unit_net_cents == 850
        assert repo.list_price_history(dish.dish_id) == []
    finally:
        repo.close()
