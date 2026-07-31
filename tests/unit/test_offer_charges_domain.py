"""Unit tests — CONFIGURABLE_OFFER_CHARGES_V1 value object validation."""

from __future__ import annotations

import pytest

from catering_system.domain.offer_charges import (
    BuffetChargeDefinition,
    DeliveryChargeDefinition,
    DishwareAdditionalLineDefinition,
    DishwareChargeDefinition,
    OfferChargesDefinition,
    validate_charge_base_mode,
)


# --- DeliveryChargeDefinition -----------------------------------------------------


def test_delivery_valid_amount_constructs() -> None:
    assert DeliveryChargeDefinition(amount_cents=3500).amount_cents == 3500


def test_delivery_zero_is_valid() -> None:
    assert DeliveryChargeDefinition(amount_cents=0).amount_cents == 0


def test_delivery_rejects_negative_amount() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        DeliveryChargeDefinition(amount_cents=-1)


def test_delivery_rejects_bool_amount() -> None:
    with pytest.raises(ValueError, match="integer euro cents"):
        DeliveryChargeDefinition(amount_cents=True)  # type: ignore[arg-type]


def test_delivery_rejects_float_amount() -> None:
    with pytest.raises(ValueError, match="integer euro cents"):
        DeliveryChargeDefinition(amount_cents=35.0)  # type: ignore[arg-type]


# --- DishwareAdditionalLineDefinition ---------------------------------------------


def test_dishware_line_valid_constructs() -> None:
    line = DishwareAdditionalLineDefinition(
        description="Weinglas", quantity=20, unit_net_cents=80
    )
    assert line.quantity == 20
    assert line.unit_net_cents == 80


def test_dishware_line_derives_net_total_and_never_stores_it() -> None:
    line = DishwareAdditionalLineDefinition(
        description="Weinglas", quantity=20, unit_net_cents=80
    )
    assert line.net_total_cents == 1600
    assert not hasattr(line, "_net_total_cents")
    assert "net_total_cents" not in line.__dataclass_fields__


def test_dishware_line_rejects_empty_description() -> None:
    with pytest.raises(ValueError, match="description is required"):
        DishwareAdditionalLineDefinition(description="", quantity=1, unit_net_cents=100)


def test_dishware_line_rejects_untrimmed_description() -> None:
    with pytest.raises(ValueError, match="must be trimmed"):
        DishwareAdditionalLineDefinition(
            description=" Weinglas ", quantity=1, unit_net_cents=100
        )


def test_dishware_line_rejects_zero_quantity() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        DishwareAdditionalLineDefinition(
            description="Weinglas", quantity=0, unit_net_cents=100
        )


def test_dishware_line_rejects_negative_quantity() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        DishwareAdditionalLineDefinition(
            description="Weinglas", quantity=-1, unit_net_cents=100
        )


def test_dishware_line_rejects_fractional_quantity() -> None:
    with pytest.raises(ValueError, match="whole number"):
        DishwareAdditionalLineDefinition(
            description="Weinglas",
            quantity=1.5,
            unit_net_cents=100,  # type: ignore[arg-type]
        )


def test_dishware_line_rejects_bool_quantity() -> None:
    with pytest.raises(ValueError, match="whole number"):
        DishwareAdditionalLineDefinition(
            description="Weinglas",
            quantity=True,
            unit_net_cents=100,  # type: ignore[arg-type]
        )


def test_dishware_line_rejects_negative_unit_net_cents() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        DishwareAdditionalLineDefinition(
            description="Weinglas", quantity=1, unit_net_cents=-1
        )


def test_dishware_line_zero_unit_net_cents_is_valid() -> None:
    line = DishwareAdditionalLineDefinition(
        description="Weinglas", quantity=1, unit_net_cents=0
    )
    assert line.net_total_cents == 0


# --- DishwareChargeDefinition ------------------------------------------------------


def test_dishware_charge_none_with_no_lines() -> None:
    charge = DishwareChargeDefinition(base_mode="NONE", pauschale_per_person_cents=200)
    assert charge.base_mode == "NONE"
    assert charge.additional_lines == ()


