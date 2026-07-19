"""Catalog Stammdaten — dish master data (6D-1 read model)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

AllergenCode = Literal[
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "G",
    "H",
    "I",
    "J",
    "K",
    "L",
    "M",
    "N",
]

ALLERGEN_CODES: tuple[AllergenCode, ...] = (
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "G",
    "H",
    "I",
    "J",
    "K",
    "L",
    "M",
    "N",
)

ALLERGEN_LABELS: dict[AllergenCode, str] = {
    "A": "Gluten",
    "B": "Krebstiere",
    "C": "Eier",
    "D": "Fisch",
    "E": "Erdnüsse",
    "F": "Soja",
    "G": "Milch",
    "H": "Schalenfrüchte",
    "I": "Sellerie",
    "J": "Senf",
    "K": "Sesam",
    "L": "Schwefeldioxid/Sulfite",
    "M": "Lupinen",
    "N": "Weichtiere",
}

_MAX_NAME_LEN = 500
_MAX_TEXT_LEN = 20_000
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _require_uuid(value: str, field: str) -> None:
    if not _UUID_RE.match(value):
        raise ValueError(f"{field} must be a UUID")
    uuid.UUID(value)


def validate_allergen_codes(
    codes: tuple[str, ...] | list[str],
) -> tuple[AllergenCode, ...]:
    normalized: list[AllergenCode] = []
    seen: set[str] = set()
    for raw in codes:
        code = raw.strip().upper()
        if code not in ALLERGEN_LABELS:
            raise ValueError(f"unknown allergen code {raw!r}")
        if code in seen:
            continue
        seen.add(code)
        normalized.append(code)
    return tuple(normalized)


def allergen_labels(codes: tuple[AllergenCode, ...]) -> tuple[str, ...]:
    return tuple(ALLERGEN_LABELS[code] for code in codes)


@dataclass(frozen=True)
class CatalogDish:
    dish_id: str
    name: str
    description: str | None
    composition: str | None
    notes: str | None
    current_unit_net_cents: int
    allergens: tuple[AllergenCode, ...]
    active: bool
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _require_uuid(self.dish_id, "dish_id")
        if not self.name.strip():
            raise ValueError("name is required")
        if len(self.name) > _MAX_NAME_LEN:
            raise ValueError("name exceeds length limit")
        for field_name, value in (
            ("description", self.description),
            ("composition", self.composition),
            ("notes", self.notes),
        ):
            if value is not None and len(value) > _MAX_TEXT_LEN:
                raise ValueError(f"{field_name} exceeds length limit")
        if self.current_unit_net_cents < 0:
            raise ValueError("current_unit_net_cents must be non-negative")
        object.__setattr__(self, "allergens", validate_allergen_codes(self.allergens))
        _require_aware(self.created_at, "created_at")
        _require_aware(self.updated_at, "updated_at")


@dataclass(frozen=True)
class CatalogPriceHistoryEntry:
    entry_id: str
    dish_id: str
    old_unit_net_cents: int | None
    new_unit_net_cents: int
    changed_at: datetime
    changed_by: str
    effective_from: date | None

    def __post_init__(self) -> None:
        _require_uuid(self.entry_id, "entry_id")
        _require_uuid(self.dish_id, "dish_id")
        if self.old_unit_net_cents is not None and self.old_unit_net_cents < 0:
            raise ValueError("old_unit_net_cents must be non-negative")
        if self.new_unit_net_cents < 0:
            raise ValueError("new_unit_net_cents must be non-negative")
        if not self.changed_by.strip():
            raise ValueError("changed_by is required")
        _require_aware(self.changed_at, "changed_at")


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


class CatalogDishNotFoundError(LookupError):
    """Raised when a catalog dish id does not exist."""


class CatalogDishStaleError(ValueError):
    """Raised when optimistic concurrency on updated_at fails."""


@dataclass(frozen=True)
class CatalogDishUpdatePayload:
    name: str
    description: str | None
    composition: str | None
    notes: str | None
    current_unit_net_cents: int
    allergens: tuple[AllergenCode, ...]
    active: bool
    effective_from: date | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name is required")
        if len(self.name) > _MAX_NAME_LEN:
            raise ValueError("name exceeds length limit")
        for field_name, value in (
            ("description", self.description),
            ("composition", self.composition),
            ("notes", self.notes),
        ):
            if value is not None and len(value) > _MAX_TEXT_LEN:
                raise ValueError(f"{field_name} exceeds length limit")
        if self.current_unit_net_cents < 0:
            raise ValueError("current_unit_net_cents must be non-negative")
        object.__setattr__(self, "allergens", validate_allergen_codes(self.allergens))


@dataclass(frozen=True)
class CatalogDishUpdateResult:
    dish: CatalogDish
    price_changed: bool
    price_history_entry_id: str | None
