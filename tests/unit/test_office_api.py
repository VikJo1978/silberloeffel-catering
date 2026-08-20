"""Core Office API contract tests (PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1
§4, §6, §9) over a live local HTTP server."""

from __future__ import annotations

import hashlib
import json
import queue
import sqlite3
import threading
import urllib.error
import urllib.request
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from http.server import HTTPServer
from pathlib import Path

import pytest

from catering_system.domain.catalog import CatalogDish
from catering_system.domain.customer_document_projection import CustomerAddress
from catering_system.domain.inquiry_customer_snapshot import InquiryCustomerSnapshot
from catering_system.domain.kitchen_print_job import KitchenPrintJob
from catering_system.domain.offer import OfferPosition, OfferVariant, OfferVersion
from catering_system.domain.offer_snapshot import compute_snapshot_hash
from catering_system.repositories.sqlite_catalog_repository import (
    SQLiteCatalogRepository,
)
from catering_system.repositories.sqlite_configurator_handoff_repository import (
    SQLiteConfiguratorHandoffRepository,
)
from catering_system.repositories.sqlite_employee_auth_repository import (
    SQLiteEmployeeAuthRepository,
)
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_kitchen_print_job_repository import (
    SQLiteKitchenPrintJobRepository,
)
from catering_system.repositories.sqlite_offer_repository import (
    SQLiteOfferRepository,
)
from catering_system.repositories.sqlite_order_commercial_snapshot_repository import (
    SQLiteOrderCommercialSnapshotRepository,
)
from catering_system.repositories.sqlite_order_repository import (
    SQLiteOrderRepository,
)
from catering_system.services.configurator_handoff_service import (
    ConfiguratorHandoffService,
)
from catering_system.services.employee_auth_service import EmployeeAuthService
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.kitchen_print_service import KitchenPrintService
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService
from catering_system.ui.remote_core_client import RemoteCoreClient, RemoteCoreError
from tests.helpers.commercial_snapshot_seed import seed_commercial_snapshot
from tests.helpers.offer_pdf_static_content import fake_offer_pdf_static_content
from tests.helpers.order_seed import seed_order

_SNAPSHOT_ID = "77777777-7777-4777-8777-777777777771"
_VARIANT_ID = "44444444-4444-4444-8444-444444444441"
_POSITION_ID = "88888888-8888-4888-8888-888888888881"

_TOKEN = "test-office-api-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}
_SERVICE_TOKENS = {
    "office-api": "svc-office-token",
    "configurator-handoff": "svc-configurator-token",
}
_CONFIGURATOR_AUTH = {"Authorization": "Bearer svc-configurator-token"}
_WRONG_SERVICE_AUTH = {"Authorization": "Bearer svc-office-token"}


def _offer_version_for_order_creation() -> OfferVersion:
    offer_version_id = str(uuid.uuid4())
    return OfferVersion(
        offer_version_id=offer_version_id,
        offer_id=str(uuid.uuid4()),
        version_number=1,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        valid_until=date(2026, 9, 1),
        snapshot_id=str(uuid.uuid4()),
        snapshot_hash="sha256:" + ("0" * 64),
        event_date=date(2026, 10, 1),
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count=25,
        planning_mode="caterer_suggestion",
        payment_method="RECHNUNG",
        payment_customer_visible_text="Zahlung per Rechnung",
        variants=(
            OfferVariant(
                variant_id=str(uuid.uuid4()),
                offer_version_id=offer_version_id,
                label="Standard",
                positions=(
                    OfferPosition(
                        position_id=str(uuid.uuid4()),
                        kind="catalog",
                        name="Menü",
                        unit_net_cents=100,
                        net_total_cents=100,
                        vat_rate_percent=7,
                        vat_amount_cents=7,
                        gross_total_cents=107,
                    ),
                ),
            ),
        ),
    )


def _seed(db_path: Path) -> dict[str, str]:
    """Fixture world: verify-pending, convertible, printed/effective,
    cancelled, and website_form inquiries."""
    inquiries = SQLiteInquiryRepository(db_path)
    orders = SQLiteOrderRepository(db_path)
    inquiry_service = InquiryService(inquiries)
    OrderService(orders)
    core = OperationalCoreService(orders)

    def make_inquiry(**overrides):  # noqa: ANN202
        base = dict(
            event_date=date(2026, 10, 1),
            inquiry_source="manual",
            crm_stage="Neue Anfrage",
            customer_linkage={},
            time_window_text="mittags",
            location_text="Hamburg",
            guest_count_estimate=25,
            planning_mode="caterer_suggestion",
            call_verification_required=False,
            call_verification_status="not_required",
            contact_email="kunde@example.com",
            contact_phone="+49301234567",
            company_name="Example GmbH",
            contact_name="Example Contact",
        )
        base.update(overrides)
        return inquiry_service.create_inquiry(**base)

    ids: dict[str, str] = {}
    needs_verify = make_inquiry(
        call_verification_required=True,
        call_verification_status="pending",
        location_text="Kiel",
    )
    ids["inquiry_verify"] = needs_verify.inquiry_id
    convertible = make_inquiry(intake_subject="Sommerfest Catering")
    ids["inquiry_convertible"] = convertible.inquiry_id

    printed_src = make_inquiry(location_text="Bremen")
    order_printed, v1 = seed_order(orders, printed_src)
    seed_commercial_snapshot(
        SQLiteOrderCommercialSnapshotRepository(db_path),
        order_printed.order_id,
    )
    core.confirm_kitchen_print(order_printed.order_id, v1.order_version_id)
    core.make_order_version_effective(order_printed.order_id, v1.order_version_id)
    ids["inquiry_printed"] = printed_src.inquiry_id
    ids["order_ready"] = order_printed.order_id
    ids["version_ready"] = v1.order_version_id

    unprinted_src = make_inquiry(location_text="Lübeck")
    order_unprinted, v1u = seed_order(orders, unprinted_src)
    seed_commercial_snapshot(
        SQLiteOrderCommercialSnapshotRepository(db_path),
        order_unprinted.order_id,
    )
    ids["order_unprinted"] = order_unprinted.order_id
    ids["version_unprinted"] = v1u.order_version_id
    ids["inquiry_unprinted"] = unprinted_src.inquiry_id

    cancelled_src = make_inquiry(location_text="Flensburg")
    order_cancelled, v1c = seed_order(orders, cancelled_src)
    seed_commercial_snapshot(
        SQLiteOrderCommercialSnapshotRepository(db_path),
        order_cancelled.order_id,
    )
    core.cancel_order(order_cancelled.order_id)
    ids["order_cancelled"] = order_cancelled.order_id
    ids["version_cancelled"] = v1c.order_version_id
    ids["inquiry_cancelled_order"] = cancelled_src.inquiry_id

    offer_ready = make_inquiry(location_text="Angebot-Stadt")
    ids["inquiry_offer_ready"] = offer_ready.inquiry_id

    website = make_inquiry(
        inquiry_source="website_form",
        intake_external_ref="web-ref-001",
        call_verification_required=True,
        call_verification_status="pending",
    )
    ids["inquiry_website"] = website.inquiry_id
    rejected = make_inquiry(
        crm_stage="Abgelehnt / verloren",
        location_text="Neumünster",
    )
    ids["inquiry_rejected"] = rejected.inquiry_id

    inquiries.close()
    orders.close()
    return ids


def _seed_employee_auth(db_path: Path) -> dict[str, str]:
    repo = SQLiteEmployeeAuthRepository(db_path)
    service = EmployeeAuthService(repo, service_tokens=_SERVICE_TOKENS)
    account = service.bootstrap_superadmin(
        username="auth.handoff",
        display_name="Auth Handoff",
        password="TempPassw0rd!",
    )
    initial_login = service.authenticate(
        username="auth.handoff", password="TempPassw0rd!"
    )
    service.change_password(
        service.authenticate_session(initial_login.session_token),
        current_password="TempPassw0rd!",
        new_password="ChangedPassw0rd!",
    )
    final_login = service.authenticate(
        username="auth.handoff", password="ChangedPassw0rd!"
    )
    repo.close()
    return {
        "account_id": account.id,
        "session_token": final_login.session_token,
    }


def _employee_auth(db_path: Path) -> dict[str, str]:
    repo = SQLiteEmployeeAuthRepository(db_path)
    service = EmployeeAuthService(repo, service_tokens=_SERVICE_TOKENS)
    account = repo.get_account_by_username("auth.handoff")
    assert account is not None
    login = service.authenticate(username="auth.handoff", password="ChangedPassw0rd!")
    repo.close()
    return {"account_id": account.id, "session_token": login.session_token}


def _create_order_with_operational_context(db_path: Path) -> tuple[str, str]:
    inquiries = SQLiteInquiryRepository(db_path)
    orders = SQLiteOrderRepository(db_path)
    inquiry = InquiryService(inquiries).create_inquiry(
        event_date=date(2026, 10, 1),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Hamburg",
        guest_count_estimate=25,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        contact_email="kunde@example.com",
        contact_phone="+4940235649",
        company_name="A GmbH",
        contact_name="B Person",
    )
    order, version = OrderService(orders).create_order_from_offer_version(
        inquiry.inquiry_id,
        _offer_version_for_order_creation(),
        inquiry,
    )
    inquiries.close()
    orders.close()
    return order.order_id, version.order_version_id


def _mint_first_offer_handoff(
    db_path: Path, *, inquiry_id: str, account_id: str
) -> tuple[str, str]:
    repo = SQLiteConfiguratorHandoffRepository(db_path)
    service = ConfiguratorHandoffService(repo)
    minted = service.mint_first_offer(
        inquiry_id=inquiry_id,
        issued_for_account_id=account_id,
    )
    repo.close()
    return minted.code, minted.record.id


def _start_api_server(db: Path) -> tuple[HTTPServer, threading.Thread, str]:
    ready: queue.Queue[HTTPServer] = queue.Queue()

    def run() -> None:
        from catering_system.ui.office_api import create_office_api_server

        server = create_office_api_server(
            str(db),
            _TOKEN,
            "127.0.0.1",
            0,
            offer_pdf_static_content=fake_offer_pdf_static_content(),
            employee_auth_service_tokens=_SERVICE_TOKENS,
        )
        ready.put(server)
        server.serve_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    server = ready.get(timeout=5)
    host, port = server.server_address[:2]
    return server, thread, f"http://{host}:{port}"


@pytest.fixture()
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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


def _get(url: str, headers: dict | None = None) -> tuple[int, dict, dict]:
    req = urllib.request.Request(url, headers=headers if headers is not None else _AUTH)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode()), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}"), dict(exc.headers)


def _post(
    url: str,
    args: dict | None = None,
    expect: dict | None = None,
    command_id: str | None = None,
    headers: dict | None = None,
    raw_body: bytes | None = None,
) -> tuple[int, dict, dict]:
    body = (
        raw_body
        if raw_body is not None
        else json.dumps(
            {
                "command_id": command_id or str(uuid.uuid4()),
                "expect": expect or {},
                "args": args or {},
            }
        ).encode("utf-8")
    )
    all_headers = {"Content-Type": "application/json"}
    all_headers.update(headers if headers is not None else _AUTH)
    req = urllib.request.Request(url, data=body, headers=all_headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode()), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}"), dict(exc.headers)


def _ack_next_kitchen_job(db_path: Path, order_version_id: str) -> None:
    orders = SQLiteOrderRepository(db_path)
    jobs = SQLiteKitchenPrintJobRepository(db_path)
    service = KitchenPrintService(orders, jobs)
    claimed = service.claim_next_eligible()
    assert claimed is not None
    assert claimed.order_version_id == order_version_id
    service.acknowledge_print_job(claimed.print_job_id)
    jobs.close()
    orders.close()


def _exchange_handoff(
    base: str,
    *,
    code: str,
    session_token: str | None,
    headers: dict[str, str] | None = None,
    raw_body: bytes | None = None,
) -> tuple[int, dict, dict]:
    request_headers = {"Content-Type": "application/json"}
    request_headers.update(headers if headers is not None else _CONFIGURATOR_AUTH)
    if session_token is not None:
        request_headers["X-Employee-Session"] = session_token
    body = (
        raw_body if raw_body is not None else json.dumps({"code": code}).encode("utf-8")
    )
    req = urllib.request.Request(
        f"{base}/office/v1/auth/configurator-handoff/exchange",
        data=body,
        headers=request_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode()), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}"), dict(exc.headers)


_CREATE_ARGS = {
    "event_date": "2026-11-11",
    "inquiry_source": "manual",
    "time_window_text": "abends",
    "location_text": "Rostock",
    "guest_count_estimate": 40,
    "planning_mode": "caterer_suggestion",
    "call_verification_required": False,
    "contact_email": "kunde@example.com",
    "contact_phone": "+49301234567",
}


# --- auth: constant 401 before anything else ---------------------------------


def test_auth_first_constant_401_everywhere(api) -> None:
    base, ids, _db = api
    for headers in ({}, {"Authorization": "Bearer wrong"}):
        status, body, _h = _get(f"{base}/office/v1/queue", headers=headers)
        assert (status, body) == (401, {"error": "unauthorized"})
        # even with a garbage body and garbage query, auth answers first
        status, body, _h = _post(
            f"{base}/office/v1/inquiries?x=1",
            headers=headers,
            raw_body=b"not json at all",
        )
        assert (status, body) == (401, {"error": "unauthorized"})
        status, body, _h = _get(f"{base}/office/v1/nowhere", headers=headers)
        assert (status, body) == (401, {"error": "unauthorized"})


def test_error_responses_carry_security_headers(api) -> None:
    base, _ids, _db = api
    status, _body, headers = _get(f"{base}/office/v1/queue", headers={})
    assert status == 401
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Content-Type"] == "application/json; charset=utf-8"


def test_valid_first_offer_handoff_exchange(api) -> None:
    base, ids, db = api
    auth = _employee_auth(db)
    code, handoff_id = _mint_first_offer_handoff(
        db,
        inquiry_id=ids["inquiry_offer_ready"],
        account_id=auth["account_id"],
    )

    status, body, _headers = _exchange_handoff(
        base,
        code=code,
        session_token=auth["session_token"],
    )

    assert status == 200
    assert body["handoff_id"] == handoff_id
    assert body["operation"] == "prepare_first_offer"
    assert body["inquiry"]["inquiry_id"] == ids["inquiry_offer_ready"]
    assert "transfer" in body["inquiry"]
    row = (
        sqlite3.connect(db)
        .execute(
            "SELECT token_hash, consumed_at, consumed_by_account_id FROM configurator_handoffs WHERE id = ?",
            (handoff_id,),
        )
        .fetchone()
    )
    assert row is not None
    assert row[0] != code
    assert row[1] is not None
    assert row[2] == auth["account_id"]


def test_expired_handoff_rejected(api) -> None:
    base, ids, db = api
    auth = _employee_auth(db)
    code, handoff_id = _mint_first_offer_handoff(
        db,
        inquiry_id=ids["inquiry_offer_ready"],
        account_id=auth["account_id"],
    )
    connection = sqlite3.connect(db)
    connection.execute(
        "UPDATE configurator_handoffs SET expires_at = ? WHERE id = ?",
        ("2000-01-01T00:00:00+00:00", handoff_id),
    )
    connection.commit()
    connection.close()

    status, body, _headers = _exchange_handoff(
        base,
        code=code,
        session_token=auth["session_token"],
    )

    assert (status, body["error"]) == (404, "not_found")


def test_replay_handoff_rejected(api) -> None:
    base, ids, db = api
    auth = _employee_auth(db)
    code, _handoff_id = _mint_first_offer_handoff(
        db,
        inquiry_id=ids["inquiry_offer_ready"],
        account_id=auth["account_id"],
    )

    first_status, _first_body, _headers = _exchange_handoff(
        base,
        code=code,
        session_token=auth["session_token"],
    )
    second_status, second_body, _headers = _exchange_handoff(
        base,
        code=code,
        session_token=auth["session_token"],
    )

    assert first_status == 200
    assert (second_status, second_body["error"]) == (410, "gone")


def test_different_employee_handoff_rejected_without_consuming(api) -> None:
    base, ids, db = api
    auth = _employee_auth(db)
    code, handoff_id = _mint_first_offer_handoff(
        db,
        inquiry_id=ids["inquiry_offer_ready"],
        account_id=auth["account_id"],
    )
    repo = SQLiteEmployeeAuthRepository(db)
    service = EmployeeAuthService(repo, service_tokens=_SERVICE_TOKENS)
    actor = service.authenticate_session(auth["session_token"])
    other = service.create_account(
        actor,
        username="other.employee",
        display_name="Other Employee",
        password="OtherPassw0rd!",
        role="USER",
        explicit_permissions={"offers.prepare"},
        must_change_password=False,
    )
    other_login = service.authenticate(
        username="other.employee", password="OtherPassw0rd!"
    )
    repo.close()

    status, body, _headers = _exchange_handoff(
        base,
        code=code,
        session_token=other_login.session_token,
    )

    assert (status, body["error"]) == (403, "forbidden")
    row = (
        sqlite3.connect(db)
        .execute(
            "SELECT consumed_at, consumed_by_account_id FROM configurator_handoffs WHERE id = ?",
            (handoff_id,),
        )
        .fetchone()
    )
    assert row == (None, None)
    assert other.id != auth["account_id"]


def test_permission_revoked_after_mint_rejected(api) -> None:
    base, ids, db = api
    auth = _employee_auth(db)
    code, handoff_id = _mint_first_offer_handoff(
        db,
        inquiry_id=ids["inquiry_offer_ready"],
        account_id=auth["account_id"],
    )
    repo = SQLiteEmployeeAuthRepository(db)
    repo.set_explicit_permissions(auth["account_id"], {"offers.view"})
    repo.close()

    refreshed = _employee_auth(db)
    status, body, _headers = _exchange_handoff(
        base,
        code=code,
        session_token=refreshed["session_token"],
    )

    assert (status, body["error"]) == (403, "forbidden")
    row = (
        sqlite3.connect(db)
        .execute(
            "SELECT consumed_at FROM configurator_handoffs WHERE id = ?",
            (handoff_id,),
        )
        .fetchone()
    )
    assert row == (None,)


def test_remote_order_delete_requires_exact_name_and_employee_permission(api) -> None:
    base, _ids, db = api
    auth = _employee_auth(db)
    order_id, _version_id = _create_order_with_operational_context(db)
    headers = {**_AUTH, "X-Employee-Session": auth["session_token"]}

    wrong_status, wrong_body, _ = _post(
        f"{base}/office/v1/orders/{order_id}/delete",
        args={"confirmation_name": "Wrong GmbH"},
        headers=headers,
    )
    assert (wrong_status, wrong_body["error"]) == (
        422,
        "order_delete_confirmation_mismatch",
    )
    repo = SQLiteOrderRepository(db)
    assert repo.get_order(order_id) is not None
    repo.close()

    status, body, _ = _post(
        f"{base}/office/v1/orders/{order_id}/delete",
        args={"confirmation_name": "A GmbH"},
        headers=headers,
    )
    assert status == 200
    assert body["order_id"] == order_id
    repo = SQLiteOrderRepository(db)
    assert repo.get_order(order_id) is None
    repo.close()


def test_remote_order_delete_without_employee_session_is_denied(api) -> None:
    base, _ids, db = api
    order_id, _version_id = _create_order_with_operational_context(db)

    status, body, _ = _post(
        f"{base}/office/v1/orders/{order_id}/delete",
        args={"confirmation_name": "A GmbH"},
    )
    assert (status, body["error"]) == (401, "unauthorized")
    repo = SQLiteOrderRepository(db)
    assert repo.get_order(order_id) is not None
    repo.close()


def test_unknown_handoff_rejected(api) -> None:
    base, _ids, db = api
    auth = _employee_auth(db)

    status, body, _headers = _exchange_handoff(
        base,
        code="missing-code",
        session_token=auth["session_token"],
    )

    assert (status, body["error"]) == (404, "not_found")


def test_ordinary_service_token_cannot_exchange_handoff(api) -> None:
    base, ids, db = api
    auth = _employee_auth(db)
    code, handoff_id = _mint_first_offer_handoff(
        db,
        inquiry_id=ids["inquiry_offer_ready"],
        account_id=auth["account_id"],
    )

    status, body, _headers = _exchange_handoff(
        base,
        code=code,
        session_token=auth["session_token"],
        headers=_WRONG_SERVICE_AUTH,
    )

    assert (status, body["error"]) == (403, "forbidden")
    row = (
        sqlite3.connect(db)
        .execute(
            "SELECT consumed_at FROM configurator_handoffs WHERE id = ?",
            (handoff_id,),
        )
        .fetchone()
    )
    assert row == (None,)


# --- methods: HEAD/OPTIONS/PUT (pack §4.0) ------------------------------------