def test_dishware_charge_pauschale_with_no_lines() -> None:
    charge = DishwareChargeDefinition(
        base_mode="PAUSCHALE", pauschale_per_person_cents=200
    )
    assert charge.base_mode == "PAUSCHALE"


def test_dishware_charge_none_with_lines() -> None:
    """Explicitly supported: additional lines are independent of base_mode."""
    line = DishwareAdditionalLineDefinition(
        description="Weinglas", quantity=20, unit_net_cents=80
    )
    charge = DishwareChargeDefinition(
        base_mode="NONE", pauschale_per_person_cents=200, additional_lines=(line,)
    )
    assert charge.base_mode == "NONE"
    assert charge.additional_lines == (line,)


def test_dishware_charge_pauschale_with_lines() -> None:
    line = DishwareAdditionalLineDefinition(
        description="Weinglas", quantity=20, unit_net_cents=80
    )
    charge = DishwareChargeDefinition(
        base_mode="PAUSCHALE",
        pauschale_per_person_cents=200,
        additional_lines=(line,),
    )
    assert charge.base_mode == "PAUSCHALE"
    assert charge.additional_lines == (line,)


def test_dishware_charge_pauschale_rate_required_even_when_none() -> None:
    """The rate survives being toggled off — still validated/required."""
    with pytest.raises(ValueError, match="non-negative"):
        DishwareChargeDefinition(base_mode="NONE", pauschale_per_person_cents=-1)


def test_dishware_charge_rejects_invalid_base_mode() -> None:
    with pytest.raises(ValueError, match="invalid charge base_mode"):
        DishwareChargeDefinition(
            base_mode="SOMETHING_ELSE",  # type: ignore[arg-type]
            pauschale_per_person_cents=200,
        )


# --- BuffetChargeDefinition ---------------------------------------------------------


def test_buffet_charge_none() -> None:
    charge = BuffetChargeDefinition(base_mode="NONE", pauschale_per_person_cents=50)
    assert charge.base_mode == "NONE"


def test_buffet_charge_pauschale() -> None:
    charge = BuffetChargeDefinition(
        base_mode="PAUSCHALE", pauschale_per_person_cents=50
    )
    assert charge.base_mode == "PAUSCHALE"


def test_buffet_charge_rejects_invalid_base_mode() -> None:
    with pytest.raises(ValueError, match="invalid charge base_mode"):
        BuffetChargeDefinition(
            base_mode="MAYBE",  # type: ignore[arg-type]
            pauschale_per_person_cents=50,
        )


def test_buffet_charge_rejects_negative_rate() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        BuffetChargeDefinition(base_mode="NONE", pauschale_per_person_cents=-1)


# --- OfferChargesDefinition ----------------------------------------------------------


def test_offer_charges_definition_constructs_with_all_three_required() -> None:
    definition = OfferChargesDefinition(
        delivery=DeliveryChargeDefinition(amount_cents=3500),
        dishware=DishwareChargeDefinition(
            base_mode="NONE", pauschale_per_person_cents=200
        ),
        buffet=BuffetChargeDefinition(base_mode="NONE", pauschale_per_person_cents=50),
    )
    assert definition.delivery.amount_cents == 3500
    assert definition.dishware.base_mode == "NONE"
    assert definition.buffet.base_mode == "NONE"


# --- validate_charge_base_mode -------------------------------------------------------


@pytest.mark.parametrize("value", ["NONE", "PAUSCHALE"])
def test_validate_charge_base_mode_accepts_known_values(value: str) -> None:
    assert validate_charge_base_mode(value) == value


def test_validate_charge_base_mode_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="invalid charge base_mode"):
        validate_charge_base_mode("none")  # lowercase — strict, uppercase-only


# --- boundary --------------------------------------------------------------------------


def test_domain_module_has_no_repository_or_api_imports() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "catering_system"
        / "domain"
        / "offer_charges.py"
    )
    text = source.read_text(encoding="utf-8")
    assert "repositories" not in text
    assert "catering_system.ui" not in text
    assert "catering_system.services" not in text
