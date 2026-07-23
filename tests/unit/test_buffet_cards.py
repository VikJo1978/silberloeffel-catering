"""6C-2 — Buffetschilder v1 over OrderPrintProjection."""

from __future__ import annotations

from tests.helpers.order_seed import seed_order

from datetime import UTC, date, datetime

import pytest

from catering_system.domain.offer_snapshot import compute_snapshot_hash
from catering_system.services.buffet_cards_service import BuffetCardsService
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_print_projection_service import (
    OrderPrintProjection,
    OrderPrintProjectionService,
    PrintCommercialBlock,
    PrintEventBlock,
    PrintFlagsBlock,
    PrintPositionLine,
)
from catering_system.services.order_service import OrderService
from catering_system.ui.office_panel_views import render_buffet_cards
from tests.unit.test_offer_service import (
    _INQUIRY_ID,
    _POSITION_ID,
    _VARIANT_ID,
    _accepted_offer_state,
    _position,
    _sample_inquiry,
    _valid_snapshot,
    _world,
)

_NOW = datetime(2026, 7, 15, 8, 30, tzinfo=UTC)
_POSITION_2 = "88888888-8888-4888-8888-888888888882"
_POSITION_3 = "88888888-8888-4888-8888-888888888883"


def _event_block(**overrides: object) -> PrintEventBlock:
    base = {
        "order_id": "11111111-1111-4111-8111-111111111111",
        "order_version_id": "22222222-2222-4222-8222-222222222222",
        "version_number": 2,
        "event_date": date(2026, 8, 15),
        "time_window_text": "mittags",
        "location_text": "Hamburg",
        "guest_count_estimate": 120,
        "planning_mode": "caterer_suggestion",
        "kitchen_print_confirmed_at": None,
        "order_cancelled_at": None,
        "is_candidate": False,
        "is_effective": True,
    }
    base.update(overrides)
    return PrintEventBlock(**base)  # type: ignore[arg-type]


def _projection(
    *,
    positions: tuple[PrintPositionLine, ...] = (),
    flags: PrintFlagsBlock | None = None,
    event: PrintEventBlock | None = None,
) -> OrderPrintProjection:
    return OrderPrintProjection(
        event=event or _event_block(),
        commercial=PrintCommercialBlock(source="offer_conversion", positions=positions),
        flags=flags
        or PrintFlagsBlock(
            intent="preview",
            is_preview=False,
            is_final_allowed=True,
            is_stale=False,
            watermark=None,
        ),
    )


def _position_line(
    *,
    position_id: str,
    name: str,
    description: str | None = None,
    composition: str | None = None,
) -> PrintPositionLine:
    return PrintPositionLine(
        position_id=position_id,
        kind="catalog",
        name=name,
        description=description,
        composition=composition,
        notes=None,
        quantity_display=None,
        unit_label=None,
    )


def _three_position_snapshot() -> dict[str, object]:
    payload = _valid_snapshot()
    variant = dict(payload["variants"][0])  # type: ignore[index]
    positions = [
        _position(),
        {
            **_position(),
            "position_id": _POSITION_2,
            "name": "Kartoffelsalat",
            "description": "Hausgemacht",
            "composition": "Kartoffeln, Gurken, Mayo",
        },
        {
            **_position(),
            "position_id": _POSITION_3,
            "name": "Obstsalat",
            "description": "Frisch",
            "composition": "Saisonobst",
        },
    ]
    variant["positions"] = positions
    variant["totals"] = {
        "net_cents": 69600,
        "vat_7_base_cents": 69600,
        "vat_7_amount_cents": 4872,
        "vat_19_base_cents": 0,
        "vat_19_amount_cents": 0,
        "gross_cents": 74472,
    }
    payload["variants"] = [variant]
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    return payload


def _buffet_service(
    orders,
    snapshots,
) -> BuffetCardsService:
    return BuffetCardsService(
        orders,
        OrderPrintProjectionService(orders, snapshots),
    )


def test_buffet_cards_render_positions() -> None:
    projection = _projection(
        positions=(
            _position_line(
                position_id=_POSITION_ID,
                name="Rinderrouladen",
                description="Hausgemachte Rinderrouladen",
                composition="mit Sauce und Beilage",
            ),
            _position_line(
                position_id=_POSITION_2,
                name="Kartoffelsalat",
                description="Hausgemacht",
            ),
            _position_line(
                position_id=_POSITION_3,
                name="Obstsalat",
                description="Frisch",
            ),
        )
    )

    html = render_buffet_cards(projection, projection.commercial.positions)

    assert html.count('class="buffet-card"') == 3
    assert "Rinderrouladen" in html
    assert "Hausgemachte Rinderrouladen" in html
    assert "mit Sauce und Beilage" in html
    assert "Kartoffelsalat" in html
    assert "Obstsalat" in html
    assert "Version 2" in html
    assert "SILBERLÖFFEL" in html