def test_head_known_path_is_405_with_headers_and_no_body(api) -> None:
    base, _ids, _db = api
    req = urllib.request.Request(
        f"{base}/office/v1/queue", headers=_AUTH, method="HEAD"
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 405
    assert int(exc.value.headers["Content-Length"]) > 0
    assert exc.value.headers["Cache-Control"] == "no-store"
    assert exc.value.read() == b""  # body suppressed, length preserved


def test_head_requires_auth_first(api) -> None:
    base, _ids, _db = api
    req = urllib.request.Request(f"{base}/office/v1/queue", method="HEAD")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 401


def test_options_and_put_known_405_unknown_404(api) -> None:
    base, _ids, _db = api
    for method in ("OPTIONS", "PUT", "DELETE", "PATCH"):
        req = urllib.request.Request(
            f"{base}/office/v1/queue", headers=_AUTH, method=method
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req)
        assert exc.value.code == 405, method
        req = urllib.request.Request(
            f"{base}/office/v1/nowhere", headers=_AUTH, method=method
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req)
        assert exc.value.code == 404, method


def test_wrong_method_on_command_route(api) -> None:
    base, ids, _db = api
    status, body, _h = _get(
        f"{base}/office/v1/inquiries/{ids['inquiry_convertible']}/convert"
    )
    assert (status, body["error"]) == (405, "method_not_allowed")


# --- reads --------------------------------------------------------------------


def test_queue_view_attention_counts_and_tops(api) -> None:
    base, ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/queue")
    assert status == 200
    assert set(body) == {
        "attention",
        "week",
        "neue_anfragen_top",
        "auftraege_top",
        "pausiert_top",
    }
    # seed world: 5 open inquiries incl. one with only a cancelled historical
    # order, plus 1 rejected inquiry without an order;
    # 1 order without print;
    # 2 not effective (unprinted + none), 2 blocked, 1 cancelled
    assert body["attention"] == {
        "neue_anfragen": 5,
        "druck_fehlt": 1,
        "nicht_wirksam": 1,
        "versand_blockiert": 1,
        "aenderungen_warten_auf_kuechendruck": 0,
        "pausiert": 0,
        "storniert": 1,
    }
    top_actions = {
        row["inquiry_id"]: row["next_action"] for row in body["neue_anfragen_top"]
    }
    assert top_actions[ids["inquiry_verify"]] == "verify"
    assert top_actions[ids["inquiry_convertible"]] == "prepare-offer"
    assert top_actions[ids["inquiry_offer_ready"]] == "prepare-offer"
    assert top_actions[ids["inquiry_website"]] == "verify"
    assert ids["inquiry_rejected"] not in top_actions
    (blocked_row,) = body["auftraege_top"]
    assert blocked_row["order_id"] == ids["order_unprinted"]
    assert blocked_row["blocker_reason"] == "no_effective_version"
    assert blocked_row["next_action"] == {
        "action": "print-confirm",
        "order_version_id": ids["version_unprinted"],
    }
    assert set(body["week"]) == {
        "iso_year",
        "iso_week",
        "entries",
        "total_count",
        "truncated",
    }


_WORK_CENTER_KEYS = {
    "rueckrufe_open",
    "missed_calls_open",
    "offers_waiting",
    "offers_accepted",
    "upcoming_orders",
    "open_tasks",
    "today_calendar_entries",
    "pending_order_changes",
}


def test_work_center_schema_and_seed_counts(api) -> None:
    base, _ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/work-center")
    assert status == 200
    assert set(body) == _WORK_CENTER_KEYS
    tasks_status, tasks_body, _h = _get(f"{base}/office/v1/tasks")
    assert tasks_status == 200
    assert body == {
        "rueckrufe_open": 2,
        "missed_calls_open": 0,
        "offers_waiting": 0,
        "offers_accepted": 0,
        "upcoming_orders": 1,
        "open_tasks": len(tasks_body["tasks"]),
        "today_calendar_entries": 0,
        "pending_order_changes": 0,
    }
    assert body["open_tasks"] >= 1


def test_work_center_requires_auth(api) -> None:
    base, _ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/work-center", headers={})
    assert (status, body["error"]) == (401, "unauthorized")


def test_list_offers_empty(api) -> None:
    base, _ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/offers")
    assert status == 200
    assert body == {"offers": []}


def test_list_offers_schema_and_states(api) -> None:
    base, _ids, _db = api
    offer_id, version_id = _prepare_offer(api)
    mark_url = _mark_sent_url(base, offer_id, version_id)
    assert _post(mark_url, args=_MARK_SENT_ARGS)[0] == 200

    status, body, _h = _get(f"{base}/office/v1/offers")
    assert status == 200
    assert len(body["offers"]) == 1
    row = body["offers"][0]
    assert set(row) == {
        "offer_id",
        "inquiry_id",
        "state",
        "event_date",
        "valid_until",
    }
    assert row["offer_id"] == offer_id
    assert row["state"] == "Sent"


def test_offer_queue_empty(api) -> None:
    base, _ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/offer-queue")
    assert status == 200
    assert body["total_count"] == 0
    assert body["limit"] == 100
    assert body["offset"] == 0
    assert len(body["sections"]) == 3
    assert all(section["count"] == 0 for section in body["sections"])


def test_offer_queue_prepared_and_sent_grouping(api) -> None:
    base, ids, _db = api
    offer_id, version_id = _prepare_offer(api)
    status, body, _h = _get(f"{base}/office/v1/offer-queue")
    assert status == 200
    assert body["total_count"] == 1
    action = next(s for s in body["sections"] if s["group"] == "action_required")
    assert action["count"] == 1
    item = action["items"][0]
    assert item["offer_id"] == offer_id
    assert item["queue_subkind"] == "prepared"
    assert item["next_action"] == "mark_sent"

    mark_url = _mark_sent_url(base, offer_id, version_id)
    assert _post(mark_url, args=_MARK_SENT_ARGS)[0] == 200
    status, body, _h = _get(f"{base}/office/v1/offer-queue")
    action = next(s for s in body["sections"] if s["group"] == "action_required")
    item = action["items"][0]
    assert item["queue_subkind"] == "sent"
    assert item["next_action"] == "await_customer"


def test_offer_queue_invalid_group(api) -> None:
    base, _ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/offer-queue?group=unknown")
    assert status == 400
    assert body["error"] == "invalid_request"


def test_offer_detail_not_found(api) -> None:
    base, _ids, _db = api
    missing = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    status, body, _h = _get(f"{base}/office/v1/offers/{missing}")
    assert status == 404
    assert body["error"] == "not_found"


def test_offer_detail_schema_prepared(api) -> None:
    base, _ids, _db = api
    offer_id, _version_id = _prepare_offer(api)
    status, body, _h = _get(f"{base}/office/v1/offers/{offer_id}")
    assert status == 200
    assert set(body) == {
        "offer_id",
        "inquiry_id",
        "offer_version_id",
        "commercial_state",
        "acceptance_id",
        "versions",
        "sent_evidence",
        "acceptance",
        "history",
    }
    assert body["offer_id"] == offer_id
    assert body["commercial_state"] == "Prepared"
    assert body["sent_evidence"] is None
    assert body["acceptance"] is None
    version = body["versions"][0]
    assert set(version) == {
        "offer_version_id",
        "version",
        "state",
        "created_at",
        "sent_at",
        "event_date",
        "valid_until",
        "time_window_text",
        "location_text",
        "guest_count",
        "planning_mode",
        "variants",
    }
    assert version["sent_at"] is None
    assert version["variants"][0]["name"] == "Variante A"
    assert "positions" in version["variants"][0]
    position = version["variants"][0]["positions"][0]
    assert position["allergens_unknown"] is True
    assert position["allergens"] is None
    assert body["history"][0]["label"] == "Version 1 vorbereitet"


def test_offer_detail_schema_sent(api) -> None:
    base, _ids, _db = api
    offer_id, version_id = _prepare_offer(api)
    assert (
        _post(_mark_sent_url(base, offer_id, version_id), args=_MARK_SENT_ARGS)[0]
        == 200
    )
    status, body, _h = _get(f"{base}/office/v1/offers/{offer_id}")
    assert status == 200
    assert body["commercial_state"] == "Sent"
    assert body["sent_evidence"] is not None
    assert body["sent_evidence"]["channel"] == "email"
    labels = [entry["label"] for entry in body["history"]]
    assert "Version 1 gesendet" in labels


def test_list_contacts_schema(api) -> None:
    base, _ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/contacts")
    assert status == 200
    assert len(body["contacts"]) >= 1
    row = body["contacts"][0]
    assert set(row) == {
        "contact_key",
        "identity_source",
        "display_name",
        "email",
        "phone",
        "inquiry_count",
        "open_inquiries",
        "active_orders",
        "linked_order_count",
        "contact_status",
        "last_activity",
    }


def test_list_contacts_grouped_by_email(api) -> None:
    base, ids, _db = api
    inquiry_id = ids["inquiry_convertible"]
    _status, detail, _h = _get(f"{base}/office/v1/inquiries/{inquiry_id}")
    status, body, _h = _post(
        f"{base}/office/v1/inquiries/{inquiry_id}/update",
        args={
            "event_date": detail["event_date"],
            "crm_stage": detail["crm_stage"],
            "time_window_text": detail["time_window_text"],
            "location_text": detail["location_text"],
            "guest_count_estimate": detail["guest_count_estimate"],
            "planning_mode": detail["planning_mode"],
            "intake_message": (
                "Firma: Test GmbH\n"
                "Name: Max Mustermann\n"
                "E-Mail: kontakt@example.invalid\n"
                "Telefon: 0151 2345678\n"
            ),
        },
        expect={"updated_at": detail["updated_at"]},
    )
    assert status == 200
    status, body, _h = _get(f"{base}/office/v1/contacts")
    assert status == 200
    assert len(body["contacts"]) >= 1
    row = next(
        item
        for item in body["contacts"]
        if item["contact_key"] == "intake:email:kontakt@example.invalid"
    )
    assert row["identity_source"] == "intake_email"
    assert row["email"] == "kontakt@example.invalid"
    assert row["inquiry_count"] >= 1


def test_contact_detail_not_found(api) -> None:
    base, _ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/contacts/inquiry%3Amissing-id")
    assert status == 404
    assert body["error"] == "not_found"


def test_list_emails_schema(api) -> None:
    base, _ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/emails")
    assert status == 200
    assert body["emails"] == []


def test_list_emails_email_source_only(api, tmp_path: Path) -> None:
    base, ids, db = api
    from catering_system.repositories.sqlite_inquiry_repository import (
        SQLiteInquiryRepository,
    )
    from catering_system.services.inquiry_service import InquiryService

    inquiry_repo = SQLiteInquiryRepository(db)
    email_inquiry = InquiryService(inquiry_repo).create_inquiry(
        event_date=date(2026, 9, 1),
        inquiry_source="email",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="abends",
        location_text="Sommerfest",
        guest_count_estimate=40,
        planning_mode="caterer_suggestion",
        call_verification_required=True,
        call_verification_status="pending",
        intake_message="E-Mail: mail@example.invalid\n",
    )
    inquiry_repo.close()

    status, body, _h = _get(f"{base}/office/v1/emails")
    assert status == 200
    assert len(body["emails"]) == 1
    row = body["emails"][0]
    assert set(row) == {
        "email_id",
        "inquiry_id",
        "contact_key",
        "sender_name",
        "sender_email",
        "subject",
        "preview",
        "crm_stage",
        "received_at",
        "external_ref",
        "linked_offer_id",
        "linked_order_ids",
    }
    assert row["email_id"] == email_inquiry.inquiry_id
    assert row["inquiry_id"] == email_inquiry.inquiry_id
    assert row["subject"] is None
    assert row["preview"] == "E-Mail: mail@example.invalid"
    assert row["sender_email"] == "mail@example.invalid"
    assert row["crm_stage"] == "Neue Anfrage"
    assert ids["inquiry_website"] not in {item["inquiry_id"] for item in body["emails"]}


def test_email_detail_not_found(api) -> None:
    base, ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/emails/{ids['inquiry_convertible']}")
    assert status == 404
    assert body["error"] == "not_found"


def test_list_tasks_schema(api) -> None:
    base, _ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/tasks")
    assert status == 200
    assert isinstance(body["tasks"], list)


def test_list_calendar_schema(api) -> None:
    base, ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/calendar?from=2026-10-01&to=2026-10-31")
    assert status == 200
    assert isinstance(body["entries"], list)
    assert len(body["entries"]) == 6
    by_inquiry = {row["source_inquiry_id"]: row for row in body["entries"]}
    assert ids["inquiry_rejected"] not in by_inquiry
    assert ids["inquiry_cancelled_order"] not in by_inquiry
    assert ids["inquiry_offer_ready"] in by_inquiry
    assert by_inquiry[ids["inquiry_printed"]]["entry_kind"] == "event_confirmed"
    assert by_inquiry[ids["inquiry_unprinted"]]["entry_kind"] == "event_planned"
    row = next(row for row in body["entries"] if row["entry_kind"] == "event_confirmed")
    assert set(row) == {
        "entry_id",
        "entry_kind",
        "status_label",
        "title",
        "event_date",
        "time_window_text",
        "location_text",
        "guest_count_estimate",
        "entity_type",
        "entity_id",
        "action_label",
        "action_href",
        "source_inquiry_id",
    }
    assert row["status_label"] == "Bestätigt"


def test_list_calendar_requires_from_and_to(api) -> None:
    base, _ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/calendar")
    assert status == 400
    assert body["error"] == "invalid_request"


def test_list_tasks_verify_and_work_center_count(api) -> None:
    base, ids, _db = api
    inquiry_id = ids["inquiry_verify"]
    status, body, _h = _get(f"{base}/office/v1/tasks")
    assert status == 200
    verify_rows = [
        row for row in body["tasks"] if row["task_id"] == f"inquiry:{inquiry_id}:verify"
    ]
    assert len(verify_rows) == 1
    row = verify_rows[0]
    assert set(row) == {
        "task_id",
        "category",
        "title",
        "subtitle",
        "entity_type",
        "entity_id",
        "action_label",
        "action_href",
        "due_at",
        "urgency",
        "opened_at",
    }
    assert row["category"] == "verify"
    assert row["entity_type"] == "inquiry"
    assert row["action_href"] == f"/inquiry/{inquiry_id}"
    wc_status, wc_body, _h = _get(f"{base}/office/v1/work-center")
    assert wc_status == 200
    assert wc_body["open_tasks"] == len(body["tasks"])


def test_inquiry_list_rows_and_search(api) -> None:
    base, ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/inquiries")
    assert status == 200
    assert set(body) == {"inquiries", "total_count", "limit", "offset"}
    assert body["total_count"] == 8
    by_id = {row["inquiry_id"]: row for row in body["inquiries"]}
    row = by_id[ids["inquiry_printed"]]
    assert row["linked_order_id"] == ids["order_ready"]
    assert row["orders_total_count"] == 1
    cancelled_row = by_id[ids["inquiry_cancelled_order"]]
    assert cancelled_row["linked_order_id"] is None  # only ACTIVE orders link
    assert cancelled_row["orders_total_count"] == 1
    assert by_id[ids["inquiry_offer_ready"]]["linked_order_id"] is None
    assert by_id[ids["inquiry_offer_ready"]]["orders_total_count"] == 0

    status, body, _h = _get(f"{base}/office/v1/inquiries?q=Sommerfest")
    assert body["total_count"] == 1
    assert body["inquiries"][0]["inquiry_id"] == ids["inquiry_convertible"]


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "limit=abc",
        "offset=-1",
        "foo=bar",
        "limit=10&limit=10",
        "q=" + "x" * 201,
    ],
)
def test_list_pagination_strictness(api, query: str) -> None:
    base, _ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/inquiries?{query}")
    assert (status, body["error"]) == (400, "invalid_request")


def test_pagination_slices_with_honest_total(api) -> None:
    base, _ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/inquiries?limit=2&offset=4")
    assert status == 200
    assert body["total_count"] == 8
    assert len(body["inquiries"]) == 2
    assert (body["limit"], body["offset"]) == (2, 4)


def test_order_list_rows_carry_derived_state(api) -> None:
    base, ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/orders")
    assert status == 200
    by_id = {row["order_id"]: row for row in body["orders"]}
    ready_row = by_id[ids["order_ready"]]
    assert ready_row["ready"] is True and ready_row["blocker_reason"] is None
    assert ready_row["next_action"] is None
    blocked_row = by_id[ids["order_unprinted"]]
    assert blocked_row["ready"] is False
    assert blocked_row["blocker_reason"] == "no_effective_version"
    cancelled_row = by_id[ids["order_cancelled"]]
    assert cancelled_row["blocker_reason"] == "order_cancelled"
    assert cancelled_row["next_action"] is None
    # ordering preserved: repository order is by order_id
    listed = [row["order_id"] for row in body["orders"]]
    assert listed == sorted(listed)


def test_inquiry_detail_shape(api) -> None:
    base, ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/inquiries/{ids['inquiry_printed']}")
    assert status == 200
    assert body["allows_conversion"] is False
    assert body["next_action"] is None
    assert body["offer_preparation_blockers"] == ["active_order_exists"]
    assert "offer" not in body
    assert body["orders"] == [{"order_id": ids["order_ready"], "cancelled_at": None}]
    assert body["orders_truncated"] is False
    assert body["customer_linkage"] == {}
    assert body["customer_id"] is None
    assert body["customer_snapshot"] == {
        "company_name": "Example GmbH",
        "contact_name": "Example Contact",
        "email": "kunde@example.com",
        "phone": "+49301234567",
        "invoice_address": None,
        "delivery_address": None,
        "delivery_address_mode": "UNKNOWN",
    }
    assert body["contact_completeness"] == "complete"
    assert body["missing_contact_fields"] == []
    assert body["contact_completion_allowed"] is False
    prefill = body["offer_prefill"]
    assert prefill["schema_version"] == "core_inquiry_offer_prefill_v1"
    assert prefill["inquiry_id"] == ids["inquiry_printed"]
    status, _body, _h = _get(f"{base}/office/v1/inquiries/{uuid.uuid4()}")
    assert status == 404


def test_prepared_offer_changes_queue_and_detail_projection(api) -> None:
    base, ids, _db = api
    inquiry_id = ids["inquiry_convertible"]
    status, _body, _h = _post(
        f"{base}/office/v1/inquiries/{inquiry_id}/prepare-offer",
        args={"snapshot": _valid_offer_snapshot(inquiry_id=inquiry_id)},
    )
    assert status == 201

    status, body, _h = _get(f"{base}/office/v1/queue")
    assert status == 200
    top_actions = {
        row["inquiry_id"]: row["next_action"] for row in body["neue_anfragen_top"]
    }
    assert top_actions[inquiry_id] == "offer-pending"

    status, detail, _h = _get(f"{base}/office/v1/inquiries/{inquiry_id}")
    assert status == 200
    assert detail["allows_conversion"] is False
    assert detail["next_action"] == "offer-pending"
    assert detail["offer_preparation_blockers"] == ["offer_already_exists"]
    assert detail["offer"]["commercial_state"] == "Prepared"


def test_order_detail_and_print_data(api) -> None:
    base, ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/orders/{ids['order_ready']}")
    assert status == 200
    assert body["ready_to_send"] == {"ready": True, "reasons": []}
    assert body["operational_pause"] == {"active": False, "latest_pause_event_id": None}
    assert [v["version_number"] for v in body["versions"]] == [1]
    assert body["versions_truncated"] is False

    status, body, _h = _get(
        f"{base}/office/v1/orders/{ids['order_ready']}/print-data"
        f"?version={ids['version_ready']}"
    )
    assert status == 200
    assert set(body) == {"order", "version", "projection"}
    assert body["projection"]["commercial"]["source"] == "offer_conversion"
    assert body["projection"]["commercial"]["positions"]

    status, body, _h = _get(
        f"{base}/office/v1/orders/{ids['order_ready']}/buffet-cards-data"
        f"?version={ids['version_ready']}"
    )
    assert status == 200
    assert set(body) == {"projection", "cards", "effective_version_number"}
    assert len(body["cards"]) == 1
    assert body["effective_version_number"] == 1

    # unknown and unowned are the same 404 (no distinction leaked)
    status, _b, _h = _get(
        f"{base}/office/v1/orders/{ids['order_ready']}/print-data"
        f"?version={ids['version_unprinted']}"
    )
    assert status == 404
    status, body, _h = _get(f"{base}/office/v1/orders/{ids['order_ready']}/print-data")
    assert (status, body["error"]) == (400, "invalid_request")


def test_payment_reminder_read_write_replay_and_stale_gate(api) -> None:
    base, ids, _db = api
    order_id = ids["order_unprinted"]
    detail_url = f"{base}/office/v1/orders/{order_id}"
    command_url = f"{detail_url}/payment-reminder"
    status, before, _h = _get(detail_url)
    assert status == 200
    assert before["payment_reminder"]["payment_method"] is None
    assert before["payment_reminder"]["next_step"] == "Zahlungsart auswählen"
    operational_before = {
        key: before[key]
        for key in (
            "candidate_order_version_id",
            "effective_order_version_id",
            "ready_to_send",
            "versions",
        )
    }
    args = {
        "payment_method": "VORKASSE",
        "invoice_created": True,
        "invoice_number": "RE-2026-0048",
        "sent_on": "2026-07-15",
        "due_on": (date.today() + timedelta(days=7)).isoformat(),
        "paid_on": None,
        "cash_received": False,
    }
    command_id = str(uuid.uuid4())

    status, saved, _h = _post(
        command_url,
        args=args,
        expect={"updated_at": None},
        command_id=command_id,
    )
    assert status == 200
    assert set(saved) == {"command_id", "order_id", "updated_at"}
    status, replay, _h = _post(
        command_url,
        args=args,
        expect={"updated_at": None},
        command_id=command_id,
    )
    assert (status, replay) == (200, saved)

    status, after, _h = _get(detail_url)
    assert status == 200
    reminder = after["payment_reminder"]
    assert reminder["payment_method_label"] == "Vorkasse"
    assert reminder["invoice_number"] == "RE-2026-0048"
    assert reminder["payment_state_label"] == "Offen"
    assert reminder["next_step"] == "Zahlungseingang prüfen"
    assert {key: after[key] for key in operational_before} == operational_before

    status, body, _h = _post(command_url, args=args, expect={"updated_at": None})
    assert (status, body["error"]) == (409, "stale_state")


def test_payment_reminder_rejects_cancelled_order_and_contradictory_facts(api) -> None:
    base, ids, _db = api
    base_args = {
        "payment_method": "BAR_VOR_ORT",
        "invoice_created": False,
        "invoice_number": None,
        "sent_on": None,
        "due_on": None,
        "paid_on": None,
        "cash_received": True,
    }
    status, body, _h = _post(
        f"{base}/office/v1/orders/{ids['order_unprinted']}/payment-reminder",
        args=base_args,
        expect={"updated_at": None},
    )
    assert (status, body["error"]) == (422, "invalid_payment_reminder")

    status, body, _h = _post(
        f"{base}/office/v1/orders/{ids['order_cancelled']}/payment-reminder",
        args={**base_args, "cash_received": False},
        expect={"updated_at": None},
    )
    assert (status, body["error"]) == (422, "order_cancelled")


# --- command envelope strictness ----------------------------------------------


def test_envelope_strictness(api) -> None:
    base, _ids, _db = api
    url = f"{base}/office/v1/inquiries"
    cases: list[bytes] = [
        b"not json",
        json.dumps({"command_id": str(uuid.uuid4()), "args": _CREATE_ARGS}).encode(),
        json.dumps(
            {
                "command_id": str(uuid.uuid4()),
                "expect": {},
                "args": _CREATE_ARGS,
                "extra": 1,
            }
        ).encode(),
        json.dumps(
            {
                "command_id": "not-a-uuid",
                "expect": {},
                "args": _CREATE_ARGS,
            }
        ).encode(),
        json.dumps(
            {
                "command_id": str(uuid.uuid4()),
                "expect": {},
                "args": dict(_CREATE_ARGS, unknown_key=1),
            }
        ).encode(),
        b'{"command_id": "a", "command_id": "b", "expect": {}, "args": {}}',
    ]
    for raw in cases:
        status, body, _h = _post(url, raw_body=raw)
        assert (status, body["error"]) == (400, "invalid_request"), raw[:40]


