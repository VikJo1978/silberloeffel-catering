"""Commercial charge definitions embedded in Offer snapshots.

The value objects in this module are shared by the incoming OfferSnapshot and
the persisted Offer aggregate. They describe operator-configured,
customer-facing charges. A missing ``charges_definition`` on an envelope still
means a legacy snapshot and is handled by the snapshot validator.

Issue #171 extends the existing charge contract with a *commercial return
request*. It deliberately stores no courier execution state. Core may freeze
``NEXT_WORKING_DAY`` or ``SAME_DAY`` plus the requested pickup window and the
configured same-day fee; assignment, checklist state, completion and overdue
signals remain outside this domain.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Literal

from catering_system.domain.logistics_timing import validate_optional_local_window

ChargeBaseMode = Literal["NONE", "PAUSCHALE"]
ReturnMode = Literal["NEXT_WORKING_DAY", "SAME_DAY"]

CHARGE_BASE_MODES: tuple[ChargeBaseMode, ...] = ("NONE", "PAUSCHALE")
RETURN_MODES: tuple[ReturnMode, ...] = ("NEXT_WORKING_DAY", "SAME_DAY")


def validate_charge_base_mode(value: str) -> ChargeBaseMode:
    if value == "NONE":
        return "NONE"
    if value == "PAUSCHALE":
        return "PAUSCHALE"
    raise ValueError("invalid charge base_mode")


def validate_return_mode(value: str) -> ReturnMode:
    if value == "NEXT_WORKING_DAY":
        return "NEXT_WORKING_DAY"
    if value == "SAME_DAY":
        return "SAME_DAY"
    raise ValueError("invalid return mode")


def _require_non_negative_cents(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be integer euro cents")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


@dataclass(frozen=True)
class DeliveryChargeDefinition:
    """One operator-configured outbound delivery amount."""

    amount_cents: int

    def __post_init__(self) -> None:
        _require_non_negative_cents(self.amount_cents, "delivery.amount_cents")


@dataclass(frozen=True)
class DishwareAdditionalLineDefinition:
    """One operator-entered additional dishware line.

    ``net_total_cents`` is derived from quantity and unit price rather than
    accepted or persisted as an independent input.
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
        return self.quantity * self.unit_net_cents


@dataclass(frozen=True)
class DishwareChargeDefinition:
    """Dishware Pauschale toggle plus independent additional lines."""

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
    """Büffetpauschale charge using the same NONE/PAUSCHALE convention."""

    base_mode: ChargeBaseMode
    pauschale_per_person_cents: int

    def __post_init__(self) -> None:
        validate_charge_base_mode(self.base_mode)
        _require_non_negative_cents(
            self.pauschale_per_person_cents, "buffet.pauschale_per_person_cents"
        )


@dataclass(frozen=True)
class ReturnLogisticsDefinition:
    """Commercial request for collecting reusable dishware/equipment.

    ``NEXT_WORKING_DAY`` is the default and carries no requested pickup
    window. ``SAME_DAY`` is an explicit request and requires a non-empty,
    trimmed pickup window. ``same_day_fee_cents`` is retained in both modes so
    toggling the option off does not erase the operator-configured rate.

    This object is intentionally not a PickupTask. It contains no driver,
    vehicle, assignment, started/completed state or overdue state.
    """

    mode: ReturnMode = "NEXT_WORKING_DAY"
    pickup_window_text: str | None = None
    same_day_fee_cents: int = 0
    pickup_window_start_local: time | None = None
    pickup_window_end_local: time | None = None

    def __post_init__(self) -> None:
        validate_return_mode(self.mode)
        _require_non_negative_cents(
            self.same_day_fee_cents, "return_logistics.same_day_fee_cents"
        )
        if self.pickup_window_text is not None:
            if not isinstance(self.pickup_window_text, str):
                raise ValueError("return pickup window must be a string or null")
            if self.pickup_window_text != self.pickup_window_text.strip():
                raise ValueError("return pickup window must be trimmed")
            if not self.pickup_window_text:
                raise ValueError("return pickup window must not be empty")
        if self.mode == "SAME_DAY" and self.pickup_window_text is None:
            raise ValueError("SAME_DAY return requires pickup_window_text")
        validate_optional_local_window(
            self.pickup_window_start_local,
            self.pickup_window_end_local,
            label="return pickup window",
        )
        if self.mode == "NEXT_WORKING_DAY":
            if self.pickup_window_text is not None:
                raise ValueError(
                    "NEXT_WORKING_DAY return must not specify pickup_window_text"
                )
            if (
                self.pickup_window_start_local is not None
                or self.pickup_window_end_local is not None
            ):
                raise ValueError(
                    "NEXT_WORKING_DAY return must not specify canonical pickup times"
                )


@dataclass(frozen=True)
class OfferChargesDefinition:
    """Complete operator-configured charges for one Offer snapshot.

    ``return_logistics`` has a backward-compatible default because structured
    charge snapshots created before issue #171 did not contain that section.
    New producers should send it explicitly once the wire contract is enabled.
    """

    delivery: DeliveryChargeDefinition
    dishware: DishwareChargeDefinition
    buffet: BuffetChargeDefinition
    return_logistics: ReturnLogisticsDefinition = ReturnLogisticsDefinition()


__all__ = [
    "CHARGE_BASE_MODES",
    "RETURN_MODES",
    "BuffetChargeDefinition",
    "ChargeBaseMode",
    "DeliveryChargeDefinition",
    "DishwareAdditionalLineDefinition",
    "DishwareChargeDefinition",
    "OfferChargesDefinition",
    "ReturnLogisticsDefinition",
    "ReturnMode",
    "validate_charge_base_mode",
    "validate_return_mode",
]
