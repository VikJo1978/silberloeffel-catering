"""Unit tests — Office Panel Offer Detail internal-only budget block.

Tests the private ``_budget_block`` renderer directly against the
``surface`` dict shape produced by ``office_api_views.offer_detail`` (one
version's dict, as consumed by ``render_offer_detail``). Never appears in
any customer-facing document.
"""

from __future__ import annotations

from catering_system.ui.office_panel_offer_detail import _budget_block


def test_no_budget_definition_renders_nothing() -> None:
    assert _budget_block({"guest_count": 80}) == ""


def test_total_budget_renders_verfuegbar() -> None:
    html = _budget_block(
        {
            "budget_definition": {
                "amount_cents": 30000,
                "type": "TOTAL",
                "tax_basis": "GROSS",
                "cost_scope": "FULL_OFFER",
                "comparison_amount_cents": 24824,
                "remaining_cents": 5176,
                "over": False,
            }
        }
    )
    assert "Budget (intern)" in html
    assert "300,00 €" in html
    assert "brutto" in html
    assert "mit allen Kosten" in html
    assert "248,24 €" in html
    assert "Verfügbar" in html
    assert "51,76 €" in html
    assert "Überschritten" not in html
    # Never per-person suffix for TOTAL.
    assert "/ Person" not in html


def test_per_person_budget_renders_ueberschritten_and_suffix() -> None:
    html = _budget_block(
        {
            "budget_definition": {
                "amount_cents": 3500,
                "type": "PER_PERSON",
                "tax_basis": "GROSS",
                "cost_scope": "FULL_OFFER",
                "comparison_amount_cents": 3644,
                "remaining_cents": -144,
                "over": True,
            }
        }
    )
    assert "35,00 €" in html
    assert "/ Person" in html
    assert "36,44 €" in html
    assert "Überschritten" in html
    assert "1,44 €" in html
    assert "Verfügbar" not in html


def test_positions_only_net_label() -> None:
    html = _budget_block(
        {
            "budget_definition": {
                "amount_cents": 20000,
                "type": "TOTAL",
                "tax_basis": "NET",
                "cost_scope": "POSITIONS_ONLY",
                "comparison_amount_cents": 23200,
                "remaining_cents": -3200,
                "over": True,
            }
        }
    )
    assert "netto" in html
    assert "nur Positionen" in html


def test_unknown_guest_count_shows_placeholder_not_crash() -> None:
    html = _budget_block(
        {
            "budget_definition": {
                "amount_cents": 3500,
                "type": "PER_PERSON",
                "tax_basis": "GROSS",
                "cost_scope": "FULL_OFFER",
                "comparison_amount_cents": None,
                "remaining_cents": None,
                "over": None,
            }
        }
    )
    assert "Gästezahl noch offen" in html
    assert "Verfügbar" not in html
    assert "Überschritten" not in html


def test_budget_block_escapes_html() -> None:
    # amount_cents/type/etc are always machine-produced enums/ints here, but
    # the renderer must still not be trivially breakable if that ever
    # changes — assert no raw "<" from arbitrary label lookups leaks in for
    # an unrecognized tax_basis/cost_scope value.
    html = _budget_block(
        {
            "budget_definition": {
                "amount_cents": 100,
                "type": "TOTAL",
                "tax_basis": "<script>",
                "cost_scope": "<script>",
                "comparison_amount_cents": 0,
                "remaining_cents": 100,
                "over": False,
            }
        }
    )
    assert "<script>" not in html