def test_transport_rules_on_commands(api) -> None:
    base, _ids, _db = api
    url = f"{base}/office/v1/inquiries"
    # wrong content type
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={**_AUTH, "Content-Type": "text/plain"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 415
    # empty body
    req = urllib.request.Request(
        url,
        data=b"",
        headers={**_AUTH, "Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 400
    # oversized body
    huge = json.dumps(
        {
            "command_id": str(uuid.uuid4()),
            "expect": {},
            "args": dict(_CREATE_ARGS, intake_message="x" * (64 * 1024)),
        }
    ).encode()
    status, body, _h = _post(url, raw_body=huge)
    assert (status, body["error"]) == (413, "body_too_large")
    # GET must reject a body
    req = urllib.request.Request(
        f"{base}/office/v1/queue", data=b"x", headers=_AUTH, method="GET"
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 400


# --- commands ------------------------------------------------------------------


def test_create_inquiry_minimal_result_and_type_strictness(api) -> None:
    base, _ids, _db = api
    url = f"{base}/office/v1/inquiries"
    status, body, _h = _post(url, args=_CREATE_ARGS)
    assert status == 201
    assert set(body) == {"command_id", "inquiry_id", "updated_at"}

    for mutation in (
        {"guest_count_estimate": True},
        {"guest_count_estimate": 0},
        {"guest_count_estimate": 2001},
        {"event_date": "2026-13-01"},
        {"event_date": "20261101"},
        {"call_verification_required": "yes"},
        {"inquiry_source": "unknown_source"},
        {"intake_subject": "x" * 1001},
    ):
        status, body, _h = _post(url, args=dict(_CREATE_ARGS, **mutation))
        assert (status, body["error"]) == (400, "invalid_request"), mutation


def test_update_requires_matching_updated_at(api) -> None:
    base, ids, _db = api
    inquiry_id = ids["inquiry_convertible"]
    _s, detail, _h = _get(f"{base}/office/v1/inquiries/{inquiry_id}")
    args = {
        "event_date": "2026-10-02",
        "crm_stage": "Neue Anfrage",
        "time_window_text": "abends",
        "location_text": "Hamburg-Altona",
        "guest_count_estimate": 30,
        "planning_mode": "caterer_suggestion",
    }
    stale = "2020-01-01T00:00:00+00:00"
    status, body, _h = _post(
        f"{base}/office/v1/inquiries/{inquiry_id}/update",
        args=args,
        expect={"updated_at": stale},
    )
    assert (status, body["error"]) == (409, "stale_state")
    status, body, _h = _post(
        f"{base}/office/v1/inquiries/{inquiry_id}/update",
        args=args,
        expect={"updated_at": detail["updated_at"]},
    )
    assert status == 200
    assert set(body) == {"command_id", "inquiry_id", "updated_at"}
    assert body["updated_at"] != detail["updated_at"]


def test_verify_then_convert_hard_blocks_without_accepted_offer(api) -> None:
    base, ids, _db = api
    inquiry_id = ids["inquiry_verify"]
    status, body, _h = _post(f"{base}/office/v1/inquiries/{inquiry_id}/convert")
    assert (status, body["error"]) == (422, "accepted_offer_required")
    status, body, _h = _post(f"{base}/office/v1/inquiries/{inquiry_id}/verify")
    assert status == 200
    status, body, _h = _post(f"{base}/office/v1/inquiries/{inquiry_id}/convert")
    assert (status, body["error"]) == (422, "accepted_offer_required")
    status, detail, _h = _get(f"{base}/office/v1/inquiries/{inquiry_id}")
    assert status == 200
    assert detail["allows_conversion"] is False
    assert detail["orders_total_count"] == 0


def test_rejected_inquiry_cannot_convert(api) -> None:
    base, ids, _db = api
    status, body, _h = _post(
        f"{base}/office/v1/inquiries/{ids['inquiry_rejected']}/convert"
    )
    assert (status, body["error"]) == (422, "accepted_offer_required")


def test_convert_after_storno_returns_existing_order_via_api(api) -> None:
    base, ids, _db = api
    inquiry_id = ids["inquiry_cancelled_order"]  # its only order is cancelled
    status, first, _h = _get(f"{base}/office/v1/inquiries/{inquiry_id}")
    assert status == 200
    existing_order_id = first["orders"][0]["order_id"]
    status, body, _h = _post(f"{base}/office/v1/inquiries/{inquiry_id}/convert")
    assert status == 200
    assert body["order_id"] == existing_order_id


def test_legacy_convert_without_order_requires_accepted_offer(api) -> None:
    base, ids, _db = api
    inquiry_id = ids["inquiry_convertible"]
    status, body, _h = _post(f"{base}/office/v1/inquiries/{inquiry_id}/convert")
    assert (status, body["error"]) == (422, "accepted_offer_required")


def test_legacy_convert_with_prepared_offer_still_requires_accepted_offer(api) -> None:
    base, ids, db = api
    offer_id, _version_id = _prepare_offer(api)
    inquiry_id = ids["inquiry_offer_ready"]
    status, body, _h = _post(f"{base}/office/v1/inquiries/{inquiry_id}/convert")
    assert (status, body["error"]) == (422, "accepted_offer_required")
    conn = sqlite3.connect(db)
    order_count = conn.execute(
        """
        SELECT COUNT(*) FROM orders
        WHERE source_inquiry_id = ?
        """,
        (inquiry_id,),
    ).fetchone()[0]
    conn.close()
    assert order_count == 0
    offers = SQLiteOfferRepository(db)
    stored = offers.get(offer_id)
    assert stored is not None
    assert stored.conversion_link is None
    offers.close()


def test_legacy_convert_with_expired_offer_still_requires_accepted_offer(api) -> None:
    base, ids, db = api
    inquiry_id = ids["inquiry_offer_ready"]
    snapshot = _valid_offer_snapshot(inquiry_id=inquiry_id)
    snapshot["valid_until"] = "2020-01-01"
    snapshot["snapshot_hash"] = compute_snapshot_hash(snapshot)
    prepare_status, prepare_body, _h = _post(
        _prepare_offer_url(base, inquiry_id),
        args={"snapshot": snapshot},
    )
    assert prepare_status == 201
    offer_id = prepare_body["offer_id"]
    version_id = prepare_body["offer_version_id"]
    assert (
        _post(
            _mark_sent_url(base, offer_id, version_id),
            args=_MARK_SENT_ARGS,
        )[0]
        == 200
    )
    status, body, _h = _post(f"{base}/office/v1/inquiries/{inquiry_id}/convert")
    assert (status, body["error"]) == (422, "accepted_offer_required")
    conn = sqlite3.connect(db)
    order_count = conn.execute(
        """
        SELECT COUNT(*) FROM orders
        WHERE source_inquiry_id = ?
        """,
        (inquiry_id,),
    ).fetchone()[0]
    conn.close()
    assert order_count == 0


def test_versions_expect_and_cancelled_gate(api) -> None:
    base, ids, db = api
    args = {
        "event_date": "2026-10-03",
        "time_window_text": "früh",
        "location_text": "Bremen",
        "guest_count_estimate": None,
        "planning_mode": "caterer_suggestion",
    }
    url = f"{base}/office/v1/orders/{ids['order_ready']}/versions"
    version_expect = {
        "latest_version_number": 7,
        "current_effective_order_version_id": ids["version_ready"],
        "current_candidate_order_version_id": None,
    }
    status, body, _h = _post(url, args=args, expect=version_expect)
    assert (status, body["error"]) == (409, "stale_state")
    version_expect["latest_version_number"] = 1
    command_id = str(uuid.uuid4())
    status, body, _h = _post(
        url, args=args, expect=version_expect, command_id=command_id
    )
    assert status == 201
    assert set(body) == {
        "command_id",
        "order_version_id",
        "version_number",
        "candidate_order_version_id",
        "parent_order_version_id",
        "changed_fields",
    }
    assert body["version_number"] == 2
    created = body
    replay_status, replay, _h = _post(
        url, args=args, expect=version_expect, command_id=command_id
    )
    assert replay_status == 201
    assert replay == created
    status, detail, _h = _get(f"{base}/office/v1/orders/{ids['order_ready']}")
    assert detail["candidate_order_version_id"] == body["order_version_id"]
    assert detail["effective_order_version_id"] == ids["version_ready"]
    assert detail["ready_to_send"] == {
        "ready": False,
        "reasons": ["pending_order_version_change"],
    }
    assert detail["version_change"]["pending"] is True
    assert detail["version_change"]["kitchen_reprint_required"] is True
    assert len(detail["versions"]) == 2

    effective_url = f"{base}/office/v1/orders/{ids['order_ready']}/effective"
    effective_expect = {
        "current_effective_order_version_id": ids["version_ready"],
        "current_candidate_order_version_id": body["order_version_id"],
    }
    status, rejected, _h = _post(
        effective_url,
        args={"order_version_id": body["order_version_id"]},
        expect=effective_expect,
    )
    assert (status, rejected["error"]) == (422, "kitchen_print_not_confirmed")
    status, _confirmed, _h = _post(
        f"{base}/office/v1/orders/{ids['order_ready']}/print-confirm",
        args={"order_version_id": body["order_version_id"]},
    )
    assert status == 200
    _ack_next_kitchen_job(db, body["order_version_id"])
    status, detail, _h = _get(f"{base}/office/v1/orders/{ids['order_ready']}")
    assert status == 200
    assert detail["effective_order_version_id"] == body["order_version_id"]
    assert detail["candidate_order_version_id"] is None

    status, body, _h = _post(
        f"{base}/office/v1/orders/{ids['order_cancelled']}/versions",
        args=args,
        expect={
            "latest_version_number": 1,
            "current_effective_order_version_id": None,
            "current_candidate_order_version_id": None,
        },
    )
    assert (status, body["error"]) == (422, "order_cancelled")


def test_delivery_address_version_command_creates_explicit_context(api) -> None:
    base, _ids, db = api
    order_id, parent_id = _create_order_with_operational_context(db)
    url = f"{base}/office/v1/orders/{order_id}/versions"
    new_address = {
        "street": "Neuer Weg 5",
        "postal_code": "20095",
        "city": "Hamburg",
        "country": "Deutschland",
    }

    status, body, _h = _post(
        url,
        args={
            "parent_order_version_id": parent_id,
            "delivery_address": new_address,
            "actor_reference": "office-panel",
            "change_reason": "Lieferadresse geändert",
        },
        expect={
            "latest_version_number": 1,
            "current_effective_order_version_id": None,
            "current_candidate_order_version_id": None,
        },
    )

    assert status == 201
    assert body["version_number"] == 2
    assert body["parent_order_version_id"] == parent_id
    assert body["changed_fields"] == ["delivery_address"]
    conn = sqlite3.connect(db)
    rows = conn.execute(
        """
        SELECT order_version_id, source, recipient_company, recipient_name,
               recipient_phone, delivery_address_json
        FROM order_version_operational_context_snapshots
        WHERE order_id = ?
        ORDER BY created_at
        """,
        (order_id,),
    ).fetchall()
    inquiry_rows = conn.execute(
        """
        SELECT snapshot_company_name, snapshot_contact_name, snapshot_phone,
               snapshot_delivery_address_json
        FROM inquiries
        WHERE inquiry_id = (SELECT source_inquiry_id FROM orders WHERE order_id = ?)
        """,
        (order_id,),
    ).fetchall()
    conn.close()
    assert len(rows) == 2
    v1_row, v2_row = rows
    assert v1_row[1] == "initial_inquiry_snapshot"
    assert v2_row[0] == body["order_version_id"]
    assert v2_row[1] == "explicit_change"
    assert v2_row[2:5] == ("A GmbH", "B Person", "+4940235649")
    assert json.loads(v2_row[5]) == new_address
    assert v1_row[5] != v2_row[5]
    assert inquiry_rows == [("A GmbH", "B Person", "+4940235649", None)]


def test_delivery_address_version_command_rejects_missing_parent_context(api) -> None:
    base, ids, db = api
    order_id = ids["order_unprinted"]
    parent_id = ids["version_unprinted"]
    conn = sqlite3.connect(db)
    before_count = conn.execute(
        "SELECT COUNT(*) FROM order_versions WHERE order_id = ?",
        (order_id,),
    ).fetchone()[0]
    conn.close()

    status, body, _h = _post(
        f"{base}/office/v1/orders/{order_id}/versions",
        args={
            "parent_order_version_id": parent_id,
            "delivery_address": {
                "street": "Neuer Weg 5",
                "postal_code": "20095",
                "city": "Hamburg",
                "country": "Deutschland",
            },
        },
        expect={
            "latest_version_number": 1,
            "current_effective_order_version_id": None,
            "current_candidate_order_version_id": None,
        },
    )

    conn = sqlite3.connect(db)
    after_count = conn.execute(
        "SELECT COUNT(*) FROM order_versions WHERE order_id = ?",
        (order_id,),
    ).fetchone()[0]
    candidate = conn.execute(
        "SELECT candidate_order_version_id FROM orders WHERE order_id = ?",
        (order_id,),
    ).fetchone()[0]
    conn.close()
    assert (status, body["error"]) == (422, "operational_context_missing")
    assert after_count == before_count
    assert candidate is None


def test_delivery_address_version_command_rejects_parent_not_owned(api) -> None:
    base, ids, db = api
    order_id, _parent_id = _create_order_with_operational_context(db)
    conn = sqlite3.connect(db)
    before_count = conn.execute(
        "SELECT COUNT(*) FROM order_versions WHERE order_id = ?",
        (order_id,),
    ).fetchone()[0]
    conn.close()

    status, body, _h = _post(
        f"{base}/office/v1/orders/{order_id}/versions",
        args={
            "parent_order_version_id": ids["version_ready"],
            "delivery_address": {
                "street": "Neuer Weg 5",
                "postal_code": None,
                "city": None,
                "country": None,
            },
        },
        expect={
            "latest_version_number": 1,
            "current_effective_order_version_id": None,
            "current_candidate_order_version_id": None,
        },
    )
    conn = sqlite3.connect(db)
    after_count = conn.execute(
        "SELECT COUNT(*) FROM order_versions WHERE order_id = ?",
        (order_id,),
    ).fetchone()[0]
    conn.close()
    assert (status, body["error"]) == (422, "version_not_owned")
    assert after_count == before_count


def test_delivery_address_version_command_preserves_stale_state_gate(api) -> None:
    base, _ids, db = api
    order_id, parent_id = _create_order_with_operational_context(db)
    status, body, _h = _post(
        f"{base}/office/v1/orders/{order_id}/versions",
        args={
            "parent_order_version_id": parent_id,
            "delivery_address": {
                "street": "Neuer Weg 5",
                "postal_code": None,
                "city": None,
                "country": None,
            },
        },
        expect={
            "latest_version_number": 9,
            "current_effective_order_version_id": None,
            "current_candidate_order_version_id": None,
        },
    )
    assert (status, body["error"]) == (409, "stale_state")


def test_print_confirm_effective_and_gates(api) -> None:
    base, ids, db = api
    order_id = ids["order_unprinted"]
    version_id = ids["version_unprinted"]
    # effective before print: existing gate
    status, body, _h = _post(
        f"{base}/office/v1/orders/{order_id}/effective",
        args={"order_version_id": version_id},
        expect={
            "current_effective_order_version_id": None,
            "current_candidate_order_version_id": None,
        },
    )
    assert (status, body["error"]) == (422, "kitchen_print_not_confirmed")
    # foreign version
    status, body, _h = _post(
        f"{base}/office/v1/orders/{order_id}/print-confirm",
        args={"order_version_id": ids["version_ready"]},
    )
    assert (status, body["error"]) == (422, "version_not_owned")
    # happy print-confirm starts the kitchen print job; it does not confirm print.
    for _round in range(2):
        status, body, _h = _post(
            f"{base}/office/v1/orders/{order_id}/print-confirm",
            args={"order_version_id": version_id},
        )
        assert status == 200
        assert set(body) == {
            "command_id",
            "order_id",
            "order_version_id",
            "print_job_id",
            "kitchen_print_confirmed_at",
        }
        assert body["kitchen_print_confirmed_at"] is None
    status, body, _h = _post(
        f"{base}/office/v1/orders/{order_id}/effective",
        args={"order_version_id": version_id},
        expect={
            "current_effective_order_version_id": None,
            "current_candidate_order_version_id": None,
        },
    )
    assert (status, body["error"]) == (422, "kitchen_print_not_confirmed")
    _ack_next_kitchen_job(db, version_id)
    status, detail, _h = _get(f"{base}/office/v1/orders/{order_id}")
    assert status == 200
    assert detail["effective_order_version_id"] == version_id
    # effective with stale pointer expectation
    status, body, _h = _post(
        f"{base}/office/v1/orders/{order_id}/effective",
        args={"order_version_id": version_id},
        expect={
            "current_effective_order_version_id": version_id,
            "current_candidate_order_version_id": None,
        },
    )
    assert status == 200
    status, body, _h = _post(
        f"{base}/office/v1/orders/{order_id}/effective",
        args={"order_version_id": version_id},
        expect={
            "current_effective_order_version_id": None,
            "current_candidate_order_version_id": None,
        },
    )
    assert (status, body["error"]) == (409, "stale_state")
    # print-confirm on a cancelled order: API-level gate
    status, body, _h = _post(
        f"{base}/office/v1/orders/{ids['order_cancelled']}/print-confirm",
        args={"order_version_id": ids["version_cancelled"]},
    )
    assert (status, body["error"]) == (422, "order_cancelled")


def test_confirmed_old_version_does_not_authorize_new_candidate(api) -> None:
    base, ids, db = api
    order_id = ids["order_ready"]
    v1_id = ids["version_ready"]
    status, body, _h = _post(
        f"{base}/office/v1/orders/{order_id}/versions",
        args={
            "event_date": "2026-10-02",
            "time_window_text": "abends",
            "location_text": "Bremen",
            "guest_count_estimate": 30,
            "planning_mode": "caterer_suggestion",
        },
        expect={
            "latest_version_number": 1,
            "current_effective_order_version_id": v1_id,
            "current_candidate_order_version_id": None,
        },
    )
    assert status == 201
    v2_id = body["order_version_id"]

    status, body, _h = _post(
        f"{base}/office/v1/orders/{order_id}/effective",
        args={"order_version_id": v2_id},
        expect={
            "current_effective_order_version_id": v1_id,
            "current_candidate_order_version_id": v2_id,
        },
    )
    assert (status, body["error"]) == (422, "kitchen_print_not_confirmed")

    status, body, _h = _post(
        f"{base}/office/v1/orders/{order_id}/print-confirm",
        args={"order_version_id": v2_id},
    )
    assert status == 200
    assert body["kitchen_print_confirmed_at"] is None
    _ack_next_kitchen_job(db, str(v2_id))

    status, body, _h = _get(f"{base}/office/v1/orders/{order_id}")
    assert status == 200
    assert body["effective_order_version_id"] == v2_id


def test_stale_accepted_print_attempt_requires_explicit_reprint(api) -> None:
    base, ids, db = api
    order_id = ids["order_unprinted"]
    version_id = ids["version_unprinted"]
    stale_job_id = str(uuid.uuid4())
    requested_at = datetime.now(UTC) - timedelta(minutes=12)
    accepted_at = requested_at + timedelta(seconds=1)

    orders = SQLiteOrderRepository(db)
    jobs = SQLiteKitchenPrintJobRepository(db)
    jobs.save(
        KitchenPrintJob(
            print_job_id=stale_job_id,
            order_id=order_id,
            order_version_id=version_id,
            attempt_number=1,
            requested_at=requested_at,
            accept_deadline_at=requested_at + timedelta(seconds=30),
            accepted_at=accepted_at,
            ack_deadline_at=accepted_at + timedelta(minutes=5),
        )
    )
    service = KitchenPrintService(orders, jobs)
    with pytest.raises(ValueError, match="ACK deadline has passed"):
        service.acknowledge_print_job(stale_job_id)
    version = orders.get_order_version(version_id)
    assert version is not None
    assert version.kitchen_print_confirmed_at is None
    jobs.close()
    orders.close()

    status, body, _h = _post(
        f"{base}/office/v1/orders/{order_id}/print-confirm",
        args={"order_version_id": version_id},
    )

    assert status == 200
    assert body["kitchen_print_confirmed_at"] is None
    assert body["print_job_id"] != stale_job_id
    jobs = SQLiteKitchenPrintJobRepository(db)
    attempts = jobs.list_for_version(version_id)
    jobs.close()
    assert [attempt.attempt_number for attempt in attempts] == [1, 2]
    assert attempts[0].superseded_at is not None
    assert attempts[1].supersedes_print_job_id == stale_job_id


def test_ready_unknown_order_is_200_with_reason(api) -> None:
    base, _ids, _db = api
    status, body, _h = _post(f"{base}/office/v1/orders/{uuid.uuid4()}/ready")
    assert status == 200
    assert body["evaluation"]["ready"] is False
    assert body["evaluation"]["reasons"] == ["ready_to_send_order_not_found"]


def test_order_operational_pause_and_resume_commands(api) -> None:
    base, ids, _db = api
    order_id = ids["order_ready"]
    pause_url = f"{base}/office/v1/orders/{order_id}/pause"
    resume_url = f"{base}/office/v1/orders/{order_id}/resume"

    status, detail, _h = _get(f"{base}/office/v1/orders/{order_id}")
    assert detail["operational_pause"] == {
        "active": False,
        "latest_pause_event_id": None,
    }

    pause_args = {"reason_code": "manual_hold", "note": "hold for review"}
    pause_expect = {
        "operational_pause_active": False,
        "latest_pause_event_id": None,
    }
    command_id = str(uuid.uuid4())
    status, body, _h = _post(
        pause_url,
        args=pause_args,
        expect=pause_expect,
        command_id=command_id,
    )
    assert status == 200
    assert set(body) == {
        "command_id",
        "order_id",
        "pause_event_id",
        "operational_pause",
    }
    assert body["operational_pause"]["active"] is True
    assert body["operational_pause"]["reason_code"] == "manual_hold"
    assert body["operational_pause"]["current_pause_event_id"] == body["pause_event_id"]
    status2, body2, _h = _post(
        pause_url,
        args=pause_args,
        expect=pause_expect,
        command_id=command_id,
    )
    assert status2 == 200
    assert body2 == body

    status, detail, _h = _get(f"{base}/office/v1/orders/{order_id}")
    assert detail["operational_pause"]["active"] is True
    assert detail["ready_to_send"] == {
        "ready": False,
        "reasons": ["operational_pause"],
    }

    status, queue, _h = _get(f"{base}/office/v1/queue")
    assert queue["attention"]["pausiert"] == 1
    assert queue["pausiert_top"][0]["order_id"] == order_id
    assert queue["pausiert_top"][0]["operational_pause_active"] is True

    status, orders_page, _h = _get(f"{base}/office/v1/orders?q={order_id}")
    assert status == 200
    assert orders_page["orders"][0]["order_id"] == order_id
    assert orders_page["orders"][0]["operational_pause_active"] is True

    status, body, _h = _post(
        pause_url,
        args={"reason_code": "manual_hold"},
        expect={
            "operational_pause_active": False,
            "latest_pause_event_id": None,
        },
    )
    assert (status, body["error"]) == (409, "stale_state")

    status, body, _h = _post(
        pause_url,
        args={"reason_code": "manual_hold"},
        expect={
            "operational_pause_active": True,
            "latest_pause_event_id": detail["operational_pause"][
                "latest_pause_event_id"
            ],
        },
    )
    assert (status, body["error"]) == (409, "order_already_paused")

    active_pause = detail["operational_pause"]
    status, body, _h = _post(
        resume_url,
        args={"reason_code": "operator_cleared", "note": "cleared"},
        expect={
            "operational_pause_active": True,
            "current_pause_event_id": active_pause["current_pause_event_id"],
            "latest_pause_event_id": active_pause["latest_pause_event_id"],
        },
    )
    assert status == 200
    assert body["operational_pause"]["active"] is False
    assert body["operational_pause"]["latest_pause_event_id"] == body["pause_event_id"]

    status, detail, _h = _get(f"{base}/office/v1/orders/{order_id}")
    assert detail["operational_pause"] == {
        "active": False,
        "latest_pause_event_id": body["pause_event_id"],
    }
    assert detail["ready_to_send"] == {"ready": True, "reasons": []}

    status, body, _h = _post(
        resume_url,
        args={"reason_code": "operator_cleared"},
        expect={
            "operational_pause_active": False,
            "current_pause_event_id": active_pause["current_pause_event_id"],
            "latest_pause_event_id": body["pause_event_id"],
        },
    )
    assert (status, body["error"]) == (409, "order_not_paused")


def test_pause_aba_stale_expect_after_resume_cycle(api) -> None:
    base, ids, _db = api
    order_id = ids["order_ready"]
    pause_url = f"{base}/office/v1/orders/{order_id}/pause"
    resume_url = f"{base}/office/v1/orders/{order_id}/resume"

    status, body, _h = _post(
        pause_url,
        args={"reason_code": "manual_hold"},
        expect={"operational_pause_active": False, "latest_pause_event_id": None},
    )
    assert status == 200
    pause_a = body["operational_pause"]

    status, body, _h = _post(
        resume_url,
        args={"reason_code": "operator_cleared"},
        expect={
            "operational_pause_active": True,
            "current_pause_event_id": pause_a["current_pause_event_id"],
            "latest_pause_event_id": pause_a["latest_pause_event_id"],
        },
    )
    assert status == 200

    status, body, _h = _post(
        pause_url,
        args={"reason_code": "customer_request"},
        expect={"operational_pause_active": False, "latest_pause_event_id": None},
    )
    assert (status, body["error"]) == (409, "stale_state")

    status, detail, _h = _get(f"{base}/office/v1/orders/{order_id}")
    status, body, _h = _post(
        pause_url,
        args={"reason_code": "customer_request"},
        expect={
            "operational_pause_active": False,
            "latest_pause_event_id": detail["operational_pause"][
                "latest_pause_event_id"
            ],
        },
    )
    assert status == 200
    pause_b = body["operational_pause"]

    status, body, _h = _post(
        resume_url,
        args={"reason_code": "operator_cleared"},
        expect={
            "operational_pause_active": True,
            "current_pause_event_id": pause_a["current_pause_event_id"],
            "latest_pause_event_id": pause_b["latest_pause_event_id"],
        },
    )
    assert (status, body["error"]) == (409, "stale_state")


def test_pause_without_effective_version_via_api(api) -> None:
    base, ids, _db = api
    order_id = ids["order_unprinted"]
    status, body, _h = _post(
        f"{base}/office/v1/orders/{order_id}/pause",
        args={"reason_code": "operational_review"},
        expect={
            "operational_pause_active": False,
            "latest_pause_event_id": None,
        },
    )
    assert status == 200
    assert body["operational_pause"]["active"] is True
    status, detail, _h = _get(f"{base}/office/v1/orders/{order_id}")
    assert detail["operational_pause"]["active"] is True
    assert detail["effective_order_version_id"] is None


def test_pause_command_rejects_invalid_contract_and_domain_values(api) -> None:
    base, ids, _db = api
    order_id = ids["order_ready"]
    pause_url = f"{base}/office/v1/orders/{order_id}/pause"

    status, body, _headers = _post(
        pause_url,
        args={"reason_code": "manual_hold"},
        expect={"operational_pause_active": False},
    )
    assert (status, body["error"]) == (400, "invalid_request")

    status, body, _headers = _post(
        pause_url,
        args={"reason_code": "manual_hold"},
        expect={
            "operational_pause_active": "false",
            "latest_pause_event_id": None,
        },
    )
    assert (status, body["error"]) == (400, "invalid_request")

    status, body, _headers = _post(
        pause_url,
        args={"reason_code": "not-a-reason"},
        expect={
            "operational_pause_active": False,
            "latest_pause_event_id": None,
        },
    )
    assert (status, body["error"]) == (422, "invalid_request")

    status, body, _headers = _post(
        pause_url,
        args={"reason_code": "manual_hold", "actor_reference": ""},
        expect={
            "operational_pause_active": False,
            "latest_pause_event_id": None,
        },
    )
    assert (status, body["error"]) == (422, "invalid_request")

    status, body, _headers = _post(
        f"{base}/office/v1/orders/{ids['order_cancelled']}/pause",
        args={"reason_code": "manual_hold"},
        expect={
            "operational_pause_active": False,
            "latest_pause_event_id": None,
        },
    )
    assert (status, body["error"]) == (422, "order_cancelled")


def test_resume_command_rejects_invalid_expect_and_reason(api) -> None:
    base, ids, _db = api
    order_id = ids["order_ready"]
    pause_url = f"{base}/office/v1/orders/{order_id}/pause"
    resume_url = f"{base}/office/v1/orders/{order_id}/resume"
    status, paused, _headers = _post(
        pause_url,
        args={"reason_code": "manual_hold"},
        expect={
            "operational_pause_active": False,
            "latest_pause_event_id": None,
        },
    )
    assert status == 200
    projection = paused["operational_pause"]

    status, body, _headers = _post(
        resume_url,
        args={"reason_code": "operator_cleared"},
        expect={
            "operational_pause_active": True,
            "latest_pause_event_id": projection["latest_pause_event_id"],
        },
    )
    assert (status, body["error"]) == (400, "invalid_request")

    status, body, _headers = _post(
        resume_url,
        args={"reason_code": "invalid"},
        expect={
            "operational_pause_active": True,
            "current_pause_event_id": projection["current_pause_event_id"],
            "latest_pause_event_id": projection["latest_pause_event_id"],
        },
    )
    assert (status, body["error"]) == (422, "invalid_request")


def test_cancel_with_expect_and_repeat(api) -> None:
    base, ids, _db = api
    order_id = ids["order_ready"]
    _s, detail, _h = _get(f"{base}/office/v1/orders/{order_id}")
    status, body, _h = _post(
        f"{base}/office/v1/orders/{order_id}/cancel",
        expect={"updated_at": "2020-01-01T00:00:00+00:00"},
    )
    assert (status, body["error"]) == (409, "stale_state")
    status, body, _h = _post(
        f"{base}/office/v1/orders/{order_id}/cancel",
        expect={"updated_at": detail["updated_at"]},
    )
    assert status == 200
    assert set(body) == {"command_id", "order_id", "cancelled_at", "updated_at"}
    # repeat with fresh expect: idempotent success (current service behavior)
    status, body2, _h = _post(
        f"{base}/office/v1/orders/{order_id}/cancel",
        expect={"updated_at": body["updated_at"]},
    )
    assert status == 200
    assert body2["cancelled_at"] == body["cancelled_at"]


def test_external_ref_conflict_is_recognized_typed(api) -> None:
    base, _ids, _db = api
    args = dict(
        _CREATE_ARGS,
        inquiry_source="website_form",
        intake_external_ref="web-ref-001",  # already seeded
        call_verification_required=True,
    )
    status, body, _h = _post(f"{base}/office/v1/inquiries", args=args)
    assert (status, body["error"]) == (409, "external_ref_conflict")


# --- idempotency ---------------------------------------------------------------


def test_command_replay_returns_recorded_result_without_double_effect(api) -> None:
    base, ids, _db = api
    command_id = str(uuid.uuid4())
    # Compatibility convert on an inquiry that already has an Order.
    url = f"{base}/office/v1/inquiries/{ids['inquiry_cancelled_order']}/convert"
    status1, body1, _h = _post(url, command_id=command_id)
    assert status1 == 200
    status2, body2, _h = _post(url, command_id=command_id)
    assert (status2, body2) == (status1, body1)  # verbatim replay
    _s, detail, _h = _get(
        f"{base}/office/v1/inquiries/{ids['inquiry_cancelled_order']}"
    )
    assert detail["orders_total_count"] == 1


def test_same_command_id_different_fingerprint_conflicts(api) -> None:
    base, ids, _db = api
    command_id = str(uuid.uuid4())
    status, _body, _h = _post(
        f"{base}/office/v1/orders/{ids['order_unprinted']}/ready",
        command_id=command_id,
    )
    assert status == 200
    # same id, different order → conflict, not replay
    status, body, _h = _post(
        f"{base}/office/v1/orders/{ids['order_ready']}/ready",
        command_id=command_id,
    )
    assert (status, body["error"]) == (409, "command_id_conflict")


# --- contention (pack §6.4) ------------------------------------------------------


def test_lock_contention_503_then_safe_retry_same_command_id(api) -> None:
    base, ids, db = api
    command_id = str(uuid.uuid4())
    url = f"{base}/office/v1/inquiries/{ids['inquiry_cancelled_order']}/convert"

    holder = sqlite3.connect(db)
    holder.execute("PRAGMA busy_timeout = 0")
    holder.execute("BEGIN IMMEDIATE")
    try:
        status, body, headers = _post(url, command_id=command_id)
        assert (status, body["error"]) == (503, "core_busy")
        assert headers["Retry-After"] == "1"
    finally:
        holder.rollback()
        holder.close()

    status, body, _h = _post(url, command_id=command_id)
    assert status == 200  # retry with the same command_id succeeds exactly once
    _s, detail, _h = _get(
        f"{base}/office/v1/inquiries/{ids['inquiry_cancelled_order']}"
    )
    assert detail["orders_total_count"] == 1


# --- logging: no PII (pack §5) ---------------------------------------------------


def test_logs_carry_no_contact_or_location_data(api, caplog) -> None:
    import logging

    base, _ids, _db = api
    secret_location = "GEHEIMSTRASSE 99, Hamburg"
    with caplog.at_level(logging.DEBUG, logger="catering_system"):
        status, _body, _h = _post(
            f"{base}/office/v1/inquiries",
            args=dict(_CREATE_ARGS, location_text=secret_location),
        )
    assert status == 201
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "GEHEIMSTRASSE" not in joined
    assert _TOKEN not in joined


def test_startup_refuses_to_run_without_token(tmp_path) -> None:
    """Pack §5: the API cannot be started unauthenticated."""
    import os
    import subprocess
    import sys

    env = dict(os.environ)
    env.pop("OFFICE_API_TOKEN", None)
    env["PYTHONPATH"] = "src"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "catering_system.ui.office_api",
            "--db",
            str(tmp_path / "x.db"),
            "--host",
            "127.0.0.1",
            "--port",
            "0",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "OFFICE_API_TOKEN" in result.stderr


# --- round-4 reviewer gaps: response cap, strict validation, intake merge ----


def test_read_over_response_cap_is_500_internal(api) -> None:
    """Pack §4.0: a read whose body would exceed the 512 KiB cap fails closed
    with `500 internal` rather than emitting an oversized payload. Simulates a
    legacy Core row with a long text the API's input caps never bounded."""
    base, ids, db = api
    inquiry_id = ids["inquiry_convertible"]
    # under the cap first: the normal detail read succeeds
    status, _body, _h = _get(f"{base}/office/v1/inquiries/{inquiry_id}")
    assert status == 200
    oversized = "x" * (600 * 1024)
    conn = sqlite3.connect(str(db))
    conn.execute(
        "UPDATE inquiries SET intake_message = ? WHERE inquiry_id = ?",
        (oversized, inquiry_id),
    )
    conn.commit()
    conn.close()
    status, body, _h = _get(f"{base}/office/v1/inquiries/{inquiry_id}")
    assert (status, body["error"]) == (500, "internal")


def test_command_id_and_version_refs_must_be_uuid4(api) -> None:
    """Pack §4.3: command_id is a uuid4; every Core-minted id is uuid4, so a
    well-formed but non-v4 uuid is rejected before routing/replay."""
    base, ids, _db = api
    url = f"{base}/office/v1/inquiries"
    non_v4 = str(uuid.uuid1())  # valid uuid, version 1
    status, body, _h = _post(url, args=_CREATE_ARGS, command_id=non_v4)
    assert (status, body["error"]) == (400, "invalid_request")
    # a proper uuid4 still works
    status, _b, _h = _post(url, args=_CREATE_ARGS, command_id=str(uuid.uuid4()))
    assert status == 201
    # the print-data version reference is held to the same rule
    order_id = ids["order_ready"]
    status, body, _h = _get(
        f"{base}/office/v1/orders/{order_id}/print-data?version={non_v4}"
    )
    assert (status, body["error"]) == (400, "invalid_request")
    # and an order_version_id command arg
    status, body, _h = _post(
        f"{base}/office/v1/orders/{order_id}/print-confirm",
        args={"order_version_id": non_v4},
    )
    assert (status, body["error"]) == (400, "invalid_request")


def test_expect_datetime_must_be_utc_aware(api) -> None:
    """Pack §4.1: timestamps are ISO-8601 UTC with offset. A naive value or a
    non-UTC offset is a 400, checked before the stale-state comparison."""
    base, ids, _db = api
    inquiry_id = ids["inquiry_convertible"]
    args = {
        "event_date": "2026-10-02",
        "crm_stage": "Neue Anfrage",
        "time_window_text": "abends",
        "location_text": "Hamburg-Altona",
        "guest_count_estimate": 30,
        "planning_mode": "caterer_suggestion",
    }
    for bad in ("2026-07-14T10:00:00", "2026-07-14T10:00:00+02:00"):
        status, body, _h = _post(
            f"{base}/office/v1/inquiries/{inquiry_id}/update",
            args=args,
            expect={"updated_at": bad},
        )
        assert (status, body["error"]) == (400, "invalid_request"), bad


def test_update_intake_merge_preserve_clear_reject_null(api) -> None:
    """Reviewer rule: on update an omitted intake field keeps its stored value,
    an empty string clears it, and an explicit `null` is a 400 (no coercion)."""
    base, ids, _db = api
    inquiry_id = ids["inquiry_convertible"]  # seeded intake_subject
    base_args = {
        "event_date": "2026-10-02",
        "crm_stage": "Neue Anfrage",
        "time_window_text": "abends",
        "location_text": "Hamburg-Altona",
        "guest_count_estimate": 30,
        "planning_mode": "caterer_suggestion",
    }

    def detail() -> dict:
        _s, d, _h = _get(f"{base}/office/v1/inquiries/{inquiry_id}")
        return d

    before = detail()
    assert before["intake_subject"] == "Sommerfest Catering"

    # omit intake_subject -> preserved
    status, _b, _h = _post(
        f"{base}/office/v1/inquiries/{inquiry_id}/update",
        args=base_args,
        expect={"updated_at": before["updated_at"]},
    )
    assert status == 200
    kept = detail()
    assert kept["intake_subject"] == "Sommerfest Catering"

    # explicit "" -> cleared
    status, _b, _h = _post(
        f"{base}/office/v1/inquiries/{inquiry_id}/update",
        args=dict(base_args, intake_subject=""),
        expect={"updated_at": kept["updated_at"]},
    )
    assert status == 200
    cleared = detail()
    assert not cleared["intake_subject"]

    # explicit null -> 400, nothing written
    status, body, _h = _post(
        f"{base}/office/v1/inquiries/{inquiry_id}/update",
        args=dict(base_args, intake_subject=None),
        expect={"updated_at": cleared["updated_at"]},
    )
    assert (status, body["error"]) == (400, "invalid_request")


def _valid_offer_snapshot(*, inquiry_id: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "offer_snapshot_v1",
        "source": "fingerfood-configurator-backend",
        "source_draft_id": "draft-1",
        "inquiry_id": inquiry_id,
        "snapshot_id": _SNAPSHOT_ID,
        "snapshot_created_at": "2026-07-15T08:30:00+00:00",
        "valid_until": "2026-07-29",
        "currency": "EUR",
        "recipient": {
            "company_name": "Example company",
            "contact_name": "Example contact",
            "email": "customer@example.invalid",
            "postal_address": "Customer-visible recipient address",
        },
        "event": {
            "event_date": "2026-08-20",
            "time_window_text": "18:00–22:00",
            "location_text": "Hamburg",
            "guest_count": 80,
            "planning_mode": "caterer_suggestion",
        },
        "customer_text": {
            "title": "Sommerfest",
            "introduction": "Customer-visible introduction",
            "notes": "Customer-visible conditions and notes",
        },
        "payment_terms": {
            "method": "RECHNUNG",
            "customer_visible_text": "Zahlung per Rechnung",
        },
        "calculator": {
            "name": "fingerfood-backend",
            "calculator_revision": "future-revision",
            "catalog_revision": "future-revision",
            "tax_revision": "future-revision",
        },
        "variants": [
            {
                "variant_id": _VARIANT_ID,
                "label": "Variante A",
                "description": "Customer-visible alternative",
                "positions": [
                    {
                        "position_id": _POSITION_ID,
                        "kind": "catalog",
                        "catalog_item_id": "catalog-1",
                        "name": "Fingerfood Paket",
                        "description": "Frozen description",
                        "composition": "Frozen composition",
                        "quantity_mode": "total",
                        "quantity": "80",
                        "unit_label": "Stück",
                        "unit_net_cents": 290,
                        "net_total_cents": 23200,
                        "vat_rate_percent": 7,
                        "vat_amount_cents": 1624,
                        "gross_total_cents": 24824,
                        "notes": "Frozen customization",
                        "related_position_id": None,
                    }
                ],
                "totals": {
                    "net_cents": 23200,
                    "vat_7_base_cents": 23200,
                    "vat_7_amount_cents": 1624,
                    "vat_19_base_cents": 0,
                    "vat_19_amount_cents": 0,
                    "gross_cents": 24824,
                },
            }
        ],
    }
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    return payload


def _valid_offer_snapshot_v2(
    *, inquiry_id: str, unit_net_cents: int = 1200
) -> dict[str, object]:
    net = unit_net_cents * 10
    vat = (net * 7) // 100
    gross = net + vat
    payload: dict[str, object] = {
        "schema_version": "offer_snapshot_v2",
        "source": "fingerfood-configurator-backend",
        "source_draft_id": "draft-v2",
        "inquiry_id": inquiry_id,
        "snapshot_id": _SNAPSHOT_ID,
        "snapshot_created_at": "2026-07-16T08:30:00+00:00",
        "valid_until": "2026-07-29",
        "currency": "EUR",
        "recipient": {
            "company_name": "Example company",
            "contact_name": "Example contact",
            "email": "customer@example.invalid",
            "postal_address": "Customer-visible recipient address",
        },
        "event": {
            "event_date": "2026-08-20",
            "time_window_text": "18:00–22:00",
            "location_text": "Hamburg",
            "guest_count": 80,
            "planning_mode": "caterer_suggestion",
        },
        "customer_text": {
            "title": "Sommerfest",
            "introduction": "Customer-visible introduction",
            "notes": "Customer-visible conditions and notes",
        },
        "payment_terms": {
            "method": "RECHNUNG",
            "customer_visible_text": "Zahlung per Rechnung",
        },
        "calculator": {
            "name": "fingerfood-backend",
            "calculator_revision": "v2-catalog-adapter",
            "catalog_revision": "core-catalog-v1",
            "tax_revision": "v1",
        },
        "variants": [
            {
                "variant_id": _VARIANT_ID,
                "label": "Variante A",
                "description": "Catalog snapshot",
                "positions": [
                    {
                        "position_id": _POSITION_ID,
                        "kind": "catalog",
                        "catalog_item_id": "11111111-1111-4111-8111-111111111111",
                        "name": "Pasta",
                        "description": "Catalog description",
                        "composition": "Catalog composition",
                        "quantity_mode": "total",
                        "quantity": "10",
                        "unit_label": "Portion",
                        "unit_net_cents": unit_net_cents,
                        "net_total_cents": net,
                        "vat_rate_percent": 7,
                        "vat_amount_cents": vat,
                        "gross_total_cents": gross,
                        "notes": None,
                        "related_position_id": None,
                        "allergens": ["A", "G"],
                        "vegan": None,
                        "vegetarian": None,
                    }
                ],
                "totals": {
                    "net_cents": net,
                    "vat_7_base_cents": net,
                    "vat_7_amount_cents": vat,
                    "vat_19_base_cents": 0,
                    "vat_19_amount_cents": 0,
                    "gross_cents": gross,
                },
            }
        ],
    }
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    return payload


def test_prepare_offer_v2_persists_allergens(api) -> None:
    base, ids, db = api
    inquiry_id = ids["inquiry_convertible"]
    status, body, _h = _post(
        _prepare_offer_url(base, inquiry_id),
        args={"snapshot": _valid_offer_snapshot_v2(inquiry_id=inquiry_id)},
    )
    assert status == 201
    offer_id = body["offer_id"]

    detail_status, detail, _h = _get(f"{base}/office/v1/offers/{offer_id}")
    assert detail_status == 200
    position = detail["versions"][0]["variants"][0]["positions"][0]
    assert position["name"] == "Pasta"
    assert position["unit_net_cents"] == 1200
    assert position["description"] == "Catalog description"
    assert position["composition"] == "Catalog composition"
    assert position["allergens"] == ["A", "G"]
    assert position["allergens_unknown"] is False

    offers = SQLiteOfferRepository(db)
    stored = offers.get(offer_id)
    assert stored is not None
    stored_position = stored.versions[0].variants[0].positions[0]
    assert stored_position.unit_net_cents == 1200
    assert stored_position.allergens == ("A", "G")
    offers.close()


def _prepare_offer_url(base: str, inquiry_id: str) -> str:
    return f"{base}/office/v1/inquiries/{inquiry_id}/prepare-offer"


def test_prepare_offer_happy_path_and_replay(api) -> None:
    base, ids, db = api
    inquiry_id = ids["inquiry_convertible"]
    url = _prepare_offer_url(base, inquiry_id)
    snapshot = _valid_offer_snapshot(inquiry_id=inquiry_id)
    command_id = str(uuid.uuid4())

    status, body, _h = _post(url, args={"snapshot": snapshot}, command_id=command_id)
    assert status == 201
    assert set(body) == {
        "command_id",
        "offer_id",
        "offer_version_id",
        "snapshot_id",
    }
    assert body["snapshot_id"] == _SNAPSHOT_ID

    status2, body2, _h = _post(url, args={"snapshot": snapshot}, command_id=command_id)
    assert (status2, body2) == (status, body)

    offers = SQLiteOfferRepository(db)
    stored = offers.get_by_source_inquiry_id(inquiry_id)
    assert stored is not None
    assert stored.offer_id == body["offer_id"]
    assert stored.conversion_link is None
    assert stored.sent_evidence == ()
    offers.close()

    conn = sqlite3.connect(db)
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM orders WHERE source_inquiry_id = ?",
            (inquiry_id,),
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_conversion_links WHERE offer_id = ?",
            (body["offer_id"],),
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_sent_evidence WHERE offer_id = ?",
            (body["offer_id"],),
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM order_commercial_snapshots WHERE source_offer_id = ?",
            (body["offer_id"],),
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_document_snapshots WHERE offer_id = ?",
            (body["offer_id"],),
        ).fetchone()[0]
        == 0
    )
    conn.close()


def test_prepare_offer_concurrent_writers_serialize_to_create_and_duplicate(
    api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from catering_system.repositories.core_transaction import CoreCommandExecutor

    base, ids, db = api
    inquiry_id = ids["inquiry_cancelled_order"]
    second_server, second_server_thread, second_base = _start_api_server(db)
    snapshot = _valid_offer_snapshot(inquiry_id=inquiry_id)
    command_start = threading.Barrier(2)
    client_start = threading.Barrier(3)
    results: queue.Queue[tuple[int, dict[str, object]]] = queue.Queue()
    command_ids = (str(uuid.uuid4()), str(uuid.uuid4()))
    assert command_ids[0] != command_ids[1]
    original_run = CoreCommandExecutor.run

    def synchronized_run(self, work):  # noqa: ANN001, ANN202
        # Align the two transaction attempts. BEGIN IMMEDIATE then serializes
        # SQLite writers, so this test covers the real create/duplicate
        # behavior and intentionally makes no claim about the IntegrityError
        # fallback.
        command_start.wait(timeout=5)
        return original_run(self, work)

    monkeypatch.setattr(CoreCommandExecutor, "run", synchronized_run)

    def submit(url: str, command_id: str) -> None:
        client_start.wait()
        status, body, _headers = _post(
            url,
            args={"snapshot": snapshot},
            command_id=command_id,
        )
        results.put((status, body))

    urls = (
        _prepare_offer_url(base, inquiry_id),
        _prepare_offer_url(second_base, inquiry_id),
    )
    clients = [
        threading.Thread(target=submit, args=(url, command_id))
        for url, command_id in zip(urls, command_ids, strict=True)
    ]
    try:
        for client in clients:
            client.start()
        client_start.wait()
        for client in clients:
            client.join(timeout=10)
            assert client.is_alive() is False
    finally:
        second_server.shutdown()
        second_server.server_close()
        second_server_thread.join(timeout=5)
        assert second_server_thread.is_alive() is False

    outcomes = [results.get_nowait(), results.get_nowait()]
    assert sorted(status for status, _body in outcomes) == [201, 409]
    conflict = next(body for status, body in outcomes if status == 409)
    assert conflict["error"] == "offer_already_exists"
    created = next(body for status, body in outcomes if status == 201)
    assert conflict["offer_id"] == created["offer_id"]

    conn = sqlite3.connect(db)
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offers WHERE source_inquiry_id = ?",
            (inquiry_id,),
        ).fetchone()[0]
        == 1
    )
    conn.close()


def test_prepare_offer_integrity_error_fallback_returns_canonical_winner(
    api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base, ids, db = api
    inquiry_id = ids["inquiry_convertible"]
    url = _prepare_offer_url(base, inquiry_id)
    snapshot = _valid_offer_snapshot(inquiry_id=inquiry_id)
    winner_command_id = str(uuid.uuid4())
    loser_command_id = str(uuid.uuid4())

    winner_status, winner_body, _headers = _post(
        url,
        args={"snapshot": snapshot},
        command_id=winner_command_id,
    )
    assert winner_status == 201
    winner_offer_id = winner_body["offer_id"]

    original_lookup = SQLiteOfferRepository.get_by_source_inquiry_id
    lookup_count = 0

    def miss_initial_lookup_then_return_winner(
        repository: SQLiteOfferRepository,
        requested_inquiry_id: str,
    ):  # noqa: ANN202
        nonlocal lookup_count
        lookup_count += 1
        if lookup_count == 1:
            return None
        return original_lookup(repository, requested_inquiry_id)

    # The first lookup models a loser that did not observe the winner yet.
    # The real repository save then hits uq_offers_source_inquiry and raises
    # sqlite3.IntegrityError; the fallback lookup must resolve the winner.
    monkeypatch.setattr(
        SQLiteOfferRepository,
        "get_by_source_inquiry_id",
        miss_initial_lookup_then_return_winner,
    )

    loser_status, loser_body, _headers = _post(
        url,
        args={"snapshot": snapshot},
        command_id=loser_command_id,
    )

    assert lookup_count == 2
    assert loser_status == 409
    assert loser_body["error"] == "offer_already_exists"
    assert loser_body["offer_id"] == winner_offer_id

    conn = sqlite3.connect(db)
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offers WHERE source_inquiry_id = ?",
            (inquiry_id,),
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            "SELECT offer_id FROM offers WHERE source_inquiry_id = ?",
            (inquiry_id,),
        ).fetchone()[0]
        == winner_offer_id
    )

    # Successful commands are committed atomically with their ledger row.
    # The losing ApiError rolls its transaction back, so it is not ledgered.
    winner_ledger = conn.execute(
        "SELECT result_status, result_body FROM office_api_commands "
        "WHERE command_id = ?",
        (winner_command_id,),
    ).fetchone()
    assert winner_ledger is not None
    assert winner_ledger[0] == 201
    assert json.loads(winner_ledger[1]) == winner_body
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM office_api_commands WHERE command_id = ?",
            (loser_command_id,),
        ).fetchone()[0]
        == 0
    )

    assert (
        conn.execute(
            "SELECT COUNT(*) FROM orders WHERE source_inquiry_id = ?",
            (inquiry_id,),
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM order_commercial_snapshots WHERE source_offer_id = ?",
            (winner_offer_id,),
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_conversion_links WHERE offer_id = ?",
            (winner_offer_id,),
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_sent_evidence WHERE offer_id = ?",
            (winner_offer_id,),
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_document_snapshots WHERE offer_id = ?",
            (winner_offer_id,),
        ).fetchone()[0]
        == 0
    )
    for table in (
        "order_confirmation_document_snapshots",
        "order_confirmation_send_attempts",
        "order_confirmation_fake_outbox_messages",
        "order_confirmation_send_evidence",
        "kitchen_print_jobs",
    ):
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if table_exists is not None:
            assert (
                conn.execute(
                    f"SELECT COUNT(*) FROM {table} "
                    "WHERE order_id IN ("
                    "SELECT order_id FROM orders WHERE source_inquiry_id = ?"
                    ")",
                    (inquiry_id,),
                ).fetchone()[0]
                == 0
            )
    conn.close()


