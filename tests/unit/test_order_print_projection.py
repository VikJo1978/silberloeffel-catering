"""6C-1 — OrderPrintProjection read layer and Küchenzettel v2."""

from __future__ import annotations

from tests.helpers.order_seed import seed_order

from datetime import date

import pytest

from catering_system.services.order_print_projection_service import (
    OrderPrintProjectionService,
    PrintFinalRequiresEffectiveError,
    PrintProjectionNotFoundError,
)
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.repositories.in_memory_offer_repository import (
    InMemoryOfferRepository,
)
from catering_system.repositories.in_memory_order_commercial_snapshot_repository import (
    InMemoryOrderCommercialSnapshotRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.order_service import OrderService
from catering_system.ui.office_panel_views import render_print_sheet
from tests.unit.test_offer_service import (
    _INQUIRY_ID,
    _accepted_offer_state,
    _sample_inquiry,
    _world,
)


def _projection_service(
    offers,
    orders,
    snapshots: InMemoryOrderCommercialSnapshotRepository | None = None,
) -> OrderPrintProjectionService:
    return OrderPrintProjectionService(orders, offers, snapshots)


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

    projection = _projection_service(
        offers, orders, service._commercial_snapshots
    ).resolve(
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
    OrderService(orders)
    inquiry = inquiries.get_by_id(_INQUIRY_ID)
    assert inquiry is not None
    order, version = seed_order(orders, inquiry)

    projection = _projection_service(offers, orders).resolve(
        order.order_id,
        version.order_version_id,
    )

    assert projection.commercial.source == "none"
    assert projection.commercial.positions == ()

    sheet = render_print_sheet(projection)
    assert "Kein Menü hinterlegt" in sheet


def test_new_order_version_uses_version_facts_and_accepted_offer_menu() -> None:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        offers,
        orders,
        _inq,
        offer_service,
    ) = _accepted_offer_state()
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
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        offers,
        orders,
        _inq,
        offer_service,
    ) = _accepted_offer_state()
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


def test_candidate_change_preview_contains_reason_diff_and_frozen_offer_menu() -> None:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        offers,
        orders,
        _inq,
        offer_service,
    ) = _accepted_offer_state()
    _converted, order, v1 = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    core.make_order_version_effective(order.order_id, v1.order_version_id)
    v2 = OrderService(orders).propose_order_version_change(
        order.order_id,
        event_date=v1.event_date,
        time_window_text="18:00",
        location_text=v1.location_text,
        guest_count_estimate=v1.guest_count_estimate,
        planning_mode=v1.planning_mode,
        actor_reference="office-panel",
        change_reason="Beginn verschoben",
    )
    service = _projection_service(offers, orders)
    effective = service.resolve(order.order_id, v1.order_version_id)
    candidate = service.resolve(order.order_id, v2.order_version_id)

    assert candidate.flags.intent == "change_preview"
    assert candidate.flags.watermark == "ÄNDERUNG – NOCH NICHT WIRKSAM"
    assert candidate.event.change_reason == "Beginn verschoben"
    assert candidate.event.changed_fields == ("time_window_text",)
    assert candidate.commercial.positions == effective.commercial.positions
    sheet = render_print_sheet(candidate)
    assert "ÄNDERUNG – NOCH NICHT WIRKSAM" in sheet
    assert "Beginn verschoben" in sheet
    assert "time_window_text" in sheet


def test_stale_stand_shows_veraltet_watermark() -> None:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        offers,
        orders,
        _inq,
        offer_service,
    ) = _accepted_offer_state()
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
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        offers,
        orders,
        _inq,
        offer_service,
    ) = _accepted_offer_state()
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
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        offers,
        orders,
        _inq,
        offer_service,
    ) = _accepted_offer_state()
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


def test_format_quantity_display_per_person_without_guest_count() -> None:
    from decimal import Decimal

    from catering_system.domain.offer import OfferPosition
    from catering_system.services.order_print_projection_service import (
        format_quantity_display,
    )

    position = OfferPosition(
        position_id="p1",
        kind="catalog",
        name="Item",
        unit_net_cents=100,
        net_total_cents=100,
        vat_rate_percent=7,
        vat_amount_cents=7,
        gross_total_cents=107,
        quantity=Decimal("2"),
        quantity_mode="per_person",
        unit_label="Portionen",
    )
    assert format_quantity_display(position, None) == "2 Portionen pro Gast"


