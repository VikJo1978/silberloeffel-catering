"""Focused presentation tests for the guided Angebot detail page."""

from __future__ import annotations

import re

from catering_system.ui.office_panel_offer_detail import (
    OfferDetailFormFields,
    render_offer_detail,
)
from tests.helpers.office_panel_context import legacy_office_context

_OFFER_ID = "11111111-1111-4111-8111-111111111111"
_VERSION_ID = "22222222-2222-4222-8222-222222222222"
_VARIANT_ID = "33333333-3333-4333-8333-333333333333"


def _detail(state: str) -> dict[str, object]:
    detail: dict[str, object] = {
        "offer_id": _OFFER_ID,
        "inquiry_id": "44444444-4444-4444-8444-444444444444",
        "offer_version_id": _VERSION_ID,
        "commercial_state": state,
        "acceptance_id": None,
        "acceptance": None,
        "versions": [
            {
                "offer_version_id": _VERSION_ID,
                "version": 1,
                "state": state,
                "sent_at": "2026-08-19T14:00:00+00:00" if state != "Prepared" else None,
                "event_date": "2026-09-01",
                "time_window_text": "13:00",
                "location_text": "Glinde",
                "guest_count": 120,
                "planning_mode": "caterer_suggestion",
                "variants": [
                    {
                        "variant_id": _VARIANT_ID,
                        "name": "Variante A",
                        "positions": [
                            {
                                "name": "Fingerfood Paket",
                                "unit_net_cents": 1290,
                                "description": "Frozen description",
                                "composition": "Frozen composition",
                                "allergen_labels": ["Gluten", "Milch"],
                                "allergens_unknown": False,
                            }
                        ],
                    }
                ],
            }
        ],
        "history": [
            {
                "at": "2026-08-19T13:00:00+00:00",
                "label": "Version 1 vorbereitet",
            }
        ],
    }
    if state == "Accepted":
        detail["acceptance_id"] = "55555555-5555-4555-8555-555555555555"
        detail["acceptance"] = {"accepted_variant_id": _VARIANT_ID}
    if state == "Converted":
        detail["order_id"] = "66666666-6666-4666-8666-666666666666"
    return detail


def _render(state: str, *, revision_url: str | None = "/configurator/revision") -> str:
    return render_offer_detail(
        _detail(state),
        context=legacy_office_context(),
        forms=OfferDetailFormFields(
            csrf_input='<input type="hidden" name="csrf" value="x">',
            command_fields='<input type="hidden" name="command_id" value="y">',
        ),
        revision_prefill_url=revision_url,
    )


def test_prepared_is_status_first_with_one_guided_next_step() -> None:
    html = _render("Prepared")

    assert 'class="offer-status-badge">Vorbereitet<' in html
    assert 'class="offer-next-label">Nächster Schritt<' in html
    assert "Angebot als gesendet markieren" in html
    assert "/mark-sent" in html
    assert "/record-acceptance" not in html
    assert html.index("Vorbereitet") < html.index("Als gesendet markieren")
    assert re.search(r'href="/angebote"[^>]*aria-current="page"', html)


def test_sent_keeps_acceptance_primary_and_subordinates_other_actions() -> None:
    html = _render("Sent")

    assert "Kundenentscheidung erfassen" in html
    assert "/record-acceptance" in html
    assert "<summary>Weitere Aktionen</summary>" in html
    assert "/record-rejection" in html
    assert "/record-withdrawal" in html
    assert "Neue Version vorbereiten" in html
    assert html.index("/record-acceptance") < html.index("Weitere Aktionen")


def test_positions_are_collapsed_without_losing_frozen_content() -> None:
    html = _render("Sent")

    assert '<details class="offer-position-detail">' in html
    assert "Fingerfood Paket" in html
    assert "Frozen description" in html
    assert "Zusammensetzung:</strong> Frozen composition" in html
    assert "Gluten" in html
    assert "Details, Zusammensetzung und Allergene nur bei Bedarf öffnen." in html


def test_accepted_and_converted_keep_existing_lifecycle_targets() -> None:
    accepted = _render("Accepted")
    assert "In Auftrag umwandeln" in accepted
    assert "/convert" in accepted
    assert "/record-acceptance" not in accepted

    converted = _render("Converted")
    assert "Auftrag erstellt" in converted
    assert "/order/66666666-6666-4666-8666-666666666666" in converted
    assert "/convert" not in converted