def test_prepare_offer_active_order_blocks(api) -> None:
    base, ids, _db = api
    inquiry_id = ids["inquiry_unprinted"]
    status, body, _h = _post(
        _prepare_offer_url(base, inquiry_id),
        args={"snapshot": _valid_offer_snapshot(inquiry_id=inquiry_id)},
    )
    assert (status, body["error"]) == (409, "active_order_exists")


@pytest.mark.parametrize(
    ("fixture_id", "error"),
    [
        ("inquiry_rejected", "inquiry_rejected"),
        (
            "inquiry_verify",
            "inquiry_call_verification_unsatisfied",
        ),
    ],
)
def test_prepare_offer_enforces_inquiry_eligibility(
    api,
    fixture_id: str,
    error: str,
) -> None:
    base, ids, db = api
    inquiry_id = ids[fixture_id]
    status, body, _h = _post(
        _prepare_offer_url(base, inquiry_id),
        args={"snapshot": _valid_offer_snapshot(inquiry_id=inquiry_id)},
    )
    assert (status, body["error"]) == (422, error)

    conn = sqlite3.connect(db)
    offer_count = conn.execute(
        "SELECT COUNT(*) FROM offers WHERE source_inquiry_id = ?",
        (inquiry_id,),
    ).fetchone()[0]
    order_count = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE source_inquiry_id = ?",
        (inquiry_id,),
    ).fetchone()[0]
    conn.close()
    assert offer_count == 0
    assert order_count == 0


def test_prepare_offer_existing_offer_blocks(api) -> None:
    base, ids, _db = api
    inquiry_id = ids["inquiry_convertible"]
    url = _prepare_offer_url(base, inquiry_id)
    snapshot = _valid_offer_snapshot(inquiry_id=inquiry_id)
    assert _post(url, args={"snapshot": snapshot})[0] == 201
    status, body, _h = _post(url, args={"snapshot": snapshot})
    assert (status, body["error"]) == (409, "offer_already_exists")
    offers = SQLiteOfferRepository(_db)
    stored = offers.get_by_source_inquiry_id(inquiry_id)
    assert stored is not None
    assert body["offer_id"] == stored.offer_id
    offers.close()


def test_prepare_offer_invalid_snapshot_and_inquiry_mismatch(api) -> None:
    base, ids, _db = api
    inquiry_id = ids["inquiry_convertible"]
    bad_hash = _valid_offer_snapshot(inquiry_id=inquiry_id)
    bad_hash["snapshot_hash"] = "sha256:" + ("f" * 64)
    status, body, _h = _post(
        _prepare_offer_url(base, inquiry_id),
        args={"snapshot": bad_hash},
    )
    assert (status, body["error"]) == (422, "invalid_snapshot")

    other_id = str(uuid.uuid4())
    status, body, _h = _post(
        _prepare_offer_url(base, other_id),
        args={"snapshot": _valid_offer_snapshot(inquiry_id=inquiry_id)},
    )
    assert (status, body["error"]) == (422, "inquiry_id_mismatch")


def test_prepare_offer_same_command_id_different_snapshot_conflicts(api) -> None:
    base, ids, _db = api
    inquiry_id = ids["inquiry_cancelled_order"]
    url = _prepare_offer_url(base, inquiry_id)
    command_id = str(uuid.uuid4())
    first = _valid_offer_snapshot(inquiry_id=inquiry_id)
    assert _post(url, args={"snapshot": first}, command_id=command_id)[0] == 201
    second = _valid_offer_snapshot(inquiry_id=inquiry_id)
    second["snapshot_id"] = "99999999-9999-4999-8999-999999999991"
    second["snapshot_hash"] = compute_snapshot_hash(second)
    status, body, _h = _post(url, args={"snapshot": second}, command_id=command_id)
    assert (status, body["error"]) == (409, "command_id_conflict")


def test_prepare_offer_accepts_body_above_global_limit(api) -> None:
    base, ids, _db = api
    inquiry_id = ids["inquiry_convertible"]
    over_global = b"x" * (64 * 1024 + 1)
    create_url = f"{base}/office/v1/inquiries"
    prepare_url = _prepare_offer_url(base, inquiry_id)
    status, body, _h = _post(create_url, raw_body=over_global)
    assert (status, body["error"]) == (413, "body_too_large")
    status, body, _h = _post(prepare_url, raw_body=over_global)
    assert status == 400
    assert body.get("error") == "invalid_request"


def test_prepare_offer_rejects_body_above_route_limit(api) -> None:
    from catering_system.ui.office_api import _MAX_PREPARE_OFFER_BODY_BYTES

    base, ids, _db = api
    inquiry_id = ids["inquiry_convertible"]
    huge = b"x" * (_MAX_PREPARE_OFFER_BODY_BYTES + 1)
    status, body, _h = _post(
        _prepare_offer_url(base, inquiry_id),
        raw_body=huge,
    )
    assert (status, body["error"]) == (413, "body_too_large")


def test_prepare_offer_failure_leaves_no_offer_or_ledger(api) -> None:
    base, ids, db = api
    inquiry_id = ids["inquiry_convertible"]
    snapshot = _valid_offer_snapshot(inquiry_id=inquiry_id)
    snapshot["snapshot_hash"] = "sha256:" + ("f" * 64)
    command_id = str(uuid.uuid4())
    status, body, _h = _post(
        _prepare_offer_url(base, inquiry_id),
        args={"snapshot": snapshot},
        command_id=command_id,
    )
    assert (status, body["error"]) == (422, "invalid_snapshot")

    conn = sqlite3.connect(db)
    offer_count = conn.execute("SELECT COUNT(*) FROM offers").fetchone()[0]
    ledger_count = conn.execute(
        "SELECT COUNT(*) FROM office_api_commands WHERE command_id = ?",
        (command_id,),
    ).fetchone()[0]
    conn.close()
    assert offer_count == 0
    assert ledger_count == 0


_SNAPSHOT_ID_V2 = "88888888-8888-4888-8888-888888888882"


def _revision_offer_snapshot(*, inquiry_id: str) -> dict[str, object]:
    payload = _valid_offer_snapshot(inquiry_id=inquiry_id)
    payload["snapshot_id"] = _SNAPSHOT_ID_V2
    payload["source_draft_id"] = "draft-2"
    payload["snapshot_created_at"] = "2026-07-16T08:30:00+00:00"
    payload["valid_until"] = "2026-08-05"
    variant_id = "55555555-5555-4555-8555-555555555552"
    position_id = "99999999-9999-4999-8999-999999999992"
    variants = payload["variants"]
    assert isinstance(variants, list)
    variant = variants[0]
    assert isinstance(variant, dict)
    variant["variant_id"] = variant_id
    positions = variant["positions"]
    assert isinstance(positions, list)
    position = positions[0]
    assert isinstance(position, dict)
    position["position_id"] = position_id
    from catering_system.domain.offer_snapshot import compute_snapshot_hash

    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    return payload


