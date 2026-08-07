"""Integration test: prepare → sent → accepted → converted order flow."""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

import pytest

from catering_system.domain.offer import derive_offer_state
from catering_system.repositories.sqlite_offer_repository import (
    SQLiteOfferRepository,
)
from catering_system.repositories.sqlite_order_commercial_snapshot_repository import (
    SQLiteOrderCommercialSnapshotRepository,
)
from catering_system.repositories.sqlite_order_repository import (
    SQLiteOrderRepository,
)
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


def test_acceptance_and_conversion_preserve_offer_and_link_order(
    office_api: tuple[str, dict[str, str], Path],
) -> None:
    base, ids, db = office_api
    inquiry_id = ids["inquiry_offer_ready"]

    prepare_status, prepare_body, _headers = _post(
        _prepare_offer_url(base, inquiry_id),
        args={"snapshot": _valid_offer_snapshot(inquiry_id=inquiry_id)},
    )
    assert prepare_status == 201
    offer_id = prepare_body["offer_id"]
    version_id = prepare_body["offer_version_id"]

    offers = SQLiteOfferRepository(db)
    prepared = offers.get(offer_id)
    assert prepared is not None
    before_hash = prepared.versions[0].snapshot_hash
    offers.close()

    assert (
        _post(_mark_sent_url(base, offer_id, version_id), args=_MARK_SENT_ARGS)[0]
        == 200
    )

    accept_status, accept_body, _headers = _post(
        _record_acceptance_url(base, offer_id, version_id),
        args=_RECORD_ACCEPTANCE_ARGS,
    )
    assert accept_status == 200
    acceptance_id = accept_body["acceptance_id"]

    offers = SQLiteOfferRepository(db)
    accepted = offers.get(offer_id)
    assert accepted is not None
    assert accepted.versions[0].snapshot_hash == before_hash
    assert (
        derive_offer_state(accepted, version_id, today=date(2026, 7, 15))
        == "Accepted"
    )
    offers.close()

    convert_args = {
        "accepted_variant_id": _VARIANT_ID,
        "acceptance_id": acceptance_id,
    }
    convert_url = _convert_accepted_url(base, offer_id, version_id)
    convert_status, convert_body, _headers = _post(
        convert_url,
        args=convert_args,
        command_id=str(uuid.uuid4()),
    )
    assert convert_status == 201
    order_id = convert_body["order_id"]

    offers = SQLiteOfferRepository(db)
    converted = offers.get(offer_id)
    assert converted is not None
    assert converted.versions[0].snapshot_hash == before_hash
    assert converted.conversion_link is not None
    assert converted.conversion_link.order_id == order_id
    assert (
        derive_offer_state(converted, version_id, today=date(2026, 7, 15))
        == "Converted"
    )
    offers.close()

    orders = SQLiteOrderRepository(db)
    order = orders.get_order(order_id)
    assert order is not None
    assert order.source_inquiry_id == inquiry_id
    orders.close()

    snapshots = SQLiteOrderCommercialSnapshotRepository(db)
    commercial = snapshots.get_by_order_id(order_id)
    assert commercial is not None
    assert commercial.source_offer_id == offer_id
    assert commercial.source_offer_version_id == version_id
    assert commercial.acceptance_id == acceptance_id
    snapshots.close()

    replay_status, replay_body, _headers = _post(convert_url, args=convert_args)
    assert replay_status == 200
    assert replay_body["order_id"] == order_id

    orders = SQLiteOrderRepository(db)
    inquiry_orders = [
        item for item in orders.list_orders() if item.source_inquiry_id == inquiry_id
    ]
    assert len(inquiry_orders) == 1
    orders.close()


def test_convert_accepted_rejects_prepared_offer(
    office_api: tuple[str, dict[str, str], Path],
) -> None:
    base, ids, db = office_api
    inquiry_id = ids["inquiry_offer_ready"]

    prepare_status, prepare_body, _headers = _post(
        _prepare_offer_url(base, inquiry_id),
        args={"snapshot": _valid_offer_snapshot(inquiry_id=inquiry_id)},
    )
    assert prepare_status == 201

    convert_status, convert_body, _headers = _post(
        _convert_accepted_url(base, prepare_body["offer_id"], prepare_body["offer_version_id"]),
        args={
            "accepted_variant_id": _VARIANT_ID,
            "acceptance_id": str(uuid.uuid4()),
        },
    )
    assert convert_status == 422
    assert convert_body["error"] == "conversion_blocked"

    orders = SQLiteOrderRepository(db)
    assert not any(
        order.source_inquiry_id == inquiry_id for order in orders.list_orders()
    )
    orders.close()
