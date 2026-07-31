"""OFFER_BUDGET_DEFINITION_V1 — internal Office Panel presentation only.

Composes the "Aktuell"/"Verfügbar" comparison shown in the Offer Detail
budget block entirely from the already-frozen, already-validated position
cents already present in the OfferVersion snapshot (``net_total_cents`` /
``vat_amount_cents`` / ``gross_total_cents`` per position). Nothing here
re-derives pricing or VAT — it only selects and sums numbers the pricing
engine already computed, exactly like the Configurator's
``utils/budgetBreakdown.ts`` does client-side. Never used for anything
customer-facing.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

from catering_system.domain.offer import OfferPosition
from catering_system.domain.offer_budget_definition import OfferBudgetDefinition

_SPEISEN_KINDS = frozenset({"catalog", "surcharge"})


@dataclass(frozen=True)
class OfferBudgetPresentation:
    amount_cents: int
    type: str
    tax_basis: str
    cost_scope: str
    # None only when type=PER_PERSON and guest_count is unknown — nothing to
    # divide by, so no comparison can be shown (never a crash / never 0).
    comparison_amount_cents: int | None
    remaining_cents: int | None
    over: bool | None


def _round_half_up_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _sum_cents(
    positions: Iterable[OfferPosition], *, gross: bool, kinds: frozenset[str] | None
) -> int:
    total = 0
    for position in positions:
        if kinds is not None and position.kind not in kinds:
            continue
        total += position.gross_total_cents if gross else position.net_total_cents
    return total


def compute_offer_budget_presentation(
    budget_definition: OfferBudgetDefinition | None,
    *,
    positions: Iterable[OfferPosition],
    guest_count: int | None,
) -> OfferBudgetPresentation | None:
    if budget_definition is None:
        return None

    positions = list(positions)
    gross = budget_definition.tax_basis == "GROSS"
    kinds = _SPEISEN_KINDS if budget_definition.cost_scope == "POSITIONS_ONLY" else None
    comparison_absolute_cents = _sum_cents(positions, gross=gross, kinds=kinds)

    if budget_definition.type == "TOTAL":
        remaining = budget_definition.amount_cents - comparison_absolute_cents
        return OfferBudgetPresentation(
            amount_cents=budget_definition.amount_cents,
            type=budget_definition.type,
            tax_basis=budget_definition.tax_basis,
            cost_scope=budget_definition.cost_scope,
            comparison_amount_cents=comparison_absolute_cents,
            remaining_cents=remaining,
            over=remaining < 0,
        )

    # PER_PERSON
    if guest_count is None or guest_count <= 0:
        return OfferBudgetPresentation(
            amount_cents=budget_definition.amount_cents,
            type=budget_definition.type,
            tax_basis=budget_definition.tax_basis,
            cost_scope=budget_definition.cost_scope,
            comparison_amount_cents=None,
            remaining_cents=None,
            over=None,
        )
    comparison_per_person_cents = _round_half_up_cents(
        Decimal(comparison_absolute_cents) / Decimal(guest_count)
    )
    remaining = budget_definition.amount_cents - comparison_per_person_cents
    return OfferBudgetPresentation(
        amount_cents=budget_definition.amount_cents,
        type=budget_definition.type,
        tax_basis=budget_definition.tax_basis,
        cost_scope=budget_definition.cost_scope,
        comparison_amount_cents=comparison_per_person_cents,
        remaining_cents=remaining,
        over=remaining < 0,
    )


__all__ = ["OfferBudgetPresentation", "compute_offer_budget_presentation"]
