"""Kitchen Print Agent HTTP API transport tests (Phase 3B)."""

from __future__ import annotations

import base64
import json
import queue
import threading
import urllib.error
import urllib.request
import uuid
from datetime import UTC, date, datetime, timedelta
from http.server import HTTPServer
from pathlib import Path

import pytest

from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    PLANNING_MODES,
    Inquiry,
)
from catering_system.domain.inquiry_customer_snapshot import (
    InquiryCustomerSnapshot as _CCSnapshot,
)
from catering_system.domain.kitchen_print_job import KitchenPrintPolicy
from catering_system.repositories.in_memory_kitchen_print_document_store import (
    InMemoryKitchenPrintDocumentStore,
)
from catering_system.repositories.kitchen_api_ledger import InMemoryKitchenCommandLedger
from catering_system.repositories.sqlite_kitchen_print_job_repository import (
    SQLiteKitchenPrintJobRepository,
)
from catering_system.repositories.sqlite_order_commercial_snapshot_repository import (
    SQLiteOrderCommercialSnapshotRepository,
)
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository
from catering_system.services.kitchen_print_service import KitchenPrintService
from catering_system.ui.kitchen_api import KitchenApi, make_kitchen_api_handler
from tests.helpers.commercial_snapshot_seed import seed_commercial_snapshot
from tests.helpers.order_seed import seed_order

_TOKEN = "test-kitchen-agent-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}
_NOW = datetime(2026, 8, 8, 11, 0, tzinfo=UTC)
_POLICY = KitchenPrintPolicy(
    acceptance_timeout=timedelta(seconds=30),
    acknowledgment_timeout=timedelta(minutes=5),
)
_JOB_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _post(url: str, payload: dict[str, object]) -> tuple[int, dict[str, object], bytes]:
    data = json.dumps(payload, sort_keys=True).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            **_AUTH,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    body = json.loads(raw.decode("utf-8")) if raw else {}
    return status, body, raw


@pytest.fixture
def kitchen_api(
    tmp_path: Path,
) -> tuple[str, Path, InMemoryKitchenCommandLedger]:
    db = tmp_path / "core.db"
    ledger = InMemoryKitchenCommandLedger()
    store = InMemoryKitchenPrintDocumentStore()
    ready: queue.Queue[HTTPServer] = queue.Queue()

    def run() -> None:
        api = KitchenApi(
            str(db),
            ledger=ledger,
            document_store=store,
            policy=_POLICY,
            clock=lambda: _NOW,
        )
        server = HTTPServer(("127.0.0.1", 0), make_kitchen_api_handler(api, _TOKEN))
        ready.put(server)
        try:
            server.serve_forever()
        finally:
            api.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    server = ready.get(timeout=5)
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        yield base, db, ledger
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _seed_claimable_job(
    db: Path,
    *,
    print_job_id: str = _JOB_A,
    inquiry_id: str | None = None,
) -> tuple[str, str]:
    now = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
    inquiry = Inquiry(
        inquiry_id=inquiry_id or str(uuid.uuid4()),
        event_date=date(2026, 10, 1),
        created_at=now,
        updated_at=now,
        inquiry_source="manual",
        crm_stage=CRM_PIPELINE[0],
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode=PLANNING_MODES[0],
        call_verification_required=False,
        call_verification_status=CALL_VERIFICATION_STATUSES[0],
        customer_snapshot=_CCSnapshot(email="kunde@example.com", phone="+49301234567"),
    )
    orders = SQLiteOrderRepository(db)
    order, order_version = seed_order(orders, inquiry)
    orders.close()
    seed_commercial_snapshot(
        SQLiteOrderCommercialSnapshotRepository(db),
        order.order_id,
    )
    jobs = SQLiteKitchenPrintJobRepository(db)
    orders = SQLiteOrderRepository(db)
    print_service = KitchenPrintService(
        orders,
        jobs,
        policy=_POLICY,
        clock=lambda: _NOW,
    )
    print_service.request_print(
        order.order_id,
        order_version.order_version_id,
        print_job_id=print_job_id,
    )
    jobs.close()
    orders.close()
    return order.order_id, order_version.order_version_id


def test_claim_returns_artifact_happy_path(kitchen_api) -> None:
    base, db, _ledger = kitchen_api
    _seed_claimable_job(db)
    command_id = str(uuid.uuid4())

    status, body, _raw = _post(
        f"{base}/kitchen/v1/print-jobs/claim-next",
        {"command_id": command_id},
    )

    assert status == 200
    assert body["command_id"] == command_id
    assert body["print_job_id"] == _JOB_A
    assert body["document_ref"].startswith("sha256:")
    assert body["document"]["content_type"] == "application/pdf"
    assert body["document"]["body_base64"]
    assert base64.b64decode(body["document"]["body_base64"]).startswith(b"%PDF-")


def test_repeated_command_id_replays_without_new_claim(kitchen_api) -> None:
    base, db, ledger = kitchen_api
    _seed_claimable_job(db)
    command_id = str(uuid.uuid4())

    status1, body1, raw1 = _post(
        f"{base}/kitchen/v1/print-jobs/claim-next",
        {"command_id": command_id},
    )
    status2, body2, raw2 = _post(
        f"{base}/kitchen/v1/print-jobs/claim-next",
        {"command_id": command_id},
    )

    assert status1 == 200
    assert (status2, body2) == (status1, body1)
    assert raw2 == raw1
    assert len(ledger._rows) == 1
    jobs = SQLiteKitchenPrintJobRepository(db)
    claimed = jobs.get(_JOB_A)
    jobs.close()
    assert claimed is not None
    assert claimed.accepted_at == _NOW