def _prepare_next_url(base: str, offer_id: str) -> str:
    return f"{base}/office/v1/offers/{offer_id}/prepare-next-version"


def test_prepare_next_version_happy_path_and_replay(api) -> None:
    base, ids, db = api
    offer_id, version_id = _prepare_offer(api)
    inquiry_id = ids["inquiry_offer_ready"]
    assert (
        _post(_mark_sent_url(base, offer_id, version_id), args=_MARK_SENT_ARGS)[0]
        == 200
    )
    url = _prepare_next_url(base, offer_id)
    snapshot = _revision_offer_snapshot(inquiry_id=inquiry_id)
    command_id = str(uuid.uuid4())

    status, body, _h = _post(
        url,
        args={"snapshot": snapshot},
        expect={"latest_version_number": 1},
        command_id=command_id,
    )
    assert status == 201
    assert set(body) == {
        "command_id",
        "offer_id",
        "offer_version_id",
        "version_number",
        "snapshot_id",
    }
    assert body["offer_id"] == offer_id
    assert body["version_number"] == 2
    assert body["snapshot_id"] == _SNAPSHOT_ID_V2

    status2, body2, _h = _post(
        url,
        args={"snapshot": snapshot},
        expect={"latest_version_number": 1},
        command_id=command_id,
    )
    assert (status2, body2) == (status, body)

    offers = SQLiteOfferRepository(db)
    stored = offers.get(offer_id)
    assert stored is not None
    assert len(stored.versions) == 2
    offers.close()


def test_prepare_next_version_conflict_and_blocked(api) -> None:
    base, ids, _db = api
    offer_id, version_id = _prepare_offer(api)
    inquiry_id = ids["inquiry_offer_ready"]
    url = _prepare_next_url(base, offer_id)
    snapshot = _revision_offer_snapshot(inquiry_id=inquiry_id)

    status, body, _h = _post(
        url,
        args={"snapshot": snapshot},
        expect={"latest_version_number": 1},
    )
    assert (status, body["error"]) == (422, "prepare_next_blocked")

    assert (
        _post(_mark_sent_url(base, offer_id, version_id), args=_MARK_SENT_ARGS)[0]
        == 200
    )
    status, body, _h = _post(
        url,
        args={"snapshot": snapshot},
        expect={"latest_version_number": 0},
    )
    assert (status, body["error"]) == (409, "version_conflict")


def test_acceptance_blocked_newer_version_exists(api) -> None:
    base, ids, _db = api
    offer_id, version_id = _prepare_offer(api)
    inquiry_id = ids["inquiry_offer_ready"]
    assert (
        _post(_mark_sent_url(base, offer_id, version_id), args=_MARK_SENT_ARGS)[0]
        == 200
    )
    assert (
        _post(
            _prepare_next_url(base, offer_id),
            args={"snapshot": _revision_offer_snapshot(inquiry_id=inquiry_id)},
            expect={"latest_version_number": 1},
        )[0]
        == 201
    )
    status, body, _h = _post(
        _record_acceptance_url(base, offer_id, version_id),
        args=_RECORD_ACCEPTANCE_ARGS,
    )
    assert (status, body["error"]) == (
        422,
        "acceptance_blocked_newer_version_exists",
    )


def test_prepare_next_version_inquiry_mismatch(api) -> None:
    base, ids, _db = api
    offer_id, version_id = _prepare_offer(api)
    assert (
        _post(_mark_sent_url(base, offer_id, version_id), args=_MARK_SENT_ARGS)[0]
        == 200
    )
    status, body, _h = _post(
        _prepare_next_url(base, offer_id),
        args={
            "snapshot": _revision_offer_snapshot(
                inquiry_id="33333333-3333-4333-8333-333333333333"
            )
        },
        expect={"latest_version_number": 1},
    )
    assert (status, body["error"]) == (422, "inquiry_id_mismatch")


def test_prepare_next_version_rejects_non_object_snapshot(api) -> None:
    base, _ids, _db = api
    offer_id, version_id = _prepare_offer(api)
    assert (
        _post(_mark_sent_url(base, offer_id, version_id), args=_MARK_SENT_ARGS)[0]
        == 200
    )
    status, body, _h = _post(
        _prepare_next_url(base, offer_id),
        args={"snapshot": "not-a-dict"},
        expect={"latest_version_number": 1},
    )
    assert status == 400
    assert body["error"] == "invalid_request"


def test_prepare_next_version_not_found(api) -> None:
    base, ids, _db = api
    inquiry_id = ids["inquiry_offer_ready"]
    status, body, _h = _post(
        _prepare_next_url(base, "11111111-1111-4111-8111-111111111111"),
        args={"snapshot": _revision_offer_snapshot(inquiry_id=inquiry_id)},
        expect={"latest_version_number": 1},
    )
    assert (status, body["error"]) == (404, "not_found")


def test_prepare_next_version_contact_incomplete(api) -> None:
    from dataclasses import replace

    base, ids, db = api
    offer_id, version_id = _prepare_offer(api)
    inquiry_id = ids["inquiry_offer_ready"]
    assert (
        _post(_mark_sent_url(base, offer_id, version_id), args=_MARK_SENT_ARGS)[0]
        == 200
    )
    inquiries = SQLiteInquiryRepository(db)
    inquiry = inquiries.get_by_id(inquiry_id)
    assert inquiry is not None
    inquiries.update(replace(inquiry, customer_snapshot=None))
    status, body, _h = _post(
        _prepare_next_url(base, offer_id),
        args={"snapshot": _revision_offer_snapshot(inquiry_id=inquiry_id)},
        expect={"latest_version_number": 1},
    )
    assert (status, body["error"]) == (422, "contact_information_incomplete")


def test_prepare_next_version_active_order_blocks(api) -> None:
    base, ids, db = api
    offer_id, version_id = _prepare_offer(api)
    inquiry_id = ids["inquiry_offer_ready"]
    assert (
        _post(_mark_sent_url(base, offer_id, version_id), args=_MARK_SENT_ARGS)[0]
        == 200
    )
    inquiries = SQLiteInquiryRepository(db)
    orders = SQLiteOrderRepository(db)
    inquiry = inquiries.get_by_id(inquiry_id)
    assert inquiry is not None
    seed_order(orders, inquiry)
    status, body, _h = _post(
        _prepare_next_url(base, offer_id),
        args={"snapshot": _revision_offer_snapshot(inquiry_id=inquiry_id)},
        expect={"latest_version_number": 1},
    )
    assert (status, body["error"]) == (409, "active_order_exists")


def test_prepare_next_version_invalid_snapshot(api) -> None:
    base, ids, _db = api
    offer_id, version_id = _prepare_offer(api)
    inquiry_id = ids["inquiry_offer_ready"]
    assert (
        _post(_mark_sent_url(base, offer_id, version_id), args=_MARK_SENT_ARGS)[0]
        == 200
    )
    bad = _revision_offer_snapshot(inquiry_id=inquiry_id)
    bad["snapshot_hash"] = "sha256:" + ("0" * 64)
    status, body, _h = _post(
        _prepare_next_url(base, offer_id),
        args={"snapshot": bad},
        expect={"latest_version_number": 1},
    )
    assert (status, body["error"]) == (422, "invalid_snapshot")


def test_prepare_next_version_integrity_conflict_on_reused_position(api) -> None:
    base, ids, _db = api
    offer_id, version_id = _prepare_offer(api)
    inquiry_id = ids["inquiry_offer_ready"]
    assert (
        _post(_mark_sent_url(base, offer_id, version_id), args=_MARK_SENT_ARGS)[0]
        == 200
    )
    reused = _revision_offer_snapshot(inquiry_id=inquiry_id)
    variants = reused["variants"]
    assert isinstance(variants, list)
    variant = variants[0]
    assert isinstance(variant, dict)
    positions = variant["positions"]
    assert isinstance(positions, list)
    position = positions[0]
    assert isinstance(position, dict)
    position["position_id"] = _POSITION_ID
    from catering_system.domain.offer_snapshot import compute_snapshot_hash

    reused["snapshot_hash"] = compute_snapshot_hash(reused)
    status, body, _h = _post(
        _prepare_next_url(base, offer_id),
        args={"snapshot": reused},
        expect={"latest_version_number": 1},
    )
    assert (status, body["error"]) == (409, "version_conflict")


_MARK_SENT_ARGS = {
    "sent_at": "2026-07-15T10:00:00+00:00",
    "channel": "email",
    "recipient_reference": "customer@example.invalid",
    "evidence_reference": "mail-123",
}


def _prepare_offer(api: tuple[str, dict[str, str], Path]) -> tuple[str, str]:
    base, ids, _db = api
    inquiry_id = ids["inquiry_offer_ready"]
    status, body, _h = _post(
        f"{base}/office/v1/inquiries/{inquiry_id}/prepare-offer",
        args={"snapshot": _valid_offer_snapshot(inquiry_id=inquiry_id)},
    )
    assert status == 201
    return body["offer_id"], body["offer_version_id"]


def _mark_sent_url(base: str, offer_id: str, version_id: str) -> str:
    return f"{base}/office/v1/offers/{offer_id}/versions/{version_id}/mark-sent"


def test_mark_sent_prepared_to_sent_and_replay(api) -> None:
    base, _ids, db = api
    offer_id, version_id = _prepare_offer(api)
    url = _mark_sent_url(base, offer_id, version_id)
    command_id = str(uuid.uuid4())

    status, body, _h = _post(url, args=_MARK_SENT_ARGS, command_id=command_id)
    assert status == 200
    assert set(body) == {"command_id", "offer_id", "offer_version_id", "sent_at"}

    status2, body2, _h = _post(url, args=_MARK_SENT_ARGS, command_id=command_id)
    assert (status2, body2) == (status, body)

    offers = SQLiteOfferRepository(db)
    stored = offers.get(offer_id)
    assert stored is not None
    assert len(stored.sent_evidence) == 1
    offers.close()


def test_mark_sent_rejects_second_send(api) -> None:
    base, _ids, _db = api
    offer_id, version_id = _prepare_offer(api)
    url = _mark_sent_url(base, offer_id, version_id)
    assert _post(url, args=_MARK_SENT_ARGS)[0] == 200
    status, body, _h = _post(url, args=_MARK_SENT_ARGS)
    assert (status, body["error"]) == (409, "sent_evidence_exists")


def test_mark_sent_rejects_invalid_channel(api) -> None:
    base, _ids, _db = api
    offer_id, version_id = _prepare_offer(api)
    status, body, _h = _post(
        _mark_sent_url(base, offer_id, version_id),
        args=dict(_MARK_SENT_ARGS, channel="EMAIL"),
    )
    assert (status, body["error"]) == (400, "invalid_request")


def test_mark_sent_failure_leaves_no_sent_evidence_or_ledger(api) -> None:
    base, _ids, db = api
    offer_id, version_id = _prepare_offer(api)
    command_id = str(uuid.uuid4())
    future_sent_at = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    status, body, _h = _post(
        _mark_sent_url(base, offer_id, version_id),
        args=dict(_MARK_SENT_ARGS, sent_at=future_sent_at),
        command_id=command_id,
    )
    assert (status, body["error"]) == (422, "invalid_sent_evidence")

    conn = sqlite3.connect(db)
    sent_count = conn.execute("SELECT COUNT(*) FROM offer_sent_evidence").fetchone()[0]
    ledger_count = conn.execute(
        "SELECT COUNT(*) FROM office_api_commands WHERE command_id = ?",
        (command_id,),
    ).fetchone()[0]
    conn.close()
    assert sent_count == 0
    assert ledger_count == 0


_RECORD_ACCEPTANCE_ARGS = {
    "accepted_variant_id": _VARIANT_ID,
    "accepted_at": "2026-07-15T11:00:00+00:00",
    "channel": "email",
    "evidence_reference": "reply-1",
    "note": None,
}


def _record_acceptance_url(base: str, offer_id: str, version_id: str) -> str:
    return f"{base}/office/v1/offers/{offer_id}/versions/{version_id}/record-acceptance"


def _prepare_and_send(api: tuple[str, dict[str, str], Path]) -> tuple[str, str]:
    base, _ids, _db = api
    offer_id, version_id = _prepare_offer(api)
    assert (
        _post(_mark_sent_url(base, offer_id, version_id), args=_MARK_SENT_ARGS)[0]
        == 200
    )
    return offer_id, version_id


def test_record_acceptance_sent_to_accepted_and_replay(api) -> None:
    base, _ids, db = api
    offer_id, version_id = _prepare_and_send(api)
    url = _record_acceptance_url(base, offer_id, version_id)
    command_id = str(uuid.uuid4())

    status, body, _h = _post(url, args=_RECORD_ACCEPTANCE_ARGS, command_id=command_id)
    assert status == 200
    assert set(body) == {
        "command_id",
        "offer_id",
        "offer_version_id",
        "accepted_variant_id",
        "acceptance_id",
    }
    assert body["offer_id"] == offer_id
    assert body["offer_version_id"] == version_id
    assert body["accepted_variant_id"] == _VARIANT_ID

    status2, body2, _h = _post(url, args=_RECORD_ACCEPTANCE_ARGS, command_id=command_id)
    assert (status2, body2) == (status, body)

    offers = SQLiteOfferRepository(db)
    stored = offers.get(offer_id)
    assert stored is not None
    assert stored.acceptance_evidence is not None
    assert stored.acceptance_evidence.acceptance_id == body["acceptance_id"]
    offers.close()


def test_record_acceptance_rejects_prepared(api) -> None:
    base, _ids, _db = api
    offer_id, version_id = _prepare_offer(api)
    status, body, _h = _post(
        _record_acceptance_url(base, offer_id, version_id),
        args=_RECORD_ACCEPTANCE_ARGS,
    )
    assert (status, body["error"]) == (422, "acceptance_blocked")


def test_record_acceptance_rejects_second_acceptance(api) -> None:
    base, _ids, _db = api
    offer_id, version_id = _prepare_and_send(api)
    url = _record_acceptance_url(base, offer_id, version_id)
    assert _post(url, args=_RECORD_ACCEPTANCE_ARGS)[0] == 200
    status, body, _h = _post(url, args=_RECORD_ACCEPTANCE_ARGS)
    assert (status, body["error"]) == (409, "acceptance_already_exists")


def test_record_acceptance_rejects_wrong_variant(api) -> None:
    base, _ids, _db = api
    offer_id, version_id = _prepare_and_send(api)
    status, body, _h = _post(
        _record_acceptance_url(base, offer_id, version_id),
        args=dict(
            _RECORD_ACCEPTANCE_ARGS,
            accepted_variant_id="55555555-5555-4555-8555-555555555551",
        ),
    )
    assert (status, body["error"]) == (422, "invalid_variant")


def test_record_acceptance_blocks_later_send(api) -> None:
    base, _ids, _db = api
    offer_id, version_id = _prepare_and_send(api)
    assert (
        _post(
            _record_acceptance_url(base, offer_id, version_id),
            args=_RECORD_ACCEPTANCE_ARGS,
        )[0]
        == 200
    )
    status, body, _h = _post(
        _mark_sent_url(base, offer_id, version_id),
        args=_MARK_SENT_ARGS,
    )
    assert (status, body["error"]) == (422, "sent_recording_blocked")


def test_record_acceptance_same_command_id_different_variant_conflicts(api) -> None:
    base, _ids, _db = api
    offer_id, version_id = _prepare_and_send(api)
    url = _record_acceptance_url(base, offer_id, version_id)
    command_id = str(uuid.uuid4())
    assert _post(url, args=_RECORD_ACCEPTANCE_ARGS, command_id=command_id)[0] == 200
    other = dict(
        _RECORD_ACCEPTANCE_ARGS,
        accepted_variant_id="55555555-5555-4555-8555-555555555551",
    )
    status, body, _h = _post(url, args=other, command_id=command_id)
    assert (status, body["error"]) == (409, "command_id_conflict")


def test_record_acceptance_failure_leaves_no_acceptance_or_ledger(api) -> None:
    base, _ids, db = api
    offer_id, version_id = _prepare_and_send(api)
    command_id = str(uuid.uuid4())
    status, body, _h = _post(
        _record_acceptance_url(base, offer_id, version_id),
        args=dict(
            _RECORD_ACCEPTANCE_ARGS,
            accepted_at="2026-07-15T09:00:00+00:00",
        ),
        command_id=command_id,
    )
    assert (status, body["error"]) == (422, "invalid_acceptance_evidence")

    conn = sqlite3.connect(db)
    acceptance_count = conn.execute(
        "SELECT COUNT(*) FROM offer_acceptance_evidence"
    ).fetchone()[0]
    ledger_count = conn.execute(
        "SELECT COUNT(*) FROM office_api_commands WHERE command_id = ?",
        (command_id,),
    ).fetchone()[0]
    conn.close()
    assert acceptance_count == 0
    assert ledger_count == 0


_RECORD_REJECTION_ARGS = {
    "rejected_at": "2026-07-15T12:00:00+00:00",
    "evidence_reference": "phone-decline",
}


def _record_rejection_url(base: str, offer_id: str, version_id: str) -> str:
    return f"{base}/office/v1/offers/{offer_id}/versions/{version_id}/record-rejection"


def _record_withdrawal_url(base: str, offer_id: str, version_id: str) -> str:
    return f"{base}/office/v1/offers/{offer_id}/versions/{version_id}/record-withdrawal"


def test_record_rejection_sent_to_rejected_and_replay(api) -> None:
    base, _ids, db = api
    offer_id, version_id = _prepare_and_send(api)
    url = _record_rejection_url(base, offer_id, version_id)
    command_id = str(uuid.uuid4())

    status, body, _h = _post(url, args=_RECORD_REJECTION_ARGS, command_id=command_id)
    assert status == 200
    assert set(body) == {
        "command_id",
        "offer_id",
        "offer_version_id",
        "rejected_at",
    }
    assert body["offer_id"] == offer_id
    assert body["offer_version_id"] == version_id

    status2, body2, _h = _post(url, args=_RECORD_REJECTION_ARGS, command_id=command_id)
    assert (status2, body2) == (status, body)

    offers = SQLiteOfferRepository(db)
    stored = offers.get(offer_id)
    assert stored is not None
    assert len(stored.rejection_evidence) == 1
    offers.close()


def test_record_rejection_rejects_prepared(api) -> None:
    base, _ids, _db = api
    offer_id, version_id = _prepare_offer(api)
    status, body, _h = _post(
        _record_rejection_url(base, offer_id, version_id),
        args=_RECORD_REJECTION_ARGS,
    )
    assert (status, body["error"]) == (422, "rejection_blocked")


def test_record_rejection_rejects_second_rejection(api) -> None:
    base, _ids, _db = api
    offer_id, version_id = _prepare_and_send(api)
    url = _record_rejection_url(base, offer_id, version_id)
    assert _post(url, args=_RECORD_REJECTION_ARGS)[0] == 200
    status, body, _h = _post(url, args=_RECORD_REJECTION_ARGS)
    assert (status, body["error"]) == (409, "rejection_evidence_exists")


def test_record_withdrawal_sent_to_withdrawn_and_replay(api) -> None:
    base, _ids, db = api
    offer_id, version_id = _prepare_and_send(api)
    url = _record_withdrawal_url(base, offer_id, version_id)
    command_id = str(uuid.uuid4())
    args = {"reason": "Angebot zurückgezogen"}

    status, body, _h = _post(url, args=args, command_id=command_id)
    assert status == 200
    assert set(body) == {
        "command_id",
        "offer_id",
        "offer_version_id",
        "withdrawn_at",
    }

    status2, body2, _h = _post(url, args=args, command_id=command_id)
    assert (status2, body2) == (status, body)

    offers = SQLiteOfferRepository(db)
    stored = offers.get(offer_id)
    assert stored is not None
    assert len(stored.withdrawal_evidence) == 1
    assert stored.withdrawal_evidence[0].reason == "Angebot zurückgezogen"
    offers.close()


def test_record_withdrawal_rejects_second_withdrawal(api) -> None:
    base, _ids, _db = api
    offer_id, version_id = _prepare_and_send(api)
    url = _record_withdrawal_url(base, offer_id, version_id)
    assert _post(url, args={})[0] == 200
    status, body, _h = _post(url, args={})
    assert (status, body["error"]) == (409, "withdrawal_evidence_exists")


def _prepare_send_accept(
    api: tuple[str, dict[str, str], Path],
) -> tuple[str, str, str, str]:
    base, _ids, _db = api
    offer_id, version_id = _prepare_and_send(api)
    status, body, _h = _post(
        _record_acceptance_url(base, offer_id, version_id),
        args=_RECORD_ACCEPTANCE_ARGS,
    )
    assert status == 200
    return offer_id, version_id, body["acceptance_id"], body["accepted_variant_id"]


def _convert_accepted_url(base: str, offer_id: str, version_id: str) -> str:
    return f"{base}/office/v1/offers/{offer_id}/versions/{version_id}/convert-accepted"


def test_convert_accepted_happy_path_and_replay(api) -> None:
    base, _ids, db = api
    offer_id, version_id, acceptance_id, variant_id = _prepare_send_accept(api)
    url = _convert_accepted_url(base, offer_id, version_id)
    args = {"accepted_variant_id": variant_id, "acceptance_id": acceptance_id}
    command_id = str(uuid.uuid4())

    status, body, _h = _post(url, args=args, command_id=command_id)
    assert status == 201
    assert set(body) == {
        "command_id",
        "offer_id",
        "offer_version_id",
        "accepted_variant_id",
        "acceptance_id",
        "order_id",
        "order_version_id",
    }
    assert body["offer_id"] == offer_id
    assert body["offer_version_id"] == version_id

    status2, body2, _h = _post(url, args=args, command_id=command_id)
    assert (status2, body2) == (status, body)

    status3, body3, _h = _post(url, args=args)
    assert status3 == 200
    assert body3["order_id"] == body["order_id"]

    offers = SQLiteOfferRepository(db)
    orders = SQLiteOrderRepository(db)
    stored = offers.get(offer_id)
    assert stored is not None
    assert stored.conversion_link is not None
    order = orders.get_order(body["order_id"])
    assert order is not None
    versions = orders.list_order_versions(body["order_id"])
    assert versions[0].location_text == "Hamburg"
    offers.close()
    orders.close()


def test_convert_accepted_rejects_prepared(api) -> None:
    base, _ids, _db = api
    offer_id, version_id = _prepare_offer(api)
    status, body, _h = _post(
        _convert_accepted_url(base, offer_id, version_id),
        args={
            "accepted_variant_id": _VARIANT_ID,
            "acceptance_id": str(uuid.uuid4()),
        },
    )
    assert (status, body["error"]) == (422, "conversion_blocked")


def test_convert_accepted_rejects_wrong_variant_or_acceptance(api) -> None:
    base, _ids, _db = api
    offer_id, version_id, acceptance_id, variant_id = _prepare_send_accept(api)
    url = _convert_accepted_url(base, offer_id, version_id)
    status, body, _h = _post(
        url,
        args={
            "accepted_variant_id": "55555555-5555-4555-8555-555555555551",
            "acceptance_id": acceptance_id,
        },
    )
    assert (status, body["error"]) == (422, "invalid_variant")
    status, body, _h = _post(
        url,
        args={
            "accepted_variant_id": variant_id,
            "acceptance_id": "66666666-6666-4666-8666-666666666666",
        },
    )
    assert (status, body["error"]) == (422, "conversion_blocked")


def test_convert_accepted_linked_order_without_link_blocks(api) -> None:
    base, ids, db = api
    inquiry_id = ids["inquiry_cancelled_order"]
    # Prepare/accept on the cancelled inquiry so a linked Order exists without
    # conversion_link; convert-accepted must not create another Order.
    status, prepared, _h = _post(
        f"{base}/office/v1/inquiries/{inquiry_id}/prepare-offer",
        args={"snapshot": _valid_offer_snapshot(inquiry_id=inquiry_id)},
    )
    assert status == 201
    offer_id = prepared["offer_id"]
    version_id = prepared["offer_version_id"]
    assert (
        _post(_mark_sent_url(base, offer_id, version_id), args=_MARK_SENT_ARGS)[0]
        == 200
    )
    status, accepted, _h = _post(
        _record_acceptance_url(base, offer_id, version_id),
        args=_RECORD_ACCEPTANCE_ARGS,
    )
    assert status == 200
    status, body, _h = _post(
        _convert_accepted_url(base, offer_id, version_id),
        args={
            "accepted_variant_id": accepted["accepted_variant_id"],
            "acceptance_id": accepted["acceptance_id"],
        },
    )
    assert (status, body["error"]) == (409, "already_converted")
    orders = SQLiteOrderRepository(db)
    assert (
        len(
            [
                order
                for order in orders.list_orders()
                if order.source_inquiry_id == inquiry_id
            ]
        )
        == 1
    )
    orders.close()


def test_convert_accepted_storno_replay_same_order(api) -> None:
    base, _ids, db = api
    offer_id, version_id, acceptance_id, variant_id = _prepare_send_accept(api)
    url = _convert_accepted_url(base, offer_id, version_id)
    args = {"accepted_variant_id": variant_id, "acceptance_id": acceptance_id}
    status, body, _h = _post(url, args=args)
    assert status == 201
    order_id = body["order_id"]

    orders = SQLiteOrderRepository(db)
    order = orders.get_order(order_id)
    assert order is not None
    cancel_status, _cancel_body, _h = _post(
        f"{base}/office/v1/orders/{order_id}/cancel",
        expect={"updated_at": order.updated_at.isoformat()},
    )
    assert cancel_status == 200
    orders.close()

    status2, body2, _h = _post(url, args=args)
    assert status2 == 200
    assert body2["order_id"] == order_id

    offers = SQLiteOfferRepository(db)
    stored = offers.get(offer_id)
    assert stored is not None
    assert stored.conversion_link is not None
    assert stored.conversion_link.order_id == order_id
    offers.close()


