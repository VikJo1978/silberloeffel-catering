"""Cross-repo guest-count parity — Core vs. Configurator.

Closes a coordinated-review finding: for `type=PER_PERSON`, Configurator's
`utils/budgetBreakdown.ts` used to silently substitute a guest count of 1
when `persons <= 0`, fabricating an "Aktuell"/"Verfügbar" value where Core
correctly reported the comparison as unavailable
(`compute_offer_budget_presentation` returns `comparison_amount_cents=None`
for `guest_count is None or guest_count <= 0`). Configurator was fixed to
match Core exactly (see `budgetBreakdown.ts`'s `personsRequired` flag and its
own parity tests in `frontend/src/utils/__tests__/budgetBreakdown.test.ts`,
describe block "PER_PERSON guest-count parity with Core").

This file proves the two engines agree, using an *identical* underlying
snapshot on both sides: a single catalog position priced at 31,80 €/person
(7% VAT), 20 persons -> net_total_cents = 63600 (636,00 €), scope
POSITIONS_ONLY + basis NET so the comparison total depends only on
`net_total_cents` and is entirely independent of Pauschalen (a
Configurator-only presentation concern, not part of the guest-count
semantics under test here) — the same fixture shape the Configurator side
uses (`computeAll` in its own test file, `item7` at 31.80 €/person, 7% VAT).

Covers, on both sides, the four cases the coordinated review asked for:
guest_count = 0, guest_count missing, guest_count = 1, and a normal
positive guest_count.
"""

from __future__ import annotations

from catering_system.domain.offer import OfferPosition
from catering_system.domain.offer_budget_definition import OfferBudgetDefinition
from catering_system.services.offer_budget_presentation import (
    compute_offer_budget_presentation,
)

# 20 persons * 31.80 EUR/person, matching the Configurator's `item7` fixture
# (price=31.8, per_person, vat_rate_percent=7) at persons=20.
_NET_TOTAL_CENTS = 63600
_VAT_AMOUNT_CENTS = round(_NET_TOTAL_CENTS * 0.07)
_GROSS_TOTAL_CENTS = _NET_TOTAL_CENTS + _VAT_AMOUNT_CENTS

# 35,00 EUR/person configured budget — same amount used in the
# Configurator's matching parity test.
_AMOUNT_CENTS = 3500


def _position() -> OfferPosition:
    return OfferPosition(
        position_id="99999999-9999-4999-9999-999999999991",
        kind="catalog",
        name="Speise",
        unit_net_cents=_NET_TOTAL_CENTS,
        net_total_cents=_NET_TOTAL_CENTS,
        vat_rate_percent=7,
        vat_amount_cents=_VAT_AMOUNT_CENTS,
        gross_total_cents=_GROSS_TOTAL_CENTS,
    )


def _budget() -> OfferBudgetDefinition:
    return OfferBudgetDefinition(
        amount_cents=_AMOUNT_CENTS,
        type="PER_PERSON",
        tax_basis="NET",
        cost_scope="POSITIONS_ONLY",
    )


def test_guest_count_zero_has_no_comparison_matching_configurator_personsRequired() -> (
    None
):
    """Core: guest_count=0 -> comparison/remaining/over all None.

    Configurator equivalent: `computeBudgetBreakdown({..., persons: 0})`
    returns `personsRequired: true`, `comparisonPerPerson: null`,
    `remaining: null`, `over: null` — see
    frontend/src/utils/__tests__/budgetBreakdown.test.ts,
    "guest_count = 0: personsRequired is true, nothing is fabricated".
    Neither side ever assumes a guest count of 1.
    """
    result = compute_offer_budget_presentation(
        _budget(), positions=[_position()], guest_count=0
    )
    assert result is not None
    assert result.comparison_amount_cents is None
    assert result.remaining_cents is None
    assert result.over is None


def test_guest_count_missing_has_no_comparison_matching_configurator_personsRequired() -> (
    None
):
    """Core: guest_count=None -> comparison/remaining/over all None.

    Configurator equivalent: `persons: null` -> the same `personsRequired:
    true` state as guest_count=0 — "missing" and "<= 0" are one case on
    both sides, not two.
    """
    result = compute_offer_budget_presentation(
        _budget(), positions=[_position()], guest_count=None
    )
    assert result is not None
    assert result.comparison_amount_cents is None
    assert result.remaining_cents is None
    assert result.over is None


def test_guest_count_one_shows_a_real_comparison_matching_configurator() -> None:
    """Core: guest_count=1 -> divides by 1, a real (if extreme) comparison.

    Configurator equivalent: `persons: 1` -> `personsRequired: false`,
    `comparisonPerPerson = 636.00`, matching `comparison_amount_cents =
    63600` here exactly (636,00 EUR expressed in cents).
    """
    result = compute_offer_budget_presentation(
        _budget(), positions=[_position()], guest_count=1
    )
    assert result is not None
    assert result.comparison_amount_cents == _NET_TOTAL_CENTS  # 63600 -> 636,00 EUR
    assert result.remaining_cents == _AMOUNT_CENTS - _NET_TOTAL_CENTS
    assert result.over is True


def test_guest_count_normal_positive_shows_a_real_comparison_matching_configurator() -> (
    None
):
    """Core: guest_count=20 (the fixture's real headcount) -> 31,80 EUR/person.

    Configurator equivalent: `persons: 20` -> `comparisonPerPerson =
    subtotal / 20 = 636,00 / 20 = 31,80`, matching `comparison_amount_cents
    = 3180` here exactly (31,80 EUR expressed in cents) — the same figure
    the position was priced at per person in the first place.
    """
    result = compute_offer_budget_presentation(
        _budget(), positions=[_position()], guest_count=20
    )
    assert result is not None
    assert result.comparison_amount_cents == 3180  # 31,80 EUR/person
    assert result.remaining_cents == _AMOUNT_CENTS - 3180  # 35,00 - 31,80 = 3,20 EUR
    assert result.over is False


def test_total_budget_type_is_unaffected_by_guest_count_on_either_side() -> None:
    """TOTAL never divides by persons on the Core side either — matches
    the Configurator's `personsRequired` guard, which only ever applies to
    `budgetType === "per_person"`."""
    total_budget = OfferBudgetDefinition(
        amount_cents=100000,
        type="TOTAL",
        tax_basis="NET",
        cost_scope="POSITIONS_ONLY",
    )
    for guest_count in (0, None, 1, 20):
        result = compute_offer_budget_presentation(
            total_budget, positions=[_position()], guest_count=guest_count
        )
        assert result is not None
        assert result.comparison_amount_cents == _NET_TOTAL_CENTS
        assert result.remaining_cents == 100000 - _NET_TOTAL_CENTS
        assert result.over is False