def test_format_quantity_display_per_person_with_guest_count() -> None:
    from decimal import Decimal

    from catering_system.domain.offer import OfferPosition
    from catering_system.services.order_print_projection_service import (
        format_quantity_display,
    )

    position = OfferPosition(
        position_id="p1",
        kind="catalog",
        name="Item",
        unit_net_cents=100,
        net_total_cents=100,
        vat_rate_percent=7,
        vat_amount_cents=7,
        gross_total_cents=107,
        quantity=Decimal("2"),
        quantity_mode="per_person",
        unit_label="Portionen",
    )
    assert format_quantity_display(position, 40) == "80 Portionen"


def test_resolve_unknown_order_raises_not_found() -> None:
    offers = InMemoryOfferRepository()
    orders = InMemoryOrderRepository()
    service = _projection_service(offers, orders)
    with pytest.raises(PrintProjectionNotFoundError):
        service.resolve(
            "00000000-0000-4000-8000-000000000000",
            "00000000-0000-4000-8000-000000000001",
        )


def test_format_quantity_display_without_unit_returns_plain_quantity() -> None:
    from decimal import Decimal

    from catering_system.domain.offer import OfferPosition
    from catering_system.services.order_print_projection_service import (
        format_quantity_display,
    )

    position = OfferPosition(
        position_id="p1",
        kind="catalog",
        name="Item",
        unit_net_cents=100,
        net_total_cents=100,
        vat_rate_percent=7,
        vat_amount_cents=7,
        gross_total_cents=107,
        quantity=Decimal("2.5"),
        quantity_mode="total",
    )
    assert format_quantity_display(position, 40) == "2.5"


def test_resolve_foreign_version_raises_not_found() -> None:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        offers,
        orders,
        _inq,
        offer_service,
    ) = _accepted_offer_state()
    _converted, order, order_version = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    service = _projection_service(offers, orders)
    with pytest.raises(PrintProjectionNotFoundError):
        service.resolve(order.order_id, "00000000-0000-4000-8000-000000000099")


def test_commercial_block_is_none_without_conversion_link() -> None:
    offers = InMemoryOfferRepository()
    orders = InMemoryOrderRepository()
    inquiry = _sample_inquiry()
    from catering_system.repositories.in_memory_inquiry_repository import (
        InMemoryInquiryRepository,
    )

    inquiries = InMemoryInquiryRepository()
    inquiries.save(inquiry)
    order, version = seed_order(orders, inquiry)
    projection = _projection_service(offers, orders).resolve(
        order.order_id, version.order_version_id
    )
    assert projection.commercial.source == "none"


def test_commercial_none_when_conversion_link_targets_other_order() -> None:
    from dataclasses import replace

    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        offers,
        orders,
        _inq,
        offer_service,
    ) = _accepted_offer_state()
    _converted, order, order_version = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    stored = offers.get(offer.offer_id)
    assert stored is not None and stored.conversion_link is not None
    bad_link = replace(
        stored.conversion_link,
        order_id="00000000-0000-4000-8000-000000000099",
    )
    offers._offers[offer.offer_id] = replace(stored, conversion_link=bad_link)

    projection = _projection_service(offers, orders).resolve(
        order.order_id,
        order_version.order_version_id,
    )
    assert projection.commercial.source == "none"


def test_commercial_none_when_accepted_variant_lookup_fails() -> None:
    from catering_system.services.order_print_projection_service import (
        _accepted_variant,
    )

    offer, version_id, variant_id, _acceptance_id, _offers, _orders, _inq, _service = (
        _accepted_offer_state()
    )
    assert (
        _accepted_variant(offer, "00000000-0000-4000-8000-000000000077", variant_id)
        is None
    )
    assert (
        _accepted_variant(offer, version_id, "00000000-0000-4000-8000-000000000088")
        is None
    )


def test_preview_entwurf_when_effective_version_record_is_missing() -> None:
    from dataclasses import replace

    inquiries, orders, offers, _service = _world(inquiry=_sample_inquiry())
    inquiry = inquiries.get_by_id(_INQUIRY_ID)
    assert inquiry is not None
    order, version = seed_order(orders, inquiry)
    broken = replace(
        order,
        effective_order_version_id="00000000-0000-4000-8000-000000000077",
        candidate_order_version_id=None,
    )
    orders._orders[order.order_id] = broken

    projection = _projection_service(offers, orders).resolve(
        order.order_id,
        version.order_version_id,
        intent="preview",
    )
    assert projection.flags.watermark == "ENTWURF"