def test_convert_accepted_failure_leaves_no_conversion_or_ledger(api) -> None:
    base, _ids, db = api
    offer_id, version_id, acceptance_id, variant_id = _prepare_send_accept(api)
    command_id = str(uuid.uuid4())
    status, body, _h = _post(
        _convert_accepted_url(base, offer_id, version_id),
        args={
            "accepted_variant_id": variant_id,
            "acceptance_id": "00000000-0000-4000-8000-000000000099",
        },
        command_id=command_id,
    )
    assert (status, body["error"]) == (422, "conversion_blocked")

    conn = sqlite3.connect(db)
    link_count = conn.execute(
        "SELECT COUNT(*) FROM offer_conversion_links WHERE offer_id = ?",
        (offer_id,),
    ).fetchone()[0]
    ledger_count = conn.execute(
        "SELECT COUNT(*) FROM office_api_commands WHERE command_id = ?",
        (command_id,),
    ).fetchone()[0]
    conn.close()
    assert link_count == 0
    assert ledger_count == 0

    offers = SQLiteOfferRepository(db)
    stored = offers.get(offer_id)
    assert stored is not None
    assert stored.conversion_link is None
    offers.close()


_CATALOG_DISH_ID = "0aee1cec-c09e-5675-835b-2622af2ddb8a"
_INACTIVE_CATALOG_DISH_ID = "728927f2-4265-542b-92d7-cb168e2bc48d"


def _seed_catalog_dish(
    db: Path,
    *,
    dish_id: str = _CATALOG_DISH_ID,
    name: str = "Kartoffelsalat",
    active: bool = True,
) -> None:
    repo = SQLiteCatalogRepository(db)
    try:
        repo.insert_dish_if_absent(
            CatalogDish(
                dish_id=dish_id,
                name=name,
                description="Hausgemacht",
                composition="Kartoffeln",
                notes=None,
                current_unit_net_cents=320,
                allergens=("G", "J"),
                active=active,
                created_at=datetime(2026, 7, 16, 8, 0, tzinfo=UTC),
                updated_at=datetime(2026, 7, 16, 8, 0, tzinfo=UTC),
            )
        )
    finally:
        repo.close()


def test_list_catalog_dishes_schema(api) -> None:
    base, _ids, db = api
    _seed_catalog_dish(db)
    status, body, _h = _get(f"{base}/office/v1/catalog/dishes")
    assert status == 200
    assert body["total_count"] >= 1
    row = body["dishes"][0]
    assert set(row) == {
        "dish_id",
        "name",
        "current_unit_net_cents",
        "price_display",
        "allergens",
        "allergen_labels",
        "active",
        "category",
        "pricing_unit",
        "vat_rate_percent",
    }
    assert row["price_display"] == "3,20 €"
    # _seed_catalog_dish predates CATALOG_ADMIN_COMPLETION_V1A — legacy row,
    # no fictitious backfill.
    assert row["category"] is None
    assert row["pricing_unit"] is None
    assert row["vat_rate_percent"] is None


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("true", True),
        ("1", True),
        ("yes", True),
        ("false", False),
        ("0", False),
        ("no", False),
    ),
)
def test_list_catalog_dishes_parses_boolean_query(
    api, value: str, expected: bool
) -> None:
    base, _ids, db = api
    _seed_catalog_dish(db)
    _seed_catalog_dish(
        db,
        dish_id=_INACTIVE_CATALOG_DISH_ID,
        name="Inaktives Gericht",
        active=False,
    )
    status, body, _h = _get(f"{base}/office/v1/catalog/dishes?active_only={value}")
    assert status == 200
    returned_ids = {row["dish_id"] for row in body["dishes"]}
    assert _CATALOG_DISH_ID in returned_ids
    assert (_INACTIVE_CATALOG_DISH_ID not in returned_ids) is expected


def test_list_catalog_dishes_rejects_invalid_boolean_query(api) -> None:
    base, _ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/catalog/dishes?active_only=maybe")
    assert (status, body["error"]) == (400, "invalid_request")


def _seed_active_and_inactive(db) -> None:
    _seed_catalog_dish(db)
    _seed_catalog_dish(
        db,
        dish_id=_INACTIVE_CATALOG_DISH_ID,
        name="Inaktives Gericht",
        active=False,
    )


@pytest.mark.parametrize(
    "query,expect_active,expect_inactive",
    [
        ("", True, True),
        ("?active=true", True, False),
        ("?active=false", False, True),
        # legacy alias: active_only=true still means "active only", and
        # active_only=false keeps its original meaning of "no filter"
        ("?active_only=true", True, False),
        ("?active_only=false", True, True),
    ],
    ids=["no-filter", "active", "inactive", "legacy-true", "legacy-false"],
)
def test_list_catalog_dishes_active_filter_contract(
    api, query: str, expect_active: bool, expect_inactive: bool
) -> None:
    """CATALOG_ADMIN_PANEL_V1: `active` is the tri-state contract;
    `active_only` stays supported for callers older than this change."""
    base, _ids, db = api
    _seed_active_and_inactive(db)
    status, body, _h = _get(f"{base}/office/v1/catalog/dishes{query}")
    assert status == 200
    returned = {row["dish_id"] for row in body["dishes"]}
    assert (_CATALOG_DISH_ID in returned) is expect_active
    assert (_INACTIVE_CATALOG_DISH_ID in returned) is expect_inactive


@pytest.mark.parametrize(
    "query",
    [
        "?active=true&active_only=true",
        "?active=false&active_only=true",
        "?active=true&active_only=false",
    ],
)
def test_list_catalog_dishes_rejects_conflicting_active_params(api, query: str) -> None:
    """Fail closed: `active=false&active_only=true` has no honest answer, so
    the request is rejected rather than resolved by precedence — including
    the combinations that happen to agree, which would otherwise make the
    contract depend on which value the server chose to believe."""
    base, _ids, db = api
    _seed_active_and_inactive(db)
    status, body, _h = _get(f"{base}/office/v1/catalog/dishes{query}")
    assert (status, body["error"]) == (400, "invalid_request")


def test_list_catalog_dishes_rejects_invalid_active_value(api) -> None:
    base, _ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/catalog/dishes?active=maybe")
    assert (status, body["error"]) == (400, "invalid_request")


def test_list_catalog_dishes_active_filter_runs_before_limit(api) -> None:
    """The regression this contract exists for: with more active dishes than
    a page holds, `active=false` must still return the inactive ones."""
    base, _ids, db = api
    for index in range(120):
        _seed_catalog_dish(
            db,
            dish_id=f"{index:08d}-1111-4111-8111-111111111111",
            name=f"Aktiv {index:03d}",
            active=True,
        )
    for index in range(3):
        _seed_catalog_dish(
            db,
            dish_id=f"9999{index:04d}-2222-4222-8222-222222222222",
            name=f"Zzz Inaktiv {index}",
            active=False,
        )
    status, body, _h = _get(f"{base}/office/v1/catalog/dishes?active=false")
    assert status == 200
    assert len(body["dishes"]) == 3
    assert body["total_count"] == 3
    assert all(row["active"] is False for row in body["dishes"])

    status, body, _h = _get(f"{base}/office/v1/catalog/dishes?active=true")
    assert status == 200
    assert len(body["dishes"]) == 100
    assert body["total_count"] == 120
    assert body["truncated"] is True


def test_catalog_dish_detail_schema(api) -> None:
    base, _ids, db = api
    _seed_catalog_dish(db)
    status, body, _h = _get(f"{base}/office/v1/catalog/dishes/{_CATALOG_DISH_ID}")
    assert status == 200
    assert body["name"] == "Kartoffelsalat"
    assert body["price_history"] == []


def test_list_allergen_codes_schema(api) -> None:
    base, _ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/catalog/allergen-codes")
    assert status == 200
    assert len(body["allergen_codes"]) == 14
    assert body["allergen_codes"][0]["code"] == "A"


def test_update_catalog_dish_command_success(api) -> None:
    base, _ids, db = api
    _seed_catalog_dish(db)
    repo = SQLiteCatalogRepository(db)
    try:
        dish = repo.get_dish(_CATALOG_DISH_ID)
        assert dish is not None
        updated_at = dish.updated_at.isoformat()
    finally:
        repo.close()
    url = f"{base}/office/v1/catalog/dishes/{_CATALOG_DISH_ID}/update"
    args = {
        "name": "Kartoffelsalat",
        "description": "Neu",
        "composition": "mit Dill",
        "notes": None,
        "current_unit_net_cents": 400,
        "allergens": ["G", "J"],
        "active": True,
        "effective_from": "2026-08-01",
    }
    status, body, _h = _post(url, args=args, expect={"updated_at": updated_at})
    assert status == 200
    assert body["price_changed"] is True
    assert "price_history_entry_id" in body
    status, detail, _h = _get(f"{base}/office/v1/catalog/dishes/{_CATALOG_DISH_ID}")
    assert status == 200
    assert detail["current_unit_net_cents"] == 400
    assert len(detail["price_history"]) == 1


def test_update_catalog_dish_text_only_no_history(api) -> None:
    base, _ids, db = api
    _seed_catalog_dish(db)
    repo = SQLiteCatalogRepository(db)
    try:
        dish = repo.get_dish(_CATALOG_DISH_ID)
        assert dish is not None
        updated_at = dish.updated_at.isoformat()
    finally:
        repo.close()
    url = f"{base}/office/v1/catalog/dishes/{_CATALOG_DISH_ID}/update"
    args = {
        "name": "Kartoffelsalat",
        "description": "Nur Text",
        "composition": "Kartoffeln",
        "notes": None,
        "current_unit_net_cents": 320,
        "allergens": ["G", "J"],
        "active": True,
    }
    status, body, _h = _post(url, args=args, expect={"updated_at": updated_at})
    assert status == 200
    assert body["price_changed"] is False
    status, detail, _h = _get(f"{base}/office/v1/catalog/dishes/{_CATALOG_DISH_ID}")
    assert detail["price_history"] == []


def test_update_catalog_dish_stale_state_409(api) -> None:
    base, _ids, db = api
    _seed_catalog_dish(db)
    url = f"{base}/office/v1/catalog/dishes/{_CATALOG_DISH_ID}/update"
    args = {
        "name": "Kartoffelsalat",
        "current_unit_net_cents": 320,
        "allergens": [],
        "active": True,
    }
    status, body, _h = _post(
        url,
        args=args,
        expect={"updated_at": "2020-01-01T00:00:00+00:00"},
    )
    assert (status, body["error"]) == (409, "stale_state")


# --- CATALOG_ADMIN_COMPLETION_V1A: create/activate/deactivate ---------------


def _create_dish_url(base: str) -> str:
    return f"{base}/office/v1/catalog/dishes"


def _full_dish_create_args(**overrides: object) -> dict[str, object]:
    args: dict[str, object] = {
        "name": "Lachs-Canape",
        "category": "fingerfood",
        "pricing_unit": "stueck",
        "current_unit_net_cents": 250,
        "vat_rate_percent": 7,
        "description": "Frisch",
        "composition": "Lachs, Brot",
        "notes": "Küchennotiz",
        "allergens": ["A", "D"],
    }
    args.update(overrides)
    return args


def test_create_catalog_dish_full_dish_is_inactive(api) -> None:
    base, _ids, _db = api
    status, body, _h = _post(_create_dish_url(base), args=_full_dish_create_args())
    assert status == 201
    assert body["active"] is False
    dish_id = body["dish_id"]

    status, detail, _h = _get(f"{base}/office/v1/catalog/dishes/{dish_id}")
    assert status == 200
    assert detail["name"] == "Lachs-Canape"
    assert detail["category"] == "fingerfood"
    assert detail["pricing_unit"] == "stueck"
    assert detail["vat_rate_percent"] == 7
    assert detail["active"] is False
    assert detail["allergens"] == ["A", "D"]


def test_create_catalog_dish_minimal_required_fields(api) -> None:
    base, _ids, _db = api
    args = {
        "name": "Minimal",
        "category": "sonstiges",
        "pricing_unit": "per_person",
        "current_unit_net_cents": 100,
        "vat_rate_percent": 19,
    }
    status, body, _h = _post(_create_dish_url(base), args=args)
    assert status == 201
    assert body["active"] is False


def test_create_catalog_dish_missing_required_field_returns_400(api) -> None:
    base, _ids, _db = api
    args = _full_dish_create_args()
    del args["category"]
    status, body, _h = _post(_create_dish_url(base), args=args)
    assert (status, body["error"]) == (400, "invalid_request")


def test_create_catalog_dish_invalid_pricing_unit_returns_400(api) -> None:
    base, _ids, _db = api
    status, body, _h = _post(
        _create_dish_url(base), args=_full_dish_create_args(pricing_unit="kg")
    )
    assert (status, body["error"]) == (400, "invalid_request")


def test_create_catalog_dish_empty_category_returns_422(api) -> None:
    base, _ids, _db = api
    status, body, _h = _post(
        _create_dish_url(base), args=_full_dish_create_args(category="   ")
    )
    assert (status, body["error"]) == (422, "validation_error")


@pytest.mark.parametrize(
    "category",
    [
        "Fingerfood",
        "finger food",
        "getränke",
        "-dessert",
        "dessert-",
        "food--hot",
        "food__hot",
    ],
)
def test_create_catalog_dish_invalid_category_key_returns_422(
    api, category: str
) -> None:
    base, _ids, _db = api
    status, body, _h = _post(
        _create_dish_url(base), args=_full_dish_create_args(category=category)
    )
    assert (status, body["error"]) == (422, "validation_error")


def test_create_catalog_dish_accepts_hyphen_and_underscore_category(api) -> None:
    base, _ids, _db = api
    status, body, _h = _post(
        _create_dish_url(base),
        args=_full_dish_create_args(category="service-personal"),
    )
    assert status == 201
    dish_id = body["dish_id"]
    status, detail, _h = _get(f"{base}/office/v1/catalog/dishes/{dish_id}")
    assert detail["category"] == "service-personal"

    status, body2, _h = _post(
        _create_dish_url(base),
        args=_full_dish_create_args(name="Warme Suppe", category="warme_speisen"),
    )
    assert status == 201
    dish_id2 = body2["dish_id"]
    status, detail2, _h = _get(f"{base}/office/v1/catalog/dishes/{dish_id2}")
    assert detail2["category"] == "warme_speisen"


def test_create_catalog_dish_invalid_vat_returns_422(api) -> None:
    base, _ids, _db = api
    status, body, _h = _post(
        _create_dish_url(base), args=_full_dish_create_args(vat_rate_percent=13)
    )
    assert (status, body["error"]) == (422, "validation_error")


def _activate_url(base: str, dish_id: str) -> str:
    return f"{base}/office/v1/catalog/dishes/{dish_id}/activate"


def _deactivate_url(base: str, dish_id: str) -> str:
    return f"{base}/office/v1/catalog/dishes/{dish_id}/deactivate"


def test_activate_catalog_dish_success(api) -> None:
    base, _ids, _db = api
    _status, created, _h = _post(_create_dish_url(base), args=_full_dish_create_args())
    dish_id = created["dish_id"]
    status, body, _h = _post(
        _activate_url(base, dish_id),
        args={},
        expect={"updated_at": created["updated_at"]},
    )
    assert status == 200
    assert body["active"] is True

    status, detail, _h = _get(f"{base}/office/v1/catalog/dishes/{dish_id}")
    assert detail["active"] is True


def test_deactivate_catalog_dish_success(api) -> None:
    base, _ids, db = api
    _seed_catalog_dish(db, active=True)
    repo = SQLiteCatalogRepository(db)
    try:
        updated_at = repo.get_dish(_CATALOG_DISH_ID).updated_at.isoformat()  # type: ignore[union-attr]
    finally:
        repo.close()
    status, body, _h = _post(
        _deactivate_url(base, _CATALOG_DISH_ID),
        args={},
        expect={"updated_at": updated_at},
    )
    assert status == 200
    assert body["active"] is False


def test_activate_catalog_dish_repeated_is_idempotent(api) -> None:
    base, _ids, _db = api
    _status, created, _h = _post(_create_dish_url(base), args=_full_dish_create_args())
    dish_id = created["dish_id"]
    status1, body1, _h = _post(
        _activate_url(base, dish_id),
        args={},
        expect={"updated_at": created["updated_at"]},
    )
    assert status1 == 200
    status2, body2, _h = _post(
        _activate_url(base, dish_id),
        args={},
        expect={"updated_at": body1["updated_at"]},
    )
    assert status2 == 200
    assert body2["updated_at"] == body1["updated_at"]


def test_deactivate_catalog_dish_repeated_is_idempotent(api) -> None:
    base, _ids, db = api
    _seed_catalog_dish(db, active=True)
    repo = SQLiteCatalogRepository(db)
    try:
        updated_at = repo.get_dish(_CATALOG_DISH_ID).updated_at.isoformat()  # type: ignore[union-attr]
    finally:
        repo.close()
    status1, body1, _h = _post(
        _deactivate_url(base, _CATALOG_DISH_ID),
        args={},
        expect={"updated_at": updated_at},
    )
    assert status1 == 200
    status2, body2, _h = _post(
        _deactivate_url(base, _CATALOG_DISH_ID),
        args={},
        expect={"updated_at": body1["updated_at"]},
    )
    assert status2 == 200
    assert body2["updated_at"] == body1["updated_at"]


def test_activate_catalog_dish_stale_state_409(api) -> None:
    base, _ids, db = api
    _seed_catalog_dish(db, active=False)
    status, body, _h = _post(
        _activate_url(base, _CATALOG_DISH_ID),
        args={},
        expect={"updated_at": "2020-01-01T00:00:00+00:00"},
    )
    assert (status, body["error"]) == (409, "stale_state")


def test_deactivate_catalog_dish_stale_state_409(api) -> None:
    base, _ids, db = api
    _seed_catalog_dish(db, active=True)
    status, body, _h = _post(
        _deactivate_url(base, _CATALOG_DISH_ID),
        args={},
        expect={"updated_at": "2020-01-01T00:00:00+00:00"},
    )
    assert (status, body["error"]) == (409, "stale_state")


def test_activate_catalog_dish_missing_dish_returns_404(api) -> None:
    base, _ids, _db = api
    missing_id = "99999999-9999-4999-8999-999999999999"
    status, body, _h = _post(
        _activate_url(base, missing_id),
        args={},
        expect={"updated_at": "2026-01-01T00:00:00+00:00"},
    )
    assert (status, body["error"]) == (404, "not_found")


def test_deactivate_catalog_dish_missing_dish_returns_404(api) -> None:
    base, _ids, _db = api
    missing_id = "99999999-9999-4999-8999-999999999999"
    status, body, _h = _post(
        _deactivate_url(base, missing_id),
        args={},
        expect={"updated_at": "2026-01-01T00:00:00+00:00"},
    )
    assert (status, body["error"]) == (404, "not_found")


def test_create_catalog_dish_routes_require_bearer_auth(api) -> None:
    base, _ids, _db = api
    no_auth: dict[str, str] = {}
    status, body, _h = _post(
        _create_dish_url(base),
        args=_full_dish_create_args(),
        headers=no_auth,
    )
    assert (status, body["error"]) == (401, "unauthorized")


def test_activate_catalog_dish_requires_bearer_auth_and_does_not_change_dish(
    api,
) -> None:
    base, _ids, db = api
    _seed_catalog_dish(db, active=False)
    repo = SQLiteCatalogRepository(db)
    try:
        updated_at = repo.get_dish(_CATALOG_DISH_ID).updated_at.isoformat()  # type: ignore[union-attr]
    finally:
        repo.close()
    no_auth: dict[str, str] = {}
    status, body, _h = _post(
        _activate_url(base, _CATALOG_DISH_ID),
        args={},
        expect={"updated_at": updated_at},
        headers=no_auth,
    )
    assert (status, body["error"]) == (401, "unauthorized")

    status, detail, _h = _get(f"{base}/office/v1/catalog/dishes/{_CATALOG_DISH_ID}")
    assert status == 200
    assert detail["active"] is False
    assert detail["updated_at"] == updated_at


def test_deactivate_catalog_dish_requires_bearer_auth_and_does_not_change_dish(
    api,
) -> None:
    base, _ids, db = api
    _seed_catalog_dish(db, active=True)
    repo = SQLiteCatalogRepository(db)
    try:
        updated_at = repo.get_dish(_CATALOG_DISH_ID).updated_at.isoformat()  # type: ignore[union-attr]
    finally:
        repo.close()
    no_auth: dict[str, str] = {}
    status, body, _h = _post(
        _deactivate_url(base, _CATALOG_DISH_ID),
        args={},
        expect={"updated_at": updated_at},
        headers=no_auth,
    )
    assert (status, body["error"]) == (401, "unauthorized")

    status, detail, _h = _get(f"{base}/office/v1/catalog/dishes/{_CATALOG_DISH_ID}")
    assert status == 200
    assert detail["active"] is True
    assert detail["updated_at"] == updated_at


# --- confirmation document (EMAIL_MVP_1 / outbound pack B1) -------------------


def _get_raw(
    url: str, headers: dict | None = None
) -> tuple[int, bytes, dict[str, str]]:
    req = urllib.request.Request(url, headers=headers if headers is not None else _AUTH)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def _confirmation_document_url(base: str, order_id: str) -> str:
    return f"{base}/office/v1/orders/{order_id}/confirmation-document"


def _live_confirmation_preview_url(base: str, order_id: str) -> str:
    """Live CDP preview before create (V1-D) — not the persisted-document renderer."""
    return f"{base}/office/v1/orders/{order_id}/confirmation-preview"


def _confirmation_preview_url(
    base: str,
    order_id: str,
    *,
    format: str = "json",
    document_snapshot_id: str | None = None,
) -> str:
    query = f"format={format}"
    if document_snapshot_id is not None:
        query += f"&document_snapshot_id={document_snapshot_id}"
    return f"{_confirmation_document_url(base, order_id)}/preview?{query}"


def _confirmation_snapshot_count(db: Path) -> int:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM order_confirmation_document_snapshots"
        ).fetchone()[0]
    finally:
        conn.close()


def _confirmation_snapshot_row(db: Path, document_snapshot_id: str) -> tuple[str, str]:
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT document_snapshot_id, document_hash "
            "FROM order_confirmation_document_snapshots "
            "WHERE document_snapshot_id = ?",
            (document_snapshot_id,),
        ).fetchone()
        assert row is not None
        return row[0], row[1]
    finally:
        conn.close()


def _create_convertible_inquiry(base: str) -> str:
    status, body, _h = _post(f"{base}/office/v1/inquiries", args=_CREATE_ARGS)
    assert status == 201
    return body["inquiry_id"]


def _unique_offer_snapshot(*, inquiry_id: str) -> dict[str, object]:
    payload = _valid_offer_snapshot(inquiry_id=inquiry_id)
    payload["snapshot_id"] = str(uuid.uuid4())
    variant = payload["variants"][0]  # type: ignore[index]
    variant["variant_id"] = str(uuid.uuid4())
    position = variant["positions"][0]  # type: ignore[index]
    position["position_id"] = str(uuid.uuid4())
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    return payload


def _ensure_inquiry_recipient_email(base: str, inquiry_id: str) -> None:
    detail = _get(f"{base}/office/v1/inquiries/{inquiry_id}")[1]
    _post(
        f"{base}/office/v1/inquiries/{inquiry_id}/update",
        args={
            "event_date": detail["event_date"],
            "crm_stage": detail["crm_stage"],
            "time_window_text": detail["time_window_text"],
            "location_text": detail["location_text"],
            "guest_count_estimate": detail["guest_count_estimate"],
            "planning_mode": detail["planning_mode"],
            "intake_message": (
                "Firma: Example GmbH\n"
                "Name: Example Contact\n"
                "E-Mail: customer@example.invalid\n"
            ),
        },
        expect={"updated_at": detail["updated_at"]},
    )


def _ensure_inquiry_fulfillment_mode(
    base: str, inquiry_id: str, *, mode: str = "PICKUP"
) -> None:
    detail = _get(f"{base}/office/v1/inquiries/{inquiry_id}")[1]
    status, _body, _h = _post(
        f"{base}/office/v1/inquiries/{inquiry_id}/fulfillment-mode",
        args={"fulfillment_mode": mode},
        expect={"updated_at": detail["updated_at"]},
    )
    assert status == 200


def _set_inquiry_customer_snapshot(
    db: Path,
    inquiry_id: str,
    snapshot: InquiryCustomerSnapshot,
) -> None:
    inquiries = SQLiteInquiryRepository(db)
    inquiry = inquiries.get_by_id(inquiry_id)
    assert inquiry is not None
    inquiries.update(replace(inquiry, customer_snapshot=snapshot))
    inquiries.close()


def _clear_inquiry_recipient_email(db: Path, inquiry_id: str) -> None:
    inquiries = SQLiteInquiryRepository(db)
    inquiry = inquiries.get_by_id(inquiry_id)
    assert inquiry is not None
    contact = inquiry.customer_snapshot
    inquiries.update(
        replace(
            inquiry,
            customer_snapshot=InquiryCustomerSnapshot(
                company_name=contact.company_name if contact else None,
                contact_name=contact.contact_name if contact else None,
                phone=contact.phone if contact else None,
                email=None,
            ),
        )
    )
    inquiries.close()


