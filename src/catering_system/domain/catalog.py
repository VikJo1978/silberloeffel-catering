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

PricingUnit = Literal["per_person", "stueck", "pauschal"]

PRICING_UNITS: tuple[PricingUnit, ...] = ("per_person", "stueck", "pauschal")

# CATALOG_ADMIN_COMPLETION_V1A: intentionally re-declared, not imported from
# domain/offer.py — offer.py's VatRatePercent is authoritative for a frozen
# OfferPosition; this one is only ever a catalog *default/suggestion*
# (decision #1) and importing from offer.py would create a domain import
# cycle (offer.py never depends on catalog.py). Values are kept in sync by
# convention (German catering VAT: reduced 7% / standard 19%), not by import.
_CATALOG_VAT_RATES_PERCENT: tuple[int, ...] = (7, 19)

_MAX_NAME_LEN = 500
_MAX_TEXT_LEN = 20_000
_MAX_CATEGORY_LEN = 200
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
# CATALOG_ADMIN_COMPLETION_V1A review fix: lowercase ASCII segments of
# a-z0-9 joined by single hyphen/underscore separators — first and last
# character must be alphanumeric, so leading/trailing/doubled separators
# are rejected (e.g. "-dessert", "dessert-", "food--hot" all fail).
_CATEGORY_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")


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


def validate_pricing_unit(value: str) -> PricingUnit:
    if value not in PRICING_UNITS:
        raise ValueError("pricing_unit must be one of: " + ", ".join(PRICING_UNITS))
    return value


def validate_catalog_vat_rate_percent(value: int) -> int:
    if value not in _CATALOG_VAT_RATES_PERCENT:
        raise ValueError(
            "vat_rate_percent must be one of: "
            + ", ".join(str(rate) for rate in _CATALOG_VAT_RATES_PERCENT)
        )
    return value


def validate_category(value: str) -> str:
    """Stable ASCII key (decision #6), not a display label: lowercase a-z0-9
    segments joined by single hyphen/underscore separators — matches
    ``[a-z0-9]+(?:[-_][a-z0-9]+)*``, e.g. "fingerfood", "service-personal",
    "warme_speisen". No closed set/table (grouping is by exact key match),
    but the key format itself is closed. Leading/trailing whitespace is
    trimmed before validation; nothing else is silently transformed — an
    invalid key (uppercase, spaces, non-ASCII, leading/trailing/doubled
    separators, empty) is rejected, never coerced into a valid one."""
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("category is required")
    if len(trimmed) > _MAX_CATEGORY_LEN:
        raise ValueError("category exceeds length limit")
    if not _CATEGORY_RE.match(trimmed):
        raise ValueError(
            "category must be a lowercase key matching "
            "[a-z0-9]+(?:[-_][a-z0-9]+)* (e.g. 'fingerfood', 'service-personal')"
        )
    return trimmed


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
    # CATALOG_ADMIN_COMPLETION_V1A: NULL for legacy rows created before this
    # slice (decision #2) — no fictitious backfill (decision #3). Required
    # only at *creation* time (decision #4), enforced by
    # CatalogDishCreatePayload, not here: this dataclass also represents
    # existing legacy dishes read straight from storage, which must keep
    # loading with these unset.
    category: str | None = None
    pricing_unit: PricingUnit | None = None
    vat_rate_percent: int | None = None

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
        if self.category is not None:
            object.__setattr__(self, "category", validate_category(self.category))
        if self.pricing_unit is not None:
            object.__setattr__(
                self, "pricing_unit", validate_pricing_unit(self.pricing_unit)
            )
        if self.vat_rate_percent is not None:
            object.__setattr__(
                self,
                "vat_rate_percent",
                validate_catalog_vat_rate_percent(self.vat_rate_percent),
            )


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


class CatalogDishAlreadyExistsError(ValueError):
    """Raised when a dish_id already exists (insert_dish_if_absent contract)."""


@dataclass(frozen=True)
class CatalogDishCreatePayload:
    """CATALOG_ADMIN_COMPLETION_V1A: creating a new dish requires the fields
    legacy rows are allowed to omit (decision #4) — name, category,
    pricing_unit, current_unit_net_cents, vat_rate_percent are all required
    here, unlike on CatalogDish itself where they stay optional for legacy
    reads (decision #2/#3)."""

    name: str
    category: str
    pricing_unit: PricingUnit
    current_unit_net_cents: int
    vat_rate_percent: int
    description: str | None = None
    composition: str | None = None
    notes: str | None = None
    allergens: tuple[AllergenCode, ...] = ()

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
        object.__setattr__(self, "category", validate_category(self.category))
        object.__setattr__(
            self, "pricing_unit", validate_pricing_unit(self.pricing_unit)
        )
        object.__setattr__(
            self,
            "vat_rate_percent",
            validate_catalog_vat_rate_percent(self.vat_rate_percent),
        )
        object.__setattr__(self, "allergens", validate_allergen_codes(self.allergens))


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
