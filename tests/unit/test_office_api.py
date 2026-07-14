"""Core Office API contract tests (PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1
§4, §6, §9) over a live local HTTP server."""

from __future__ import annotations

import json
import queue
import sqlite3
import threading
import urllib.error
import urllib.request
import uuid
from datetime import date
from pathlib import Path

import pytest

from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_order_repository import (
    SQLiteOrderRepository,
)
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService

_TOKEN = "test-office-api-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


def _seed(db_path: Path) -> dict[str, str]:
    """Fixture world: verify-pending, convertible, printed/effective,
    cancelled, and website_form inquiries."""
    inquiries = SQLiteInquiryRepository(db_path)
    orders = SQLiteOrderRepository(db_path)
    inquiry_service = InquiryService(inquiries)
    order_service = OrderService(orders)
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
    order_printed, v1 = order_service.convert_inquiry_to_order(printed_src)
    core.confirm_kitchen_print(order_printed.order_id, v1.order_version_id)
    core.make_order_version_effective(order_printed.order_id, v1.order_version_id)
    ids["inquiry_printed"] = printed_src.inquiry_id
    ids["order_ready"] = order_printed.order_id
    ids["version_ready"] = v1.order_version_id

    unprinted_src = make_inquiry(location_text="Lübeck")
    order_unprinted, v1u = order_service.convert_inquiry_to_order(unprinted_src)
    ids["order_unprinted"] = order_unprinted.order_id
    ids["version_unprinted"] = v1u.order_version_id
    ids["inquiry_unprinted"] = unprinted_src.inquiry_id

    cancelled_src = make_inquiry(location_text="Flensburg")
    order_cancelled, v1c = order_service.convert_inquiry_to_order(cancelled_src)
    core.cancel_order(order_cancelled.order_id)
    ids["order_cancelled"] = order_cancelled.order_id
    ids["version_cancelled"] = v1c.order_version_id
    ids["inquiry_cancelled_order"] = cancelled_src.inquiry_id

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


@pytest.fixture()
def api(tmp_path: Path):
    db = tmp_path / "core.db"
    ids = _seed(db)
    ready: queue.Queue = queue.Queue()

    def run() -> None:
        from catering_system.ui.office_api import create_office_api_server

        server = create_office_api_server(str(db), _TOKEN, "127.0.0.1", 0)
        ready.put(server)
        server.serve_forever()

    threading.Thread(target=run, daemon=True).start()
    server = ready.get(timeout=5)
    host, port = server.server_address[:2]
    yield f"http://{host}:{port}", ids, db
    server.shutdown()
    server.server_close()


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


