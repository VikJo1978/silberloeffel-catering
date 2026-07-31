"""CONFIGURABLE_OFFER_CHARGES_V1 — delivery/dishware/buffet charge definitions.

Shared value objects embedded (optionally) in both the OfferSnapshot wire
envelope (``domain/offer_snapshot.py``) and the persisted Offer aggregate
(``domain/offer.py``). Unlike ``OfferBudgetDefinition``, these *are*
customer-facing: they describe real offer-level charges that materialize as
``delivery``/``dishware``/``buffet_fee`` positions, appear in totals, and
render in the customer document/PDF exactly like any other position.

Absent (``None``) on the envelope means "legacy snapshot" — no charges
definition was ever sent, and the snapshot's already-materialized positions
(historically always ``kind="fee"`` Büffetpauschale/Geschirrpauschale/
Anlieferung, added unconditionally by the pre-this-slice Configurator
backend) are trusted as-is, never reinterpreted or synthesized from this
module. See ``services/offer_snapshot_validation.py`` for the consistency
check that only ever applies when a ``charges_definition`` is actually
present on the incoming snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ChargeBaseMode = Literal["NONE", "PAUSCHALE"]

CHARGE_BASE_MODES: tuple[ChargeBaseMode, ...] = ("NONE", "PAUSCHALE")


def validate_charge_base_mode(value: str) -> ChargeBaseMode:
    if value == "NONE":
        return "NONE"
    if value == "PAUSCHALE":
        return "PAUSCHALE"
    raise ValueError("invalid charge base_mode")


def _require_non_negative_cents(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be integer euro cents")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


@dataclass(frozen=True)
class DeliveryChargeDefinition:
    """One operator-configured delivery amount.

    ``amount_cents`` is the complete, standalone charge — 0 is explicitly
    valid (collection / free delivery), not a sentinel for "no delivery".
    Every ``charges_definition`` that specifies delivery at all carries this
    object; there is no separate on/off toggle for delivery the way
    dishware/buffet have ``base_mode``.
    """

    amount_cents: int

    def __post_init__(self) -> None:
        _require_non_negative_cents(self.amount_cents, "delivery.amount_cents")


@dataclass(frozen=True)
class DishwareAdditionalLineDefinition:
    """One operator-entered additional dishware line.

    Deliberately carries no calculated total — ``net_total_cents`` is never
    accepted from the wire and never stored here (binding decision: the
    server always derives ``quantity * unit_net_cents`` itself, at whatever
    point it is needed, rather than trusting or persisting a client-supplied
    figure that could drift from the inputs that produced it).
    """

    description: str
    quantity: int
    unit_net_cents: int

    def __post_init__(self) -> None:
        if not isinstance(self.description, str):
            raise ValueError("dishware line description must be a string")
        if self.description != self.description.strip():
            raise ValueError("dishware line description must be trimmed")
        if not self.description:
            raise ValueError("dishware line description is required")
        if not isinstance(self.quantity, int) or isinstance(self.quantity, bool):
            raise ValueError("dishware line quantity must be a whole number")
        if self.quantity < 1:
            raise ValueError("dishware line quantity must be a positive integer")
        _require_non_negative_cents(self.unit_net_cents, "dishware line unit_net_cents")

    @property
    def net_total_cents(self) -> int:
        """Derived on demand — never a stored/persisted field (see class docstring)."""
        return self.quantity * self.unit_net_cents


@dataclass(frozen=True)
class DishwareChargeDefinition:
    """Dishware charge: an independent Pauschale toggle plus an independent
    list of additional lines. The two are orthogonal — all four
    combinations (NONE/no lines, NONE/lines, PAUSCHALE/no lines,
    PAUSCHALE/lines) are valid and meaningful; a non-empty ``additional_lines``
    does not imply or require ``base_mode == "PAUSCHALE"``.

    ``pauschale_per_person_cents`` is always present and validated even when
    ``base_mode == "NONE"`` — the configured rate survives being toggled
    off, so switching back to PAUSCHALE later does not lose it.
    """

    base_mode: ChargeBaseMode
    pauschale_per_person_cents: int
    additional_lines: tuple[DishwareAdditionalLineDefinition, ...] = ()

    def __post_init__(self) -> None:
        validate_charge_base_mode(self.base_mode)
        _require_non_negative_cents(
            self.pauschale_per_person_cents, "dishware.pauschale_per_person_cents"
        )


@dataclass(frozen=True)
class BuffetChargeDefinition:
    """Büffetpauschale charge — same NONE/PAUSCHALE shape as dishware's base
    mode, no additional lines. Existing canonical rate: 50 cents/person."""

    base_mode: ChargeBaseMode
    pauschale_per_person_cents: int

    def __post_init__(self) -> None:
        validate_charge_base_mode(self.base_mode)
        _require_non_negative_cents(
            self.pauschale_per_person_cents, "buffet.pauschale_per_person_cents"
        )


@dataclass(frozen=True)
class OfferChargesDefinition:
    """Complete operator-configured charges for one Offer snapshot.

    All three fields are required whenever ``charges_definition`` is present
    on the envelope at all — there is no partial shape; a snapshot either
    carries the complete, explicit charge configuration or none of it
    (``charges_definition`` itself is ``None`` on the envelope/version).
    """

    delivery: DeliveryChargeDefinition
    dishware: DishwareChargeDefinition
    buffet: BuffetChargeDefinition


__all__ = [
    "CHARGE_BASE_MODES",
    "BuffetChargeDefinition",
    "ChargeBaseMode",
    "DeliveryChargeDefinition",
    "DishwareAdditionalLineDefinition",
    "DishwareChargeDefinition",
    "OfferChargesDefinition",
    "validate_charge_base_mode",
]
