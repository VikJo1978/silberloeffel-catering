"""Integration test: READY_TO_SEND → kitchen queue → completion evidence."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from catering_system.repositories.sqlite_kitchen_completion_evidence_repository import (
    SQLiteKitchenCompletionEvidenceRepository,
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

_COMPLETED_AT = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


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


def _release_order(
    office_api: tuple[str, dict[str, str], Path],
) -> tuple[str, str, str]:
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
        _post(f"{base}/office/v1/orders/{order_id}/ready")[1]["evaluation"]["ready"]
        is True
    )
    return base, order_id, order_version_id


def test_released_order_flows_through_kitchen_queue_to_completion_evidence(
    office_api: tuple[str, dict[str, str], Path],
) -> None:
    base, order_id, order_version_id = _release_order(office_api)
    _base, _ids, db = office_api

    queue_status, queue_body, _headers = _get(f"{base}/office/v1/kitchen-queue")
    assert queue_status == 200
    matching = [entry for entry in queue_body["entries"] if entry["order_id"] == order_id]
    assert len(matching) == 1
    entry = matching[0]
    assert entry["order_id"] == order_id
    assert entry["order_version_id"] == order_version_id
    assert entry["projection"]["commercial"]["source"] == "offer_conversion"

    completion_args = {
        "order_version_id": order_version_id,
        "recorded_by": "kitchen-panel",
        "evidence_reference": "ticket-42",
        "completed_at": _COMPLETED_AT.isoformat(),
    }
    first_status, first_body, _headers = _post(
        f"{base}/office/v1/orders/{order_id}/kitchen-completion",
        args=completion_args,
        expect={"current_effective_order_version_id": order_version_id},
    )
    assert first_status == 201
    evidence_id = first_body["evidence"]["kitchen_completion_evidence_id"]

    second_status, second_body, _headers = _post(
        f"{base}/office/v1/orders/{order_id}/kitchen-completion",
        args=completion_args,
        expect={"current_effective_order_version_id": order_version_id},
    )
    assert second_status == 200
    assert (
        second_body["evidence"]["kitchen_completion_evidence_id"] == evidence_id
    )

    orders = SQLiteOrderRepository(db)
    order_before = orders.get_order(order_id)
    version_before = orders.get_order_version(order_version_id)
    orders.close()

    evidence_repo = SQLiteKitchenCompletionEvidenceRepository(db)
    stored = evidence_repo.get_by_order_version_id(order_id, order_version_id)
    evidence_repo.close()
    assert stored is not None
    assert stored.evidence_reference == "ticket-42"

    orders = SQLiteOrderRepository(db)
    assert orders.get_order(order_id) == order_before
    assert orders.get_order_version(order_version_id) == version_before
    orders.close()