_CREATE_ARGS = {
    "event_date": "2026-11-11",
    "inquiry_source": "manual",
    "time_window_text": "abends",
    "location_text": "Rostock",
    "guest_count_estimate": 40,
    "planning_mode": "caterer_suggestion",
    "call_verification_required": False,
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
    assert set(body) == {"attention", "week", "neue_anfragen_top", "auftraege_top"}
    # seed world: 3 open inquiries plus 1 rejected inquiry without an order;
    # 1 order without print;
    # 2 not effective (unprinted + none), 2 blocked, 1 cancelled
    assert body["attention"] == {
        "neue_anfragen": 3,
        "druck_fehlt": 1,
        "nicht_wirksam": 1,
        "versand_blockiert": 1,
        "storniert": 1,
    }
    top_actions = {
        row["inquiry_id"]: row["next_action"] for row in body["neue_anfragen_top"]
    }
    assert top_actions[ids["inquiry_verify"]] == "verify"
    assert top_actions[ids["inquiry_convertible"]] == "convert"
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


def test_inquiry_list_rows_and_search(api) -> None:
    base, ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/inquiries")
    assert status == 200
    assert set(body) == {"inquiries", "total_count", "limit", "offset"}
    assert body["total_count"] == 7
    by_id = {row["inquiry_id"]: row for row in body["inquiries"]}
    row = by_id[ids["inquiry_printed"]]
    assert row["linked_order_id"] == ids["order_ready"]
    assert row["orders_total_count"] == 1
    cancelled_row = by_id[ids["inquiry_cancelled_order"]]
    assert cancelled_row["linked_order_id"] is None  # only ACTIVE orders link
    assert cancelled_row["orders_total_count"] == 1

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
    assert body["total_count"] == 7
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
    assert body["orders"] == [{"order_id": ids["order_ready"], "cancelled_at": None}]
    assert body["orders_truncated"] is False
    assert body["customer_linkage"] == {}
    prefill = body["offer_prefill"]
    assert prefill["schema_version"] == "core_inquiry_offer_prefill_v1"
    assert prefill["inquiry_id"] == ids["inquiry_printed"]
    status, _body, _h = _get(f"{base}/office/v1/inquiries/{uuid.uuid4()}")
    assert status == 404


def test_order_detail_and_print_data(api) -> None:
    base, ids, _db = api
    status, body, _h = _get(f"{base}/office/v1/orders/{ids['order_ready']}")
    assert status == 200
    assert body["ready_to_send"] == {"ready": True, "reasons": []}
    assert [v["version_number"] for v in body["versions"]] == [1]
    assert body["versions_truncated"] is False

    status, body, _h = _get(
        f"{base}/office/v1/orders/{ids['order_ready']}/print-data"
        f"?version={ids['version_ready']}"
    )
    assert status == 200
    assert set(body) == {"order", "version"}

    # unknown and unowned are the same 404 (no distinction leaked)
    status, _b, _h = _get(
        f"{base}/office/v1/orders/{ids['order_ready']}/print-data"
        f"?version={ids['version_unprinted']}"
    )
    assert status == 404
    status, body, _h = _get(f"{base}/office/v1/orders/{ids['order_ready']}/print-data")
    assert (status, body["error"]) == (400, "invalid_request")


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


def test_verify_then_convert_flow_with_gates(api) -> None:
    base, ids, _db = api
    inquiry_id = ids["inquiry_verify"]
    # convert before verification: B5 gate
    status, body, _h = _post(f"{base}/office/v1/inquiries/{inquiry_id}/convert")
    assert (status, body["error"]) == (422, "verification_gate_blocked")
    status, body, _h = _post(f"{base}/office/v1/inquiries/{inquiry_id}/verify")
    assert status == 200
    # repeated verify stays success (current behavior)
    status, _body, _h = _post(f"{base}/office/v1/inquiries/{inquiry_id}/verify")
    assert status == 200
    status, body, _h = _post(f"{base}/office/v1/inquiries/{inquiry_id}/convert")
    assert status == 201
    assert set(body) == {"command_id", "order_id", "order_version_id"}
    status, detail, _h = _get(f"{base}/office/v1/inquiries/{inquiry_id}")
    assert status == 200
    assert detail["crm_stage"] == "Bestätigt / Auftrag"
    assert detail["allows_conversion"] is False
    # second convert while active: 409
    status, body, _h = _post(f"{base}/office/v1/inquiries/{inquiry_id}/convert")
    assert (status, body["error"]) == (409, "already_converted")


def test_rejected_inquiry_cannot_convert(api) -> None:
    base, ids, _db = api
    status, body, _h = _post(
        f"{base}/office/v1/inquiries/{ids['inquiry_rejected']}/convert"
    )
    assert (status, body["error"]) == (422, "inquiry_rejected")


def test_reconvert_after_storno_via_api(api) -> None:
    base, ids, _db = api
    inquiry_id = ids["inquiry_cancelled_order"]  # its only order is cancelled
    status, body, _h = _post(f"{base}/office/v1/inquiries/{inquiry_id}/convert")
    assert status == 201


def test_versions_expect_and_cancelled_gate(api) -> None:
    base, ids, _db = api
    args = {
        "event_date": "2026-10-03",
        "time_window_text": "früh",
        "location_text": "Bremen",
        "guest_count_estimate": None,
        "planning_mode": "caterer_suggestion",
    }
    url = f"{base}/office/v1/orders/{ids['order_ready']}/versions"
    status, body, _h = _post(url, args=args, expect={"latest_version_number": 7})
    assert (status, body["error"]) == (409, "stale_state")
    status, body, _h = _post(url, args=args, expect={"latest_version_number": 1})
    assert status == 201
    assert set(body) == {"command_id", "order_version_id", "version_number"}
    assert body["version_number"] == 2

    status, body, _h = _post(
        f"{base}/office/v1/orders/{ids['order_cancelled']}/versions",
        args=args,
        expect={"latest_version_number": 1},
    )
    assert (status, body["error"]) == (422, "order_cancelled")


def test_print_confirm_effective_and_gates(api) -> None:
    base, ids, _db = api
    order_id = ids["order_unprinted"]
    version_id = ids["version_unprinted"]
    # effective before print: existing gate
    status, body, _h = _post(
        f"{base}/office/v1/orders/{order_id}/effective",
        args={"order_version_id": version_id},
        expect={"current_effective_order_version_id": None},
    )
    assert (status, body["error"]) == (422, "kitchen_print_not_confirmed")
    # foreign version
    status, body, _h = _post(
        f"{base}/office/v1/orders/{order_id}/print-confirm",
        args={"order_version_id": ids["version_ready"]},
    )
    assert (status, body["error"]) == (422, "version_not_owned")
    # happy print-confirm; repeat is success (idempotent service)
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
            "kitchen_print_confirmed_at",
        }
    # effective with stale pointer expectation
    status, body, _h = _post(
        f"{base}/office/v1/orders/{order_id}/effective",
        args={"order_version_id": version_id},
        expect={"current_effective_order_version_id": version_id},
    )
    assert (status, body["error"]) == (409, "stale_state")
    status, body, _h = _post(
        f"{base}/office/v1/orders/{order_id}/effective",
        args={"order_version_id": version_id},
        expect={"current_effective_order_version_id": None},
    )
    assert status == 200
    assert body["effective_order_version_id"] == version_id
    # print-confirm on a cancelled order: API-level gate
    status, body, _h = _post(
        f"{base}/office/v1/orders/{ids['order_cancelled']}/print-confirm",
        args={"order_version_id": ids["version_cancelled"]},
    )
    assert (status, body["error"]) == (422, "order_cancelled")


def test_ready_unknown_order_is_200_with_reason(api) -> None:
    base, _ids, _db = api
    status, body, _h = _post(f"{base}/office/v1/orders/{uuid.uuid4()}/ready")
    assert status == 200
    assert body["evaluation"]["ready"] is False
    assert body["evaluation"]["reasons"] == ["ready_to_send_order_not_found"]


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
    url = f"{base}/office/v1/inquiries/{ids['inquiry_convertible']}/convert"
    status1, body1, _h = _post(url, command_id=command_id)
    assert status1 == 201
    status2, body2, _h = _post(url, command_id=command_id)
    assert (status2, body2) == (status1, body1)  # verbatim replay
    # only one active order exists
    _s, detail, _h = _get(f"{base}/office/v1/inquiries/{ids['inquiry_convertible']}")
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
    url = f"{base}/office/v1/inquiries/{ids['inquiry_convertible']}/convert"

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
    assert status == 201  # retry with the same command_id succeeds exactly once
    _s, detail, _h = _get(f"{base}/office/v1/inquiries/{ids['inquiry_convertible']}")
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
