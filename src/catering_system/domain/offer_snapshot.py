"""OfferSnapshot V1 — validated transport shape and canonical content hash."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Literal

from catering_system.domain.inquiry import PlanningMode
from catering_system.domain.logistics_timing import validate_optional_service_window
from catering_system.domain.offer_budget_definition import OfferBudgetDefinition
from catering_system.domain.offer_charges import OfferChargesDefinition
from catering_system.domain.order_payment_reminder import PaymentMethod

SCHEMA_VERSION = "offer_snapshot_v1"
SCHEMA_VERSION_V2 = "offer_snapshot_v2"
SOURCE = "fingerfood-configurator-backend"
CURRENCY = "EUR"

MAX_PAYLOAD_BYTES = 256 * 1024
MIN_VARIANTS = 1
MAX_VARIANTS = 5
MIN_POSITIONS_PER_VARIANT = 1
MAX_POSITIONS_PER_VARIANT = 100

MAX_EMAIL_LEN = 320
MAX_SHORT_TEXT_LEN = 500
MAX_LONG_TEXT_LEN = 20_000

SnapshotPositionKind = Literal[
    "catalog", "surcharge", "fee", "custom", "delivery", "dishware", "buffet_fee"
]
SnapshotQuantityMode = Literal["total", "per_person"]

# CONFIGURABLE_OFFER_CHARGES_V1: "delivery"/"dishware"/"buffet_fee" are new,
# explicit kinds; legacy "fee" positions keep working unchanged (see
# domain/offer.py PositionKind for the full rationale).
_POSITION_KINDS: frozenset[str] = frozenset(
    {"catalog", "surcharge", "fee", "custom", "delivery", "dishware", "buffet_fee"}
)
_QUANTITY_MODES: frozenset[str] = frozenset({"total", "per_person"})
_VAT_RATES: frozenset[int] = frozenset({7, 19})
_QUANTITY_RE = re.compile(r"^(?:0|[1-9]\d*)(?:\.\d{1,3})?\Z")
_SNAPSHOT_HASH_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class OfferSnapshotRecipient:
    company_name: str
    contact_name: str
    email: str
    postal_address: str


@dataclass(frozen=True)
class OfferSnapshotEvent:
    event_date: date
    time_window_text: str
    location_text: str
    guest_count: int | None
    planning_mode: PlanningMode
    # Legacy V3 logistics window fields remain readable for historical snapshots.
    delivery_date_local: date | None = None
    delivery_window_start_local: time | None = None
    delivery_window_end_local: time | None = None
    event_start_local: time | None = None
    delivery_time_local: time | None = None

    def __post_init__(self) -> None:
        validate_optional_service_window(
            self.delivery_date_local,
            self.delivery_window_start_local,
            self.delivery_window_end_local,
            label="delivery window",
        )


@dataclass(frozen=True)
class OfferSnapshotCustomerText:
    title: str
    introduction: str
    notes: str


@dataclass(frozen=True)
class OfferSnapshotPaymentTerms:
    method: PaymentMethod
    customer_visible_text: str


@dataclass(frozen=True)
class OfferSnapshotCalculator:
    name: str
    calculator_revision: str
    catalog_revision: str
    tax_revision: str


@dataclass(frozen=True)
class OfferSnapshotPosition:
    position_id: str
    kind: SnapshotPositionKind
    name: str
    quantity_mode: SnapshotQuantityMode
    quantity: str
    unit_label: str
    unit_net_cents: int
    net_total_cents: int
    vat_rate_percent: Literal[7, 19]
    vat_amount_cents: int
    gross_total_cents: int
    catalog_item_id: str | None = None
    description: str | None = None
    composition: str | None = None
    notes: str | None = None
    related_position_id: str | None = None
    allergens: tuple[str, ...] | None = None
    vegan: bool | None = None
    vegetarian: bool | None = None


@dataclass(frozen=True)
class OfferSnapshotVariantTotals:
    net_cents: int
    vat_7_base_cents: int
    vat_7_amount_cents: int
    vat_19_base_cents: int
    vat_19_amount_cents: int
    gross_cents: int


@dataclass(frozen=True)
class OfferSnapshotVariant:
    variant_id: str
    label: str
    description: str
    positions: tuple[OfferSnapshotPosition, ...]
    totals: OfferSnapshotVariantTotals


@dataclass(frozen=True)
class OfferSnapshotEnvelope:
    """Shared validated OfferSnapshot envelope (V1 or V2)."""

    schema_version: str
    source: str
    inquiry_id: str
    snapshot_id: str
    snapshot_hash: str
    snapshot_created_at: datetime
    valid_until: date
    currency: str
    recipient: OfferSnapshotRecipient
    event: OfferSnapshotEvent
    customer_text: OfferSnapshotCustomerText
    payment_terms: OfferSnapshotPaymentTerms
    calculator: OfferSnapshotCalculator
    variants: tuple[OfferSnapshotVariant, ...]
    source_draft_id: str | None = None
    # OFFER_BUDGET_DEFINITION_V1: optional internal-only operator planning
    # metadata — never customer-facing (see domain/offer_budget_definition.py).
    budget_definition: OfferBudgetDefinition | None = None
    # CONFIGURABLE_OFFER_CHARGES_V1: optional structured delivery/dishware/
    # buffet definition (see domain/offer_charges.py). Absent means legacy —
    # the snapshot's positions (historically kind="fee") are trusted as-is,
    # never reinterpreted from this field.
    charges_definition: OfferChargesDefinition | None = None


@dataclass(frozen=True)
class OfferSnapshotV1(OfferSnapshotEnvelope):
    """Validated OfferSnapshot V1 envelope ready for OfferVersion mapping."""


@dataclass(frozen=True)
class OfferSnapshotV2(OfferSnapshotEnvelope):
    """Validated OfferSnapshot V2 envelope with catalog allergen facts."""


def canonical_snapshot_json(value: object) -> str:
    """Serialize JSON data using RFC 8785-style deterministic rules."""
    return _serialize_json_value(value)


def compute_snapshot_hash(payload: dict[str, object]) -> str:
    """Hash the snapshot envelope with ``snapshot_hash`` omitted."""
    body = {key: value for key, value in payload.items() if key != "snapshot_hash"}
    canonical = canonical_snapshot_json(body)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def snapshot_hash_matches(payload: dict[str, object]) -> bool:
    declared = payload.get("snapshot_hash")
    if not isinstance(declared, str) or not _SNAPSHOT_HASH_RE.fullmatch(declared):
        return False
    return declared == compute_snapshot_hash(payload)


def _serialize_json_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        raise ValueError("floating-point values are forbidden")
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join(_serialize_json_value(item) for item in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        parts = [
            json.dumps(key, ensure_ascii=False)
            + ":"
            + _serialize_json_value(value[key])
            for key in sorted(value)
        ]
        return "{" + ",".join(parts) + "}"
    raise ValueError(f"unsupported JSON value type: {type(value)!r}")


__all__ = [
    "CURRENCY",
    "MAX_PAYLOAD_BYTES",
    "MAX_POSITIONS_PER_VARIANT",
    "MAX_VARIANTS",
    "MIN_POSITIONS_PER_VARIANT",
    "MIN_VARIANTS",
    "OfferSnapshotCalculator",
    "OfferSnapshotCustomerText",
    "OfferSnapshotEvent",
    "OfferSnapshotPaymentTerms",
    "OfferSnapshotPosition",
    "OfferSnapshotRecipient",
    "OfferSnapshotV1",
    "OfferSnapshotV2",
    "OfferSnapshotVariant",
    "OfferSnapshotVariantTotals",
    "SCHEMA_VERSION",
    "SCHEMA_VERSION_V2",
    "SOURCE",
    "canonical_snapshot_json",
    "compute_snapshot_hash",
    "snapshot_hash_matches",
]
