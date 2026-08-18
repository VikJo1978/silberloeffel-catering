"""OPERATIONAL_PAUSE_ENFORCEMENT_V1 — panel, outbound, and interaction tests."""

from __future__ import annotations

from tests.helpers.office_panel_context import legacy_office_context
from tests.helpers.order_seed import seed_order

import sqlite3
import re
from pathlib import Path
from uuid import uuid4

import pytest

from catering_system.repositories.core_transaction import (
    CoreCommandExecutor,
    open_core_connection,
)
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_offer_repository import SQLiteOfferRepository
from catering_system.repositories.sqlite_order_confirmation_document_repository import (
    SQLiteOrderConfirmationDocumentRepository,
)
from catering_system.repositories.sqlite_order_confirmation_outbound_repository import (
    SQLiteOrderConfirmationOutboundRepository,
)
from catering_system.repositories.sqlite_order_operational_pause_repository import (
    SQLiteOrderOperationalPauseRepository,
)
from catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository
from catering_system.services.order_confirmation_outbound_service import (
    OrderConfirmationOutboundBlockedError,
)
from catering_system.ui.office_panel import OfficePanel
from catering_system.ui.remote_core_client import RemoteCoreClient
from catering_system.ui.office_panel_order_detail import (
    OrderDetailFormFields,
    render_confirmation_outbound_card,
)
from tests.unit.test_office_panel_confirmation_document import _sqlite_world
from tests.unit.test_office_panel_remote import (
    _API_TOKEN,
    _CSRF_TOKEN,
    _extract_hidden,
    _get,
    _post_form,
    _seed,
    _start_api_server,
    _start_remote_panel,
)
from tests.unit.test_order_operational_pause import (
    _pause,
    _resume,
    _sample_inquiry,
    _setup,
)


def _panel(db: Path, *, ui_version: str = "legacy") -> OfficePanel:
    connection = open_core_connection(db)
    return OfficePanel(
        SQLiteInquiryRepository.from_connection(connection),
        SQLiteOrderRepository.from_connection(connection),
        confirmation_document_repo=SQLiteOrderConfirmationDocumentRepository.from_connection(
            connection
        ),
        confirmation_outbound_repo=SQLiteOrderConfirmationOutboundRepository.from_connection(
            connection
        ),
        offer_repo=SQLiteOfferRepository.from_connection(connection),
        pause_repository=SQLiteOrderOperationalPauseRepository.from_connection(
            connection
        ),
        command_executor=CoreCommandExecutor(connection),
        ui_version=ui_version,
    )


def test_legacy_and_v2_pause_card_parity(tmp_path: Path) -> None:
    db, doc_service, _core, orders, order_id, _version_id = _sqlite_world(tmp_path)
    legacy = _panel(db, ui_version="legacy")
    v2 = _panel(db, ui_version="v2")
    inactive_legacy = legacy.render_order(order_id, context=legacy_office_context())
    inactive_v2 = v2.render_order(order_id, context=legacy_office_context())
    assert inactive_legacy is not None and inactive_v2 is not None
    assert "Auftrag pausieren" in inactive_legacy
    assert "Auftrag pausieren" in inactive_v2

    _pause(
        legacy.core,
        order_id,
        reason_code="manual_hold",
        note="<script>alert(1)</script>",
        actor_reference="office-panel",
        command_id=str(uuid4()),
    )
    active_legacy = legacy.render_order(order_id, context=legacy_office_context())
    active_v2 = v2.render_order(order_id, context=legacy_office_context())
    assert active_legacy is not None and active_v2 is not None
    for page in (active_legacy, active_v2):
        assert "Auftrag pausiert" in page
        assert "Pause aufheben" in page
        assert "Testversand blockiert: Auftrag pausiert" in page
        assert "Testversand erzeugen" not in page
        assert "<script>" not in page
        assert "&lt;script&gt;" in page


def test_outbound_card_hidden_without_send_permission(tmp_path: Path) -> None:
    db, doc_service, _core, orders, order_id, order_version_id = _sqlite_world(tmp_path)
    snapshot = doc_service.prepare_snapshot(order_id, order_version_id, "office-panel")
    panel = _panel(db)
    _pause(
        panel.core,
        order_id,
        reason_code="manual_hold",
        note=None,
        actor_reference="office-panel",
        command_id=str(uuid4()),
    )
    confirmation = doc_service.eligibility(order_id)
    outbound = panel.confirmation_outbound_service.send_eligibility(
        order_id,
        document_snapshot_id=snapshot.document_snapshot_id,
    )
    pause_view = panel._operational_pause_view(order_id)
    card = render_confirmation_outbound_card(
        orders.get_order(order_id),
        confirmation,
        outbound,
        OrderDetailFormFields(
            csrf_input="",
            print_confirm_command_fields={},
            effective_command_fields={},
            ready_command_fields="",
            cancel_command_fields="",
            version_command_fields="",
            payment_command_fields="",
        ),
        operational_pause=pause_view,
    )
    assert card == ""


