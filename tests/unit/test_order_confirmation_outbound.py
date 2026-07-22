"""EMAIL_MVP_2 — fake outbox outbound send (Slice B2)."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest

from catering_system.domain.order_confirmation_outbound import (
    OUTCOME_ACCEPTED,
    TRANSPORT_KIND,
)
from catering_system.domain.ready_to_send import ReadyToSendEvaluation
from catering_system.repositories.in_memory_inquiry_repository import (
    InMemoryInquiryRepository,
)
from catering_system.repositories.in_memory_offer_repository import (
    InMemoryOfferRepository,
)
from catering_system.repositories.in_memory_order_confirmation_document_repository import (
    InMemoryOrderConfirmationDocumentRepository,
)
from catering_system.repositories.in_memory_order_confirmation_outbound_repository import (
    InMemoryOrderConfirmationOutboundRepository,
)
from catering_system.repositories.in_memory_order_repository import (
    InMemoryOrderRepository,
)
from catering_system.repositories.sqlite_order_confirmation_outbound_repository import (
    SQLiteOrderConfirmationOutboundRepository,
)
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_confirmation_document_service import (
    OrderConfirmationDocumentService,
)
from catering_system.services.order_confirmation_outbound_payload_hash import (
    compute_payload_hash,
)
from catering_system.services.order_confirmation_outbound_service import (
    OrderConfirmationOutboundAlreadySentError,
    OrderConfirmationOutboundBlockedError,
    OrderConfirmationOutboundNotFoundError,
    OrderConfirmationOutboundPayloadInvalidError,
    OrderConfirmationOutboundRecipientMissingError,
    OrderConfirmationOutboundService,
)
from catering_system.services.order_service import OrderService
from tests.unit.test_offer_service import (
    _INQUIRY_ID,
    _accepted_offer_state,
)


def _world() -> tuple[
    InMemoryOrderRepository,
    InMemoryOfferRepository,
    InMemoryInquiryRepository,
    InMemoryOrderConfirmationDocumentRepository,
    InMemoryOrderConfirmationOutboundRepository,
    OrderConfirmationDocumentService,
    OrderConfirmationOutboundService,
    OperationalCoreService,
]:
    (
        offer,
        version_id,
        variant_id,
        acceptance_id,
        offers,
        orders,
        inquiries,
        offer_service,
    ) = _accepted_offer_state()
    inquiry = inquiries.get_by_id(_INQUIRY_ID)
    assert inquiry is not None
    inquiries.update(
        replace(
            inquiry,
            intake_message="Firma: Example GmbH\nE-Mail: customer@example.invalid\n",
        )
    )
    _converted, order, order_version = offer_service.convert_accepted_offer(
        offer.offer_id,
        version_id,
        variant_id,
        acceptance_id,
    )
    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, order_version.order_version_id)
    core.make_order_version_effective(order.order_id, order_version.order_version_id)
    documents = InMemoryOrderConfirmationDocumentRepository()
    outbound = InMemoryOrderConfirmationOutboundRepository()
    doc_service = OrderConfirmationDocumentService(
        orders,
        offers,
        inquiries,
        documents,
        offer_service._commercial_snapshots,
        now=lambda: datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
    )
    outbound_service = OrderConfirmationOutboundService(
        orders,
        documents,
        outbound,
        core,
        now=lambda: datetime(2026, 7, 18, 11, 0, tzinfo=UTC),
    )
    return (
        orders,
        offers,
        inquiries,
        documents,
        outbound,
        doc_service,
        outbound_service,
        core,
    )


def _prepared_snapshot(
    world: tuple[object, ...],
) -> tuple[object, object, object]:
    (
        orders,
        _offers,
        _inquiries,
        _documents,
        _outbound,
        doc_service,
        _outbound_service,
        _core,
    ) = world
    order = orders.list_orders()[0]
    version = orders.get_order_version(order.effective_order_version_id)
    assert version is not None
    snapshot = doc_service.prepare_snapshot(
        order.order_id,
        version.order_version_id,
        "office-panel",
    )
    return order, version, snapshot


def test_eligible_send_creates_attempt_outbox_and_evidence() -> None:
    world = _world()
    order, version, snapshot = _prepared_snapshot(world)
    outbound_service = world[6]
    result = outbound_service.send_to_fake_outbox(
        order.order_id,
        snapshot.document_snapshot_id,
        version.order_version_id,
        "office-panel",
    )
    assert result.real_delivery is False
    assert result.attempt.transport_kind == TRANSPORT_KIND
    assert result.evidence.outcome == OUTCOME_ACCEPTED
    assert (
        result.attempt.payload_hash
        == result.message.payload_hash
        == result.evidence.payload_hash
    )
    assert result.message.text_body
    assert result.message.html_body
    assert snapshot.document_hash == result.evidence.document_hash


def test_send_does_not_mutate_snapshot_or_order() -> None:
    world = _world()
    order, version, snapshot = _prepared_snapshot(world)
    (
        orders,
        _offers,
        _inquiries,
        documents,
        _outbound,
        _doc_service,
        outbound_service,
        _core,
    ) = world
    before_order = orders.get_order(order.order_id)
    before_snapshot = documents.get_by_id(snapshot.document_snapshot_id)
    outbound_service.send_to_fake_outbox(
        order.order_id,
        snapshot.document_snapshot_id,
        version.order_version_id,
        "office-panel",
    )
    assert orders.get_order(order.order_id) == before_order
    assert documents.get_by_id(snapshot.document_snapshot_id) == before_snapshot


def test_missing_email_blocks_send() -> None:
    world = _world()
    (
        orders,
        offers,
        inquiries,
        documents,
        outbound,
        doc_service,
        outbound_service,
        core,
    ) = world
    inquiry = inquiries.get_by_id(_INQUIRY_ID)
    assert inquiry is not None
    inquiries.update(replace(inquiry, intake_message="Firma: Example GmbH\n"))
    order, version, snapshot = _prepared_snapshot(
        (
            orders,
            offers,
            inquiries,
            documents,
            outbound,
            doc_service,
            outbound_service,
            core,
        )
    )
    with pytest.raises(OrderConfirmationOutboundRecipientMissingError):
        outbound_service.send_to_fake_outbox(
            order.order_id,
            snapshot.document_snapshot_id,
            version.order_version_id,
            "office-panel",
        )


def test_pending_candidate_blocks_send() -> None:
    world = _world()
    (
        orders,
        _offers,
        _inquiries,
        _documents,
        _outbound,
        doc_service,
        outbound_service,
        _core,
    ) = world
    order, version, snapshot = _prepared_snapshot(world)
    OrderService(orders).propose_order_version_change(
        order.order_id,
        event_date=date(2026, 9, 1),
        time_window_text=version.time_window_text,
        location_text=version.location_text,
        guest_count_estimate=version.guest_count_estimate,
        planning_mode=version.planning_mode,
        actor_reference="office-panel",
        change_reason="Test",
    )
    with pytest.raises(OrderConfirmationOutboundBlockedError, match="pending"):
        outbound_service.send_to_fake_outbox(
            order.order_id,
            snapshot.document_snapshot_id,
            version.order_version_id,
            "office-panel",
        )


def test_stale_snapshot_version_blocks_send() -> None:
    world = _world()
    (
        orders,
        _offers,
        _inquiries,
        documents,
        _outbound,
        doc_service,
        outbound_service,
        core,
    ) = world
    order, version, snapshot = _prepared_snapshot(world)
    OrderService(orders).propose_order_version_change(
        order.order_id,
        event_date=date(2026, 9, 1),
        time_window_text=version.time_window_text,
        location_text=version.location_text,
        guest_count_estimate=version.guest_count_estimate,
        planning_mode=version.planning_mode,
        actor_reference="office-panel",
        change_reason="Test",
    )
    candidate = orders.get_order(order.order_id)
    assert candidate is not None and candidate.candidate_order_version_id is not None
    core.confirm_kitchen_print(order.order_id, candidate.candidate_order_version_id)
    core.make_order_version_effective(
        order.order_id, candidate.candidate_order_version_id
    )
    updated = orders.get_order(order.order_id)
    assert updated is not None
    with pytest.raises(OrderConfirmationOutboundBlockedError, match="not_current"):
        outbound_service.send_to_fake_outbox(
            order.order_id,
            snapshot.document_snapshot_id,
            updated.effective_order_version_id or "",
            "office-panel",
        )


def test_kitchen_print_not_confirmed_blocks_send() -> None:
    world = _world()
    order, version, snapshot = _prepared_snapshot(world)
    outbound_service = world[6]
    stripped = replace(version, kitchen_print_confirmed_at=None)
    with patch.object(
        outbound_service._orders, "get_order_version", return_value=stripped
    ):
        with pytest.raises(
            OrderConfirmationOutboundBlockedError, match="kitchen_print"
        ):
            outbound_service.send_to_fake_outbox(
                order.order_id,
                snapshot.document_snapshot_id,
                version.order_version_id,
                "office-panel",
            )


def test_ready_to_send_false_blocks_with_reason() -> None:
    world = _world()
    order, version, snapshot = _prepared_snapshot(world)
    outbound_service = world[6]
    blocked = ReadyToSendEvaluation(
        order_id=order.order_id,
        ready=False,
        reasons=("kitchen_print_not_confirmed",),
    )
    with patch.object(
        outbound_service._core, "evaluate_ready_to_send", return_value=blocked
    ) as evaluate:
        with pytest.raises(
            OrderConfirmationOutboundBlockedError, match="order_not_ready_to_send"
        ) as caught:
            outbound_service.send_to_fake_outbox(
                order.order_id,
                snapshot.document_snapshot_id,
                version.order_version_id,
                "office-panel",
            )
    assert caught.value.blocker_code == "order_not_ready_to_send"
    assert caught.value.reasons == ("kitchen_print_not_confirmed",)
    evaluate.assert_called_once_with(order.order_id)


def test_operational_pause_blocks_fake_send_via_ready_to_send() -> None:
    world = _world()
    order, version, snapshot = _prepared_snapshot(world)
    outbound_service = world[6]
    core = world[7]
    core.pause_order(
        order.order_id,
        reason_code="manual_hold",
        note=None,
        actor_reference="office-panel",
        command_id="11111111-1111-4111-8111-111111111111",
        expected_latest_pause_event_id=None,
    )
    with patch.object(
        core, "evaluate_ready_to_send", wraps=core.evaluate_ready_to_send
    ) as evaluate:
        with pytest.raises(
            OrderConfirmationOutboundBlockedError, match="order_not_ready_to_send"
        ) as caught:
            outbound_service.send_to_fake_outbox(
                order.order_id,
                snapshot.document_snapshot_id,
                version.order_version_id,
                "office-panel",
            )
    assert caught.value.reasons == ("operational_pause",)
    evaluate.assert_called_once_with(order.order_id)


def test_storniert_order_blocks_send() -> None:
    world = _world()
    (
        orders,
        _offers,
        _inquiries,
        _documents,
        _outbound,
        doc_service,
        outbound_service,
        core,
    ) = world
    order, version, snapshot = _prepared_snapshot(world)
    core.cancel_order(order.order_id)
    with pytest.raises(OrderConfirmationOutboundBlockedError, match="order_storniert"):
        outbound_service.send_to_fake_outbox(
            order.order_id,
            snapshot.document_snapshot_id,
            version.order_version_id,
            "office-panel",
        )


def test_corrupt_document_hash_blocks_send() -> None:
    world = _world()
    order, version, snapshot = _prepared_snapshot(world)
    documents = world[3]
    outbound_service = world[6]
    documents._by_id[snapshot.document_snapshot_id] = replace(
        snapshot,
        document_hash="sha256:" + ("a" * 64),
    )
    with pytest.raises(OrderConfirmationOutboundPayloadInvalidError):
        outbound_service.send_to_fake_outbox(
            order.order_id,
            snapshot.document_snapshot_id,
            version.order_version_id,
            "office-panel",
        )


def test_new_command_after_evidence_raises_already_sent() -> None:
    world = _world()
    order, version, snapshot = _prepared_snapshot(world)
    outbound_service = world[6]
    outbound_service.send_to_fake_outbox(
        order.order_id,
        snapshot.document_snapshot_id,
        version.order_version_id,
        "office-panel",
    )
    with pytest.raises(OrderConfirmationOutboundAlreadySentError):
        outbound_service.send_to_fake_outbox(
            order.order_id,
            snapshot.document_snapshot_id,
            version.order_version_id,
            "office-panel",
        )


def test_payload_hash_is_stable() -> None:
    world = _world()
    _order, _version, snapshot = _prepared_snapshot(world)
    outbound_service = world[6]
    result = outbound_service.send_to_fake_outbox(
        _order.order_id,
        snapshot.document_snapshot_id,
        _version.order_version_id,
        "office-panel",
    )
    recomputed = compute_payload_hash(
        {
            "schema_version": 1,
            "transport_kind": result.attempt.transport_kind,
            "document_snapshot_id": snapshot.document_snapshot_id,
            "document_hash": snapshot.document_hash,
            "recipient_email": result.message.recipient_email,
            "subject": result.message.subject,
            "text_body": result.message.text_body,
            "html_body": result.message.html_body,
        }
    )
    assert recomputed == result.attempt.payload_hash


def test_send_evidence_does_not_claim_real_delivery() -> None:
    world = _world()
    order, version, snapshot = _prepared_snapshot(world)
    result = world[6].send_to_fake_outbox(
        order.order_id,
        snapshot.document_snapshot_id,
        version.order_version_id,
        "office-panel",
    )
    assert result.summary.real_delivery is False
    assert result.evidence.outcome == OUTCOME_ACCEPTED


def test_sqlite_immutable_and_owner_triggers(tmp_path) -> None:
    world = _world()
    order, version, snapshot = _prepared_snapshot(world)
    db = tmp_path / "outbound-only.db"
    repo = SQLiteOrderConfirmationOutboundRepository(db)
    conn = repo._conn
    conn.execute(
        "CREATE TABLE IF NOT EXISTS orders (order_id TEXT PRIMARY KEY, source_inquiry_id TEXT, "
        "created_at TEXT, updated_at TEXT, candidate_order_version_id TEXT, "
        "effective_order_version_id TEXT, cancelled_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS order_versions (order_version_id TEXT PRIMARY KEY, order_id TEXT, "
        "version_number INTEGER, event_date TEXT, time_window_text TEXT, location_text TEXT, "
        "guest_count_estimate INTEGER, planning_mode TEXT, created_at TEXT, "
        "kitchen_print_confirmed_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS order_confirmation_document_snapshots ("
        "document_snapshot_id TEXT PRIMARY KEY, order_id TEXT, order_version_id TEXT, "
        "document_hash TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            order.order_id,
            order.source_inquiry_id,
            order.created_at.isoformat(),
            order.updated_at.isoformat(),
            None,
            version.order_version_id,
            None,
        ),
    )
    conn.execute(
        "INSERT INTO order_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            version.order_version_id,
            order.order_id,
            version.version_number,
            version.event_date.isoformat(),
            version.time_window_text,
            version.location_text,
            version.guest_count_estimate,
            version.planning_mode,
            version.created_at.isoformat(),
            version.kitchen_print_confirmed_at.isoformat()
            if version.kitchen_print_confirmed_at
            else None,
        ),
    )
    conn.execute(
        "INSERT INTO order_confirmation_document_snapshots VALUES (?, ?, ?, ?)",
        (
            snapshot.document_snapshot_id,
            order.order_id,
            version.order_version_id,
            snapshot.document_hash,
        ),
    )
    outbound_service = OrderConfirmationOutboundService(
        world[0],
        world[3],
        repo,
        world[7],
        now=lambda: datetime(2026, 7, 18, 11, 0, tzinfo=UTC),
    )
    result = outbound_service.send_to_fake_outbox(
        order.order_id,
        snapshot.document_snapshot_id,
        version.order_version_id,
        "office-panel",
    )
    with pytest.raises(sqlite3.Error, match="immutable"):
        conn.execute(
            "UPDATE order_confirmation_send_evidence SET outcome = 'x' "
            "WHERE send_evidence_id = ?",
            (result.evidence.send_evidence_id,),
        )
    with pytest.raises(OrderConfirmationOutboundAlreadySentError):
        outbound_service.send_to_fake_outbox(
            order.order_id,
            snapshot.document_snapshot_id,
            version.order_version_id,
            "office-panel",
        )
    conn.close()


def test_b2_service_does_not_open_network_sockets() -> None:
    world = _world()
    order, version, snapshot = _prepared_snapshot(world)
    outbound_service = world[6]

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("network socket must not be used in B2 fake transport")

    with patch("socket.socket", side_effect=_forbidden):
        result = outbound_service.send_to_fake_outbox(
            order.order_id,
            snapshot.document_snapshot_id,
            version.order_version_id,
            "office-panel",
        )
    assert result.real_delivery is False


def test_send_eligibility_reports_missing_document() -> None:
    world = _world()
    order, _version, _snapshot = _prepared_snapshot(world)
    outbound_service = OrderConfirmationOutboundService(
        world[0], world[3], world[4], world[7]
    )
    eligibility = outbound_service.send_eligibility(
        order.order_id, document_snapshot_id="00000000-0000-4000-8000-000000000099"
    )
    assert eligibility.state == "dokument_fehlt"
    assert eligibility.can_send is False


def test_send_eligibility_unknown_order_raises_not_found() -> None:
    world = _world()
    outbound_service = OrderConfirmationOutboundService(
        world[0], world[3], world[4], world[7]
    )
    with pytest.raises(OrderConfirmationOutboundNotFoundError):
        outbound_service.send_eligibility("00000000-0000-4000-8000-000000000000")


def test_send_status_unknown_order_raises_not_found() -> None:
    world = _world()
    outbound_service = OrderConfirmationOutboundService(
        world[0], world[3], world[4], world[7]
    )
    with pytest.raises(OrderConfirmationOutboundNotFoundError):
        outbound_service.send_status("00000000-0000-4000-8000-000000000000")
