"""6C-1 — OrderPrintProjection read layer and Küchenzettel v2."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry_customer_snapshot import InquiryCustomerSnapshot
from catering_system.domain.order_commercial_snapshot import (
    MissingCommercialSnapshotError,
)
from catering_system.domain.order_confirmation_document import (
    SCHEMA_VERSION_V3,
    OrderConfirmationDocumentSnapshot,
)
from catering_system.repositories.in_memory_order_commercial_snapshot_repository import (
    InMemoryOrderCommercialSnapshotRepository,
)
from catering_system.repositories.in_memory_order_confirmation_document_repository import (
    InMemoryOrderConfirmationDocumentRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_print_projection_service import (
    OrderPrintProjectionService,
    PrintFinalRequiresEffectiveError,
    PrintProjectionNotFoundError,
)
from catering_system.services.order_service import OrderService
from catering_system.ui.office_panel_views import render_print_sheet
from tests.helpers.order_seed import seed_order
from tests.unit.test_offer_service import (
    _INQUIRY_ID,
    _accepted_offer_state,
    _sample_inquiry,
    _world,
)


def _projection_service(
    orders,
    snapshots: InMemoryOrderCommercialSnapshotRepository,
    confirmations: InMemoryOrderConfirmationDocumentRepository | None = None,
) -> OrderPrintProjectionService:
    return OrderPrintProjectionService(orders, snapshots, confirmations)


def _insert_confirmation_snapshot(
    confirmations: InMemoryOrderConfirmationDocumentRepository,
    *,
    order_id: str,
    order_version_id: str,
    event_date: date,
    gross_total_cents: int = 32109,
    payment_method: str = "RECHNUNG",
    company_name: str = "Müller GmbH",
    contact_name: str = "Anna Müller",
    phone: str = "+49 40 123456",
) -> None:
    address = CustomerAddress(
        street="Alter Wall 22",
        postal_code="20457",
        city="Hamburg",
        country="Deutschland",
    )
    confirmations.insert(
        OrderConfirmationDocumentSnapshot(
            document_snapshot_id=f"doc-{order_version_id}",
            order_id=order_id,
            order_version_id=order_version_id,
            offer_id="offer-1",
            offer_version_id="offer-version-1",
            document_reference="AB-TEST-V1",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            created_by="office",
            recipient_name=contact_name,
            recipient_email="anna.mueller@example.invalid",
            recipient_company=company_name,
            recipient_phone=phone,
            recipient_status="ready",
            event_date=event_date,
            time_window_text="12:00–13:00",
            location_text="Hamburg",
            guest_count_estimate=35,
            planning_mode="caterer_suggestion",
            positions=(),
            vat_buckets=(),
            net_total_cents=30000,
            vat_total_cents=gross_total_cents - 30000,
            gross_total_cents=gross_total_cents,
            payment_method=payment_method,
            payment_customer_visible_text="Zahlung laut Vereinbarung.",
            document_hash="sha256:" + ("0" * 64),
            schema_version=SCHEMA_VERSION_V3,
            invoice_address=address,
            delivery_address=address,
            delivery_address_differs=False,
            fulfillment_mode="DELIVERY",
        )
    )


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

    projection = _projection_service(orders, service._commercial_snapshots).resolve(
        order.order_id,
        order_version.order_version_id,
    )

    assert projection.commercial.source == "offer_conversion"
    assert len(projection.commercial.positions) == 1
    assert projection.commercial.positions[0].name == "Fingerfood Paket"
    assert projection.commercial.positions[0].description == "Frozen description"
    assert projection.commercial.positions[0].quantity_display == "80 Stück"

    sheet = render_print_sheet(projection)
    assert "Bestellung / Menü" in sheet
    assert "@page{size:A4 portrait" in sheet
    assert "Version 1" in sheet
    assert "Fingerfood Paket" in sheet
    assert "Frozen description" in sheet
    assert "80 Stück" in sheet
    assert "Frozen customization" in sheet
    assert "Stand Version" not in sheet
    assert "guest_count_estimate" not in sheet
    assert "caterer_suggestion" not in sheet
    assert order.order_id not in sheet
    assert order_version.order_version_id not in sheet


def test_kitchen_sheet_shows_existing_customer_contact_and_delivery_address() -> None:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        _offers,
        orders,
        inquiries,
        service,
    ) = _accepted_offer_state()
    inquiry = inquiries.get_by_id(_INQUIRY_ID)
    assert inquiry is not None
    inquiries.update(
        replace(
            inquiry,
            customer_snapshot=InquiryCustomerSnapshot(
                company_name="Müller GmbH",
                contact_name="Anna Müller",
                email="anna.mueller@example.invalid",
                phone="+49 40 123456",
                invoice_address=CustomerAddress(
                    street="Alter Wall 22",
                    postal_code="20457",
                    city="Hamburg",
                    country="Deutschland",
                ),
                delivery_address_mode="SAME_AS_INVOICE",
            ),
        )
    )
    _converted, order, order_version = service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    inquiries.update(
        replace(
            inquiry,
            customer_snapshot=InquiryCustomerSnapshot(
                company_name="Live Mutation GmbH",
                contact_name="Live Mutation",
                email="live@example.invalid",
                phone="+49 40 999999",
                invoice_address=CustomerAddress(
                    street="Mutable Weg 1",
                    postal_code="99999",
                    city="Geändert",
                    country="Deutschland",
                ),
                delivery_address_mode="SAME_AS_INVOICE",
            ),
        )
    )

    projection = _projection_service(
        orders,
        service._commercial_snapshots,
    ).resolve(order.order_id, order_version.order_version_id)
    sheet = render_print_sheet(projection)

    assert "Müller GmbH" in sheet
    assert "Anna Müller" in sheet
    assert "+49 40 123456" in sheet
    assert "Alter Wall 22" in sheet
    assert "20457 Hamburg" in sheet
    assert "Deutschland" in sheet
    assert "Live Mutation" not in sheet
    assert "Mutable Weg" not in sheet
    assert "Sonstiges" not in sheet


def test_kitchen_sheet_missing_operational_context_shows_blank_facts() -> None:
    offer, version_id, variant_id, acceptance_id, _offers, orders, _inq, service = (
        _accepted_offer_state()
    )
    _converted, order, version = service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    orders._operational_contexts.pop(version.order_version_id, None)
    projection = _projection_service(orders, service._commercial_snapshots).resolve(
        order.order_id,
        version.order_version_id,
    )

    sheet = render_print_sheet(projection)

    assert "<dt>Kunde / Firma</dt><dd>–</dd>" in sheet
    assert "<dt>Ansprechpartner</dt><dd>–</dd>" in sheet
    assert "<dt>Telefonnummer</dt><dd>–</dd>" in sheet
    assert "<dt>Lieferadresse</dt><dd>–</dd>" in sheet


def test_kitchen_sheet_cash_block_only_for_barzahlung() -> None:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        _offers,
        orders,
        _inquiries,
        service,
    ) = _accepted_offer_state()
    _converted, order, order_version = service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    snapshots = service._commercial_snapshots
    invoice_projection = _projection_service(orders, snapshots).resolve(
        order.order_id,
        order_version.order_version_id,
    )
    assert "BARZAHLUNG" not in render_print_sheet(invoice_projection)

    snapshot = snapshots.get_by_order_id(order.order_id)
    assert snapshot is not None
    cash_snapshot = replace(snapshot, payment_method="BAR_VOR_ORT")
    snapshots._by_id[snapshot.snapshot_id] = cash_snapshot
    cash_projection = _projection_service(orders, snapshots).resolve(
        order.order_id,
        order_version.order_version_id,
    )
    sheet = render_print_sheet(cash_projection)

    assert "BARZAHLUNG – BEIM KUNDEN KASSIEREN" in sheet
    assert "RECHNUNG MITNEHMEN UND DEM KUNDEN ÜBERGEBEN" in sheet

    confirmations = InMemoryOrderConfirmationDocumentRepository()
    _insert_confirmation_snapshot(
        confirmations,
        order_id=order.order_id,
        order_version_id=order_version.order_version_id,
        event_date=order_version.event_date,
        gross_total_cents=43210,
        payment_method="BAR_VOR_ORT",
    )
    cash_projection_with_amount = _projection_service(
        orders,
        snapshots,
        confirmations,
    ).resolve(order.order_id, order_version.order_version_id)
    sheet = render_print_sheet(cash_projection_with_amount)

    assert "BARZAHLUNG – 432,10 € KASSIEREN" in sheet
    assert "BARZAHLUNG – BEIM KUNDEN KASSIEREN" not in sheet
    assert "RECHNUNG MITNEHMEN UND DEM KUNDEN ÜBERGEBEN" in sheet


def test_print_fails_when_commercial_snapshot_missing_for_seeded_order() -> None:
    inquiries, orders, _offers, _service = _world(inquiry=_sample_inquiry())
    OrderService(orders)
    inquiry = inquiries.get_by_id(_INQUIRY_ID)
    assert inquiry is not None
    order, version = seed_order(orders, inquiry)
    snapshots = InMemoryOrderCommercialSnapshotRepository()

    with pytest.raises(MissingCommercialSnapshotError):
        _projection_service(orders, snapshots).resolve(
            order.order_id,
            version.order_version_id,
        )


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

    projection = _projection_service(
        orders, offer_service._commercial_snapshots
    ).resolve(
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
    assert "Stand Version" not in sheet
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

    service = _projection_service(orders, offer_service._commercial_snapshots)
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
    intermediate = OrderService(orders).propose_order_version_change(
        order.order_id,
        event_date=v1.event_date,
        time_window_text=v1.time_window_text,
        location_text=v1.location_text,
        guest_count_estimate=35,
        planning_mode=v1.planning_mode,
        actor_reference="office-panel",
        change_reason="Anzahl geändert",
    )
    core.confirm_kitchen_print(order.order_id, intermediate.order_version_id)
    core.make_order_version_effective(order.order_id, intermediate.order_version_id)
    v2 = OrderService(orders).propose_order_version_change(
        order.order_id,
        event_date=intermediate.event_date,
        time_window_text=intermediate.time_window_text,
        location_text=intermediate.location_text,
        guest_count_estimate=40,
        planning_mode=intermediate.planning_mode,
        actor_reference="office-panel",
        change_reason="anzahl",
    )
    service = _projection_service(orders, offer_service._commercial_snapshots)
    effective = service.resolve(order.order_id, intermediate.order_version_id)
    candidate = service.resolve(order.order_id, v2.order_version_id)

    assert candidate.flags.intent == "change_preview"
    assert candidate.flags.watermark == "ÄNDERUNG – NOCH NICHT WIRKSAM"
    assert candidate.event.change_reason == "anzahl"
    assert candidate.event.changed_fields == ("guest_count_estimate",)
    assert candidate.commercial.positions == effective.commercial.positions
    sheet = render_print_sheet(candidate)
    assert "ÄNDERUNG – NOCH NICHT WIRKSAM" in sheet
    assert "Version 3" in sheet
    assert "Gästezahl geändert: 35 → 40" in sheet
    assert "Anzahl geändert" not in sheet
    assert "anzahl" not in sheet
    assert "guest_count_estimate" not in sheet


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

    projection = _projection_service(
        orders, offer_service._commercial_snapshots
    ).resolve(
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
    service = _projection_service(orders, offer_service._commercial_snapshots)
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

    projection = _projection_service(
        orders, offer_service._commercial_snapshots
    ).resolve(
        order.order_id,
        order_version.order_version_id,
    )
    assert projection.event.order_cancelled_at is not None
    assert projection.flags.is_final_allowed is False

    sheet = render_print_sheet(projection)
    assert "STORNIERT" in sheet
    assert "SILBERLÖFFEL" in sheet
    assert "Bestellung / Menü" in sheet
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
    orders = InMemoryOrderRepository()
    snapshots = InMemoryOrderCommercialSnapshotRepository()
    service = _projection_service(orders, snapshots)
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
    service = _projection_service(orders, offer_service._commercial_snapshots)
    with pytest.raises(PrintProjectionNotFoundError):
        service.resolve(order.order_id, "00000000-0000-4000-8000-000000000099")


def test_preview_entwurf_when_effective_version_record_is_missing() -> None:
    from dataclasses import replace

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
    _converted, order, version = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    broken = replace(
        order,
        effective_order_version_id="00000000-0000-4000-8000-000000000077",
        candidate_order_version_id=None,
    )
    orders._orders[order.order_id] = broken

    projection = _projection_service(
        orders, offer_service._commercial_snapshots
    ).resolve(
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

    projection = _projection_service(
        orders, offer_service._commercial_snapshots
    ).resolve(
        order.order_id,
        v2.order_version_id,
        intent="preview",
    )
    assert projection.flags.watermark == "ENTWURF"


def test_print_uses_snapshot_when_offer_repository_unavailable() -> None:
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
    offers._offers.clear()

    projection = _projection_service(orders, snapshots).resolve(
        order.order_id, order_version.order_version_id
    )

    assert projection.commercial.source == "offer_conversion"
    assert projection.commercial.positions[0].name == "Fingerfood Paket"
    assert projection.commercial.positions[0].description == "Frozen description"
    assert projection.commercial.positions[0].quantity_display == "80 Stück"
    sheet = render_print_sheet(projection)
    assert "Fingerfood Paket" in sheet
    assert "80 Stück" in sheet


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

    projection = _projection_service(orders, snapshots).resolve(
        order.order_id,
        order_version.order_version_id,
    )
    assert projection.commercial.positions[0].name == "Fingerfood Paket"
    assert "MUTATED LIVE OFFER" not in render_print_sheet(projection)


def test_print_fails_when_commercial_snapshot_missing_after_convert() -> None:
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
    assert offers.get(offer.offer_id) is not None
    snapshots._by_id.clear()
    snapshots._by_order_id.clear()
    # OfferRepository still has the Offer — must not hide missing Snapshot.
    assert offers.get(offer.offer_id) is not None

    with pytest.raises(MissingCommercialSnapshotError):
        _projection_service(orders, snapshots).resolve(
            order.order_id,
            order_version.order_version_id,
        )


def test_print_and_confirmation_services_must_not_depend_on_offer_or_conversion_link() -> (
    None
):
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "src" / "catering_system" / "services"
    for name in (
        "order_print_projection_service.py",
        "order_confirmation_document_service.py",
    ):
        text = (root / name).read_text(encoding="utf-8")
        assert "OfferRepository" not in text, name
        assert "conversion_link" not in text, name


def _kitchen_job_setup():
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
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    core.make_order_version_effective(order.order_id, v1.order_version_id)
    v2 = order_service.create_relevant_order_change_version(
        order,
        event_date=date(2026, 9, 1),
        time_window_text="abends",
        location_text="Lübeck",
        guest_count_estimate=40,
        planning_mode="caterer_suggestion",
    )
    order_service.set_candidate_order_version(order.order_id, v2.order_version_id)
    service = _projection_service(orders, offer_service._commercial_snapshots)
    return offer, order, v1, v2, offers, service


def test_kitchen_job_intent_uses_requested_version_not_effective() -> None:
    _offer, order, v1, v2, _offers, service = _kitchen_job_setup()

    projection = service.resolve(
        order.order_id,
        v2.order_version_id,
        intent="kitchen_job",
    )

    assert projection.event.order_version_id == v2.order_version_id
    assert projection.event.version_number == 2
    assert projection.event.location_text == "Lübeck"
    assert projection.event.is_effective is False
    assert projection.event.is_candidate is True


def test_kitchen_job_intent_has_no_ui_watermarks() -> None:
    _offer, order, _v1, v2, _offers, service = _kitchen_job_setup()

    projection = service.resolve(
        order.order_id,
        v2.order_version_id,
        intent="kitchen_job",
    )

    assert projection.flags.intent == "kitchen_job"
    assert projection.flags.watermark is None
    assert projection.flags.is_preview is False
    assert projection.flags.is_stale is False
    assert projection.flags.is_final_allowed is False
    assert "ENTWURF" not in render_print_sheet(projection)
    assert "VERALTET" not in render_print_sheet(projection)
    assert "ÄNDERUNG" not in render_print_sheet(projection)


def test_kitchen_job_intent_keeps_frozen_commercial_snapshot() -> None:
    from dataclasses import replace

    offer, order, _v1, v2, offers, service = _kitchen_job_setup()
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

    projection = service.resolve(
        order.order_id,
        v2.order_version_id,
        intent="kitchen_job",
    )

    assert projection.commercial.positions[0].name == "Fingerfood Paket"
    assert "MUTATED LIVE OFFER" not in render_print_sheet(projection)


def test_kitchen_job_does_not_change_preview_change_preview_or_final_intents() -> None:
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
    service = _projection_service(orders, offer_service._commercial_snapshots)

    preview = service.resolve(order.order_id, v2.order_version_id, intent="preview")
    change_preview = service.resolve(order.order_id, v2.order_version_id)
    final = service.resolve(order.order_id, v1.order_version_id, intent="final")

    assert preview.flags.intent == "change_preview"
    assert preview.flags.watermark == "ÄNDERUNG – NOCH NICHT WIRKSAM"
    assert change_preview.flags.intent == "change_preview"
    assert final.flags.intent == "final"
    assert final.flags.is_final_allowed is True