def test_preview_entwurf_for_non_effective_version_without_candidate_parent() -> None:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        offers,
        orders,
        _inq,
        offer_service,
    ) = _accepted_offer_state()
    _converted, order, v1 = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    order_service = OrderService(orders)
    v2 = order_service.create_relevant_order_change_version(
        order,
        event_date=date(2026, 9, 2),
        time_window_text="abends",
        location_text="Kiel",
        guest_count_estimate=30,
        planning_mode="caterer_suggestion",
    )
    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    core.make_order_version_effective(order.order_id, v1.order_version_id)

    projection = _projection_service(offers, orders).resolve(
        order.order_id,
        v2.order_version_id,
        intent="preview",
    )
    assert projection.flags.watermark == "ENTWURF"


def test_commercial_none_when_variant_resolution_returns_none(monkeypatch) -> None:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        offers,
        orders,
        _inq,
        offer_service,
    ) = _accepted_offer_state()
    _converted, order, order_version = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    import catering_system.services.order_print_projection_service as mod

    monkeypatch.setattr(mod, "_accepted_variant", lambda *_args, **_kwargs: None)
    projection = _projection_service(offers, orders).resolve(
        order.order_id,
        order_version.order_version_id,
    )
    assert projection.commercial.source == "none"


def test_print_uses_snapshot_when_offer_repository_unavailable() -> None:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        _offers,
        orders,
        _inq,
        offer_service,
    ) = _accepted_offer_state()
    _converted, order, order_version = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    snapshots = offer_service._commercial_snapshots
    assert snapshots.get_by_order_id(order.order_id) is not None

    class _UnavailableOfferRepository:
        def get_by_source_inquiry_id(self, inquiry_id: str):  # noqa: ANN201
            raise RuntimeError("offer repository unavailable")

    projection = OrderPrintProjectionService(
        orders,
        _UnavailableOfferRepository(),  # type: ignore[arg-type]
        snapshots,
    ).resolve(order.order_id, order_version.order_version_id)

    assert projection.commercial.source == "offer_conversion"
    assert projection.commercial.positions[0].name == "Fingerfood Paket"
    assert projection.commercial.positions[0].description == "Frozen description"
    assert projection.commercial.positions[0].quantity_display == "80 Stück"
    sheet = render_print_sheet(projection)
    assert "Fingerfood Paket" in sheet
    assert "Menge: 80 Stück" in sheet


def test_print_snapshot_immune_to_later_offer_mutation() -> None:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        offers,
        orders,
        _inq,
        offer_service,
    ) = _accepted_offer_state()
    _converted, order, order_version = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    snapshots = offer_service._commercial_snapshots
    from dataclasses import replace

    stored = offers.get(offer.offer_id)
    assert stored is not None
    version = stored.versions[0]
    variant = version.variants[0]
    mutated = replace(
        stored,
        versions=(
            replace(
                version,
                variants=(
                    replace(
                        variant,
                        positions=(
                            replace(variant.positions[0], name="MUTATED LIVE OFFER"),
                        ),
                    ),
                ),
            ),
        ),
    )
    offers._offers[stored.offer_id] = mutated

    projection = _projection_service(offers, orders, snapshots).resolve(
        order.order_id,
        order_version.order_version_id,
    )
    assert projection.commercial.positions[0].name == "Fingerfood Paket"
    assert "MUTATED LIVE OFFER" not in render_print_sheet(projection)


def test_print_legacy_offer_fallback_when_snapshot_missing() -> None:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        offers,
        orders,
        _inq,
        offer_service,
    ) = _accepted_offer_state()
    _converted, order, order_version = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    snapshots = offer_service._commercial_snapshots
    assert snapshots.get_by_order_id(order.order_id) is not None
    snapshots._by_id.clear()
    snapshots._by_order_id.clear()

    projection = _projection_service(offers, orders, snapshots).resolve(
        order.order_id,
        order_version.order_version_id,
    )
    assert projection.commercial.source == "offer_conversion"
    assert projection.commercial.positions[0].name == "Fingerfood Paket"
    assert "Fingerfood Paket" in render_print_sheet(projection)