def test_existing_send_evidence_remains_visible_after_pause(tmp_path: Path) -> None:
    db, doc_service, _core, _orders, order_id, order_version_id = _sqlite_world(
        tmp_path
    )
    snapshot = doc_service.prepare_snapshot(order_id, order_version_id, "office-panel")
    panel = _panel(db)
    panel.confirmation_outbound_service.send_to_fake_outbox(
        order_id,
        snapshot.document_snapshot_id,
        order_version_id,
        "office-panel",
    )
    assert (
        sqlite3.connect(db)
        .execute("SELECT COUNT(*) FROM order_confirmation_send_evidence")
        .fetchone()[0]
        == 1
    )
    _pause(
        panel.core,
        order_id,
        reason_code="manual_hold",
        note=None,
        actor_reference="office-panel",
        command_id=str(uuid4()),
    )
    hidden_page = panel.render_order(order_id)
    assert hidden_page is not None
    assert "Fake Outbox" not in hidden_page
    assert "Testversand protokolliert" not in hidden_page
    assert "Testversand blockiert: Auftrag pausiert" not in hidden_page

    permitted_page = panel.render_order(order_id, context=legacy_office_context())
    assert permitted_page is not None
    assert "Testversand protokolliert" in permitted_page
    assert "Testversand blockiert: Auftrag pausiert" in permitted_page


def test_b1_preview_link_still_available_during_pause(tmp_path: Path) -> None:
    db, doc_service, _core, _orders, order_id, order_version_id = _sqlite_world(
        tmp_path
    )
    doc_service.prepare_snapshot(order_id, order_version_id, "office-panel")
    panel = _panel(db)
    _pause(
        panel.core,
        order_id,
        reason_code="manual_hold",
        note=None,
        actor_reference="office-panel",
        command_id=str(uuid4()),
    )
    page = panel.render_order(order_id)
    assert page is not None
    assert "Vorschau öffnen" in page


def test_fake_send_during_pause_returns_blocked_with_zero_rows(tmp_path: Path) -> None:
    db, doc_service, _core, _orders, order_id, order_version_id = _sqlite_world(
        tmp_path
    )
    snapshot = doc_service.prepare_snapshot(order_id, order_version_id, "office-panel")
    panel = _panel(db)
    _pause(
        panel.core,
        order_id,
        reason_code="manual_hold",
        note=None,
        actor_reference="office-panel",
        command_id=str(uuid4()),
    )
    with pytest.raises(
        OrderConfirmationOutboundBlockedError, match="order_not_ready_to_send"
    ):
        panel.confirmation_outbound_service.send_to_fake_outbox(
            order_id,
            snapshot.document_snapshot_id,
            order_version_id,
            "office-panel",
        )
    counts = (
        sqlite3.connect(db)
        .execute(
            "SELECT "
            "(SELECT COUNT(*) FROM order_confirmation_send_attempts), "
            "(SELECT COUNT(*) FROM order_confirmation_fake_outbox_messages), "
            "(SELECT COUNT(*) FROM order_confirmation_send_evidence)"
        )
        .fetchone()
    )
    assert counts == (0, 0, 0)


def test_effective_switch_during_pause_does_not_clear_pause() -> None:
    repo, _pauses, osvc, core, _events = _setup()
    order, v1 = seed_order(repo, _sample_inquiry())
    core.confirm_kitchen_print(order.order_id, v1.order_version_id)
    core.make_order_version_effective(order.order_id, v1.order_version_id)
    v2 = osvc.propose_order_version_change(
        order.order_id,
        event_date=v1.event_date,
        time_window_text="abends",
        location_text=v1.location_text,
        guest_count_estimate=v1.guest_count_estimate,
        planning_mode=v1.planning_mode,
        actor_reference="office-panel",
        change_reason="Zeit geändert",
    )
    core.confirm_kitchen_print(order.order_id, v2.order_version_id)
    _pause(
        core,
        order.order_id,
        reason_code="manual_hold",
        note=None,
        actor_reference="office-panel",
        command_id=str(uuid4()),
    )
    core.make_order_version_effective(order.order_id, v2.order_version_id)
    assert core.get_active_operational_pause(order.order_id) is not None
    reasons = core.evaluate_ready_to_send(order.order_id).reasons
    assert reasons == ("operational_pause",)
    _resume(
        core,
        order.order_id,
        reason_code="operator_cleared",
        note=None,
        actor_reference="office-panel",
        command_id=str(uuid4()),
    )
    assert core.evaluate_ready_to_send(order.order_id).ready is True


