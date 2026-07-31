"""OFFER_BUDGET_DEFINITION_V1 — internal-only operator planning metadata.

Shared value object embedded (optionally) in both the OfferSnapshot wire
envelope (``domain/offer_snapshot.py``) and the persisted Offer aggregate
(``domain/offer.py``). Never customer-facing: not included in the Offer
document/PDF, printed wording, or any customer-visible text — it exists only
for the Office Panel's internal Offer Detail view.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

OfferBudgetType = Literal["TOTAL", "PER_PERSON"]
OfferBudgetTaxBasis = Literal["GROSS", "NET"]
OfferBudgetCostScope = Literal["FULL_OFFER", "POSITIONS_ONLY"]

OFFER_BUDGET_TYPES: tuple[OfferBudgetType, ...] = ("TOTAL", "PER_PERSON")
OFFER_BUDGET_TAX_BASES: tuple[OfferBudgetTaxBasis, ...] = ("GROSS", "NET")
OFFER_BUDGET_COST_SCOPES: tuple[OfferBudgetCostScope, ...] = (
    "FULL_OFFER",
    "POSITIONS_ONLY",
)


def validate_offer_budget_type(value: str) -> OfferBudgetType:
    if value == "TOTAL":
        return "TOTAL"
    if value == "PER_PERSON":
        return "PER_PERSON"
    raise ValueError("invalid budget_definition.type")


def validate_offer_budget_tax_basis(value: str) -> OfferBudgetTaxBasis:
    if value == "GROSS":
        return "GROSS"
    if value == "NET":
        return "NET"
    raise ValueError("invalid budget_definition.tax_basis")


def validate_offer_budget_cost_scope(value: str) -> OfferBudgetCostScope:
    if value == "FULL_OFFER":
        return "FULL_OFFER"
    if value == "POSITIONS_ONLY":
        return "POSITIONS_ONLY"
    raise ValueError("invalid budget_definition.cost_scope")


@dataclass(frozen=True)
class OfferBudgetDefinition:
    """One operator-configured budget figure and how it is compared.

    ``amount_cents`` follows the same non-negative integer euro-cents
    representation as every other money field in the Offer snapshot — no
    floats cross this boundary. ``type`` decides whether ``amount_cents`` is
    an absolute total or a per-person rate; ``tax_basis``/``cost_scope``
    decide which totals it is compared against (see
    OFFER_OPERATIONAL_QUEUE_V1-adjacent Configurator docs for the four
    included/excluded combinations).
    """

    amount_cents: int
    type: OfferBudgetType
    tax_basis: OfferBudgetTaxBasis
    cost_scope: OfferBudgetCostScope

    def __post_init__(self) -> None:
        if not isinstance(self.amount_cents, int) or isinstance(
            self.amount_cents, bool
        ):
            raise ValueError(
                "budget_definition.amount_cents must be integer euro cents"
            )
        if self.amount_cents < 0:
            raise ValueError("budget_definition.amount_cents must be non-negative")
        validate_offer_budget_type(self.type)
        validate_offer_budget_tax_basis(self.tax_basis)
        validate_offer_budget_cost_scope(self.cost_scope)


__all__ = [
    "OFFER_BUDGET_COST_SCOPES",
    "OFFER_BUDGET_TAX_BASES",
    "OFFER_BUDGET_TYPES",
    "OfferBudgetCostScope",
    "OfferBudgetDefinition",
    "OfferBudgetTaxBasis",
    "OfferBudgetType",
    "validate_offer_budget_cost_scope",
    "validate_offer_budget_tax_basis",
    "validate_offer_budget_type",
]
