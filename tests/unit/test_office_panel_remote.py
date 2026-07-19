"""Office panel Phase 2 dual mode (PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1 §7):
RemoteCoreClient wired behind the real, unmodified panel rendering code,
against a real Core Office API server. Covers: read-parity with direct mode
(§3.10/§9 "dashboard parity"), full write flows through the frozen command
envelope, form-embedded idempotent retry, degradation on an unreachable API,
never opening core.db in remote mode, and half-config startup rejection.
"""

from __future__ import annotations

import base64
import json
import os
import queue
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date
from http.server import HTTPServer
from pathlib import Path

import pytest

from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_offer_repository import (
    SQLiteOfferRepository,
)
from catering_system.repositories.sqlite_catalog_repository import (
    SQLiteCatalogRepository,
)
from catering_system.domain.catalog import CatalogDish
from datetime import UTC, datetime
from catering_system.repositories.sqlite_order_repository import (
    SQLiteOrderRepository,
)
from catering_system.domain.offer_snapshot import compute_snapshot_hash
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService
from catering_system.ui.office_api import create_office_api_server
from catering_system.ui.office_panel_http import (
    create_office_panel_server,
    csrf_token_for_password,
)
from catering_system.ui.remote_core_client import RemoteCoreClient

_PASSWORD = "test-pw"
_AUTH = "Basic " + base64.b64encode(f"office:{_PASSWORD}".encode()).decode()
_CSRF_TOKEN = csrf_token_for_password(_PASSWORD)
_API_TOKEN = "test-remote-api-token"
_API_AUTH = {"Authorization": f"Bearer {_API_TOKEN}"}
_SNAPSHOT_ID = "77777777-7777-4777-8777-777777777771"

_HIDDEN_REMOTE_FIELD = re.compile(
    r'<input type="hidden" name="_(?:command_id|expect_[a-zA-Z_]+)" value="[^"]*">'
)


def _strip_remote_fields(html: str) -> str:
    return _HIDDEN_REMOTE_FIELD.sub("", html)


def _seed(db_path: Path) -> dict[str, str]:
    """Same fixture world as test_office_api.py's _seed: verify-pending,
    convertible, printed/effective, cancelled, and website_form inquiries —
    rich enough to exercise attention counts, search, next-action, and
    print-data on both a direct-mode and a remote-mode panel."""
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
    ids["order_ready"] = order_printed.order_id
    ids["version_ready"] = v1.order_version_id

    unprinted_src = make_inquiry(location_text="Lübeck")
    order_unprinted, v1u = order_service.convert_inquiry_to_order(unprinted_src)
    ids["order_unprinted"] = order_unprinted.order_id
    ids["version_unprinted"] = v1u.order_version_id

    cancelled_src = make_inquiry(location_text="Flensburg")
    order_cancelled, _v1c = order_service.convert_inquiry_to_order(cancelled_src)
    core.cancel_order(order_cancelled.order_id)
    ids["order_cancelled"] = order_cancelled.order_id
    ids["inquiry_cancelled_order"] = cancelled_src.inquiry_id

    website = make_inquiry(
        inquiry_source="website_form",
        intake_external_ref="web-ref-001",
        intake_subject="Sommerfest",
    )
    ids["inquiry_website"] = website.inquiry_id

    catalog = SQLiteCatalogRepository(db_path)
    catalog_dish_id = "11111111-1111-4111-8111-111111111111"
    catalog.insert_dish_if_absent(
        CatalogDish(
            dish_id=catalog_dish_id,
            name="Kartoffelsalat",
            description="Hausgemacht",
            composition="Kartoffeln",
            notes=None,
            current_unit_net_cents=320,
            allergens=("G", "J"),
            active=True,
            created_at=datetime(2026, 7, 16, 8, 0, tzinfo=UTC),
            updated_at=datetime(2026, 7, 16, 8, 0, tzinfo=UTC),
        )
    )
    catalog.close()
    ids["catalog_dish_id"] = catalog_dish_id

    inquiries.close()
    orders.close()
    return ids


def _run_server_in_thread(build_server) -> tuple[str, HTTPServer]:
    """Builds and serves an HTTPServer on the SAME thread throughout — a
    sqlite3 connection is thread-affine (WORKLOG Entry 048), so a repo/
    RemoteCoreClient wired to one must be constructed on the very thread
    that will later call serve_forever(), not handed in from the caller's
    thread. Mirrors test_office_api.py's `api` fixture."""
    ready: queue.Queue = queue.Queue()

    def run() -> None:
        server = build_server()
        ready.put(server)
        server.serve_forever()

    threading.Thread(target=run, daemon=True).start()
    server = ready.get(timeout=5)
    host, port = server.server_address[:2]
    return f"http://{host}:{port}", server


def _start_api_server(db: Path) -> tuple[str, HTTPServer]:
    return _run_server_in_thread(
        lambda: create_office_api_server(str(db), _API_TOKEN, "127.0.0.1", 0)
    )


def _start_direct_panel(
    db: Path, *, ui_version: str = "legacy"
) -> tuple[str, HTTPServer]:
    return _run_server_in_thread(
        lambda: create_office_panel_server(
            SQLiteInquiryRepository(db),
            SQLiteOrderRepository(db),
            _PASSWORD,
            host="127.0.0.1",
            port=0,
            offer_repo=SQLiteOfferRepository(db),
            catalog_repo=SQLiteCatalogRepository(db),
            ui_version=ui_version,
        )
    )


