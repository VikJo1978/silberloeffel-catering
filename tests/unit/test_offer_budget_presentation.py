"""Unit tests — OFFER_BUDGET_DEFINITION_V1 Office Panel presentation math.

Everything here sums already-frozen position cents (net_total_cents /
gross_total_cents) grouped by kind — no pricing or VAT is re-derived.
"""

from __future__ import annotations

from catering_system.domain.offer import OfferPosition
from catering_system.domain.offer_budget_definition import OfferBudgetDefinition
from catering_system.services.offer_budget_presentation import (
    compute_offer_budget_presentation,
)


def _catalog_position(
    *, net_total_cents: int, vat_amount_cents: int, gross_total_cents: int
) -> OfferPosition:
    return OfferPosition(
        position_id="88888888-8888-4888-8888-888888888881",
        kind="catalog",
        name="Fingerfood Paket",
        unit_net_cents=net_total_cents,
        net_total_cents=net_total_cents,
        vat_rate_percent=7,
        vat_amount_cents=vat_amount_cents,
        gross_total_cents=gross_total_cents,
    )


def _fee_position(
    *, net_total_cents: int, vat_amount_cents: int, gross_total_cents: int
) -> OfferPosition:
    return OfferPosition(
        position_id="88888888-8888-4888-8888-888888888882",
        kind="fee",
        name="Büffetpauschale",
        unit_net_cents=net_total_cents,
        net_total_cents=net_total_cents,
        vat_rate_percent=19,
        vat_amount_cents=vat_amount_cents,
        gross_total_cents=gross_total_cents,
    )


def test_no_budget_definition_returns_none() -> None:
    result = compute_offer_budget_presentation(None, positions=[], guest_count=80)
    assert result is None


def test_total_gross_full_offer_includes_fees() -> None:
    positions = [
        _catalog_position(
            net_total_cents=23200, vat_amount_cents=1624, gross_total_cents=24824
        ),
        _fee_position(
            net_total_cents=1500, vat_amount_cents=285, gross_total_cents=1785
        ),
    ]
    budget = OfferBudgetDefinition(
        amount_cents=30000, type="TOTAL", tax_basis="GROSS", cost_scope="FULL_OFFER"
    )
    result = compute_offer_budget_presentation(
        budget, positions=positions, guest_count=80
    )
    assert result is not None
    assert result.comparison_amount_cents == 24824 + 1785
    assert result.remaining_cents == 30000 - (24824 + 1785)
    assert result.over is False


def test_total_net_positions_only_excludes_fees() -> None:
    positions = [
        _catalog_position(
            net_total_cents=23200, vat_amount_cents=1624, gross_total_cents=24824
        ),
        _fee_position(
            net_total_cents=1500, vat_amount_cents=285, gross_total_cents=1785
        ),
    ]
    budget = OfferBudgetDefinition(
        amount_cents=20000, type="TOTAL", tax_basis="NET", cost_scope="POSITIONS_ONLY"
    )
    result = compute_offer_budget_presentation(
        budget, positions=positions, guest_count=80
    )
    assert result is not None
    assert result.comparison_amount_cents == 23200
    assert result.remaining_cents == 20000 - 23200
    assert result.over is True


def test_positions_only_gross_includes_position_vat_but_not_fee_vat() -> None:
    positions = [
        _catalog_position(
            net_total_cents=23200, vat_amount_cents=1624, gross_total_cents=24824
        ),
        _fee_position(
            net_total_cents=1500, vat_amount_cents=285, gross_total_cents=1785
        ),
    ]
    budget = OfferBudgetDefinition(
        amount_cents=30000,
        type="TOTAL",
        tax_basis="GROSS",
        cost_scope="POSITIONS_ONLY",
    )
    result = compute_offer_budget_presentation(
        budget, positions=positions, guest_count=80
    )
    assert result is not None
    # Only the catalog position's own gross — fee gross is excluded entirely,
    # not partially subtracted; this differs from the Configurator's
    # positions-only+gross derivation (which reconstructs a Speisen-only
    # gross from aggregate VAT buckets) because here each position already
    # carries its own final gross_total_cents, so a straight sum-by-kind is
    # sufficient and exact.
    assert result.comparison_amount_cents == 24824


def test_per_person_rounds_half_up() -> None:
    positions = [
        _catalog_position(
            net_total_cents=23200, vat_amount_cents=1624, gross_total_cents=24824
        ),
    ]
    budget = OfferBudgetDefinition(
        amount_cents=350, type="PER_PERSON", tax_basis="GROSS", cost_scope="FULL_OFFER"
    )
    result = compute_offer_budget_presentation(
        budget, positions=positions, guest_count=80
    )
    assert result is not None
    # 24824 / 80 = 310.3 -> ROUND_HALF_UP -> 310
    assert result.comparison_amount_cents == 310
    assert result.remaining_cents == 40
    assert result.over is False


def test_per_person_exact_equality_is_neither_remaining_nor_exceeded_incorrectly() -> (
    None
):
    positions = [
        _catalog_position(
            net_total_cents=24800, vat_amount_cents=0, gross_total_cents=24800
        )
    ]
    budget = OfferBudgetDefinition(
        amount_cents=310, type="PER_PERSON", tax_basis="GROSS", cost_scope="FULL_OFFER"
    )
    result = compute_offer_budget_presentation(
        budget, positions=positions, guest_count=80
    )
    assert result is not None
    assert result.comparison_amount_cents == 310
    assert result.remaining_cents == 0
    assert result.over is False


def test_total_exact_equality_is_not_over() -> None:
    positions = [
        _catalog_position(
            net_total_cents=24824, vat_amount_cents=0, gross_total_cents=24824
        )
    ]
    budget = OfferBudgetDefinition(
        amount_cents=24824, type="TOTAL", tax_basis="GROSS", cost_scope="FULL_OFFER"
    )
    result = compute_offer_budget_presentation(
        budget, positions=positions, guest_count=80
    )
    assert result is not None
    assert result.remaining_cents == 0
    assert result.over is False


def test_per_person_with_none_guest_count_has_no_comparison() -> None:
    positions = [
        _catalog_position(
            net_total_cents=23200, vat_amount_cents=1624, gross_total_cents=24824
        )
    ]
    budget = OfferBudgetDefinition(
        amount_cents=350, type="PER_PERSON", tax_basis="GROSS", cost_scope="FULL_OFFER"
    )
    result = compute_offer_budget_presentation(
        budget, positions=positions, guest_count=None
    )
    assert result is not None
    assert result.comparison_amount_cents is None
    assert result.remaining_cents is None
    assert result.over is None


def test_per_person_with_zero_guest_count_has_no_comparison() -> None:
    """Never divides by zero."""
    positions = [
        _catalog_position(
            net_total_cents=23200, vat_amount_cents=1624, gross_total_cents=24824
        )
    ]
    budget = OfferBudgetDefinition(
        amount_cents=350, type="PER_PERSON", tax_basis="GROSS", cost_scope="FULL_OFFER"
    )
    result = compute_offer_budget_presentation(
        budget, positions=positions, guest_count=0
    )
    assert result is not None
    assert result.comparison_amount_cents is None


def test_empty_positions_gives_zero_comparison() -> None:
    budget = OfferBudgetDefinition(
        amount_cents=30000, type="TOTAL", tax_basis="GROSS", cost_scope="FULL_OFFER"
    )
    result = compute_offer_budget_presentation(budget, positions=[], guest_count=80)
    assert result is not None
    assert result.comparison_amount_cents == 0
    assert result.remaining_cents == 30000
    assert result.over is False
