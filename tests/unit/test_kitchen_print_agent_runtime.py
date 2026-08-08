"""Kitchen print agent runtime tests (Phase 3B edge component)."""

from __future__ import annotations

import importlib
import inspect
import queue
import subprocess
import threading
import uuid
from datetime import UTC, date, datetime, timedelta
from http.server import HTTPServer
from pathlib import Path

import pytest

from catering_system.domain.inquiry import (
    CALL_VERIFICATION_STATUSES,
    CRM_PIPELINE,
    Inquiry,
    PLANNING_MODES,
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
from kitchen_print_agent.agent import KitchenPrintAgent
from kitchen_print_agent.client import KitchenPrintAgentClient
from kitchen_print_agent.config import AgentConfig
from kitchen_print_agent.printer import CupsPrinterAdapter, FakePrinterAdapter
from tests.helpers.commercial_snapshot_seed import seed_commercial_snapshot
from tests.helpers.order_seed import seed_order

_TOKEN = "test-kitchen-agent-token"
_NOW = datetime(2026, 8, 8, 11, 0, tzinfo=UTC)
_POLICY = KitchenPrintPolicy(
    acceptance_timeout=timedelta(seconds=30),
    acknowledgment_timeout=timedelta(minutes=5),
)
_JOB_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


@pytest.fixture
def kitchen_api_server(
    tmp_path: Path,
) -> tuple[str, Path]:
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
        yield base, db
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _seed_claimable_job(db: Path, *, print_job_id: str = _JOB_A) -> tuple[str, str]:
    now = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
    inquiry = Inquiry(
        inquiry_id=str(uuid.uuid4()),
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


def _agent_config(base_url: str) -> AgentConfig:
    return AgentConfig(
        api_url=base_url,
        agent_token=_TOKEN,
        poll_interval_seconds=0.01,
        printer_name="fake-printer",
    )


def test_claim_receives_document_and_prints_via_fake_printer(
    kitchen_api_server,
) -> None:
    base, db = kitchen_api_server
    _seed_claimable_job(db)
    printer = FakePrinterAdapter()
    agent = KitchenPrintAgent(
        _agent_config(base),
        KitchenPrintAgentClient(base, _TOKEN),
        printer,
    )

    claimed = agent.run_once()

    assert claimed is True
    assert len(printer.printed) == 1
    content_type, body = printer.printed[0]
    assert content_type == "text/html; charset=utf-8"
    assert b"<!DOCTYPE html>" in body or len(body) > 0


def test_printer_failure_triggers_technical_reject(kitchen_api_server) -> None:
    base, db = kitchen_api_server
    _seed_claimable_job(db)
    printer = FakePrinterAdapter(fail_on_print=True)
    agent = KitchenPrintAgent(
        _agent_config(base),
        KitchenPrintAgentClient(base, _TOKEN),
        printer,
    )

    agent.run_once()

    jobs = SQLiteKitchenPrintJobRepository(db)
    job = jobs.get(_JOB_A)
    jobs.close()
    assert job is not None
    assert job.rejected_at == _NOW
    assert job.rejection_code == "printer_unavailable"


def test_cups_adapter_failure_propagates_rejection_code(kitchen_api_server) -> None:
    base, db = kitchen_api_server
    _order_id, version_id = _seed_claimable_job(db)

    def run_lp(_command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["lp"],
            returncode=1,
            stdout="",
            stderr="job rejected by spooler",
        )

    agent = KitchenPrintAgent(
        _agent_config(base),
        KitchenPrintAgentClient(base, _TOKEN),
        CupsPrinterAdapter("Kitchen", run_lp=run_lp),
    )
    agent.run_once()

    jobs = SQLiteKitchenPrintJobRepository(db)
    job = jobs.get(_JOB_A)
    jobs.close()
    assert job is not None
    assert job.rejection_code == "spool_rejected"
    assert job.rejected_at == _NOW

    orders = SQLiteOrderRepository(db)
    version = orders.get_order_version(version_id)
    orders.close()
    assert version is not None
    assert version.kitchen_print_confirmed_at is None


def test_agent_restart_has_no_local_state(kitchen_api_server) -> None:
    base, db = kitchen_api_server
    _seed_claimable_job(db)
    config = _agent_config(base)

    first = KitchenPrintAgent(
        config,
        KitchenPrintAgentClient(base, _TOKEN),
        FakePrinterAdapter(),
    )
    assert first.run_once() is True

    second = KitchenPrintAgent(
        config,
        KitchenPrintAgentClient(base, _TOKEN),
        FakePrinterAdapter(),
    )
    assert second.run_once() is False

    jobs = SQLiteKitchenPrintJobRepository(db)
    job = jobs.get(_JOB_A)
    jobs.close()
    assert job is not None
    assert job.accepted_at == _NOW
    assert job.rejected_at is None


def test_duplicate_command_id_returns_same_response(kitchen_api_server) -> None:
    base, db = kitchen_api_server
    _seed_claimable_job(db)
    client = KitchenPrintAgentClient(base, _TOKEN)
    command_id = str(uuid.uuid4())

    first = client.claim_next(command_id)
    second = client.claim_next(command_id)

    assert first == second
    assert first.document is not None
    assert second.document is not None
    assert first.document.body == second.document.body


def test_successful_print_does_not_acknowledge_order(kitchen_api_server) -> None:
    base, db = kitchen_api_server
    _order_id, version_id = _seed_claimable_job(db)
    agent = KitchenPrintAgent(
        _agent_config(base),
        KitchenPrintAgentClient(base, _TOKEN),
        FakePrinterAdapter(),
    )

    assert agent.run_once() is True

    orders = SQLiteOrderRepository(db)
    version = orders.get_order_version(version_id)
    orders.close()
    assert version is not None
    assert version.kitchen_print_confirmed_at is None


def test_agent_package_has_no_acknowledge_path() -> None:
    package = importlib.import_module("kitchen_print_agent")
    for name in package.__all__:
        assert "acknowledge" not in name.lower()

    agent_module = importlib.import_module("kitchen_print_agent.agent")
    source = inspect.getsource(agent_module)
    assert "acknowledge_print_job" not in source
    assert "kitchen_print_confirmed_at" not in source