def _start_remote_panel(
    remote: RemoteCoreClient, *, ui_version: str = "legacy"
) -> tuple[str, HTTPServer]:
    """`remote` is constructed by the caller (no sqlite inside it, so no
    thread-affinity concern), but the panel/server objects that reference it
    are still built here on the serving thread, matching the same pattern."""
    return _run_server_in_thread(
        lambda: create_office_panel_server(
            remote,
            remote,
            _PASSWORD,
            host="127.0.0.1",
            port=0,
            remote=remote,
            ui_version=ui_version,
        )
    )


def _get(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url)
    req.add_header("Authorization", _AUTH)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _extract_hidden(html: str, name: str) -> str:
    match = re.search(rf'name="{re.escape(name)}" value="([^"]*)"', html)
    assert match, f"missing hidden field {name!r} in:\n{html}"
    return match.group(1)


def _post_form(url: str, fields: dict[str, str]) -> tuple[int, str]:
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", _AUTH)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


_VARIANT_ID = "44444444-4444-4444-8444-444444444441"
_POSITION_ID = "88888888-8888-4888-8888-888888888881"


def _api_get(url: str) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers=_API_AUTH, method="GET")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def _api_post(
    url: str,
    *,
    args: dict | None = None,
    expect: dict | None = None,
    command_id: str | None = None,
) -> tuple[int, dict]:
    body = json.dumps(
        {
            "command_id": command_id or str(uuid.uuid4()),
            "expect": expect or {},
            "args": args or {},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={**_API_AUTH, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


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


def _post_panel_convert(
    panel_url: str, inquiry_id: str, *, remote: bool
) -> tuple[int, str]:
    _status, detail_html = _get(f"{panel_url}/inquiry/{inquiry_id}")
    fields = {"_csrf_token": _CSRF_TOKEN}
    if remote:
        convert_form = re.search(
            r'(<form[^>]*action="/inquiry/[^"]*/convert"[^>]*>.*?</form>)',
            detail_html,
            re.DOTALL,
        )
        if convert_form is not None:
            fields["_command_id"] = _extract_hidden(
                convert_form.group(0), "_command_id"
            )
        else:
            fields["_command_id"] = str(uuid.uuid4())
    return _post_form(f"{panel_url}/inquiry/{inquiry_id}/convert", fields)


def _active_orders_for_inquiry(db: Path, inquiry_id: str) -> int:
    orders = SQLiteOrderRepository(db)
    try:
        return len(
            [
                order
                for order in orders.list_orders()
                if order.source_inquiry_id == inquiry_id and order.cancelled_at is None
            ]
        )
    finally:
        orders.close()


def test_legacy_convert_offer_gate_parity_direct_vs_remote(tmp_path: Path) -> None:
    """Direct panel work() and remote panel → Core API must both refuse legacy
    convert while a Prepared Offer blocks the inquiry path."""
    db = tmp_path / "offer-gate.db"
    ids = _seed(db)
    inquiry_id = ids["inquiry_cancelled_order"]

    api_url, api_server = _start_api_server(db)
    try:
        status, _body = _api_post(
            f"{api_url}/office/v1/inquiries/{inquiry_id}/prepare-offer",
            args={"snapshot": _valid_offer_snapshot(inquiry_id=inquiry_id)},
        )
        assert status == 201

        direct_url, direct_server = _start_direct_panel(db)
        remote = RemoteCoreClient(api_url, _API_TOKEN)
        remote_url, remote_server = _start_remote_panel(remote)
        try:
            direct_status, direct_body = _post_panel_convert(
                direct_url, inquiry_id, remote=False
            )
            remote_status, remote_body = _post_panel_convert(
                remote_url, inquiry_id, remote=True
            )

            assert direct_status == 400
            assert "Angebotsprozess blockiert" in direct_body
            assert remote_status == 422
            assert "Angebotsprozess blockiert" in remote_body
            assert _active_orders_for_inquiry(db, inquiry_id) == 0
        finally:
            for server in (direct_server, remote_server):
                server.shutdown()
                server.server_close()
    finally:
        api_server.shutdown()
        api_server.server_close()


# --- read parity: same seeded core.db, direct-mode HTML vs remote-mode HTML -


@pytest.fixture()
def parity_world(tmp_path: Path):
    db = tmp_path / "core.db"
    ids = _seed(db)

    direct_url, direct_server = _start_direct_panel(db)

    api_url, api_server = _start_api_server(db)
    remote = RemoteCoreClient(api_url, _API_TOKEN)
    remote_url, remote_server = _start_remote_panel(remote)

    yield direct_url, remote_url, ids

    for server in (direct_server, remote_server, api_server):
        server.shutdown()
        server.server_close()


def _assert_same_modulo_remote_fields(direct_html: str, remote_html: str) -> None:
    assert direct_html == _strip_remote_fields(remote_html)


def test_dashboard_parity_direct_vs_remote(parity_world) -> None:
    direct_url, remote_url, _ids = parity_world
    d_status, d_html = _get(f"{direct_url}/")
    r_status, r_html = _get(f"{remote_url}/")
    assert d_status == r_status == 200
    _assert_same_modulo_remote_fields(d_html, r_html)
    # sanity: the remote page really does carry the extra hidden fields, so
    # the stripped-equality check above isn't vacuously comparing two empty
    # diffs
    assert "_command_id" in r_html
    assert "_command_id" not in d_html


def test_v2_dashboard_parity_direct_vs_remote(tmp_path: Path) -> None:
    db = tmp_path / "core-v2.db"
    _seed(db)
    direct_url, direct_server = _start_direct_panel(db, ui_version="v2")
    api_url, api_server = _start_api_server(db)
    remote = RemoteCoreClient(api_url, _API_TOKEN)
    remote_url, remote_server = _start_remote_panel(remote, ui_version="v2")
    try:
        d_status, d_html = _get(f"{direct_url}/")
        r_status, r_html = _get(f"{remote_url}/")
        assert d_status == r_status == 200
        _assert_same_modulo_remote_fields(d_html, r_html)
        assert '<div class="wc-page">' in d_html
        assert "_command_id" not in d_html
        assert "_command_id" not in r_html
    finally:
        for server in (direct_server, remote_server, api_server):
            server.shutdown()
            server.server_close()


def test_v2_inquiry_detail_parity_direct_vs_remote(tmp_path: Path) -> None:
    db = tmp_path / "core-v2-inquiry.db"
    ids = _seed(db)
    direct_url, direct_server = _start_direct_panel(db, ui_version="v2")
    api_url, api_server = _start_api_server(db)
    remote = RemoteCoreClient(api_url, _API_TOKEN)
    remote_url, remote_server = _start_remote_panel(remote, ui_version="v2")
    try:
        for key in ("inquiry_verify", "inquiry_website"):
            inquiry_id = ids[key]
            d_status, d_html = _get(f"{direct_url}/inquiry/{inquiry_id}")
            r_status, r_html = _get(f"{remote_url}/inquiry/{inquiry_id}")
            assert d_status == r_status == 200
            _assert_same_modulo_remote_fields(d_html, r_html)
            assert "inquiry-hero" in d_html
            assert 'name="_command_id"' in r_html
            assert 'name="_expect_updated_at"' in r_html
            assert 'name="_command_id"' not in d_html
    finally:
        for server in (direct_server, remote_server, api_server):
            server.shutdown()
            server.server_close()


def test_anfragen_search_parity_direct_vs_remote(parity_world) -> None:
    direct_url, remote_url, _ids = parity_world
    for query in ("", "Bremen", "website_form"):
        q = urllib.parse.urlencode({"q": query})
        d_status, d_html = _get(f"{direct_url}/anfragen?{q}")
        r_status, r_html = _get(f"{remote_url}/anfragen?{q}")
        assert d_status == r_status == 200
        _assert_same_modulo_remote_fields(d_html, r_html)


def test_auftraege_parity_direct_vs_remote(parity_world) -> None:
    direct_url, remote_url, _ids = parity_world
    d_status, d_html = _get(f"{direct_url}/auftraege")
    r_status, r_html = _get(f"{remote_url}/auftraege")
    assert d_status == r_status == 200
    _assert_same_modulo_remote_fields(d_html, r_html)


def test_angebote_parity_direct_vs_remote(parity_world) -> None:
    direct_url, remote_url, _ids = parity_world
    d_status, d_html = _get(f"{direct_url}/angebote")
    r_status, r_html = _get(f"{remote_url}/angebote")
    assert d_status == r_status == 200
    _assert_same_modulo_remote_fields(d_html, r_html)
    assert "Keine Angebote vorhanden" in d_html


def test_kontakte_parity_direct_vs_remote(parity_world) -> None:
    direct_url, remote_url, _ids = parity_world
    d_status, d_html = _get(f"{direct_url}/kontakte")
    r_status, r_html = _get(f"{remote_url}/kontakte")
    assert d_status == r_status == 200
    _assert_same_modulo_remote_fields(d_html, r_html)
    assert "Kontakte" in d_html


def test_aufgaben_parity_direct_vs_remote(parity_world) -> None:
    direct_url, remote_url, ids = parity_world
    d_status, d_html = _get(f"{direct_url}/aufgaben")
    r_status, r_html = _get(f"{remote_url}/aufgaben")
    assert d_status == r_status == 200
    _assert_same_modulo_remote_fields(d_html, r_html)
    assert "Rückrufprüfung durchführen" in d_html
    assert f"/inquiry/{ids['inquiry_verify']}" in d_html


def test_kalender_parity_direct_vs_remote(parity_world) -> None:
    direct_url, remote_url, ids = parity_world
    d_status, d_html = _get(f"{direct_url}/kalender")
    r_status, r_html = _get(f"{remote_url}/kalender")
    assert d_status == r_status == 200
    _assert_same_modulo_remote_fields(d_html, r_html)
    assert "Kalender" in d_html
    assert f"/inquiry/{ids['inquiry_convertible']}" in d_html


def test_email_parity_direct_vs_remote(tmp_path: Path) -> None:
    db = tmp_path / "email-list.db"
    _seed(db)
    from catering_system.repositories.sqlite_inquiry_repository import (
        SQLiteInquiryRepository,
    )
    from catering_system.services.inquiry_service import InquiryService

    inquiry_repo = SQLiteInquiryRepository(db)
    InquiryService(inquiry_repo).create_inquiry(
        event_date=date(2026, 9, 1),
        inquiry_source="email",
        crm_stage="Neue Anfrage",
        customer_linkage={},
        time_window_text="Wir planen ein Sommerfest.",
        location_text="Catering Anfrage",
        guest_count_estimate=40,
        planning_mode="caterer_suggestion",
        call_verification_required=True,
        call_verification_status="pending",
        intake_message="E-Mail: parity-mail@example.invalid\n",
    )
    inquiry_repo.close()

    direct_url, direct_server = _start_direct_panel(db)
    api_url, api_server = _start_api_server(db)
    remote = RemoteCoreClient(api_url, _API_TOKEN)
    remote_url, remote_server = _start_remote_panel(remote)
    try:
        d_status, d_html = _get(f"{direct_url}/email")
        r_status, r_html = _get(f"{remote_url}/email")
        assert d_status == r_status == 200
        _assert_same_modulo_remote_fields(d_html, r_html)
        assert "Catering Anfrage" in d_html
        assert "parity-mail@example.invalid" in d_html
    finally:
        for server in (direct_server, remote_server, api_server):
            server.shutdown()
            server.server_close()


def test_kontakt_detail_parity_direct_vs_remote(tmp_path: Path) -> None:
    db = tmp_path / "kontakt-detail.db"
    ids = _seed(db)
    inquiry_id = ids["inquiry_convertible"]
    from catering_system.repositories.sqlite_inquiry_repository import (
        SQLiteInquiryRepository,
    )
    from catering_system.services.inquiry_service import InquiryService

    inquiry_repo = SQLiteInquiryRepository(db)
    inquiry = inquiry_repo.get_by_id(inquiry_id)
    assert inquiry is not None
    InquiryService(inquiry_repo).update_inquiry(
        inquiry.inquiry_id,
        intake_message="Firma: Parity GmbH\nE-Mail: parity@example.invalid\n",
    )
    inquiry_repo.close()
    contact_key = "intake:email:parity@example.invalid"
    direct_url, direct_server = _start_direct_panel(db)
    api_url, api_server = _start_api_server(db)
    remote = RemoteCoreClient(api_url, _API_TOKEN)
    remote_url, remote_server = _start_remote_panel(remote)
    try:
        encoded = urllib.parse.quote(contact_key, safe="")
        d_status, d_html = _get(f"{direct_url}/kontakt/{encoded}")
        r_status, r_html = _get(f"{remote_url}/kontakt/{encoded}")
        assert d_status == r_status == 200
        _assert_same_modulo_remote_fields(d_html, r_html)
        assert "Parity GmbH" in d_html
        assert "Kontakt-Profil" in d_html
    finally:
        for server in (direct_server, remote_server, api_server):
            server.shutdown()
            server.server_close()


def test_offer_detail_parity_direct_vs_remote(tmp_path: Path) -> None:
    db = tmp_path / "offer-detail.db"
    ids = _seed(db)
    inquiry_id = ids["inquiry_cancelled_order"]
    api_url, api_server = _start_api_server(db)
    try:
        status, body = _api_post(
            f"{api_url}/office/v1/inquiries/{inquiry_id}/prepare-offer",
            args={"snapshot": _valid_offer_snapshot(inquiry_id=inquiry_id)},
        )
        assert status == 201
        offer_id = body["offer_id"]
        version_id = body["offer_version_id"]
        mark_url = (
            f"{api_url}/office/v1/offers/{offer_id}/versions/{version_id}/mark-sent"
        )
        assert (
            _api_post(
                mark_url,
                args={
                    "sent_at": "2026-07-15T10:00:00+00:00",
                    "channel": "email",
                    "recipient_reference": "customer@example.invalid",
                    "evidence_reference": "mail-123",
                },
            )[0]
            == 200
        )

        direct_url, direct_server = _start_direct_panel(db)
        remote = RemoteCoreClient(api_url, _API_TOKEN)
        remote_url, remote_server = _start_remote_panel(remote)
        try:
            d_status, d_html = _get(f"{direct_url}/offer/{offer_id}")
            r_status, r_html = _get(f"{remote_url}/offer/{offer_id}")
            assert d_status == r_status == 200
            _assert_same_modulo_remote_fields(d_html, r_html)
            assert "Gesendet" in d_html
            assert "Angebotsvarianten" in d_html
            assert "Angebot gesendet" in d_html
            assert f'href="/inquiry/{inquiry_id}"' in d_html
            assert 'name="_command_id"' not in d_html
            assert 'name="_command_id"' in r_html
            assert "Annahme erfassen" in d_html
        finally:
            for server in (direct_server, remote_server):
                server.shutdown()
                server.server_close()
    finally:
        api_server.shutdown()
        api_server.server_close()


def test_offer_detail_not_found_parity(tmp_path: Path) -> None:
    db = tmp_path / "offer-missing.db"
    _seed(db)
    missing = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    direct_url, direct_server = _start_direct_panel(db)
    api_url, api_server = _start_api_server(db)
    remote = RemoteCoreClient(api_url, _API_TOKEN)
    remote_url, remote_server = _start_remote_panel(remote)
    try:
        d_status, _d_html = _get(f"{direct_url}/offer/{missing}")
        r_status, _r_html = _get(f"{remote_url}/offer/{missing}")
        assert d_status == r_status == 404
    finally:
        for server in (direct_server, remote_server, api_server):
            server.shutdown()
            server.server_close()


def test_order_detail_parity_direct_vs_remote(parity_world) -> None:
    direct_url, remote_url, ids = parity_world
    for key in ("order_ready", "order_unprinted", "order_cancelled"):
        order_id = ids[key]
        d_status, d_html = _get(f"{direct_url}/order/{order_id}")
        r_status, r_html = _get(f"{remote_url}/order/{order_id}")
        assert d_status == r_status == 200
        _assert_same_modulo_remote_fields(d_html, r_html)


def test_v2_order_detail_parity_direct_vs_remote(tmp_path: Path) -> None:
    db = tmp_path / "core-v2-order.db"
    ids = _seed(db)
    direct_url, direct_server = _start_direct_panel(db, ui_version="v2")
    api_url, api_server = _start_api_server(db)
    remote = RemoteCoreClient(api_url, _API_TOKEN)
    remote_url, remote_server = _start_remote_panel(remote, ui_version="v2")
    try:
        for key in ("order_ready", "order_unprinted", "order_cancelled"):
            order_id = ids[key]
            d_status, d_html = _get(f"{direct_url}/order/{order_id}")
            r_status, r_html = _get(f"{remote_url}/order/{order_id}")
            assert d_status == r_status == 200
            _assert_same_modulo_remote_fields(d_html, r_html)
            assert "order-hero" in d_html
            assert 'name="_command_id"' not in d_html
            if key != "order_cancelled":
                assert 'name="_command_id"' in r_html
                assert 'name="_expect_updated_at"' in r_html
                assert 'name="_expect_latest_version_number"' in r_html
                assert 'name="_expect_payment_reminder_updated_at"' in r_html
    finally:
        for server in (direct_server, remote_server, api_server):
            server.shutdown()
            server.server_close()


def test_remote_payment_reminder_command_and_operational_actions(parity_world) -> None:
    _direct_url, remote_url, ids = parity_world
    order_id = ids["order_unprinted"]
    status, detail = _get(f"{remote_url}/order/{order_id}")
    assert status == 200
    form = re.search(
        rf'(<form method="post" action="/order/{order_id}/payment-reminder".*?</form>)',
        detail,
        re.DOTALL,
    )
    assert form is not None
    form_html = form.group(1)

    status, saved = _post_form(
        f"{remote_url}/order/{order_id}/payment-reminder",
        {
            "_csrf_token": _CSRF_TOKEN,
            "_command_id": _extract_hidden(form_html, "_command_id"),
            "_expect_payment_reminder_updated_at": _extract_hidden(
                form_html, "_expect_payment_reminder_updated_at"
            ),
            "payment_method": "RECHNUNG",
            "invoice_created": "1",
            "invoice_number": "RE-REMOTE-1",
            "sent_on": "2026-07-15",
            "due_on": "2026-07-22",
        },
    )

    assert status == 200
    assert "Zahlungsart:</strong> Rechnung" in saved
    assert "Rechnungsnummer:</strong> RE-REMOTE-1" in saved
    assert "Druck bestätigen" in saved


@pytest.mark.parametrize("ui_version", ("legacy", "v2"))
def test_truncated_order_detail_warns_and_uses_true_latest_version(
    tmp_path: Path,
    ui_version: str,
) -> None:
    db = tmp_path / "core.db"
    inquiries = SQLiteInquiryRepository(db)
    orders = SQLiteOrderRepository(db)
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
    )
    service = OrderService(orders)
    order, _version = service.convert_inquiry_to_order(inquiry)
    for number in range(2, 202):
        service.create_relevant_order_change_version(
            order,
            event_date=date(2026, 10, 1),
            time_window_text=f"Fenster {number}",
            location_text="Hamburg",
            guest_count_estimate=25,
            planning_mode="caterer_suggestion",
        )
    inquiries.close()
    orders.close()

    api_url, api_server = _start_api_server(db)
    remote = RemoteCoreClient(api_url, _API_TOKEN)
    panel_url, panel_server = _start_remote_panel(remote, ui_version=ui_version)
    try:
        status, html = _get(f"{panel_url}/order/{order.order_id}")
        assert status == 200
        assert "Unvollständige Ansicht" in html
        expected_warning = (
            "200 von 201 Versionen"
            if ui_version == "legacy"
            else "200 von 201 Auftragsständen"
        )
        assert expected_warning in html
        assert _extract_hidden(html, "_expect_latest_version_number") == "201"
    finally:
        panel_server.shutdown()
        panel_server.server_close()
        api_server.shutdown()
        api_server.server_close()


def test_v2_remote_inquiry_detail_preserves_linked_order_truncation_warning(
    tmp_path: Path,
) -> None:
    db = tmp_path / "core-v2-inquiry-truncated.db"
    inquiries = SQLiteInquiryRepository(db)
    orders = SQLiteOrderRepository(db)
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
    )
    order_service = OrderService(orders)
    core = OperationalCoreService(orders)
    for _index in range(51):
        order, _version = order_service.convert_inquiry_to_order(inquiry)
        core.cancel_order(order.order_id)
    inquiries.close()
    orders.close()

    api_url, api_server = _start_api_server(db)
    remote = RemoteCoreClient(api_url, _API_TOKEN)
    panel_url, panel_server = _start_remote_panel(remote, ui_version="v2")
    try:
        status, body = _get(f"{panel_url}/inquiry/{inquiry.inquiry_id}")
        assert status == 200
        assert "Unvollständige Ansicht" in body
        assert "Nicht alle 51 verknüpften Aufträge" in body
        assert "Stornierten Auftrag öffnen" in body
        assert "In Auftrag umwandeln" in body
    finally:
        panel_server.shutdown()
        panel_server.server_close()
        api_server.shutdown()
        api_server.server_close()


def test_inquiry_detail_parity_direct_vs_remote(parity_world) -> None:
    direct_url, remote_url, ids = parity_world
    for key in ("inquiry_verify", "inquiry_website"):
        inquiry_id = ids[key]
        d_status, d_html = _get(f"{direct_url}/inquiry/{inquiry_id}")
        r_status, r_html = _get(f"{remote_url}/inquiry/{inquiry_id}")
        assert d_status == r_status == 200
        _assert_same_modulo_remote_fields(d_html, r_html)


def test_print_data_parity_direct_vs_remote(parity_world) -> None:
    direct_url, remote_url, ids = parity_world
    order_id, version_id = ids["order_ready"], ids["version_ready"]
    q = urllib.parse.urlencode({"version": version_id})
    d_status, d_html = _get(f"{direct_url}/order/{order_id}/print?{q}")
    r_status, r_html = _get(f"{remote_url}/order/{order_id}/print?{q}")
    assert d_status == r_status == 200
    assert d_html == r_html  # print sheet embeds no command form at all


def test_buffet_cards_direct_remote_parity(parity_world) -> None:
    direct_url, remote_url, ids = parity_world
    order_id, version_id = ids["order_ready"], ids["version_ready"]
    q = urllib.parse.urlencode({"version": version_id})
    d_status, d_html = _get(f"{direct_url}/order/{order_id}/buffet-cards?{q}")
    r_status, r_html = _get(f"{remote_url}/order/{order_id}/buffet-cards?{q}")
    assert d_status == r_status == 200
    assert d_html == r_html


def test_gerichte_direct_remote_parity(parity_world) -> None:
    direct_url, remote_url, _ids = parity_world
    d_status, d_html = _get(f"{direct_url}/gerichte")
    r_status, r_html = _get(f"{remote_url}/gerichte")
    assert d_status == r_status == 200
    assert d_html == r_html


def test_gericht_edit_direct_remote_parity(parity_world) -> None:
    direct_url, remote_url, ids = parity_world
    dish_id = ids["catalog_dish_id"]
    d_status, d_html = _get(f"{direct_url}/gerichte/{dish_id}/edit")
    r_status, r_html = _get(f"{remote_url}/gerichte/{dish_id}/edit")
    assert d_status == r_status == 200
    assert _strip_remote_fields(d_html) == _strip_remote_fields(r_html)


def test_rueckruf_stays_local_not_routed_through_core(parity_world) -> None:
    """Rückruf/Auerswald stays outside Core.  On Proxmox, an unconfigured
    local integration must carry the frozen "only on premises" explanation
    rather than pretending that it is an ordinary missing URL."""
    direct_url, remote_url, _ids = parity_world
    d_status, d_html = _get(f"{direct_url}/rueckruf")
    r_status, r_html = _get(f"{remote_url}/rueckruf")
    assert d_status == r_status == 200
    assert "AUERSWALD_SYNC_URL nicht konfiguriert" in d_html
    assert "Rückruf-Liste: nur vor Ort verfügbar" in r_html


# --- full write flow through the frozen command envelope ---------------------


@pytest.fixture()
def remote_world(tmp_path: Path):
    db = tmp_path / "core.db"
    api_url, api_server = _start_api_server(db)
    remote = RemoteCoreClient(api_url, _API_TOKEN)
    panel_url, panel_server = _start_remote_panel(remote)
    yield panel_url
    panel_server.shutdown()
    panel_server.server_close()
    api_server.shutdown()
    api_server.server_close()


def test_full_write_flow_through_remote_panel(remote_world) -> None:
    base = remote_world
    status, form_html = _get(f"{base}/inquiry/new")
    assert status == 200
    command_id = _extract_hidden(form_html, "_command_id")

    status, redirect_body = _post_form(
        f"{base}/inquiry/new",
        {
            "_csrf_token": _CSRF_TOKEN,
            "_command_id": command_id,
            "event_date": "2026-11-11",
            "inquiry_source": "manual",
            "time_window_text": "abends",
            "location_text": "Rostock",
            "guest_count_estimate": "40",
            "planning_mode": "caterer_suggestion",
        },
    )
    assert status == 200
    inquiry_id_match = re.search(r"Anfrage ([0-9a-f]{8})", redirect_body)
    assert inquiry_id_match

    status, detail_html = _get(f"{base}/anfragen?q=Rostock")
    assert status == 200
    assert "Rostock" in detail_html
    inquiry_id = re.search(r'/inquiry/([0-9a-f-]{36})"', detail_html).group(1)

    status, detail_html = _get(f"{base}/inquiry/{inquiry_id}")
    assert status == 200
    update_form = re.search(
        r'(<form method="post" action="/inquiry/[^"]*/update".*</form>)',
        detail_html,
        re.DOTALL,
    ).group(0)
    update_command_id = _extract_hidden(update_form, "_command_id")
    update_expect = _extract_hidden(update_form, "_expect_updated_at")
    status, _body = _post_form(
        f"{base}/inquiry/{inquiry_id}/update",
        {
            "_csrf_token": _CSRF_TOKEN,
            "_command_id": update_command_id,
            "_expect_updated_at": update_expect,
            "event_date": "2026-11-11",
            "time_window_text": "abends",
            "location_text": "Rostock-Ost",
            "guest_count_estimate": "40",
            "planning_mode": "caterer_suggestion",
            "crm_stage": "Neue Anfrage",
        },
    )
    assert status == 200

    status, detail_html = _get(f"{base}/inquiry/{inquiry_id}")
    assert status == 200
    assert "Rostock-Ost" in detail_html
    convert_command_id = _extract_hidden(
        re.search(r"(<form[^>]*convert[^\"]*\"[^>]*>.*?</form>)", detail_html).group(0),
        "_command_id",
    )
    status, _body = _post_form(
        f"{base}/inquiry/{inquiry_id}/convert",
        {"_csrf_token": _CSRF_TOKEN, "_command_id": convert_command_id},
    )
    assert status == 200

    status, converted_inquiry_html = _get(f"{base}/inquiry/{inquiry_id}")
    assert status == 200
    assert "Bestätigt / Auftrag" in converted_inquiry_html
    assert "In Auftrag umwandeln" not in converted_inquiry_html
    assert '<select name="crm_stage">' not in converted_inquiry_html
    assert (
        '<input type="hidden" name="crm_stage" value="Bestätigt / Auftrag">'
        in converted_inquiry_html
    )
    locked_update_form = re.search(
        r'(<form method="post" action="/inquiry/[^\"]*/update".*</form>)',
        converted_inquiry_html,
        re.DOTALL,
    ).group(0)
    status, error_html = _post_form(
        f"{base}/inquiry/{inquiry_id}/update",
        {
            "_csrf_token": _CSRF_TOKEN,
            "_command_id": _extract_hidden(locked_update_form, "_command_id"),
            "_expect_updated_at": _extract_hidden(
                locked_update_form, "_expect_updated_at"
            ),
            "event_date": "2026-11-11",
            "time_window_text": "abends",
            "location_text": "Rostock-Ost",
            "guest_count_estimate": "40",
            "planning_mode": "caterer_suggestion",
            "crm_stage": "Abgelehnt / verloren",
        },
    )
    assert status == 422
    assert "active_order_crm_stage_conflict" in error_html
    status, converted_inquiry_html = _get(f"{base}/inquiry/{inquiry_id}")
    assert status == 200
    assert "Bestätigt / Auftrag" in converted_inquiry_html

    status, order_list_html = _get(f"{base}/auftraege?q={inquiry_id[:8]}")
    assert status == 200
    order_id = re.search(r'/order/([0-9a-f-]{36})"', order_list_html).group(1)

    status, order_html = _get(f"{base}/order/{order_id}")
    assert status == 200
    assert f'action="/order/{order_id}/print-confirm"' in order_html
    assert f'action="/order/{order_id}/effective"' not in order_html
    assert "Wirksam machen" not in order_html
    version_id_match = re.search(r'name="order_version_id" value="([^"]+)"', order_html)
    assert version_id_match
    version_id = version_id_match.group(1)
    print_confirm_command_id = _extract_hidden(order_html, "_command_id")

    status, _body = _post_form(
        f"{base}/order/{order_id}/print-confirm",
        {
            "_csrf_token": _CSRF_TOKEN,
            "_command_id": print_confirm_command_id,
            "order_version_id": version_id,
        },
    )
    assert status == 200

    status, order_html = _get(f"{base}/order/{order_id}")
    assert status == 200
    assert "Druck bestätigt" in order_html
    assert f'action="/order/{order_id}/effective"' in order_html
    assert "Wirksam machen" in order_html

    ready_command_id = _extract_hidden(
        re.search(
            r'(<form[^>]*action="/order/[^"]*/ready"[^>]*>.*?</form>)', order_html
        ).group(0),
        "_command_id",
    )
    status, _body = _post_form(
        f"{base}/order/{order_id}/ready",
        {"_csrf_token": _CSRF_TOKEN, "_command_id": ready_command_id},
    )
    assert status == 200  # not yet effective, but the command itself succeeds

    effective_command_id = _extract_hidden(
        re.search(
            r'(<form[^>]*action="/order/[^"]*/effective"[^>]*>.*?</form>)', order_html
        ).group(0),
        "_command_id",
    )
    effective_expect = _extract_hidden(order_html, "_expect_effective_version_id")
    status, _body = _post_form(
        f"{base}/order/{order_id}/effective",
        {
            "_csrf_token": _CSRF_TOKEN,
            "_command_id": effective_command_id,
            "_expect_effective_version_id": effective_expect,
            "order_version_id": version_id,
        },
    )
    assert status == 200

    status, order_html = _get(f"{base}/order/{order_id}")
    assert status == 200
    assert "wirksam" in order_html
    assert "READY_TO_SEND: bereit." in order_html

    cancel_command_id = _extract_hidden(
        re.search(
            r'(<form[^>]*action="/order/[^"]*/cancel"[^>]*>.*?</form>)', order_html
        ).group(0),
        "_command_id",
    )
    cancel_expect = _extract_hidden(order_html, "_expect_updated_at")
    status, _body = _post_form(
        f"{base}/order/{order_id}/cancel",
        {
            "_csrf_token": _CSRF_TOKEN,
            "_command_id": cancel_command_id,
            "_expect_updated_at": cancel_expect,
        },
    )
    assert status == 200
    status, order_html = _get(f"{base}/order/{order_id}")
    assert "STORNIERT" in order_html


def test_verify_flow_through_remote_panel(remote_world) -> None:
    """The main flow above never sets call_verification_required, so it never
    exercises verify_customer_by_call — cover it here."""
    base = remote_world
    _status, form_html = _get(f"{base}/inquiry/new")
    command_id = _extract_hidden(form_html, "_command_id")
    _status, _body = _post_form(
        f"{base}/inquiry/new",
        {
            "_csrf_token": _CSRF_TOKEN,
            "_command_id": command_id,
            "event_date": "2026-11-13",
            "inquiry_source": "phone_by_office",
            "time_window_text": "mittags",
            "location_text": "Schwerin",
            "guest_count_estimate": "15",
            "planning_mode": "caterer_suggestion",
            "call_verification_required": "1",
        },
    )
    _status, list_html = _get(f"{base}/anfragen?q=Schwerin")
    inquiry_id = re.search(r'/inquiry/([0-9a-f-]{36})"', list_html).group(1)

    _status, detail_html = _get(f"{base}/inquiry/{inquiry_id}")
    assert "Telefonisch verifiziert" in detail_html
    verify_form = re.search(
        r'(<form[^>]*action="/inquiry/[^"]*/verify"[^>]*>.*?</form>)', detail_html
    ).group(0)
    verify_command_id = _extract_hidden(verify_form, "_command_id")
    status, _body = _post_form(
        f"{base}/inquiry/{inquiry_id}/verify",
        {"_csrf_token": _CSRF_TOKEN, "_command_id": verify_command_id},
    )
    assert status == 200

    _status, detail_html = _get(f"{base}/inquiry/{inquiry_id}")
    assert "Telefonisch verifiziert" not in detail_html  # button gone once verified
    assert "In Auftrag umwandeln" in detail_html  # convert now offered


def test_idempotent_retry_same_command_id_and_preconditions(remote_world) -> None:
    """§6.1/§6.3: after an indeterminate failure, retrying with the identical
    envelope must not double the effect — convert twice with the same
    command_id must produce exactly one order."""
    base = remote_world
    _status, form_html = _get(f"{base}/inquiry/new")
    command_id = _extract_hidden(form_html, "_command_id")
    fields = {
        "_csrf_token": _CSRF_TOKEN,
        "_command_id": command_id,
        "event_date": "2026-11-12",
        "inquiry_source": "manual",
        "time_window_text": "abends",
        "location_text": "Idempotenz-Stadt",
        "guest_count_estimate": "10",
        "planning_mode": "caterer_suggestion",
    }
    status1, _ = _post_form(f"{base}/inquiry/new", fields)
    status2, _ = _post_form(f"{base}/inquiry/new", fields)  # identical retry
    assert status1 == status2 == 200

    _status, list_html = _get(f"{base}/anfragen?q=Idempotenz-Stadt")
    # exactly one row, not two (the search box also echoes the query term
    # into its value= attribute, so count the table cell specifically)
    assert list_html.count("<td>Idempotenz-Stadt</td>") == 1

    inquiry_id = re.search(r'/inquiry/([0-9a-f-]{36})"', list_html).group(1)
    _status, detail_html = _get(f"{base}/inquiry/{inquiry_id}")
    convert_form = re.search(
        r'(<form[^>]*action="/inquiry/[^"]*/convert"[^>]*>.*?</form>)', detail_html
    ).group(0)
    convert_command_id = _extract_hidden(convert_form, "_command_id")
    convert_fields = {"_csrf_token": _CSRF_TOKEN, "_command_id": convert_command_id}
    status1, _ = _post_form(f"{base}/inquiry/{inquiry_id}/convert", convert_fields)
    status2, _ = _post_form(f"{base}/inquiry/{inquiry_id}/convert", convert_fields)
    assert status1 == status2 == 200  # replay returns the recorded result

    _status, orders_html = _get(f"{base}/auftraege?q={inquiry_id[:8]}")
    # exactly one order row for this inquiry, not two — one header <tr> plus
    # one data <tr>
    assert orders_html.count("<tr>") == 2


# --- degradation: unreachable Core Office API --------------------------------


def test_unreachable_api_shows_german_message_never_empty_queue(tmp_path: Path) -> None:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        dead_port = sock.getsockname()[1]
    remote = RemoteCoreClient(f"http://127.0.0.1:{dead_port}", _API_TOKEN)
    url, server = _start_remote_panel(remote)
    try:
        status, html = _get(f"{url}/")
        assert status == 503
        assert "Core nicht erreichbar" in html
        assert "nichts wurde gespeichert" in html
        # never an empty/broken dashboard rendered as if all-clear
        assert "Anfragen prüfen" not in html
    finally:
        server.shutdown()
        server.server_close()


# --- remote mode never opens core.db / half-config startup rejection --------


def test_remote_mode_never_constructs_sqlite_repos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("remote mode must never open core.db")

    monkeypatch.setattr(SQLiteInquiryRepository, "__init__", _boom)
    monkeypatch.setattr(SQLiteOrderRepository, "__init__", _boom)
    # constructing the remote client and the panel server must not touch
    # either SQLite repo class at all
    remote = RemoteCoreClient("http://127.0.0.1:8084", _API_TOKEN)
    _url, server = _start_remote_panel(remote)
    server.shutdown()
    server.server_close()


def test_half_config_url_only_rejects_before_startup(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"
    env["CORE_OFFICE_API_URL"] = "http://127.0.0.1:8084"
    env.pop("CORE_OFFICE_API_TOKEN", None)
    env["OFFICE_PANEL_PASSWORD"] = "x"
    result = subprocess.run(
        [sys.executable, "-m", "catering_system.ui.office_panel", "--port", "0"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "CORE_OFFICE_API_URL" in result.stderr
    assert "CORE_OFFICE_API_TOKEN" in result.stderr


def test_half_config_token_only_rejects_before_startup(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"
    env.pop("CORE_OFFICE_API_URL", None)
    env["CORE_OFFICE_API_TOKEN"] = "some-token"
    env["OFFICE_PANEL_PASSWORD"] = "x"
    result = subprocess.run(
        [sys.executable, "-m", "catering_system.ui.office_panel", "--port", "0"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "CORE_OFFICE_API_URL" in result.stderr


def test_remote_mode_starts_without_any_db_argument(tmp_path: Path) -> None:
    """Proves remote mode truly needs no --db: if it ever tried the direct
    path it would fail for lack of one. Started as a subprocess and killed
    once it prints its startup banner (it would otherwise serve forever)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"
    with __import__("socket").socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with __import__("socket").socket() as api_probe:
        api_probe.bind(("127.0.0.1", 0))
        api_port = api_probe.getsockname()[1]
    env["CORE_OFFICE_API_URL"] = f"http://127.0.0.1:{api_port}"
    env["CORE_OFFICE_API_TOKEN"] = "x"
    env["OFFICE_PANEL_PASSWORD"] = "x"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-u",  # unbuffered stdout, so readline() below sees it promptly
            "-m",
            "catering_system.ui.office_panel",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        import select

        ready, _, _ = select.select([proc.stdout], [], [], 10)
        assert ready, "office panel printed no startup banner within 10s"
        line = proc.stdout.readline()
        assert "remote mode" in line
        assert proc.poll() is None  # still running, didn't crash on startup
    finally:
        proc.terminate()
        proc.wait(timeout=10)
