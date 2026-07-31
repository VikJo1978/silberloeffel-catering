"""Unit tests — OfferBudgetDefinition value object validation."""

from __future__ import annotations

import pytest

from catering_system.domain.offer_budget_definition import (
    OfferBudgetDefinition,
    validate_offer_budget_cost_scope,
    validate_offer_budget_tax_basis,
    validate_offer_budget_type,
)


def test_valid_definition_constructs() -> None:
    definition = OfferBudgetDefinition(
        amount_cents=3500, type="PER_PERSON", tax_basis="GROSS", cost_scope="FULL_OFFER"
    )
    assert definition.amount_cents == 3500


def test_rejects_negative_amount() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        OfferBudgetDefinition(
            amount_cents=-1, type="TOTAL", tax_basis="GROSS", cost_scope="FULL_OFFER"
        )


def test_rejects_float_amount() -> None:
    with pytest.raises(ValueError, match="integer euro cents"):
        OfferBudgetDefinition(
            amount_cents=35.0,  # type: ignore[arg-type]
            type="TOTAL",
            tax_basis="GROSS",
            cost_scope="FULL_OFFER",
        )


def test_rejects_bool_amount() -> None:
    with pytest.raises(ValueError, match="integer euro cents"):
        OfferBudgetDefinition(
            amount_cents=True,
            type="TOTAL",
            tax_basis="GROSS",
            cost_scope="FULL_OFFER",
        )


def test_zero_amount_is_valid() -> None:
    definition = OfferBudgetDefinition(
        amount_cents=0, type="TOTAL", tax_basis="GROSS", cost_scope="FULL_OFFER"
    )
    assert definition.amount_cents == 0


@pytest.mark.parametrize("value", ["TOTAL", "PER_PERSON"])
def test_validate_offer_budget_type_accepts_known_values(value: str) -> None:
    assert validate_offer_budget_type(value) == value


def test_validate_offer_budget_type_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="invalid budget_definition.type"):
        validate_offer_budget_type("total")


@pytest.mark.parametrize("value", ["GROSS", "NET"])
def test_validate_offer_budget_tax_basis_accepts_known_values(value: str) -> None:
    assert validate_offer_budget_tax_basis(value) == value


def test_validate_offer_budget_tax_basis_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="invalid budget_definition.tax_basis"):
        validate_offer_budget_tax_basis("brutto")


@pytest.mark.parametrize("value", ["FULL_OFFER", "POSITIONS_ONLY"])
def test_validate_offer_budget_cost_scope_accepts_known_values(value: str) -> None:
    assert validate_offer_budget_cost_scope(value) == value


def test_validate_offer_budget_cost_scope_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="invalid budget_definition.cost_scope"):
        validate_offer_budget_cost_scope("EVERYTHING")


def test_domain_module_has_no_repository_or_api_imports() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "catering_system"
        / "domain"
        / "offer_budget_definition.py"
    )
    text = source.read_text(encoding="utf-8")
    assert "repositories" not in text
    assert "catering_system.ui" not in text
    assert "catering_system.services" not in text