def test_storno_blocks_pause_and_preserves_history() -> None:
    _repo, pauses, osvc, core, _events = _setup()
    order, _v1 = seed_order(_repo, _sample_inquiry())
    _pause(
        core,
        order.order_id,
        reason_code="manual_hold",
        note="before storno",
        actor_reference="office-panel",
        command_id=str(uuid4()),
    )
    history_before = pauses.list_events(order.order_id)
    core.cancel_order(order.order_id)
    with pytest.raises(ValueError, match="cancelled"):
        _pause(
            core,
            order.order_id,
            reason_code="manual_hold",
            note=None,
            actor_reference="office-panel",
            command_id=str(uuid4()),
        )
    assert pauses.list_events(order.order_id) == history_before


def test_direct_pause_survives_new_panel_instance(tmp_path: Path) -> None:
    db, _doc_service, _core, _orders, order_id, _version_id = _sqlite_world(tmp_path)
    first = _panel(db)
    first.pause_order(
        order_id,
        {
            "reason_code": "manual_hold",
            "note": "persist across restart",
            "_command_id": str(uuid4()),
            "_expect_latest_pause_event_id": "",
        },
    )
    second = _panel(db)
    page = second.render_order(order_id)
    assert page is not None
    assert "Auftrag pausiert" in page
    assert "persist across restart" in page


def test_remote_panel_pause_resume_handoff_and_escaping(tmp_path: Path) -> None:
    db = tmp_path / "remote-pause.db"
    ids = _seed(db)
    api_url, api_server = _start_api_server(db)
    remote_url, remote_server = _start_remote_panel(
        RemoteCoreClient(api_url, _API_TOKEN)
    )
    order_id = ids["order_ready"]
    try:
        status, page = _get(f"{remote_url}/order/{order_id}")
        assert status == 200
        pause_match = re.search(
            rf'(<form[^>]*action="/order/{order_id}/pause"[^>]*>.*?</form>)',
            page,
            re.DOTALL,
        )
        assert pause_match is not None
        pause_form = pause_match.group(1)
        status, paused_page = _post_form(
            f"{remote_url}/order/{order_id}/pause",
            {
                "_csrf_token": _CSRF_TOKEN,
                "_command_id": _extract_hidden(pause_form, "_command_id"),
                "_expect_operational_pause_active": _extract_hidden(
                    pause_form, "_expect_operational_pause_active"
                ),
                "_expect_latest_pause_event_id": _extract_hidden(
                    pause_form, "_expect_latest_pause_event_id"
                ),
                "reason_code": "customer_request",
                "note": "<b>Rückfrage</b>",
            },
        )
        assert status == 200
        assert "Auftrag pausiert" in paused_page
        assert "&lt;b&gt;Rückfrage&lt;/b&gt;" in paused_page
        assert "<b>Rückfrage</b>" not in paused_page

        resume_match = re.search(
            rf'(<form[^>]*action="/order/{order_id}/resume"[^>]*>.*?</form>)',
            paused_page,
            re.DOTALL,
        )
        assert resume_match is not None
        resume_form = resume_match.group(1)
        status, resumed_page = _post_form(
            f"{remote_url}/order/{order_id}/resume",
            {
                "_csrf_token": _CSRF_TOKEN,
                "_command_id": _extract_hidden(resume_form, "_command_id"),
                "_expect_operational_pause_active": _extract_hidden(
                    resume_form, "_expect_operational_pause_active"
                ),
                "_expect_current_pause_event_id": _extract_hidden(
                    resume_form, "_expect_current_pause_event_id"
                ),
                "_expect_latest_pause_event_id": _extract_hidden(
                    resume_form, "_expect_latest_pause_event_id"
                ),
                "reason_code": "operator_cleared",
                "note": "geklärt",
            },
        )
        assert status == 200
        assert "Auftrag pausiert" not in resumed_page
        assert "Auftrag pausieren" in resumed_page
    finally:
        remote_server.shutdown()
        remote_server.server_close()
        api_server.shutdown()
        api_server.server_close()