def test_buffet_cards_without_menu() -> None:
    projection = OrderPrintProjection(
        event=_event_block(),
        commercial=PrintCommercialBlock(source="none"),
        flags=PrintFlagsBlock(
            intent="preview",
            is_preview=True,
            is_final_allowed=False,
            is_stale=False,
            watermark="ENTWURF",
        ),
    )

    html = render_buffet_cards(projection, ())

    assert "Kein Menü hinterlegt" in html
    assert 'class="buffet-card"' not in html


def test_buffet_cards_candidate_has_entwurf() -> None:
    projection = _projection(
        positions=(
            _position_line(
                position_id=_POSITION_ID,
                name="Rinderrouladen",
                description="Hausgemacht",
            ),
        ),
        event=_event_block(is_candidate=True, is_effective=False, version_number=2),
        flags=PrintFlagsBlock(
            intent="preview",
            is_preview=True,
            is_final_allowed=False,
            is_stale=False,
            watermark="ENTWURF",
        ),
    )

    html = render_buffet_cards(projection, projection.commercial.positions)

    assert "ENTWURF" in html
    assert "Stand Version 2" in html


def test_buffet_cards_effective_is_final() -> None:
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
    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, order_version.order_version_id)
    core.make_order_version_effective(order.order_id, order_version.order_version_id)

    view = _buffet_service(orders, offer_service._commercial_snapshots).resolve(
        order.order_id,
        order_version.order_version_id,
    )
    html = render_buffet_cards(
        view.projection,
        view.cards,
        effective_version_number=view.effective_version_number,
    )

    assert view.projection.flags.watermark is None
    assert view.projection.event.is_effective is True
    assert "ENTWURF" not in html
    assert "VERALTET" not in html
    assert "Fingerfood Paket" in html


def test_buffet_cards_old_version_is_veraltet() -> None:
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

    view = _buffet_service(orders, offer_service._commercial_snapshots).resolve(
        order.order_id, v1.order_version_id
    )
    html = render_buffet_cards(
        view.projection,
        view.cards,
        effective_version_number=view.effective_version_number,
    )

    assert view.projection.flags.watermark == "VERALTET"
    assert view.effective_version_number == 2
    assert "VERALTET" in html
    assert "Aktueller Küchenstand:" in html
    assert "Version 2" in html


def test_buffet_cards_from_conversion_link() -> None:
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

    view = _buffet_service(orders, offer_service._commercial_snapshots).resolve(
        order.order_id,
        order_version.order_version_id,
    )

    assert view.projection.commercial.source == "offer_conversion"
    assert len(view.cards) == 1
    assert view.cards[0].name == "Fingerfood Paket"
    assert view.cards[0].description == "Frozen description"


def test_buffet_cards_three_positions_from_offer_snapshot() -> None:
    _inquiries, orders, offers, service = _world(inquiry=_sample_inquiry())
    offer = service.prepare_offer_version(_INQUIRY_ID, _three_position_snapshot())
    version_id = offer.versions[0].offer_version_id
    service.record_sent_evidence(offer.offer_id, version_id, **_record_args())
    updated = service.record_acceptance_evidence(
        offer.offer_id,
        version_id,
        _VARIANT_ID,
        **_acceptance_args(),
    )
    assert updated.acceptance_evidence is not None
    _converted, order, order_version = service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        _VARIANT_ID,
        updated.acceptance_evidence.acceptance_id,
    )

    view = _buffet_service(orders, service._commercial_snapshots).resolve(
        order.order_id,
        order_version.order_version_id,
    )

    assert len(view.cards) == 3
    names = {card.name for card in view.cards}
    assert names == {"Fingerfood Paket", "Kartoffelsalat", "Obstsalat"}


def test_buffet_cards_fail_when_commercial_snapshot_missing() -> None:
    from catering_system.domain.order_commercial_snapshot import (
        MissingCommercialSnapshotError,
    )
    from catering_system.repositories.in_memory_order_commercial_snapshot_repository import (
        InMemoryOrderCommercialSnapshotRepository,
    )

    inquiries, orders, _offers, _service = _world(inquiry=_sample_inquiry())
    OrderService(orders)
    inquiry = inquiries.get_by_id(_INQUIRY_ID)
    assert inquiry is not None
    order, version = seed_order(orders, inquiry)

    with pytest.raises(MissingCommercialSnapshotError):
        _buffet_service(orders, InMemoryOrderCommercialSnapshotRepository()).resolve(
            order.order_id,
            version.order_version_id,
        )


def _record_args() -> dict[str, object]:
    from tests.unit.test_offer_service import _record_args as record_args

    return record_args()


def _acceptance_args() -> dict[str, object]:
    from tests.unit.test_offer_service import _acceptance_args as acceptance_args

    return acceptance_args()
