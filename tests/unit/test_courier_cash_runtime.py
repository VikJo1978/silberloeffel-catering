from __future__ import annotations

import json
import queue
import sqlite3
import threading
import urllib.error
import urllib.request
from dataclasses import replace
from datetime import UTC, date, datetime
from http.server import HTTPServer
from pathlib import Path
from uuid import uuid4

import pytest

from catering_system.domain.courier_cash_handoff import (
    CONTRACT_VERSION,
    EVENT_CHEF_DIRECT,
    EVENT_CHEF_RECEIVED_FROM_DRIVER,
    EVENT_CORRECTION,
    EVENT_DRIVER_HANDED_TO_CHEF,
    EVENT_DRIVER_RECEIVED,
    EVENT_NOT_RECEIVED,
    QUITTUNG_NOT_READY,
    QUITTUNG_PRINTED_CURRENT,
    STATE_AWAITING_CHEF,
    STATE_DRIVER_CUSTODY,
    STATE_FINAL_PAID,
    STATE_MANUAL_REVIEW,
    STATE_NOT_RECEIVED,
    CourierCashCommand,
    CourierCashProjection,
    UnsupportedCourierCashContractVersion,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_payment_reminder import OrderPaymentReminder
from catering_system.domain.wochenuebersicht import WochenuebersichtEntry
from catering_system.repositories.core_transaction import open_core_connection
from catering_system.repositories.sqlite_courier_cash_repository import (
    SQLiteCourierCashRepository,
)
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_offer_repository import SQLiteOfferRepository
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository
from catering_system.repositories.sqlite_payment_reminder_repository import (
    SQLitePaymentReminderRepository,
)
from catering_system.services.courier_cash_context_service import CourierCashContextService
from catering_system.services.courier_cash_service import (
    CourierCashCommandError,
    CourierCashService,
)
from catering_system.services.payment_reminder_service import PaymentReminderService
from catering_system.services.task_projection_service import TaskProjectionService
from catering_system.ui.kiosk_server import render_order_feed_json
from tests.helpers.offer_pdf_static_content import fake_offer_pdf_static_content

_ORDER_ID = "50000000-0000-4000-8000-000000000001"
_VERSION_ID = "70000000-0000-4000-8000-000000000001"
_ASSIGNMENT_ID = "60000000-0000-4000-8000-000000000001"
_NOW = datetime(2026, 8, 31, 9, 0, tzinfo=UTC)


def _seed_world(
    db: Path,
    *,
    quittung_printed: bool = True,
) -> tuple[
    sqlite3.Connection,
    SQLiteOrderRepository,
    SQLitePaymentReminderRepository,
    SQLiteCourierCashRepository,
    PaymentReminderService,
    CourierCashContextService,
    CourierCashService,
]:
    connection = open_core_connection(db)
    orders = SQLiteOrderRepository.from_connection(connection)
    payments = SQLitePaymentReminderRepository.from_connection(connection)
    cash_events = SQLiteCourierCashRepository.from_connection(connection)

    version = OrderVersion(
        order_version_id=_VERSION_ID,
        order_id=_ORDER_ID,
        version_number=1,
        created_at=datetime(2026, 8, 31, 8, 0, tzinfo=UTC),
        event_date=date(2026, 8, 31),
        time_window_text="12:00",
        location_text="Hamburg",
        guest_count_estimate=20,
        planning_mode="caterer_suggestion",
    )
    order = Order(
        order_id=_ORDER_ID,
        source_inquiry_id="20000000-0000-4000-8000-000000000001",
        created_at=version.created_at,
        updated_at=version.created_at,
        candidate_order_version_id=_VERSION_ID,
        effective_order_version_id=_VERSION_ID,
    )
    orders.save_order_with_initial_version(order, version)
    payment_service = PaymentReminderService(
        payments,
        orders,
        now=lambda: _NOW,
        today=lambda: _NOW.date(),
    )
    payment_service.save(
        OrderPaymentReminder(
            order_id=_ORDER_ID,
            payment_method="BAR_VOR_ORT",
            quittung_printed=quittung_printed,
        ),
        actor_reference="Office",
    )
    context_service = CourierCashContextService(orders, payments, cash_events)
    service = CourierCashService(
        orders,
        payments,
        cash_events,
        payment_service,
        context_service,
        now=lambda: _NOW,
    )
    connection.commit()
    return (
        connection,
        orders,
        payments,
        cash_events,
        payment_service,
        context_service,
        service,
    )


def _command(
    context_service: CourierCashContextService,
    *,
    event_type: str,
    actor_role: str,
    actor_id: str,
    idempotency_key: str | None = None,
    not_received_reason: str | None = None,
    note: str | None = None,
    correction_reason: str | None = None,
    correction_of_idempotency_key: str | None = None,
    order_version_id: str = _VERSION_ID,
    cash_execution_context_id: str | None = None,
) -> CourierCashCommand:
    projection = context_service.projection(_ORDER_ID)
    assert projection is not None
    return CourierCashCommand.from_json(
        {
            "contract_version": CONTRACT_VERSION,
            "idempotency_key": idempotency_key or str(uuid4()),
            "event_type": event_type,
            "order_id": _ORDER_ID,
            "assignment_id": _ASSIGNMENT_ID,
            "order_version_id": order_version_id,
            "cash_execution_context_id": (
                cash_execution_context_id
                if cash_execution_context_id is not None
                else projection.cash_execution_context_id
            ),
            "actor_id": actor_id,
            "actor_role": actor_role,
            "occurred_at": _NOW.isoformat(),
            "not_received_reason": not_received_reason,
            "note": note,
            "correction_reason": correction_reason,
            "correction_of_idempotency_key": correction_of_idempotency_key,
        }
    )


def test_context_projection_distinguishes_current_and_not_ready_quittung(
    tmp_path: Path,
) -> None:
    db = tmp_path / "core.db"
    connection, _orders, _payments, _cash, _payment, context, _service = _seed_world(
        db
    )
    ready = context.projection(_ORDER_ID)
    assert ready is not None
    assert ready.quittung_status == QUITTUNG_PRINTED_CURRENT
    assert ready.order_version_id == _VERSION_ID

    connection.close()
    db2 = tmp_path / "core-not-ready.db"
    (
        connection2,
        _orders2,
        _payments2,
        _cash2,
        _payment2,
        context2,
        _service2,
    ) = _seed_world(db2, quittung_printed=False)
    not_ready = context2.projection(_ORDER_ID)
    assert not_ready is not None
    assert not_ready.quittung_status == QUITTUNG_NOT_READY
    connection2.close()


def test_driver_to_chef_requires_two_transitions_before_final_payment(
    tmp_path: Path,
) -> None:
    db = tmp_path / "core.db"
    connection, _orders, payments, cash, _payment, context, service = _seed_world(db)

    driver = service.process(
        _command(
            context,
            event_type=EVENT_DRIVER_RECEIVED,
            actor_role="DRIVER",
            actor_id="driver-17",
        )
    )
    assert driver.cash_state == STATE_DRIVER_CUSTODY
    unpaid = payments.get(_ORDER_ID)
    assert unpaid is not None
    assert unpaid.paid_on is None
    assert unpaid.cash_received is False

    handoff = service.process(
        _command(
            context,
            event_type=EVENT_DRIVER_HANDED_TO_CHEF,
            actor_role="DRIVER",
            actor_id="driver-17",
        )
    )
    assert handoff.cash_state == STATE_AWAITING_CHEF
    still_unpaid = payments.get(_ORDER_ID)
    assert still_unpaid is not None
    assert still_unpaid.cash_received is False

    final = service.process(
        _command(
            context,
            event_type=EVENT_CHEF_RECEIVED_FROM_DRIVER,
            actor_role="CHEF",
            actor_id="chef-2",
        )
    )
    assert final.cash_state == STATE_FINAL_PAID
    paid = payments.get(_ORDER_ID)
    assert paid is not None
    assert paid.paid_on == date(2026, 8, 31)
    assert paid.cash_received is True
    assert paid.paid_recorded_by == "courier:chef:chef-2"
    assert cash.get_latest_for_order(_ORDER_ID) is not None
    connection.close()


def test_direct_chef_pickup_finalizes_without_driver_custody(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    connection, _orders, payments, _cash, _payment, context, service = _seed_world(db)

    result = service.process(
        _command(
            context,
            event_type=EVENT_CHEF_DIRECT,
            actor_role="CHEF",
            actor_id="chef-2",
        )
    )

    assert result.cash_state == STATE_FINAL_PAID
    paid = payments.get(_ORDER_ID)
    assert paid is not None and paid.cash_received is True
    connection.close()


def test_not_received_stays_unpaid_and_projects_urgent_office_task(
    tmp_path: Path,
) -> None:
    db = tmp_path / "core.db"
    connection, orders, payments, cash, payment, context, service = _seed_world(db)

    result = service.process(
        _command(
            context,
            event_type=EVENT_NOT_RECEIVED,
            actor_role="DRIVER",
            actor_id="driver-17",
            not_received_reason="CUSTOMER_NOT_FOUND",
        )
    )
    assert result.cash_state == STATE_NOT_RECEIVED
    stored = payments.get(_ORDER_ID)
    assert stored is not None
    assert stored.cash_received is False
    assert stored.paid_on is None

    inquiries = SQLiteInquiryRepository.from_connection(connection)
    offers = SQLiteOfferRepository.from_connection(connection)
    tasks = TaskProjectionService(
        inquiries,
        offers,
        orders,
        payment,
        today=lambda: date(2026, 8, 31),
        courier_cash_repository=cash,
    ).list_tasks()
    payment_task = next(task for task in tasks if task.category == "payment")
    assert payment_task.title == "Barzahlung klären"
    assert payment_task.urgency == "urgent"
    assert payment_task.due_at == date(2026, 8, 31)
    connection.close()


def test_replay_returns_exact_success_and_changed_payload_conflicts(
    tmp_path: Path,
) -> None:
    db = tmp_path / "core.db"
    connection, _orders, _payments, _cash, _payment, context, service = _seed_world(db)
    key = str(uuid4())
    command = _command(
        context,
        event_type=EVENT_DRIVER_RECEIVED,
        actor_role="DRIVER",
        actor_id="driver-17",
        idempotency_key=key,
    )
    first = service.process(command)
    replay = service.process(command)
    assert replay == first

    conflicting = replace(command, actor_id="driver-99")
    with pytest.raises(CourierCashCommandError) as exc:
        service.process(conflicting)
    assert (exc.value.status, exc.value.code) == (409, "idempotency_conflict")
    count = connection.execute(
        "SELECT COUNT(*) FROM courier_cash_events WHERE order_id = ?",
        (_ORDER_ID,),
    ).fetchone()[0]
    assert count == 1
    connection.close()


def test_stale_revision_and_context_fail_before_mutation(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    connection, _orders, _payments, _cash, _payment, context, service = _seed_world(db)

    stale_revision = _command(
        context,
        event_type=EVENT_DRIVER_RECEIVED,
        actor_role="DRIVER",
        actor_id="driver-17",
        order_version_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )
    with pytest.raises(CourierCashCommandError) as exc_revision:
        service.process(stale_revision)
    assert exc_revision.value.code == "stale_order_revision"

    stale_context = _command(
        context,
        event_type=EVENT_DRIVER_RECEIVED,
        actor_role="DRIVER",
        actor_id="driver-17",
        cash_execution_context_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    )
    with pytest.raises(CourierCashCommandError) as exc_context:
        service.process(stale_context)
    assert exc_context.value.code == "stale_cash_context"
    assert connection.execute("SELECT COUNT(*) FROM courier_cash_events").fetchone()[0] == 0
    connection.close()


def test_out_of_order_driver_or_chef_event_is_rejected(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    connection, _orders, _payments, _cash, _payment, context, service = _seed_world(db)

    with pytest.raises(CourierCashCommandError) as exc:
        service.process(
            _command(
                context,
                event_type=EVENT_CHEF_RECEIVED_FROM_DRIVER,
                actor_role="CHEF",
                actor_id="chef-2",
            )
        )
    assert exc.value.code == "invalid_transition"
    connection.close()


def test_privileged_correction_preserves_history_and_forces_manual_review(
    tmp_path: Path,
) -> None:
    db = tmp_path / "core.db"
    connection, _orders, payments, cash, _payment, context, service = _seed_world(db)
    before_context = context.projection(_ORDER_ID)
    assert before_context is not None

    final_command = _command(
        context,
        event_type=EVENT_CHEF_DIRECT,
        actor_role="CHEF",
        actor_id="chef-2",
    )
    final = service.process(final_command)
    assert final.cash_state == STATE_FINAL_PAID

    correction = service.process(
        _command(
            context,
            event_type=EVENT_CORRECTION,
            actor_role="CHEF",
            actor_id="chef-2",
            correction_reason="Falsche Bestätigung",
            correction_of_idempotency_key=final_command.idempotency_key,
        )
    )
    assert correction.cash_state == STATE_MANUAL_REVIEW
    corrected_payment = payments.get(_ORDER_ID)
    assert corrected_payment is not None
    assert corrected_payment.paid_on is None
    assert corrected_payment.cash_received is False
    assert len(payments.list_payment_corrections(_ORDER_ID)) == 1

    after_context = context.projection(_ORDER_ID)
    assert after_context is not None
    assert after_context.cash_execution_context_id != before_context.cash_execution_context_id
    latest = cash.get_latest_for_order(_ORDER_ID)
    assert latest is not None and latest.to_state == STATE_MANUAL_REVIEW

    with pytest.raises(CourierCashCommandError) as exc:
        service.process(
            _command(
                context,
                event_type=EVENT_DRIVER_RECEIVED,
                actor_role="DRIVER",
                actor_id="driver-17",
            )
        )
    assert exc.value.code == "invalid_transition"
    connection.close()


def test_cash_event_journal_survives_restart_and_is_append_only(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    connection, _orders, _payments, _cash, _payment, context, service = _seed_world(db)
    command = _command(
        context,
        event_type=EVENT_DRIVER_RECEIVED,
        actor_role="DRIVER",
        actor_id="driver-17",
    )
    result = service.process(command)
    connection.commit()
    connection.close()

    reopened = SQLiteCourierCashRepository(db)
    stored = reopened.get_by_idempotency_key(command.idempotency_key)
    assert stored is not None
    assert stored.result() == result
    with pytest.raises(sqlite3.IntegrityError):
        reopened._conn.execute(
            "UPDATE courier_cash_events SET actor_id = 'other' WHERE event_id = ?",
            (result.event_id,),
        )
    reopened.close()


def test_command_parser_is_exact_and_role_safe() -> None:
    base = {
        "contract_version": CONTRACT_VERSION,
        "idempotency_key": "40000000-0000-4000-8000-000000000001",
        "event_type": EVENT_DRIVER_RECEIVED,
        "order_id": _ORDER_ID,
        "assignment_id": _ASSIGNMENT_ID,
        "order_version_id": _VERSION_ID,
        "cash_execution_context_id": "80000000-0000-4000-8000-000000000001",
        "actor_id": "driver-17",
        "actor_role": "DRIVER",
        "occurred_at": _NOW.isoformat(),
        "not_received_reason": None,
        "note": None,
        "correction_reason": None,
        "correction_of_idempotency_key": None,
    }
    command = CourierCashCommand.from_json(base)
    assert command.to_json() == base

    with pytest.raises(ValueError, match="field set"):
        CourierCashCommand.from_json({**base, "amount": 100})
    with pytest.raises(UnsupportedCourierCashContractVersion):
        CourierCashCommand.from_json(
            {**base, "contract_version": "courier-cash-handoff-v2"}
        )
    with pytest.raises(ValueError, match="actor role"):
        CourierCashCommand.from_json(
            {
                **base,
                "event_type": EVENT_CHEF_RECEIVED_FROM_DRIVER,
                "actor_role": "DRIVER",
            }
        )
    with pytest.raises(ValueError, match="OTHER requires note"):
        CourierCashCommand.from_json(
            {
                **base,
                "event_type": EVENT_NOT_RECEIVED,
                "not_received_reason": "OTHER",
            }
        )


def test_kiosk_feed_cash_extension_keeps_absent_null_object_semantics() -> None:
    entry = WochenuebersichtEntry(
        order_id=_ORDER_ID,
        effective_order_version_id=_VERSION_ID,
        version_number=1,
        event_date=date(2026, 8, 31),
        time_window_text="12:00",
        location_text="Hamburg",
        guest_count_estimate=20,
        planning_mode="caterer_suggestion",
    )
    absent = json.loads(render_order_feed_json(entry.event_date, (entry,)))
    assert "cash_handoff" not in absent["orders"][0]

    null_value = json.loads(
        render_order_feed_json(
            entry.event_date,
            (entry,),
            cash_handoff_by_order_id={_ORDER_ID: None},
        )
    )
    assert null_value["orders"][0]["cash_handoff"] is None

    projection = CourierCashProjection(
        order_version_id=_VERSION_ID,
        cash_execution_context_id="80000000-0000-4000-8000-000000000001",
        quittung_status=QUITTUNG_PRINTED_CURRENT,
    )
    obj = json.loads(
        render_order_feed_json(
            entry.event_date,
            (entry,),
            cash_handoff_by_order_id={_ORDER_ID: projection},
        )
    )
    assert obj["orders"][0]["cash_handoff"] == projection.to_json()


def _start_machine_server(
    db: Path,
    *,
    cash_token: str | None,
) -> tuple[HTTPServer, threading.Thread, str]:
    ready: queue.Queue[HTTPServer] = queue.Queue()

    def run() -> None:
        from catering_system.ui.office_api import create_office_api_server

        server = create_office_api_server(
            str(db),
            "office-token",
            "127.0.0.1",
            0,
            offer_pdf_static_content=fake_offer_pdf_static_content(),
            courier_cash_service_token=cash_token,
        )
        ready.put(server)
        server.serve_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    server = ready.get(timeout=5)
    host, port = server.server_address[:2]
    return server, thread, f"http://{host}:{port}"


def _machine_post(
    url: str,
    body: bytes,
    *,
    authorization: str | None,
) -> tuple[int, dict[str, object], dict[str, str]]:
    headers = {"Content-Type": "application/json"}
    if authorization is not None:
        headers["Authorization"] = authorization
    request = urllib.request.Request(
        f"{url}/machine/v1/courier/cash-events",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return (
                response.status,
                json.loads(response.read().decode()),
                dict(response.headers),
            )
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}"), dict(exc.headers)


def test_machine_route_is_dormant_without_token_and_auth_first_when_enabled(
    tmp_path: Path,
) -> None:
    db = tmp_path / "core.db"
    connection, _orders, _payments, _cash, _payment, context, _service = _seed_world(db)
    command = _command(
        context,
        event_type=EVENT_DRIVER_RECEIVED,
        actor_role="DRIVER",
        actor_id="driver-17",
    )
    body = json.dumps(command.to_json()).encode()
    connection.commit()
    connection.close()

    server, thread, base = _start_machine_server(db, cash_token=None)
    try:
        status, response, headers = _machine_post(
            base, b"not-json", authorization="Bearer anything"
        )
        assert (status, response) == (404, {"error": "not_found"})
        assert headers["Cache-Control"] == "no-store"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    server, thread, base = _start_machine_server(db, cash_token="cash-secret")
    try:
        for auth in (None, "Bearer wrong"):
            status, response, _headers = _machine_post(
                base, b"not-json", authorization=auth
            )
            assert (status, response) == (401, {"error": "unauthorized"})

        status, response, headers = _machine_post(
            base, body, authorization="Bearer cash-secret"
        )
        assert status == 200
        assert response["cash_state"] == STATE_DRIVER_CUSTODY
        assert response["idempotency_key"] == command.idempotency_key
        assert headers["Cache-Control"] == "no-store"
        assert headers["X-Content-Type-Options"] == "nosniff"

        replay_status, replay, _headers = _machine_post(
            base, body, authorization="Bearer cash-secret"
        )
        assert replay_status == 200
        assert replay == response
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_machine_route_rejects_query_and_unsupported_contract(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    connection, _orders, _payments, _cash, _payment, context, _service = _seed_world(db)
    command = _command(
        context,
        event_type=EVENT_DRIVER_RECEIVED,
        actor_role="DRIVER",
        actor_id="driver-17",
    )
    connection.commit()
    connection.close()

    server, thread, base = _start_machine_server(db, cash_token="cash-secret")
    try:
        request = urllib.request.Request(
            f"{base}/machine/v1/courier/cash-events?x=1",
            data=json.dumps(command.to_json()).encode(),
            headers={
                "Authorization": "Bearer cash-secret",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as query_error:
            urllib.request.urlopen(request)
        assert query_error.value.code == 400
        assert json.loads(query_error.value.read()) == {"error": "invalid_request"}

        unsupported = command.to_json()
        unsupported["contract_version"] = "courier-cash-handoff-v2"
        status, response, _headers = _machine_post(
            base,
            json.dumps(unsupported).encode(),
            authorization="Bearer cash-secret",
        )
        assert (status, response) == (
            400,
            {"error": "unsupported_contract_version"},
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
