"""Append-only commercial snapshot frozen at Accepted Offer → Order conversion.

Operational consumers (print/confirmation/PDF) must read this aggregate, not
live Offer data. Event facts stay on OrderVersion; Offer lifecycle stays on Offer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from catering_system.domain.catalog import AllergenCode, validate_allergen_codes
from catering_system.domain.offer import (
    POSITION_KINDS,
    POSITION_QUANTITY_MODES,
    VAT_RATES,
    AcceptanceEvidence,
    Offer,
    OfferPosition,
    OfferVariant,
    OfferVersion,
    PositionKind,
    PositionQuantityMode,
    VatRatePercent,
)
from catering_system.domain.offer_charges import ReturnLogisticsDefinition
from catering_system.domain.order_payment_reminder import (
    PaymentMethod,
    validate_payment_method,
)

_MAX_TEXT = 20_000
_MAX_LABEL = 500


class MissingCommercialSnapshotError(LookupError):
    """Order has no OrderCommercialSnapshot; operational consumers must not proceed."""

    def __init__(self, order_id: str) -> None:
        self.order_id = order_id
        super().__init__(f"order commercial snapshot missing (order_id={order_id!r})")


def _require_text(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} is required")


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _require_non_negative_cents(value: int, field: str) -> None:
    if value < 0:
        raise ValueError(f"{field} must be non-negative")


def _optional_bounded_text(value: str | None, field: str, *, max_len: int) -> None:
    if value is None:
        return
    _require_text(value, field)
    if len(value) > max_len:
        raise ValueError(f"{field} exceeds length limit")


def _validate_optional_quantity(value: Decimal | None) -> None:
    if value is None:
        return
    if value < 0:
        raise ValueError("quantity must be non-negative")
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -3:
        raise ValueError("quantity exceeds fractional precision")


@dataclass(frozen=True)
class OrderCommercialPosition:
    """Frozen menu/money line from the accepted OfferVariant."""

    position_id: str
    kind: PositionKind
    name: str
    unit_net_cents: int
    net_total_cents: int
    vat_rate_percent: VatRatePercent
    vat_amount_cents: int
    gross_total_cents: int
    related_position_id: str | None = None
    description: str | None = None
    composition: str | None = None
    notes: str | None = None
    quantity: Decimal | None = None
    quantity_mode: PositionQuantityMode | None = None
    unit_label: str | None = None
    catalog_item_id: str | None = None
    allergens: tuple[AllergenCode, ...] | None = None

    def __post_init__(self) -> None:
        _require_text(self.position_id, "position_id")
        _require_text(self.name, "name")
        if self.kind not in POSITION_KINDS:
            raise ValueError("invalid position kind")
        if self.vat_rate_percent not in VAT_RATES:
            raise ValueError("vat_rate_percent must be 7 or 19")
        for field, value in (
            ("unit_net_cents", self.unit_net_cents),
            ("net_total_cents", self.net_total_cents),
            ("vat_amount_cents", self.vat_amount_cents),
            ("gross_total_cents", self.gross_total_cents),
        ):
            _require_non_negative_cents(value, field)
        _optional_bounded_text(self.description, "description", max_len=_MAX_TEXT)
        _optional_bounded_text(self.composition, "composition", max_len=_MAX_TEXT)
        _optional_bounded_text(self.notes, "notes", max_len=_MAX_TEXT)
        _optional_bounded_text(self.unit_label, "unit_label", max_len=_MAX_LABEL)
        _validate_optional_quantity(self.quantity)
        if (
            self.quantity_mode is not None
            and self.quantity_mode not in POSITION_QUANTITY_MODES
        ):
            raise ValueError("invalid quantity_mode")
        if self.kind == "surcharge":
            if self.related_position_id is None:
                raise ValueError("surcharge requires related_position_id")
        elif self.related_position_id is not None:
            raise ValueError("related_position_id is only valid for surcharges")
        if self.catalog_item_id is not None:
            _require_text(self.catalog_item_id, "catalog_item_id")
        if self.allergens is not None:
            object.__setattr__(
                self, "allergens", validate_allergen_codes(self.allergens)
            )


@dataclass(frozen=True)
class OrderCommercialSnapshot:
    """One immutable commercial decision bound to one Order at conversion."""

    snapshot_id: str
    order_id: str
    source_offer_id: str
    source_offer_version_id: str
    source_variant_id: str
    acceptance_id: str
    accepted_at: datetime
    recorded_by: str
    variant_label: str
    payment_method: PaymentMethod
    payment_customer_visible_text: str
    created_at: datetime
    positions: tuple[OrderCommercialPosition, ...]
    variant_description: str | None = None
    return_logistics: ReturnLogisticsDefinition | None = None

    def __post_init__(self) -> None:
        _require_text(self.snapshot_id, "snapshot_id")
        _require_text(self.order_id, "order_id")
        _require_text(self.source_offer_id, "source_offer_id")
        _require_text(self.source_offer_version_id, "source_offer_version_id")
        _require_text(self.source_variant_id, "source_variant_id")
        _require_text(self.acceptance_id, "acceptance_id")
        _require_aware(self.accepted_at, "accepted_at")
        _require_text(self.recorded_by, "recorded_by")
        _require_text(self.variant_label, "variant_label")
        validate_payment_method(self.payment_method)
        _require_text(
            self.payment_customer_visible_text, "payment_customer_visible_text"
        )
        if len(self.payment_customer_visible_text) > _MAX_TEXT:
            raise ValueError("payment_customer_visible_text exceeds length limit")
        _require_aware(self.created_at, "created_at")
        _optional_bounded_text(
            self.variant_description, "variant_description", max_len=_MAX_TEXT
        )
        if not self.positions:
            raise ValueError(
                "an OrderCommercialSnapshot requires at least one position"
            )
        position_ids: set[str] = set()
        for position in self.positions:
            if position.position_id in position_ids:
                raise ValueError("position_id must be unique within a snapshot")
            position_ids.add(position.position_id)
        for position in self.positions:
            if position.kind == "surcharge":
                if position.related_position_id not in position_ids:
                    raise ValueError(
                        "surcharge must reference a position in the snapshot"
                    )


def map_offer_position(position: OfferPosition) -> OrderCommercialPosition:
    """Copy frozen OfferPosition fields into a commercial snapshot line."""
    return OrderCommercialPosition(
        position_id=position.position_id,
        kind=position.kind,
        name=position.name,
        unit_net_cents=position.unit_net_cents,
        net_total_cents=position.net_total_cents,
        vat_rate_percent=position.vat_rate_percent,
        vat_amount_cents=position.vat_amount_cents,
        gross_total_cents=position.gross_total_cents,
        related_position_id=position.related_position_id,
        description=position.description,
        composition=position.composition,
        notes=position.notes,
        quantity=position.quantity,
        quantity_mode=position.quantity_mode,
        unit_label=position.unit_label,
        catalog_item_id=position.catalog_item_id,
        allergens=position.allergens,
    )


def build_order_commercial_snapshot(
    *,
    order_id: str,
    offer: Offer,
    offer_version: OfferVersion,
    variant: OfferVariant,
    acceptance: AcceptanceEvidence,
    created_at: datetime,
    snapshot_id: str | None = None,
) -> OrderCommercialSnapshot:
    """Pure factory: Accepted commercial facts → OrderCommercialSnapshot."""
    if offer.offer_id != acceptance.offer_id:
        raise ValueError("acceptance does not belong to offer")
    if offer_version.offer_id != offer.offer_id:
        raise ValueError("offer_version does not belong to offer")
    if variant.offer_version_id != offer_version.offer_version_id:
        raise ValueError("variant does not belong to offer_version")
    if acceptance.accepted_offer_version_id != offer_version.offer_version_id:
        raise ValueError("acceptance version mismatch")
    if acceptance.accepted_variant_id != variant.variant_id:
        raise ValueError("acceptance variant mismatch")
    return OrderCommercialSnapshot(
        snapshot_id=snapshot_id or str(uuid.uuid4()),
        order_id=order_id,
        source_offer_id=offer.offer_id,
        source_offer_version_id=offer_version.offer_version_id,
        source_variant_id=variant.variant_id,
        acceptance_id=acceptance.acceptance_id,
        accepted_at=acceptance.accepted_at,
        recorded_by=acceptance.recorded_by,
        variant_label=variant.label,
        variant_description=variant.description,
        payment_method=offer_version.payment_method,
        payment_customer_visible_text=offer_version.payment_customer_visible_text,
        created_at=created_at,
        positions=tuple(map_offer_position(item) for item in variant.positions),
        return_logistics=(
            offer_version.charges_definition.return_logistics
            if offer_version.charges_definition is not None
            else None
        ),
    )