def _make_effective_offer_order(
    api: tuple[str, dict[str, str], Path],
    *,
    inquiry_id: str | None = None,
    snapshot: dict[str, object] | None = None,
    ensure_recipient_email: bool = True,
) -> tuple[str, str]:
    base, ids, db = api
    resolved_inquiry = inquiry_id or ids["inquiry_offer_ready"]
    if ensure_recipient_email:
        _ensure_inquiry_recipient_email(base, resolved_inquiry)
    _ensure_inquiry_fulfillment_mode(base, resolved_inquiry)
    resolved_snapshot = snapshot or _unique_offer_snapshot(inquiry_id=resolved_inquiry)
    variant_id = resolved_snapshot["variants"][0]["variant_id"]  # type: ignore[index]
    prep_status, prep_body, _h = _post(
        _prepare_offer_url(base, resolved_inquiry),
        args={"snapshot": resolved_snapshot},
    )
    assert prep_status == 201
    offer_id = prep_body["offer_id"]
    offer_version_id = prep_body["offer_version_id"]

    assert (
        _post(
            _mark_sent_url(base, offer_id, offer_version_id),
            args=_MARK_SENT_ARGS,
        )[0]
        == 200
    )
    accept_status, accept_body, _h = _post(
        _record_acceptance_url(base, offer_id, offer_version_id),
        args={**_RECORD_ACCEPTANCE_ARGS, "accepted_variant_id": variant_id},
    )
    assert accept_status == 200

    convert_status, convert_body, _h = _post(
        _convert_accepted_url(base, offer_id, offer_version_id),
        args={
            "accepted_variant_id": accept_body["accepted_variant_id"],
            "acceptance_id": accept_body["acceptance_id"],
        },
    )
    assert convert_status in (200, 201)
    order_id = convert_body["order_id"]
    order_version_id = convert_body["order_version_id"]

    assert (
        _post(
            f"{base}/office/v1/orders/{order_id}/print-confirm",
            args={"order_version_id": order_version_id},
        )[0]
        == 200
    )
    _ack_next_kitchen_job(db, order_version_id)
    return order_id, order_version_id


def test_confirmation_document_post_create_get_and_replay(api) -> None:
    base, _ids, db = api
    order_id, order_version_id = _make_effective_offer_order(api)
    command_url = _confirmation_document_url(base, order_id)
    command_id = str(uuid.uuid4())
    expect = {"current_effective_order_version_id": order_version_id}
    args = {"created_by": "office-api-test"}

    status, created, _h = _post(
        command_url,
        args=args,
        expect=expect,
        command_id=command_id,
    )
    assert status == 201
    assert set(created) == {
        "command_id",
        "order_id",
        "document_snapshot_id",
        "snapshot",
    }
    assert created["order_id"] == order_id
    snapshot = created["snapshot"]
    assert snapshot["order_version_id"] == order_version_id
    assert snapshot["recipient_status"] == "ready"
    assert snapshot["document_hash_short"].startswith("sha256:")

    stored_id, stored_hash = _confirmation_snapshot_row(
        db, created["document_snapshot_id"]
    )
    assert stored_id == created["document_snapshot_id"]
    assert stored_hash.startswith("sha256:")
    assert snapshot["document_hash_short"].endswith(stored_hash[-4:])

    status, replay, _h = _post(
        command_url,
        args=args,
        expect=expect,
        command_id=command_id,
    )
    assert (status, replay) == (201, created)
    assert _confirmation_snapshot_count(db) == 1

    status, second, _h = _post(command_url, args=args, expect=expect)
    assert status == 200
    assert second["document_snapshot_id"] == created["document_snapshot_id"]
    assert second["snapshot"] == snapshot
    assert _confirmation_snapshot_count(db) == 1

    read_status, summary, _h = _get(command_url)
    assert read_status == 200
    assert summary["document_snapshot_id"] == created["document_snapshot_id"]
    assert summary["snapshot"] == snapshot


def test_confirmation_document_get_not_found_cases(api) -> None:
    base, _ids, db = api
    order_id, order_version_id = _make_effective_offer_order(api)

    status, body, _h = _get(_confirmation_document_url(base, order_id))
    assert (status, body["error"]) == (404, "not_found")

    _, created, _h = _post(
        _confirmation_document_url(base, order_id),
        args={"created_by": "office-api-test"},
        expect={"current_effective_order_version_id": order_version_id},
    )
    snapshot_id = created["document_snapshot_id"]

    status, body, _h = _get(_confirmation_document_url(base, str(uuid.uuid4())))
    assert (status, body["error"]) == (404, "not_found")

    status, body, _h = _get(
        f"{_confirmation_document_url(base, order_id)}"
        f"?document_snapshot_id={uuid.uuid4()}"
    )
    assert (status, body["error"]) == (404, "not_found")

    assert _confirmation_snapshot_count(db) == 1
    status, body, _h = _get(
        f"{_confirmation_document_url(base, order_id)}"
        f"?document_snapshot_id={snapshot_id}"
    )
    assert status == 200
    assert body["document_snapshot_id"] == snapshot_id


def test_confirmation_document_preview_json_and_html(api) -> None:
    base, _ids, _db = api
    order_id, order_version_id = _make_effective_offer_order(api)
    created = _post(
        _confirmation_document_url(base, order_id),
        args={"created_by": "office-api-test"},
        expect={"current_effective_order_version_id": order_version_id},
    )[1]
    snapshot_id = created["document_snapshot_id"]

    status, body, _h = _get(_confirmation_preview_url(base, order_id, format="json"))
    assert status == 200
    assert set(body) == {"document_snapshot_id", "preview"}
    assert body["document_snapshot_id"] == snapshot_id
    preview = body["preview"]
    assert preview["title"] == "Auftragsbestätigung"
    assert preview["positions"]
    assert preview["vat_buckets"]
    assert preview["net_total_eur"]
    assert preview["vat_total_eur"]
    assert preview["gross_total_eur"]
    assert preview["schema_version"] == 3
    assert preview["address_facts_stored"] is True
    assert "invoice_address" in preview
    assert "delivery_address" in preview
    assert "delivery_address_differs" in preview
    assert "document_warnings" in preview
    assert "canonical_snapshot_json" not in body
    assert "unit_net_cents" not in preview["positions"][0]

    status, raw, headers = _get_raw(
        _confirmation_preview_url(base, order_id, format="html")
    )
    assert status == 200
    html = raw.decode("utf-8")
    content_type = headers.get("Content-type") or headers.get("Content-Type", "")
    assert content_type.startswith("text/html")
    assert "Auftragsbestätigung" in html
    assert created["snapshot"]["document_reference"] in html
    assert preview["gross_total_eur"] in html


def test_confirmation_document_preview_escapes_html_but_preserves_json_text(
    api,
) -> None:
    base, ids, db = api
    malicious = "<script>alert(1)</script>"
    rich = "<b>Test</b>"
    amp = "A&B"
    inquiry_id = ids["inquiry_offer_ready"]
    detail = _get(f"{base}/office/v1/inquiries/{inquiry_id}")[1]
    _post(
        f"{base}/office/v1/inquiries/{inquiry_id}/update",
        args={
            "event_date": detail["event_date"],
            "crm_stage": detail["crm_stage"],
            "time_window_text": detail["time_window_text"],
            "location_text": amp,
            "guest_count_estimate": detail["guest_count_estimate"],
            "planning_mode": detail["planning_mode"],
            "intake_message": f"Firma: {malicious}\nName: {rich}\nE-Mail: customer@example.invalid\n",
        },
        expect={"updated_at": detail["updated_at"]},
    )
    snapshot_payload = _valid_offer_snapshot(inquiry_id=inquiry_id)
    position = snapshot_payload["variants"][0]["positions"][0]  # type: ignore[index]
    position["name"] = malicious
    position["description"] = rich
    snapshot_payload["event"]["location_text"] = amp  # type: ignore[index]
    snapshot_payload["snapshot_hash"] = compute_snapshot_hash(snapshot_payload)

    order_id, order_version_id = _make_effective_offer_order(
        api,
        inquiry_id=inquiry_id,
        snapshot=snapshot_payload,
        ensure_recipient_email=False,
    )
    _set_inquiry_customer_snapshot(
        db,
        inquiry_id,
        InquiryCustomerSnapshot(
            company_name=malicious,
            contact_name=rich,
            email="customer@example.invalid",
            phone="+49301234567",
        ),
    )
    _post(
        _confirmation_document_url(base, order_id),
        args={"created_by": "office-api-test"},
        expect={"current_effective_order_version_id": order_version_id},
    )

    preview = _get(_confirmation_preview_url(base, order_id, format="json"))[1][
        "preview"
    ]
    assert preview["recipient_company"] == malicious
    assert preview["recipient_name"] == rich
    assert preview["location_text"] == amp
    assert preview["positions"][0]["name"] == malicious

    status, raw, _h = _get_raw(_confirmation_preview_url(base, order_id, format="html"))
    html = raw.decode("utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "<b>Test</b>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;b&gt;Test&lt;/b&gt;" in html
    assert "A&amp;B" in html


def test_confirmation_document_snapshot_isolated_by_order(api) -> None:
    base, ids, db = api
    order_a, version_a = _make_effective_offer_order(
        api, inquiry_id=ids["inquiry_convertible"]
    )
    order_b, _version_b = _make_effective_offer_order(
        api, inquiry_id=_create_convertible_inquiry(base)
    )
    created_a = _post(
        _confirmation_document_url(base, order_a),
        args={"created_by": "office-api-test"},
        expect={"current_effective_order_version_id": version_a},
    )[1]
    snapshot_id = created_a["document_snapshot_id"]

    status, body, _h = _get(
        f"{_confirmation_document_url(base, order_b)}"
        f"?document_snapshot_id={snapshot_id}"
    )
    assert (status, body["error"]) == (404, "not_found")
    assert _confirmation_snapshot_count(db) == 1


def test_confirmation_document_stale_expect_and_blocked_states(api) -> None:
    base, ids, db = api
    order_id, order_version_id = _make_effective_offer_order(api)

    status, body, _h = _post(
        _confirmation_document_url(base, order_id),
        args={"created_by": "office-api-test"},
        expect={"current_effective_order_version_id": str(uuid.uuid4())},
    )
    assert (status, body["error"]) == (409, "stale_state")

    version_args = {
        "event_date": "2026-10-03",
        "time_window_text": "abends",
        "location_text": "Hamburg",
        "guest_count_estimate": 40,
        "planning_mode": "caterer_suggestion",
    }
    _post(
        f"{base}/office/v1/orders/{order_id}/versions",
        args=version_args,
        expect={
            "latest_version_number": 1,
            "current_effective_order_version_id": order_version_id,
            "current_candidate_order_version_id": None,
        },
    )
    status, body, _h = _post(
        _confirmation_document_url(base, order_id),
        args={"created_by": "office-api-test"},
        expect={"current_effective_order_version_id": order_version_id},
    )
    assert (status, body["error"]) == (422, "confirmation_document_blocked")
    assert "INVALID_ORDER_STATE" in body.get("reasons", [])

    # Order without commercial snapshot: confirmation is blocked (invariant).
    inquiries = SQLiteInquiryRepository(db)
    orders = SQLiteOrderRepository(db)
    core = OperationalCoreService(orders)
    inquiry = InquiryService(inquiries).create_inquiry(
        event_date=date(2026, 10, 1),
        inquiry_source="manual",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="mittags",
        location_text="Ohne Snapshot",
        guest_count_estimate=10,
        planning_mode="caterer_suggestion",
        call_verification_required=False,
        call_verification_status="not_required",
        contact_email="kunde@example.com",
        contact_phone="+49301234567",
    )
    order, version = seed_order(orders, inquiry)
    core.confirm_kitchen_print(order.order_id, version.order_version_id)
    core.make_order_version_effective(order.order_id, version.order_version_id)
    inquiries.close()
    orders.close()

    status, body, _h = _post(
        _confirmation_document_url(base, order.order_id),
        args={"created_by": "office-api-test"},
        expect={"current_effective_order_version_id": version.order_version_id},
    )
    assert (status, body["error"]) == (422, "confirmation_document_blocked")


def test_confirmation_document_missing_recipient_is_blocked(api) -> None:
    base, ids, db = api
    inquiry_id = ids["inquiry_offer_ready"]
    order_id, order_version_id = _make_effective_offer_order(
        api, inquiry_id=inquiry_id, ensure_recipient_email=False
    )
    _clear_inquiry_recipient_email(db, inquiry_id)
    inquiries = SQLiteInquiryRepository(db)
    inquiry = inquiries.get_by_id(inquiry_id)
    assert inquiry is not None
    contact = inquiry.customer_snapshot
    inquiries.update(
        replace(
            inquiry,
            customer_snapshot=InquiryCustomerSnapshot(
                company_name=contact.company_name if contact else None,
                contact_name=contact.contact_name if contact else None,
                phone=None,
                email=None,
            ),
        )
    )
    inquiries.close()
    status, created, _h = _post(
        _confirmation_document_url(base, order_id),
        args={"created_by": "office-api-test"},
        expect={"current_effective_order_version_id": order_version_id},
    )
    assert status == 422
    assert created["error"] == "confirmation_document_blocked"
    assert "MISSING_CUSTOMER_CONTACT" in created.get("reasons", [])
    assert _confirmation_snapshot_count(db) == 0


def test_confirmation_document_preview_rejects_unknown_format(api) -> None:
    base, _ids, _db = api
    order_id, order_version_id = _make_effective_offer_order(api)
    _post(
        _confirmation_document_url(base, order_id),
        args={"created_by": "office-api-test"},
        expect={"current_effective_order_version_id": order_version_id},
    )
    status, body, _h = _get(_confirmation_preview_url(base, order_id, format="pdf"))
    assert (status, body["error"]) == (400, "invalid_request")


def test_confirmation_document_reads_are_side_effect_free(api) -> None:
    base, _ids, db = api
    order_id, order_version_id = _make_effective_offer_order(api)
    detail_before = _get(f"{base}/office/v1/orders/{order_id}")[1]
    _post(
        _confirmation_document_url(base, order_id),
        args={"created_by": "office-api-test"},
        expect={"current_effective_order_version_id": order_version_id},
    )
    count_after_create = _confirmation_snapshot_count(db)

    for _ in range(2):
        assert _get(_confirmation_document_url(base, order_id))[0] == 200
        assert _get(_confirmation_preview_url(base, order_id, format="json"))[0] == 200
        assert (
            _get_raw(_confirmation_preview_url(base, order_id, format="html"))[0] == 200
        )

    assert _confirmation_snapshot_count(db) == count_after_create
    detail_after = _get(f"{base}/office/v1/orders/{order_id}")[1]
    assert (
        detail_after["effective_order_version_id"]
        == detail_before["effective_order_version_id"]
    )
    assert (
        detail_after["candidate_order_version_id"]
        == detail_before["candidate_order_version_id"]
    )


def test_confirmation_document_routes_require_bearer_auth(api) -> None:
    base, ids, _db = api
    order_id = ids["order_ready"]
    no_auth: dict[str, str] = {}
    for url in (
        _confirmation_document_url(base, order_id),
        _confirmation_preview_url(base, order_id, format="json"),
        _live_confirmation_preview_url(base, order_id),
    ):
        status, body, _h = _get(url, headers=no_auth)
        assert (status, body["error"]) == (401, "unauthorized")
    status, body, _h = _post(
        _confirmation_document_url(base, order_id),
        args={"created_by": "office-api-test"},
        expect={"current_effective_order_version_id": ids["version_ready"]},
        headers=no_auth,
    )
    assert (status, body["error"]) == (401, "unauthorized")


# --- live confirmation preview (CUSTOMER_DOCUMENT_PROJECTION_V1-D) ------------


def test_live_confirmation_preview_eligible_does_not_persist(api) -> None:
    base, _ids, db = api
    order_id, _version_id = _make_effective_offer_order(api)
    count_before = _confirmation_snapshot_count(db)

    status, body, _h = _get(_live_confirmation_preview_url(base, order_id))
    assert status == 200
    assert body["document_type"] == "ORDER_CONFIRMATION"
    assert body["eligible"] is True
    assert body["blockers"] == []
    assert body["commercial"] is not None
    assert body["positions"]
    assert body["recipient"]["email"] == "kunde@example.com"
    assert body["recipient"]["name"] == "Example Contact"
    assert "document_id" not in body
    assert "document_snapshot_id" not in body
    assert _confirmation_snapshot_count(db) == count_before


def test_live_confirmation_preview_missing_commercial_returns_200_with_blocker(
    api,
) -> None:
    base, ids, db = api
    inquiries = SQLiteInquiryRepository(db)
    orders = SQLiteOrderRepository(db)
    inquiry = inquiries.get_by_id(ids["inquiry_convertible"])
    assert inquiry is not None
    inquiries.update(replace(inquiry, fulfillment_mode="PICKUP"))
    order, version = seed_order(orders, inquiry)
    core = OperationalCoreService(orders)
    core.confirm_kitchen_print(order.order_id, version.order_version_id)
    core.make_order_version_effective(order.order_id, version.order_version_id)
    inquiries.close()
    orders.close()

    status, body, _h = _get(_live_confirmation_preview_url(base, order.order_id))
    assert status == 200
    assert body["eligible"] is False
    assert [row["code"] for row in body["blockers"]] == ["MISSING_COMMERCIAL_SNAPSHOT"]
    assert body["commercial"] is None
    assert body["positions"] == []
    assert body["event"] is not None
    assert body["recipient"]["name"] == "Example Contact"
    assert "document_id" not in body
    assert _confirmation_snapshot_count(db) == 0


def test_live_confirmation_preview_shows_blockers_while_prepare_still_enforces(
    api,
) -> None:
    base, ids, db = api
    inquiry_id = ids["inquiry_offer_ready"]
    order_id, order_version_id = _make_effective_offer_order(
        api, inquiry_id=inquiry_id, ensure_recipient_email=False
    )
    _clear_inquiry_recipient_email(db, inquiry_id)
    inquiries = SQLiteInquiryRepository(db)
    inquiry = inquiries.get_by_id(inquiry_id)
    assert inquiry is not None
    contact = inquiry.customer_snapshot
    inquiries.update(
        replace(
            inquiry,
            customer_snapshot=InquiryCustomerSnapshot(
                company_name=contact.company_name if contact else None,
                contact_name=contact.contact_name if contact else None,
                phone=None,
                email=None,
            ),
        )
    )
    inquiries.close()

    status, preview, _h = _get(_live_confirmation_preview_url(base, order_id))
    assert status == 200
    assert preview["eligible"] is False
    assert "MISSING_CUSTOMER_CONTACT" in [row["code"] for row in preview["blockers"]]
    assert _confirmation_snapshot_count(db) == 0

    status, created, _h = _post(
        _confirmation_document_url(base, order_id),
        args={"created_by": "office-api-test"},
        expect={"current_effective_order_version_id": order_version_id},
    )
    assert status == 422
    assert created["error"] == "confirmation_document_blocked"
    assert "MISSING_CUSTOMER_CONTACT" in created.get("reasons", [])
    assert _confirmation_snapshot_count(db) == 0


def test_live_confirmation_preview_unknown_order_is_404(api) -> None:
    base, _ids, _db = api
    status, body, _h = _get(_live_confirmation_preview_url(base, str(uuid.uuid4())))
    assert (status, body["error"]) == (404, "not_found")


# --- confirmation outbound fake outbox (EMAIL_MVP_2 / outbound pack B2) ------


def _confirmation_send_url(base: str, order_id: str) -> str:
    return f"{base}/office/v1/orders/{order_id}/confirmation-document/send"


def _confirmation_send_status_url(base: str, order_id: str) -> str:
    return f"{base}/office/v1/orders/{order_id}/confirmation-document/send-status"


def _confirmation_fake_outbox_url(base: str, order_id: str) -> str:
    return f"{base}/office/v1/orders/{order_id}/confirmation-document/fake-outbox"


def _pause_order_via_api(base: str, order_id: str) -> dict[str, object]:
    detail = _get(f"{base}/office/v1/orders/{order_id}")[1]
    status, body, _headers = _post(
        f"{base}/office/v1/orders/{order_id}/pause",
        args={
            "reason_code": "operational_review",
            "note": "API acceptance test",
            "actor_reference": "office-api-test",
        },
        expect={
            "operational_pause_active": False,
            "latest_pause_event_id": detail["operational_pause"][
                "latest_pause_event_id"
            ],
        },
    )
    assert status == 200
    return body["operational_pause"]


def _resume_order_via_api(
    base: str, order_id: str, pause: dict[str, object]
) -> dict[str, object]:
    status, body, _headers = _post(
        f"{base}/office/v1/orders/{order_id}/resume",
        args={
            "reason_code": "operator_cleared",
            "note": "API acceptance test complete",
            "actor_reference": "office-api-test",
        },
        expect={
            "operational_pause_active": True,
            "current_pause_event_id": pause["current_pause_event_id"],
            "latest_pause_event_id": pause["latest_pause_event_id"],
        },
    )
    assert status == 200
    return body["operational_pause"]


def _outbound_counts_for_snapshot(db: Path, snapshot_id: str) -> tuple[int, int, int]:
    with sqlite3.connect(db) as conn:
        return conn.execute(
            "SELECT "
            "(SELECT COUNT(*) FROM order_confirmation_send_attempts "
            " WHERE document_snapshot_id = ?), "
            "(SELECT COUNT(*) FROM order_confirmation_fake_outbox_messages "
            " WHERE document_snapshot_id = ?), "
            "(SELECT COUNT(*) FROM order_confirmation_send_evidence "
            " WHERE document_snapshot_id = ?)",
            (snapshot_id, snapshot_id, snapshot_id),
        ).fetchone()


def _prepare_confirmation_snapshot(
    api: tuple[str, dict[str, str], Path],
) -> tuple[str, str, str]:
    base, _ids, _db = api
    order_id, order_version_id = _make_effective_offer_order(api)
    status, body, _h = _post(
        _confirmation_document_url(base, order_id),
        args={"created_by": "office-api-test"},
        expect={"current_effective_order_version_id": order_version_id},
    )
    assert status == 201
    return order_id, order_version_id, body["document_snapshot_id"]


def test_confirmation_outbound_send_status_and_payload(api) -> None:
    base, _ids, db = api
    order_id, order_version_id, snapshot_id = _prepare_confirmation_snapshot(api)
    status_before, before, _h = _get(_confirmation_send_status_url(base, order_id))
    assert status_before == 200
    assert before["state"] == "not_sent"
    assert before["real_delivery"] is False

    command_id = str(uuid.uuid4())
    status, sent, _h = _post(
        _confirmation_send_url(base, order_id),
        args={
            "document_snapshot_id": snapshot_id,
            "requested_by": "office-api-test",
        },
        expect={"current_effective_order_version_id": order_version_id},
        command_id=command_id,
    )
    assert status == 201
    assert sent["real_delivery"] is False
    assert sent["transport_kind"] == "fake_outbox"
    assert sent["outcome"] == "accepted_by_fake_outbox"

    replay_status, replay_body, _h = _post(
        _confirmation_send_url(base, order_id),
        args={
            "document_snapshot_id": snapshot_id,
            "requested_by": "office-api-test",
        },
        expect={"current_effective_order_version_id": order_version_id},
        command_id=command_id,
    )
    assert replay_status in (200, 201)
    assert replay_body["send_attempt_id"] == sent["send_attempt_id"]

    dup_status, dup_body, _h = _post(
        _confirmation_send_url(base, order_id),
        args={
            "document_snapshot_id": snapshot_id,
            "requested_by": "office-api-test",
        },
        expect={"current_effective_order_version_id": order_version_id},
        command_id=str(uuid.uuid4()),
    )
    assert (dup_status, dup_body["error"]) == (
        409,
        "confirmation_document_already_sent",
    )

    status_after, after, _h = _get(_confirmation_send_status_url(base, order_id))
    assert status_after == 200
    assert after["state"] == "sent"
    assert after["real_delivery"] is False
    assert "html_body" not in after

    inspect_status, inspect_body, _h = _get(
        _confirmation_fake_outbox_url(base, order_id)
    )
    assert inspect_status == 200
    assert inspect_body["test_transport"] is True
    assert inspect_body["real_delivery"] is False
    assert inspect_body["subject"].startswith("Auftragsbestätigung")
    assert "<" in inspect_body["html_body"]

    conn = sqlite3.connect(db)
    try:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM order_confirmation_send_attempts"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM order_confirmation_fake_outbox_messages"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM order_confirmation_send_evidence"
            ).fetchone()[0]
            == 1
        )
    finally:
        conn.close()


def test_paused_confirmation_send_returns_ready_reasons_and_writes_nothing(
    api,
) -> None:
    base, _ids, db = api
    order_id, order_version_id, snapshot_id = _prepare_confirmation_snapshot(api)
    _pause_order_via_api(base, order_id)
    command_id = str(uuid.uuid4())

    responses = []
    for _round in range(2):
        status, body, _headers = _post(
            _confirmation_send_url(base, order_id),
            args={
                "document_snapshot_id": snapshot_id,
                "requested_by": "office-api-test",
            },
            expect={"current_effective_order_version_id": order_version_id},
            command_id=command_id,
        )
        assert status == 422
        assert body == {
            "error": "order_not_ready_to_send",
            "reasons": ["operational_pause"],
        }
        responses.append(body)

    assert responses[0] == responses[1]
    assert _outbound_counts_for_snapshot(db, snapshot_id) == (0, 0, 0)
    with sqlite3.connect(db) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM office_api_commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()[0]
            == 0
        )


def test_paused_candidate_send_returns_all_ready_reasons_in_stable_order(api) -> None:
    base, _ids, db = api
    order_id, order_version_id, snapshot_id = _prepare_confirmation_snapshot(api)
    _pause_order_via_api(base, order_id)
    status, candidate, _headers = _post(
        f"{base}/office/v1/orders/{order_id}/versions",
        args={
            "event_date": "2026-10-03",
            "time_window_text": "abends",
            "location_text": "Hamburg",
            "guest_count_estimate": 40,
            "planning_mode": "caterer_suggestion",
        },
        expect={
            "latest_version_number": 1,
            "current_effective_order_version_id": order_version_id,
            "current_candidate_order_version_id": None,
        },
    )
    assert status == 201
    assert candidate["version_number"] == 2

    status, body, _headers = _post(
        _confirmation_send_url(base, order_id),
        args={
            "document_snapshot_id": snapshot_id,
            "requested_by": "office-api-test",
        },
        expect={"current_effective_order_version_id": order_version_id},
    )
    assert status == 422
    assert body == {
        "error": "order_not_ready_to_send",
        "reasons": ["operational_pause", "pending_order_version_change"],
    }
    assert _outbound_counts_for_snapshot(db, snapshot_id) == (0, 0, 0)