def test_two_command_ids_can_claim_two_jobs_when_queue_allows(kitchen_api) -> None:
    base, db, ledger = kitchen_api
    _seed_claimable_job(db, print_job_id=_JOB_A)
    _seed_claimable_job(db, print_job_id=_JOB_B)

    status_a, body_a, _raw_a = _post(
        f"{base}/kitchen/v1/print-jobs/claim-next",
        {"command_id": str(uuid.uuid4())},
    )
    status_b, body_b, _raw_b = _post(
        f"{base}/kitchen/v1/print-jobs/claim-next",
        {"command_id": str(uuid.uuid4())},
    )

    assert status_a == 200
    assert status_b == 200
    assert body_a["print_job_id"] != body_b["print_job_id"]
    assert len(ledger._rows) == 2


def test_reject_replay_is_idempotent(kitchen_api) -> None:
    base, db, ledger = kitchen_api
    _seed_claimable_job(db)
    claim_command = str(uuid.uuid4())
    _post(
        f"{base}/kitchen/v1/print-jobs/claim-next",
        {"command_id": claim_command},
    )
    reject_command = str(uuid.uuid4())
    url = f"{base}/kitchen/v1/print-jobs/{_JOB_A}/reject"
    payload = {
        "command_id": reject_command,
        "rejection_code": "printer_unavailable",
    }
    status1, body1, raw1 = _post(url, payload)
    status2, body2, raw2 = _post(url, payload)

    assert status1 == 200
    assert (status2, body2) == (status1, body1)
    assert raw2 == raw1
    assert len(ledger._rows) == 2


def test_reject_unknown_code_returns_domain_validation_error(kitchen_api) -> None:
    base, db, _ledger = kitchen_api
    _seed_claimable_job(db)
    _post(
        f"{base}/kitchen/v1/print-jobs/claim-next",
        {"command_id": str(uuid.uuid4())},
    )
    status, body, _raw = _post(
        f"{base}/kitchen/v1/print-jobs/{_JOB_A}/reject",
        {
            "command_id": str(uuid.uuid4()),
            "rejection_code": "not_a_real_code",
        },
    )
    assert status == 422
    assert body["error"] == "invalid_request"


def test_claim_does_not_set_kitchen_print_confirmed_at(kitchen_api) -> None:
    base, db, _ledger = kitchen_api
    _order_id, version_id = _seed_claimable_job(db)
    status, body, _raw = _post(
        f"{base}/kitchen/v1/print-jobs/claim-next",
        {"command_id": str(uuid.uuid4())},
    )
    assert status == 200
    orders = SQLiteOrderRepository(db)
    version = orders.get_order_version(version_id)
    orders.close()
    assert version is not None
    assert version.kitchen_print_confirmed_at is None
    assert body["print_job_id"] == _JOB_A


def test_ack_confirms_order_version_and_replays(kitchen_api) -> None:
    base, db, ledger = kitchen_api
    _order_id, version_id = _seed_claimable_job(db)
    _post(
        f"{base}/kitchen/v1/print-jobs/claim-next",
        {"command_id": str(uuid.uuid4())},
    )
    command_id = str(uuid.uuid4())
    url = f"{base}/kitchen/v1/print-jobs/{_JOB_A}/ack"
    payload = {"command_id": command_id}

    status1, body1, raw1 = _post(url, payload)
    status2, body2, raw2 = _post(url, payload)

    assert status1 == 200
    assert (status2, body2) == (status1, body1)
    assert raw2 == raw1
    assert body1["print_job_id"] == _JOB_A
    assert body1["acknowledged_at"] == _NOW.isoformat()
    assert len(ledger._rows) == 2

    jobs = SQLiteKitchenPrintJobRepository(db)
    job = jobs.get(_JOB_A)
    jobs.close()
    assert job is not None
    assert job.acknowledged_at == _NOW

    orders = SQLiteOrderRepository(db)
    version = orders.get_order_version(version_id)
    orders.close()
    assert version is not None
    assert version.kitchen_print_confirmed_at == _NOW


def test_ack_requires_agent_auth(kitchen_api) -> None:
    base, db, _ledger = kitchen_api
    _seed_claimable_job(db)
    _post(
        f"{base}/kitchen/v1/print-jobs/claim-next",
        {"command_id": str(uuid.uuid4())},
    )
    data = json.dumps({"command_id": str(uuid.uuid4())}).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/kitchen/v1/print-jobs/{_JOB_A}/ack",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(request, timeout=5)

    assert exc_info.value.code == 401


def test_ack_requires_accepted_job(kitchen_api) -> None:
    base, db, _ledger = kitchen_api
    _seed_claimable_job(db)

    status, body, _raw = _post(
        f"{base}/kitchen/v1/print-jobs/{_JOB_A}/ack",
        {"command_id": str(uuid.uuid4())},
    )

    assert status == 422
    assert body["error"] == "invalid_request"


def test_unauthorized_request_is_rejected(kitchen_api) -> None:
    base, db, _ledger = kitchen_api
    _seed_claimable_job(db)
    data = json.dumps({"command_id": str(uuid.uuid4())}).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/kitchen/v1/print-jobs/claim-next",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(request, timeout=5)
    assert exc_info.value.code == 401
