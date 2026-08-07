"""Integration test: converted Order → kitchen print → effective → READY_TO_SEND."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from catering_system.domain.order_commercial_snapshot import (
    MissingCommercialSnapshotError,
)
from catering_system.domain.ready_to_send import READY_REASON_NO_EFFECTIVE_VERSION
from catering_system.repositories.in_memory_order_commercial_snapshot_repository import (
    InMemoryOrderCommercialSnapshotRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.repositories.sqlite_order_commercial_snapshot_repository import (
    SQLiteOrderCommercialSnapshotRepository,
)
from catering_system.repositories.sqlite_order_repository import (
    SQLiteOrderRepository,
)
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_print_projection_service import (
    OrderPrintProjectionService,
)
from catering_system.ui.office_panel_views import render_print_sheet
from tests.helpers.order_seed import seed_order
from tests.unit.test_office_api import (
    _MARK_SENT_ARGS,
    _RECORD_ACCEPTANCE_ARGS,
    _VARIANT_ID,
    _convert_accepted_url,
    _mark_sent_url,
    _post,
    _prepare_offer_url,
    _record_acceptance_url,
    _seed,
    _seed_employee_auth,
    _start_api_server,
    _valid_offer_snapshot,
)
from tests.unit.test_offer_service import _sample_inquiry


@pytest.fixture()
def office_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from catering_system.ui import office_api_views

    monkeypatch.setattr(
        office_api_views,
        "berlin_today",
        lambda: date(2026, 7, 15),
    )
    db = tmp_path / "core.db"
    ids = _seed(db)
    _seed_employee_auth(db)
    server, thread, base = _start_api_server(db)
    yield base, ids, db
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    assert thread.is_alive() is False


def _convert_offer_to_order(
    office_api: tuple[str, dict[str, str], Path],
) -> tuple[str, str, str, str]:
    base, ids, _db = office_api
    inquiry_id = ids["inquiry_offer_ready"]

    prepare_status, prepare_body, _headers = _post(
        _prepare_offer_url(base, inquiry_id),
        args={"snapshot": _valid_offer_snapshot(inquiry_id=inquiry_id)},
    )
    assert prepare_status == 201
    offer_id = prepare_body["offer_id"]
    version_id = prepare_body["offer_version_id"]

    assert (
        _post(_mark_sent_url(base, offer_id, version_id), args=_MARK_SENT_ARGS)[0]
        == 200
    )
    accept_status, accept_body, _headers = _post(
        _record_acceptance_url(base, offer_id, version_id),
        args=_RECORD_ACCEPTANCE_ARGS,
    )
    assert accept_status == 200

    convert_status, convert_body, _headers = _post(
        _convert_accepted_url(base, offer_id, version_id),
        args={
            "accepted_variant_id": _VARIANT_ID,
            "acceptance_id": accept_body["acceptance_id"],
        },
    )
    assert convert_status == 201
    return inquiry_id, convert_body["order_id"], convert_body["order_version_id"], base


def test_converted_order_reaches_ready_to_send(office_api: tuple[str, dict[str, str], Path]) -> None:
    _inquiry_id, order_id, order_version_id, base = _convert_offer_to_order(office_api)
    _base, _ids, db = office_api

    orders = SQLiteOrderRepository(db)
    snapshots = SQLiteOrderCommercialSnapshotRepository(db)
    core = OperationalCoreService(orders)

    blocked = core.evaluate_ready_to_send(order_id)
    assert blocked.ready is False
    assert READY_REASON_NO_EFFECTIVE_VERSION in blocked.reasons

    print_status, _print_body, _headers = _post(
        f"{base}/office/v1/orders/{order_id}/print-confirm",
        args={"order_version_id": order_version_id},
    )
    assert print_status == 200

    printed_not_effective = core.evaluate_ready_to_send(order_id)
    assert printed_not_effective.ready is False
    assert READY_REASON_NO_EFFECTIVE_VERSION in printed_not_effective.reasons

    effective_status, _effective_body, _headers = _post(
        f"{base}/office/v1/orders/{order_id}/effective",
        args={"order_version_id": order_version_id},
        expect={
            "current_effective_order_version_id": None,
            "current_candidate_order_version_id": None,
        },
    )
    assert effective_status == 200

    ready = core.evaluate_ready_to_send(order_id)
    assert ready.ready is True
    assert ready.reasons == ()

    projection = OrderPrintProjectionService(orders, snapshots).resolve(
        order_id,
        order_version_id,
    )
    assert projection.commercial.source == "offer_conversion"
    assert render_print_sheet(projection)

    order_before = orders.get_order(order_id)
    assert order_before is not None

    for _ in range(2):
        ready_status, ready_body, _headers = _post(
            f"{base}/office/v1/orders/{order_id}/ready",
        )
        assert ready_status == 200
        assert ready_body["evaluation"]["ready"] is True
        assert ready_body["evaluation"]["reasons"] == []

    order_after = orders.get_order(order_id)
    assert order_after == order_before
    orders.close()
    snapshots.close()


def test_kitchen_print_fails_without_commercial_snapshot() -> None:
    orders = InMemoryOrderRepository()
    snapshots = InMemoryOrderCommercialSnapshotRepository()
    order, version = seed_order(orders, _sample_inquiry())
    service = OrderPrintProjectionService(orders, snapshots)

    with pytest.raises(MissingCommercialSnapshotError):
        render_print_sheet(
            service.resolve(order.order_id, version.order_version_id),
        )
