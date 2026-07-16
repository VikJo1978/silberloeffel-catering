"""6C-1 — OrderPrintProjection read layer and Küchenzettel v2."""

from __future__ import annotations

from datetime import date

import pytest

from catering_system.services.order_print_projection_service import (
    OrderPrintProjectionService,
    PrintFinalRequiresEffectiveError,
)
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService
from catering_system.ui.office_panel_views import render_print_sheet
from tests.unit.test_offer_service import (
    _INQUIRY_ID,
    _accepted_offer_state,
    _sample_inquiry,
    _world,
)


def _projection_service(
    offers, orders
) -> OrderPrintProjectionService:
    return OrderPrintProjectionService(orders, offers)


def test_order_with_offer_conversion_has_menu_positions() -> None:
    offer, version_id, variant_id, acceptance_id, offers, orders, _inq, service = (
        _accepted_offer_state()
    )
    converted, order, order_version = service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    assert converted.conversion_link is not None

    projection = _projection_service(offers, orders).resolve(
        order.order_id,
        order_version.order_version_id,
    )

    assert projection.commercial.source == "offer_conversion"
    assert len(projection.commercial.positions) == 1
    assert projection.commercial.positions[0].name == "Fingerfood Paket"
    assert projection.commercial.positions[0].description == "Frozen description"
    assert projection.commercial.positions[0].quantity_display == "80 Stück"

    sheet = render_print_sheet(projection)
    assert "MENÜ" in sheet
    assert "Fingerfood Paket" in sheet
    assert "Frozen description" in sheet
    assert "Menge: 80 Stück" in sheet


def test_order_without_offer_has_empty_menu() -> None:
    inquiries, orders, offers, _service = _world(inquiry=_sample_inquiry())
    order_service = OrderService(orders)
    inquiry = inquiries.get_by_id(_INQUIRY_ID)
    assert inquiry is not None
    order, version = order_service.convert_inquiry_to_order(inquiry)

    projection = _projection_service(offers, orders).resolve(
        order.order_id,
        version.order_version_id,
    )

    assert projection.commercial.source == "none"
    assert projection.commercial.positions == ()

    sheet = render_print_sheet(projection)
    assert "Kein Menü hinterlegt" in sheet


def test_new_order_version_uses_version_facts_and_accepted_offer_menu() -> None:
    offer, version_id, variant_id, acceptance_id, offers, orders, _inq, offer_service = (
        _accepted_offer_state()
    )
    _converted, order, v1 = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    order_service = OrderService(orders)
    v2 = order_service.create_relevant_order_change_version(
        order,
        event_date=date(2026, 9, 1),
        time_window_text="abends",
        location_text="Lübeck",
        guest_count_estimate=40,
        planning_mode="caterer_suggestion",
    )

    projection = _projection_service(offers, orders).resolve(
        order.order_id,
        v2.order_version_id,
    )

    assert projection.event.version_number == 2
    assert projection.event.location_text == "Lübeck"
    assert projection.event.guest_count_estimate == 40
    assert projection.commercial.source == "offer_conversion"
    assert projection.commercial.positions[0].name == "Fingerfood Paket"

    sheet = render_print_sheet(projection)
    assert "Lübeck" in sheet
    assert "Version 2" in sheet
    assert "Fingerfood Paket" in sheet


def test_preview_watermark_candidate_entwurf_effective_clear() -> None:
    offer, version_id, variant_id, acceptance_id, offers, orders, _inq, offer_service = (
        _accepted_offer_state()
    )
    _converted, order, order_version = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    order_service = OrderService(orders)
    core = OperationalCoreService(orders)
    order_service.set_candidate_order_version(
        order.order_id, order_version.order_version_id
    )

    service = _projection_service(offers, orders)
    candidate_projection = service.resolve(
        order.order_id,
        order_version.order_version_id,
        intent="preview",
    )
    assert candidate_projection.flags.watermark == "ENTWURF"
    assert candidate_projection.flags.is_preview is True
    assert "ENTWURF" in render_print_sheet(candidate_projection)

    core.confirm_kitchen_print(order.order_id, order_version.order_version_id)
    core.make_order_version_effective(order.order_id, order_version.order_version_id)

    effective_projection = service.resolve(
        order.order_id,
        order_version.order_version_id,
        intent="preview",
    )
    assert effective_projection.flags.watermark is None
    assert effective_projection.flags.is_preview is False
    assert effective_projection.flags.is_final_allowed is True
    assert "ENTWURF" not in render_print_sheet(effective_projection)

    final_projection = service.resolve(
        order.order_id,
        order_version.order_version_id,
        intent="final",
    )
    assert final_projection.flags.intent == "final"
    assert final_projection.flags.is_final_allowed is True


def test_stale_stand_shows_veraltet_watermark() -> None:
    offer, version_id, variant_id, acceptance_id, offers, orders, _inq, offer_service = (
        _accepted_offer_state()
    )
    _converted, order, v1 = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    order_service = OrderService(orders)
    core = OperationalCoreService(orders)
    v2 = order_service.create_relevant_order_change_version(
        order,
        event_date=date(2026, 9, 1),
        time_window_text="abends",
        location_text="Lübeck",
        guest_count_estimate=40,
        planning_mode="caterer_suggestion",
    )
    core.confirm_kitchen_print(order.order_id, v2.order_version_id)
    core.make_order_version_effective(order.order_id, v2.order_version_id)

    projection = _projection_service(offers, orders).resolve(
        order.order_id,
        v1.order_version_id,
        intent="preview",
    )
    assert projection.flags.watermark == "VERALTET"
    assert "VERALTET" in render_print_sheet(projection)


def test_final_intent_requires_effective_version() -> None:
    offer, version_id, variant_id, acceptance_id, offers, orders, _inq, offer_service = (
        _accepted_offer_state()
    )
    _converted, order, order_version = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    service = _projection_service(offers, orders)
    with pytest.raises(PrintFinalRequiresEffectiveError):
        service.resolve(
            order.order_id,
            order_version.order_version_id,
            intent="final",
        )


def test_cancelled_order_shows_storniert_banner_but_remains_readable() -> None:
    offer, version_id, variant_id, acceptance_id, offers, orders, _inq, offer_service = (
        _accepted_offer_state()
    )
    _converted, order, order_version = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    OperationalCoreService(orders).cancel_order(order.order_id)

    projection = _projection_service(offers, orders).resolve(
        order.order_id,
        order_version.order_version_id,
    )
    assert projection.event.order_cancelled_at is not None
    assert projection.flags.is_final_allowed is False

    sheet = render_print_sheet(projection)
    assert "STORNIERT" in sheet
    assert "SILBERLÖFFEL" in sheet
    assert "MENÜ" in sheet
    assert "Fingerfood Paket" in sheet
