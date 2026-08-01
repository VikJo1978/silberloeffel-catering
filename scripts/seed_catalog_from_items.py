#!/usr/bin/env python3
"""One-time seed: import configurator items.json into Core catalog_dishes.

Rules (6D-1):
- Skip rows whose dish_id already exists (never update).
- Do not write catalog_price_history rows.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from catering_system.domain.catalog import CatalogDish, validate_allergen_codes
from catering_system.repositories.sqlite_catalog_repository import SQLiteCatalogRepository

_CATALOG_NAMESPACE = uuid.UUID("6d1c0000-0000-4000-8000-000000000001")
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# Configurator items.json legacy allergen tokens → EU codes A–N.
LEGACY_ALLERGEN_MAP: dict[str, str] = {
    "gluten": "A",
    "crustaceans": "B",
    "egg": "C",
    "fish": "D",
    "peanuts": "E",
    "soy": "F",
    "milk": "G",
    "nuts": "H",
    "celery": "I",
    "mustard": "J",
    "sesame": "K",
    "sulfites": "L",
    "lupin": "M",
    "molluscs": "N",
}


def _dish_id_from_source(source_id: str) -> str:
    if _UUID_RE.match(source_id):
        return source_id
    return str(uuid.uuid5(_CATALOG_NAMESPACE, source_id))


def _normalize_legacy_allergen_token(token: str) -> str:
    text = token.strip()
    if not text:
        raise ValueError("allergen token must not be empty")
    upper = text.upper()
    if len(upper) == 1 and upper in LEGACY_ALLERGEN_MAP.values():
        return upper
    mapped = LEGACY_ALLERGEN_MAP.get(text.lower())
    if mapped is not None:
        return mapped
    return upper


def _normalize_legacy_allergens(tokens: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        code = _normalize_legacy_allergen_token(token)
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def _parse_allergens(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        parts = [part.strip() for part in raw.replace(",", " ").split() if part.strip()]
        return validate_allergen_codes(_normalize_legacy_allergens(parts))
    if isinstance(raw, list):
        return validate_allergen_codes(
            _normalize_legacy_allergens([str(item) for item in raw])
        )
    raise ValueError(f"unsupported allergens value: {raw!r}")


def _price_to_cents(raw: object) -> int:
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(round(raw * 100))
    if isinstance(raw, str):
        text = raw.strip().replace(",", ".")
        if text.endswith("€"):
            text = text[:-1].strip()
        value = Decimal(text)
        return int((value * 100).quantize(Decimal("1")))
    raise ValueError(f"unsupported price value: {raw!r}")


def _load_items(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise ValueError("items.json object must contain an 'items' list")
        items = raw_items
    else:
        raise ValueError("items.json must be a list or object")
    result: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each item must be an object")
        result.append(item)
    return result


def _map_item(item: dict[str, object], *, now: datetime) -> CatalogDish:
    source_id = str(
        item.get("dish_id")
        or item.get("id")
        or item.get("catalog_item_id")
        or item.get("sku")
        or ""
    ).strip()
    if not source_id:
        raise ValueError(f"item missing id: {item!r}")
    name = str(item.get("name") or "").strip()
    if not name:
        raise ValueError(f"item {source_id!r} missing name")
    price_raw = (
        item.get("current_unit_net_cents")
        if item.get("current_unit_net_cents") is not None
        else item.get("unit_net_cents", item.get("price"))
    )
    if price_raw is None:
        raise ValueError(f"item {source_id!r} missing price")
    try:
        cents = _price_to_cents(price_raw)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"item {source_id!r} invalid price") from exc
    active_raw = item.get("active", True)
    if not isinstance(active_raw, bool):
        raise ValueError(f"item {source_id!r} active must be boolean")
    return CatalogDish(
        dish_id=_dish_id_from_source(source_id),
        name=name,
        description=_optional_str(item.get("description")),
        composition=_optional_str(
            item.get("composition", item.get("ingredients"))
        ),
        notes=_optional_str(item.get("notes")),
        current_unit_net_cents=cents,
        allergens=_parse_allergens(item.get("allergens")),
        active=active_raw,
        created_at=now,
        updated_at=now,
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def seed_catalog(db_path: Path, items_path: Path) -> tuple[int, int]:
    repo = SQLiteCatalogRepository(db_path)
    try:
        now = datetime.now(tz=UTC)
        inserted = 0
        skipped = 0
        for item in _load_items(items_path):
            dish = _map_item(item, now=now)
            if repo.insert_dish_if_absent(dish):
                inserted += 1
            else:
                skipped += 1
        return inserted, skipped
    finally:
        repo.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Path to core.db")
    parser.add_argument("--items", required=True, help="Path to items.json")
    args = parser.parse_args(argv)
    db_path = Path(args.db)
    items_path = Path(args.items)
    if not db_path.exists():
        print(f"database not found: {db_path}", file=sys.stderr)
        return 1
    if not items_path.exists():
        print(f"items file not found: {items_path}", file=sys.stderr)
        return 1
    try:
        inserted, skipped = seed_catalog(db_path, items_path)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"seed failed: {exc}", file=sys.stderr)
        return 1
    print(f"catalog seed complete: inserted={inserted} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
