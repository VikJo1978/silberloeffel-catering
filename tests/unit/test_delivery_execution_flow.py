"""Integration test: kitchen completion → delivery queue → dispatch → completion."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from catering_system.repositories.sqlite_delivery_completion_evidence_repository import (
    SQLiteDeliveryCompletionEvidenceRepository,
)
from catering_system.repositories.sqlite_dispatch_evidence_repository import (
    SQLiteDispatchEvidenceRepository,
)
from catering_system.repositories.sqlite_order_delivery_snapshot_repository import (
    SQLiteOrderDeliverySnapshotRepository,
)
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository
from tests.unit.test_office_api import (
    _MARK_SENT_ARGS,
    _RECORD_ACCEPTANCE_ARGS,
    _VARIANT_ID,
    _convert_accepted_url,
    _get,
    _mark_sent_url,
    _post,
    _prepare_offer_url,
    _record_acceptance_url,
    _seed,
    _seed_employee_auth,
    _start_api_server,
    _valid_offer_snapshot,
)

_DISPATCHED_AT = datetime(2026, 8, 7, 15, 0, tzinfo=UTC)
_COMPLETED_AT = datetime(2026, 8, 7, 16, 0, tzinfo=UTC)


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


def _release_and_complete_kitchen(
    office_api: tuple[str, dict[str, str], Path],
) -> tuple[str, str, str]:
    base, ids, _db = office_api
    inquiry_id = ids["inquiry_offer_ready"]

    detail = _get(f"{base}/office/v1/inquiries/{inquiry_id}")[1]
    assert (
        _post(
            f"{base}/office/v1/inquiries/{inquiry_id}/fulfillment-mode",
            args={"fulfillment_mode": "DELIVERY"},
            expect={"updated_at": detail["updated_at"]},
        )[0]
        == 200
    )

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
    order_id = convert_body["order_id"]
    order_version_id = convert_body["order_version_id"]

    assert (
        _post(
            f"{base}/office/v1/orders/{order_id}/print-confirm",
            args={"order_version_id": order_version_id},
        )[0]
        == 200
    )
    assert (
        _post(
            f"{base}/office/v1/orders/{order_id}/effective",
            args={"order_version_id": order_version_id},
            expect={
                "current_effective_order_version_id": None,
                "current_candidate_order_version_id": None,
            },
        )[0]
        == 200
    )
    assert (
        _post(
            f"{base}/office/v1/orders/{order_id}/kitchen-completion",
            args={
                "order_version_id": order_version_id,
                "recorded_by": "kitchen-panel",
                "evidence_reference": "kitchen-ticket-42",
                "completed_at": _DISPATCHED_AT.isoformat(),
            },
            expect={"current_effective_order_version_id": order_version_id},
        )[0]
        in {200, 201}
    )
    return base, order_id, order_version_id


def test_delivery_execution_cycle_from_kitchen_completion(
    office_api: tuple[str, dict[str, str], Path],
) -> None:
    base, order_id, order_version_id = _release_and_complete_kitchen(office_api)
    _base, _ids, db = office_api

    queue_status, queue_body, _headers = _get(f"{base}/office/v1/delivery-queue")
    assert queue_status == 200
    matching = [entry for entry in queue_body["entries"] if entry["order_id"] == order_id]
    assert len(matching) == 1
    entry = matching[0]
    assert entry["order_version_id"] == order_version_id
    assert entry["delivery_snapshot"]["fulfillment_mode"] == "DELIVERY"
    assert entry["delivery_snapshot"]["created_from"] == "accepted_order_conversion"

    dispatch_args = {
        "order_version_id": order_version_id,
        "recorded_by": "office-dispatch",
        "evidence_reference": "dispatch-77",
        "dispatched_at": _DISPATCHED_AT.isoformat(),
    }
    dispatch_status, dispatch_body, _headers = _post(
        f"{base}/office/v1/orders/{order_id}/dispatch",
        args=dispatch_args,
        expect={"current_effective_order_version_id": order_version_id},
    )
    assert dispatch_status == 201
    dispatch_id = dispatch_body["evidence"]["dispatch_evidence_id"]

    completion_status, completion_body, _headers = _post(
        f"{base}/office/v1/orders/{order_id}/delivery-completion",
        args={
            "order_version_id": order_version_id,
            "recorded_by": "office-dispatch",
            "evidence_reference": "delivered-88",
            "completed_at": _COMPLETED_AT.isoformat(),
        },
        expect={"current_effective_order_version_id": order_version_id},
    )
    assert completion_status == 201

    replay_status, replay_body, _headers = _post(
        f"{base}/office/v1/orders/{order_id}/delivery-completion",
        args={
            "order_version_id": order_version_id,
            "recorded_by": "office-dispatch",
            "evidence_reference": "delivered-88",
            "completed_at": _COMPLETED_AT.isoformat(),
        },
        expect={"current_effective_order_version_id": order_version_id},
    )
    assert replay_status == 200
    assert (
        replay_body["evidence"]["delivery_completion_evidence_id"]
        == completion_body["evidence"]["delivery_completion_evidence_id"]
    )

    orders = SQLiteOrderRepository(db)
    order_before = orders.get_order(order_id)
    version_before = orders.get_order_version(order_version_id)
    orders.close()

    dispatch_repo = SQLiteDispatchEvidenceRepository(db)
    assert dispatch_repo.get_by_order_version_id(order_id, order_version_id) is not None
    dispatch_repo.close()

    completion_repo = SQLiteDeliveryCompletionEvidenceRepository(db)
    assert completion_repo.get_by_order_version_id(order_id, order_version_id) is not None
    completion_repo.close()

    delivery_repo = SQLiteOrderDeliverySnapshotRepository(db)
    snapshot = delivery_repo.get_by_order_version_id(order_id, order_version_id)
    delivery_repo.close()
    assert snapshot is not None

    orders = SQLiteOrderRepository(db)
    assert orders.get_order(order_id) == order_before
    assert orders.get_order_version(order_version_id) == version_before
    orders.close()

    assert dispatch_id