def test_confirmation_send_succeeds_after_pause_is_resumed(api) -> None:
    base, _ids, db = api
    order_id, order_version_id, snapshot_id = _prepare_confirmation_snapshot(api)
    pause = _pause_order_via_api(base, order_id)
    resumed = _resume_order_via_api(base, order_id, pause)
    assert resumed["active"] is False

    status, detail, _headers = _get(f"{base}/office/v1/orders/{order_id}")
    assert status == 200
    assert detail["ready_to_send"] == {"ready": True, "reasons": []}
    status, sent, _headers = _post(
        _confirmation_send_url(base, order_id),
        args={
            "document_snapshot_id": snapshot_id,
            "requested_by": "office-api-test",
        },
        expect={"current_effective_order_version_id": order_version_id},
    )
    assert status == 201
    assert sent["real_delivery"] is False
    assert _outbound_counts_for_snapshot(db, snapshot_id) == (1, 1, 1)


def test_confirmation_outbound_missing_recipient_returns_422(api) -> None:
    base, ids, db = api
    inquiry_id = ids["inquiry_offer_ready"]
    order_id, order_version_id = _make_effective_offer_order(
        api, inquiry_id=inquiry_id, ensure_recipient_email=False
    )
    _clear_inquiry_recipient_email(db, inquiry_id)
    status, body, _h = _post(
        _confirmation_document_url(base, order_id),
        args={"created_by": "office-api-test"},
        expect={"current_effective_order_version_id": order_version_id},
    )
    assert status == 201
    snapshot_id = body["document_snapshot_id"]
    send_status, send_body, _h = _post(
        _confirmation_send_url(base, order_id),
        args={
            "document_snapshot_id": snapshot_id,
            "requested_by": "office-api-test",
        },
        expect={"current_effective_order_version_id": order_version_id},
    )
    assert (send_status, send_body["error"]) == (
        422,
        "confirmation_document_recipient_missing",
    )


def test_confirmation_outbound_routes_require_bearer_auth(api) -> None:
    base, ids, _db = api
    order_id = ids["order_ready"]
    no_auth: dict[str, str] = {}
    for url in (
        _confirmation_send_status_url(base, order_id),
        _confirmation_fake_outbox_url(base, order_id),
    ):
        status, body, _h = _get(url, headers=no_auth)
        assert (status, body["error"]) == (401, "unauthorized")


# --- OFFER_DOCUMENT_SNAPSHOT_V1 — offer-document endpoint ---------------------


def _offer_document_url(base: str, offer_id: str) -> str:
    return f"{base}/office/v1/offers/{offer_id}/offer-document"


def _pickup_eligible_invoice_snapshot() -> InquiryCustomerSnapshot:
    return InquiryCustomerSnapshot(
        company_name="ACME GmbH",
        contact_name="Anna",
        email="anna@example.invalid",
        phone="+49301234567",
        invoice_address=CustomerAddress(
            street="Bürostraße 1",
            postal_code="20095",
            city="Hamburg",
            country="DE",
        ),
        delivery_address=None,
        delivery_address_mode="SAME_AS_INVOICE",
    )


def _prepared_offer_for_document(
    api: tuple[str, dict[str, str], Path],
    *,
    inquiry_id: str | None = None,
) -> tuple[str, str, str, str]:
    """Returns (base, offer_id, offer_version_id, offer_variant_id) for a
    freshly Prepared, PICKUP-eligible offer (invoice address only)."""
    base, ids, db = api
    resolved_inquiry = inquiry_id or ids["inquiry_offer_ready"]
    _set_inquiry_customer_snapshot(
        db, resolved_inquiry, _pickup_eligible_invoice_snapshot()
    )
    _ensure_inquiry_fulfillment_mode(base, resolved_inquiry, mode="PICKUP")
    snapshot = _valid_offer_snapshot(inquiry_id=resolved_inquiry)
    status, body, _h = _post(
        _prepare_offer_url(base, resolved_inquiry),
        args={"snapshot": snapshot},
    )
    assert status == 201
    variant_id = snapshot["variants"][0]["variant_id"]  # type: ignore[index]
    return base, body["offer_id"], body["offer_version_id"], variant_id


def test_offer_document_create_success(api) -> None:
    base, offer_id, offer_version_id, variant_id = _prepared_offer_for_document(api)
    status, body, _h = _post(
        _offer_document_url(base, offer_id),
        args={
            "offer_version_id": offer_version_id,
            "offer_variant_id": variant_id,
            "created_by": "office-api-test",
        },
    )
    assert status == 201
    assert body["offer_id"] == offer_id
    snapshot = body["snapshot"]
    assert snapshot["offer_version_id"] == offer_version_id
    assert snapshot["offer_variant_id"] == variant_id
    assert snapshot["fulfillment_mode"] == "PICKUP"
    assert snapshot["document_reference"].startswith("ANG-")
    assert snapshot["document_hash"].startswith("sha256:")


def test_offer_document_replay_is_idempotent(api) -> None:
    base, offer_id, offer_version_id, variant_id = _prepared_offer_for_document(api)
    args = {
        "offer_version_id": offer_version_id,
        "offer_variant_id": variant_id,
        "created_by": "office-api-test",
    }
    status1, body1, _h = _post(_offer_document_url(base, offer_id), args=args)
    assert status1 == 201
    status2, body2, _h = _post(_offer_document_url(base, offer_id), args=args)
    assert status2 == 200
    assert body2["offer_document_snapshot_id"] == body1["offer_document_snapshot_id"]
    assert body2["snapshot"]["document_hash"] == body1["snapshot"]["document_hash"]


def _two_variant_offer_snapshot(*, inquiry_id: str) -> dict[str, object]:
    payload = _valid_offer_snapshot(inquiry_id=inquiry_id)
    second_variant_id = "44444444-4444-4444-8444-444444444442"
    second_position_id = "88888888-8888-4888-8888-888888888882"
    second_variant = json.loads(json.dumps(payload["variants"][0]))
    second_variant["variant_id"] = second_variant_id
    second_variant["label"] = "Variante B"
    second_variant["positions"][0]["position_id"] = second_position_id
    payload["variants"].append(second_variant)  # type: ignore[union-attr]
    payload["snapshot_hash"] = compute_snapshot_hash(payload)
    return payload


def test_offer_document_variant_conflict(api) -> None:
    base, ids, db = api
    resolved_inquiry = ids["inquiry_offer_ready"]
    _set_inquiry_customer_snapshot(
        db, resolved_inquiry, _pickup_eligible_invoice_snapshot()
    )
    _ensure_inquiry_fulfillment_mode(base, resolved_inquiry, mode="PICKUP")
    snapshot = _two_variant_offer_snapshot(inquiry_id=resolved_inquiry)
    status, body, _h = _post(
        _prepare_offer_url(base, resolved_inquiry),
        args={"snapshot": snapshot},
    )
    assert status == 201
    offer_id = body["offer_id"]
    offer_version_id = body["offer_version_id"]
    variant_ids = [v["variant_id"] for v in snapshot["variants"]]  # type: ignore[index]
    assert len(variant_ids) >= 2, "test requires an offer with 2+ variants"

    first = _post(
        _offer_document_url(base, offer_id),
        args={
            "offer_version_id": offer_version_id,
            "offer_variant_id": variant_ids[0],
            "created_by": "office-api-test",
        },
    )
    assert first[0] == 201

    status2, body2, _h = _post(
        _offer_document_url(base, offer_id),
        args={
            "offer_version_id": offer_version_id,
            "offer_variant_id": variant_ids[1],
            "created_by": "office-api-test",
        },
    )
    assert (status2, body2["error"]) == (409, "offer_document_variant_conflict")


def test_offer_document_create_rejects_mismatched_offer_id(api) -> None:
    """REVIEW FIX: POSTing Offer B's path with Offer A's real version/variant
    must 404, never return (or leak) Offer A's document."""
    base, ids, _db = api
    _base_a, offer_a_id, version_a_id, variant_a_id = _prepared_offer_for_document(
        api, inquiry_id=ids["inquiry_offer_ready"]
    )
    # Offer B only needs to exist as a real, distinct Offer — it is never
    # itself made document-eligible. Its snapshot must use fresh
    # variant/position ids (_unique_offer_snapshot) so it doesn't collide
    # with Offer A's fixed-id fixture snapshot in the shared offer_variants
    # table.
    other_inquiry_id = ids["inquiry_convertible"]
    other_status, other_body, _h = _post(
        _prepare_offer_url(base, other_inquiry_id),
        args={"snapshot": _unique_offer_snapshot(inquiry_id=other_inquiry_id)},
    )
    assert other_status == 201
    offer_b_id = other_body["offer_id"]
    assert offer_b_id != offer_a_id

    # Establish the real snapshot for Offer A first (this is what a replay
    # under the wrong offer_id must not be able to reach).
    create_status, create_body, _h = _post(
        _offer_document_url(base, offer_a_id),
        args={
            "offer_version_id": version_a_id,
            "offer_variant_id": variant_a_id,
            "created_by": "office-api-test",
        },
    )
    assert create_status == 201

    status, body, _h = _post(
        _offer_document_url(base, offer_b_id),
        args={
            "offer_version_id": version_a_id,
            "offer_variant_id": variant_a_id,
            "created_by": "office-api-test",
        },
    )
    assert (status, body["error"]) == (404, "not_found")
    leaked_keys = {
        "document_reference",
        "document_hash",
        "recipient",
        "recipient_name",
        "recipient_company",
        "recipient_email",
        "recipient_phone",
        "invoice_address",
        "delivery_address",
        "positions",
        "vat_buckets",
        "net_total_cents",
        "vat_total_cents",
        "gross_total_cents",
        "snapshot",
        "offer_document_snapshot_id",
    }
    assert not leaked_keys & set(body)

    # Offer A's document is unaffected and reads back exactly as created.
    read_status, read_body, _h = _get(
        f"{_offer_document_url(base, offer_a_id)}?offer_version_id={version_a_id}"
    )
    assert read_status == 200
    assert (
        read_body["offer_document_snapshot_id"]
        == create_body["offer_document_snapshot_id"]
    )


def test_offer_document_eligibility_blocked_missing_invoice_address(api) -> None:
    base, ids, db = api
    resolved_inquiry = ids["inquiry_offer_ready"]
    # No invoice address set on the inquiry's customer_snapshot.
    _ensure_inquiry_fulfillment_mode(base, resolved_inquiry, mode="PICKUP")
    snapshot = _valid_offer_snapshot(inquiry_id=resolved_inquiry)
    status, body, _h = _post(
        _prepare_offer_url(base, resolved_inquiry),
        args={"snapshot": snapshot},
    )
    assert status == 201
    offer_id = body["offer_id"]
    offer_version_id = body["offer_version_id"]
    variant_id = snapshot["variants"][0]["variant_id"]  # type: ignore[index]

    status2, body2, _h = _post(
        _offer_document_url(base, offer_id),
        args={
            "offer_version_id": offer_version_id,
            "offer_variant_id": variant_id,
            "created_by": "office-api-test",
        },
    )
    assert (status2, body2["error"]) == (422, "offer_document_blocked")
    assert "INVOICE_ADDRESS_REQUIRED" in body2["reasons"]

    conn = sqlite3.connect(db)
    count = conn.execute(
        "SELECT COUNT(*) FROM offer_document_snapshots WHERE offer_id = ?",
        (offer_id,),
    ).fetchone()[0]
    conn.close()
    assert count == 0


def test_offer_document_read_after_create(api) -> None:
    base, offer_id, offer_version_id, variant_id = _prepared_offer_for_document(api)
    create_status, create_body, _h = _post(
        _offer_document_url(base, offer_id),
        args={
            "offer_version_id": offer_version_id,
            "offer_variant_id": variant_id,
            "created_by": "office-api-test",
        },
    )
    assert create_status == 201

    read_status, read_body, _h = _get(
        f"{_offer_document_url(base, offer_id)}?offer_version_id={offer_version_id}"
    )
    assert read_status == 200
    assert (
        read_body["offer_document_snapshot_id"]
        == create_body["offer_document_snapshot_id"]
    )
    assert (
        read_body["snapshot"]["document_hash"]
        == create_body["snapshot"]["document_hash"]
    )


def test_offer_document_read_not_found(api) -> None:
    base, ids, _db = api
    offer_id = str(uuid.uuid4())
    missing_version_id = str(uuid.uuid4())
    status, body, _h = _get(
        f"{_offer_document_url(base, offer_id)}?offer_version_id={missing_version_id}"
    )
    assert (status, body["error"]) == (404, "not_found")


def test_offer_document_routes_require_bearer_auth(api) -> None:
    base, ids, _db = api
    offer_id = str(uuid.uuid4())
    no_auth: dict[str, str] = {}
    status, body, _h = _get(
        f"{_offer_document_url(base, offer_id)}?offer_version_id={offer_id}",
        headers=no_auth,
    )
    assert (status, body["error"]) == (401, "unauthorized")
    status, body, _h = _post(
        _offer_document_url(base, offer_id),
        args={
            "offer_version_id": offer_id,
            "offer_variant_id": offer_id,
            "created_by": "office-api-test",
        },
        headers=no_auth,
    )
    assert (status, body["error"]) == (401, "unauthorized")


# --- OFFER_PDF_DOWNLOAD_V1 — offer-document/pdf endpoint -------------------------


def _offer_document_pdf_url(base: str, offer_id: str) -> str:
    return f"{base}/office/v1/offers/{offer_id}/offer-document/pdf"


def _prepared_offer_for_pdf(
    api: tuple[str, dict[str, str], Path],
    *,
    inquiry_id: str | None = None,
    contact_name: str = "Anna",
) -> tuple[str, str, str, str]:
    """Like _prepared_offer_for_document, but also creates the
    OfferDocumentSnapshot (JSON create) so the PDF endpoint has something
    real to read. Returns (base, offer_id, offer_version_id, offer_document_snapshot_id)."""
    base, ids, db = api
    resolved_inquiry = inquiry_id or ids["inquiry_offer_ready"]
    _set_inquiry_customer_snapshot(
        db,
        resolved_inquiry,
        replace(_pickup_eligible_invoice_snapshot(), contact_name=contact_name),
    )
    _ensure_inquiry_fulfillment_mode(base, resolved_inquiry, mode="PICKUP")
    snapshot = _valid_offer_snapshot(inquiry_id=resolved_inquiry)
    status, body, _h = _post(
        _prepare_offer_url(base, resolved_inquiry),
        args={"snapshot": snapshot},
    )
    assert status == 201
    offer_id = body["offer_id"]
    offer_version_id = body["offer_version_id"]
    variant_id = snapshot["variants"][0]["variant_id"]  # type: ignore[index]

    create_status, create_body, _h = _post(
        _offer_document_url(base, offer_id),
        args={
            "offer_version_id": offer_version_id,
            "offer_variant_id": variant_id,
            "created_by": "office-api-test",
        },
    )
    assert create_status == 201
    return base, offer_id, offer_version_id, create_body["offer_document_snapshot_id"]


def test_offer_document_pdf_download_returns_valid_pdf(api) -> None:
    base, offer_id, offer_version_id, _snapshot_id = _prepared_offer_for_pdf(api)
    status, data, headers = _get_raw(
        f"{_offer_document_pdf_url(base, offer_id)}?offer_version_id={offer_version_id}"
    )
    assert status == 200
    assert data[:5] == b"%PDF-"
    assert headers.get("Content-Type") == "application/pdf"


def test_offer_document_pdf_content_disposition_filename(api) -> None:
    base, offer_id, offer_version_id, _snapshot_id = _prepared_offer_for_pdf(api)
    # read back the frozen document_reference the filename must be derived from
    read_status, read_body, _h = _get(
        f"{_offer_document_url(base, offer_id)}?offer_version_id={offer_version_id}"
    )
    assert read_status == 200
    document_reference = read_body["snapshot"]["document_reference"]

    _status, _data, headers = _get_raw(
        f"{_offer_document_pdf_url(base, offer_id)}?offer_version_id={offer_version_id}"
    )
    assert headers.get("Content-Disposition") == (
        f'attachment; filename="{document_reference}.pdf"'
    )


def test_offer_document_pdf_repeated_download_is_byte_identical(api) -> None:
    base, offer_id, offer_version_id, _snapshot_id = _prepared_offer_for_pdf(api)
    url = (
        f"{_offer_document_pdf_url(base, offer_id)}?offer_version_id={offer_version_id}"
    )
    status1, data1, _h1 = _get_raw(url)
    status2, data2, _h2 = _get_raw(url)
    assert status1 == status2 == 200
    assert data1 == data2
    assert hashlib.sha256(data1).hexdigest() == hashlib.sha256(data2).hexdigest()


def test_offer_document_pdf_missing_snapshot_returns_404(api) -> None:
    base, ids, _db = api
    offer_id = ids["inquiry_offer_ready"]
    missing_version_id = str(uuid.uuid4())
    status, data, _h = _get_raw(
        f"{_offer_document_pdf_url(base, offer_id)}?offer_version_id={missing_version_id}"
    )
    assert status == 404
    assert json.loads(data) == {"error": "not_found"}


def test_offer_document_pdf_cross_offer_access_returns_404_without_leak(api) -> None:
    base, ids, db = api
    base_a, offer_a_id, version_a_id, _snap_a = _prepared_offer_for_pdf(
        api, inquiry_id=ids["inquiry_offer_ready"]
    )
    other_inquiry_id = ids["inquiry_convertible"]
    other_status, other_body, _h = _post(
        _prepare_offer_url(base, other_inquiry_id),
        args={"snapshot": _unique_offer_snapshot(inquiry_id=other_inquiry_id)},
    )
    assert other_status == 201
    offer_b_id = other_body["offer_id"]
    assert offer_b_id != offer_a_id

    status, data, _h = _get_raw(
        f"{_offer_document_pdf_url(base, offer_b_id)}?offer_version_id={version_a_id}"
    )
    assert status == 404
    assert json.loads(data) == {"error": "not_found"}
    assert b"%PDF-" not in data


def test_offer_document_pdf_routes_require_bearer_auth(api) -> None:
    base, offer_id, offer_version_id, _snapshot_id = _prepared_offer_for_pdf(api)
    no_auth: dict[str, str] = {}
    status, data, _h = _get_raw(
        f"{_offer_document_pdf_url(base, offer_id)}?offer_version_id={offer_version_id}",
        headers=no_auth,
    )
    assert status == 401
    assert json.loads(data) == {"error": "unauthorized"}
    assert b"%PDF-" not in data


def test_offer_document_pdf_unsupported_character_returns_422(api) -> None:
    base, offer_id, offer_version_id, _snapshot_id = _prepared_offer_for_pdf(
        api, contact_name="Анна Иванова"
    )
    status, data, _h = _get_raw(
        f"{_offer_document_pdf_url(base, offer_id)}?offer_version_id={offer_version_id}"
    )
    assert status == 422
    assert json.loads(data) == {"error": "offer_pdf_unsupported_character"}
    assert b"%PDF-" not in data


def test_offer_document_pdf_download_does_not_create_new_snapshot(api) -> None:
    base, offer_id, offer_version_id, _snapshot_id = _prepared_offer_for_pdf(api)
    _base, _db_ids, db = api
    conn = sqlite3.connect(db)
    before = conn.execute(
        "SELECT COUNT(*) FROM offer_document_snapshots WHERE offer_id = ?",
        (offer_id,),
    ).fetchone()[0]
    conn.close()
    assert before == 1

    for _ in range(3):
        status, _data, _h = _get_raw(
            f"{_offer_document_pdf_url(base, offer_id)}?offer_version_id={offer_version_id}"
        )
        assert status == 200

    conn = sqlite3.connect(db)
    after = conn.execute(
        "SELECT COUNT(*) FROM offer_document_snapshots WHERE offer_id = ?",
        (offer_id,),
    ).fetchone()[0]
    conn.close()
    assert after == 1


def test_offer_document_pdf_static_content_overflow_returns_422(api) -> None:
    """Configured footer text too long for the reserved footer area is an
    operator-fixable static-content validation failure (422), never a 500
    and never a clipped PDF."""
    from dataclasses import replace as dataclass_replace

    base, offer_id, offer_version_id, _snapshot_id = _prepared_offer_for_pdf(api)
    _base, _ids, db = api

    oversized = dataclass_replace(
        fake_offer_pdf_static_content(),
        footer_note="Sehr langer Footertext. " * 40,
    )
    ready: queue.Queue = queue.Queue()

    def run() -> None:
        from catering_system.ui.office_api import create_office_api_server

        server = create_office_api_server(
            str(db), _TOKEN, "127.0.0.1", 0, offer_pdf_static_content=oversized
        )
        ready.put(server)
        server.serve_forever()

    threading.Thread(target=run, daemon=True).start()
    server = ready.get(timeout=5)
    host, port = server.server_address[:2]
    try:
        status, data, _h = _get_raw(
            f"http://{host}:{port}/office/v1/offers/{offer_id}"
            f"/offer-document/pdf?offer_version_id={offer_version_id}"
        )
        assert status == 422
        assert json.loads(data) == {"error": "offer_pdf_render_failed"}
        assert b"%PDF-" not in data
    finally:
        server.shutdown()
        server.server_close()


# --- issue #39: structured error contracts, client against the real API ------
#
# These are contract tests, not schema tests: they drive the actual Office API
# server through RemoteCoreClient and assert that a reasons-bearing 422 keeps
# its real business code. The JSON is never hand-written here — it is whatever
# the endpoint really produces, which is exactly what the unit-level tests in
# test_remote_core_client.py cannot prove on their own.


def _remote_client(base: str) -> RemoteCoreClient:
    client = RemoteCoreClient(base, _TOKEN)
    client.begin_request({})
    return client


def test_remote_client_preserves_offer_document_blocked_with_reasons(api) -> None:
    """Real producer: POST /offers/{id}/offer-document with no invoice
    address returns 422 offer_document_blocked + reasons."""
    base, ids, _db = api
    resolved_inquiry = ids["inquiry_offer_ready"]
    _ensure_inquiry_fulfillment_mode(base, resolved_inquiry, mode="PICKUP")
    snapshot = _valid_offer_snapshot(inquiry_id=resolved_inquiry)
    status, body, _h = _post(
        _prepare_offer_url(base, resolved_inquiry), args={"snapshot": snapshot}
    )
    assert status == 201
    offer_id = body["offer_id"]

    # the raw endpoint really does emit reasons
    raw_status, raw_body, _h = _post(
        _offer_document_url(base, offer_id),
        args={
            "offer_version_id": body["offer_version_id"],
            "offer_variant_id": snapshot["variants"][0]["variant_id"],  # type: ignore[index]
            "created_by": "office-api-test",
        },
    )
    assert raw_status == 422
    assert raw_body["error"] == "offer_document_blocked"
    assert raw_body["reasons"]

    # and the client surfaces it as the business error, not 502
    client = _remote_client(base)
    with pytest.raises(RemoteCoreError) as exc:
        client.command(
            f"/office/v1/offers/{offer_id}/offer-document",
            {
                "offer_version_id": body["offer_version_id"],
                "offer_variant_id": snapshot["variants"][0]["variant_id"],  # type: ignore[index]
                "created_by": "office-api-test",
            },
            {},
            expected={201},
            result_keys={"offer_document_snapshot_id"},
        )
    assert (exc.value.status, exc.value.code) == (422, "offer_document_blocked")
    assert not exc.value.unavailable


def test_remote_client_preserves_confirmation_document_blocked_with_reasons(
    api,
) -> None:
    """Real producer: confirmation document creation with no customer contact
    returns 422 confirmation_document_blocked + reasons."""
    base, ids, db = api
    inquiry_id = ids["inquiry_offer_ready"]
    order_id, order_version_id = _make_effective_offer_order(
        api, inquiry_id=inquiry_id, ensure_recipient_email=False
    )
    _clear_inquiry_recipient_email(db, inquiry_id)
    inquiries = SQLiteInquiryRepository(db)
    inquiry = inquiries.get_by_id(inquiry_id)
    assert inquiry is not None
    contact = inquiry.customer_snapshot
    inquiries.update(
        replace(
            inquiry,
            customer_snapshot=InquiryCustomerSnapshot(
                company_name=contact.company_name if contact else None,
                contact_name=contact.contact_name if contact else None,
                phone=None,
                email=None,
            ),
        )
    )
    inquiries.close()

    raw_status, raw_body, _h = _post(
        _confirmation_document_url(base, order_id),
        args={"created_by": "office-api-test"},
        expect={"current_effective_order_version_id": order_version_id},
    )
    assert raw_status == 422
    assert raw_body["error"] == "confirmation_document_blocked"
    assert raw_body.get("reasons")

    client = _remote_client(base)
    with pytest.raises(RemoteCoreError) as exc:
        client.command(
            f"/office/v1/orders/{order_id}/confirmation-document",
            {"created_by": "office-api-test"},
            {"current_effective_order_version_id": order_version_id},
            expected={201},
            result_keys={"document_snapshot_id"},
        )
    assert (exc.value.status, exc.value.code) == (
        422,
        "confirmation_document_blocked",
    )
    assert not exc.value.unavailable


def test_remote_client_preserves_order_not_ready_to_send_with_reasons(api) -> None:
    """Real producer: confirmation send while the order is paused returns
    422 order_not_ready_to_send + reasons."""
    base, _ids, _db = api
    order_id, order_version_id, snapshot_id = _prepare_confirmation_snapshot(api)
    _pause_order_via_api(base, order_id)

    raw_status, raw_body, _h = _post(
        _confirmation_send_url(base, order_id),
        args={"document_snapshot_id": snapshot_id, "requested_by": "office-api-test"},
        expect={"current_effective_order_version_id": order_version_id},
    )
    assert raw_status == 422
    assert raw_body == {
        "error": "order_not_ready_to_send",
        "reasons": ["operational_pause"],
    }

    client = _remote_client(base)
    with pytest.raises(RemoteCoreError) as exc:
        client.command(
            f"/office/v1/orders/{order_id}/confirmation-document/send",
            {
                "document_snapshot_id": snapshot_id,
                "requested_by": "office-api-test",
            },
            {"current_effective_order_version_id": order_version_id},
            expected={200},
            result_keys={"send_attempt_id"},
        )
    assert (exc.value.status, exc.value.code) == (422, "order_not_ready_to_send")
    assert not exc.value.unavailable
