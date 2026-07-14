"""Remote Core backend for the office panel (Proxmox pack, Phase 2).

The panel keeps its existing rendering code.  This adapter exposes the small
repository/service surface that rendering already consumes, while every write
is sent to the frozen Core Office API.  It never opens ``core.db``.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, NoReturn, cast
from urllib.parse import quote, urlencode, urlparse

from catering_system.domain.inquiry import (
    Inquiry,
    validate_call_verification_status,
    validate_crm_stage,
    validate_customer_linkage,
    validate_planning_mode,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.ready_to_send import ReadyToSendEvaluation
from catering_system.services.inquiry_service import validate_inquiry_source

_MAX_RESPONSE_BYTES = 512 * 1024
_READ_TIMEOUT_SECONDS = 3
_COMMAND_TIMEOUT_SECONDS = 5
_PAGE_SIZE = 100


class RemoteCoreError(ValueError):
    """Stable remote failure; never contains response payload or bearer data."""

    def __init__(self, status: int, code: str, *, unavailable: bool = False) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.unavailable = unavailable


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


def _bad_response() -> NoReturn:
    raise RemoteCoreError(502, "invalid_response", unavailable=True)


def _dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        _bad_response()
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        _bad_response()
    return value


def _str(value: object) -> str:
    if not isinstance(value, str):
        _bad_response()
    return value


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return _str(value)


def _bool(value: object) -> bool:
    if not isinstance(value, bool):
        _bad_response()
    return value


def _int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        _bad_response()
    return value


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _int(value)


def _date(value: object) -> date:
    try:
        return date.fromisoformat(_str(value))
    except ValueError:
        _bad_response()


def _datetime(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(_str(value))
    except ValueError:
        _bad_response()
    if parsed.tzinfo is None:
        _bad_response()
    return parsed


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return _datetime(value)


def _inquiry(data: Mapping[str, object]) -> Inquiry:
    linkage_raw = data.get("customer_linkage", {})
    try:
        linkage = validate_customer_linkage(_dict(linkage_raw))
        source = validate_inquiry_source(_str(data["inquiry_source"]))
        crm_stage = validate_crm_stage(_str(data["crm_stage"]))
        planning_mode = validate_planning_mode(_str(data["planning_mode"]))
        verification = validate_call_verification_status(
            _str(data["call_verification_status"])
        )
    except (KeyError, TypeError, ValueError):
        _bad_response()
    return Inquiry(
        inquiry_id=_str(data.get("inquiry_id")),
        event_date=_date(data.get("event_date")),
        created_at=_datetime(data.get("created_at")),
        updated_at=_datetime(data.get("updated_at")),
        inquiry_source=source,
        crm_stage=crm_stage,
        customer_linkage=linkage,
        time_window_text=_str(data.get("time_window_text")),
        location_text=_str(data.get("location_text")),
        guest_count_estimate=_optional_int(data.get("guest_count_estimate")),
        planning_mode=planning_mode,
        call_verification_required=_bool(data.get("call_verification_required")),
        call_verification_status=verification,
        intake_subject=_optional_str(data.get("intake_subject")),
        intake_message=_optional_str(data.get("intake_message")),
        intake_summary=_optional_str(data.get("intake_summary")),
        intake_external_ref=_optional_str(data.get("intake_external_ref")),
    )


def _order(data: Mapping[str, object]) -> Order:
    return Order(
        order_id=_str(data.get("order_id")),
        source_inquiry_id=_str(data.get("source_inquiry_id")),
        created_at=_datetime(data.get("created_at")),
        updated_at=_datetime(data.get("updated_at")),
        candidate_order_version_id=_optional_str(
            data.get("candidate_order_version_id")
        ),
        effective_order_version_id=_optional_str(
            data.get("effective_order_version_id")
        ),
        cancelled_at=_optional_datetime(data.get("cancelled_at")),
    )


def _version(data: Mapping[str, object]) -> OrderVersion:
    try:
        planning_mode = validate_planning_mode(_str(data["planning_mode"]))
    except (KeyError, ValueError):
        _bad_response()
    return OrderVersion(
        order_version_id=_str(data.get("order_version_id")),
        order_id=_str(data.get("order_id")),
        version_number=_int(data.get("version_number")),
        created_at=_datetime(data.get("created_at")),
        event_date=_date(data.get("event_date")),
        time_window_text=_str(data.get("time_window_text")),
        location_text=_str(data.get("location_text")),
        guest_count_estimate=_optional_int(data.get("guest_count_estimate")),
        planning_mode=planning_mode,
        kitchen_print_confirmed_at=_optional_datetime(
            data.get("kitchen_print_confirmed_at")
        ),
    )


class RemoteCoreClient:
    """Strict bearer client plus read facades used by ``OfficePanel``."""

    is_remote = True

    def __init__(self, base_url: str, token: str) -> None:
        parsed = urlparse(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("CORE_OFFICE_API_URL must be an absolute HTTP(S) URL")
        if not token:
            raise ValueError("CORE_OFFICE_API_TOKEN is required in remote mode")
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._opener = urllib.request.build_opener(_NoRedirect)
        self._command_id = ""
        self._form: dict[str, str] = {}
        self._order_details: dict[str, dict[str, object]] = {}
        self._known_order_ids: list[str] = []
        self._evaluations: dict[str, ReadyToSendEvaluation] = {}
        self.inquiry_service = _RemoteInquiryService(self)
        self.order_service = _RemoteOrderService(self)
        self.core = _RemoteOperationalCoreService(self)

    def begin_request(self, form: Mapping[str, str] | None = None) -> None:
        self._order_details.clear()
        self._known_order_ids = []
        self._evaluations.clear()
        self._form = dict(form or {})
        self._command_id = self._form.get("_command_id", "")

    def new_page_command_id(self) -> str:
        return str(uuid.uuid4())

    def _id(self) -> str:
        return self._command_id or str(uuid.uuid4())

    def form_value(self, key: str) -> str | None:
        return self._form.get(key)

    def _url(self, path: str, query: Mapping[str, object] | None = None) -> str:
        url = f"{self.base_url}{path}"
        if query:
            url += "?" + urlencode(query)
        return url

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, object] | None = None,
        body: Mapping[str, object] | None = None,
        expected: set[int],
    ) -> dict[str, object]:
        data = None
        headers = {"Authorization": f"Bearer {self._token}"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self._url(path, query), data=data, headers=headers, method=method
        )
        timeout = (
            _READ_TIMEOUT_SECONDS if method == "GET" else _COMMAND_TIMEOUT_SECONDS
        )
        try:
            response = self._opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                raise RemoteCoreError(502, "redirect_refused", unavailable=True) from exc
            raw = exc.read(_MAX_RESPONSE_BYTES + 1)
            code = "remote_error"
            try:
                parsed = _dict(json.loads(raw.decode("utf-8")))
                code = _str(parsed.get("error"))
            except (UnicodeDecodeError, json.JSONDecodeError, RemoteCoreError):
                pass
            raise RemoteCoreError(exc.code, code) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise RemoteCoreError(503, "unreachable", unavailable=True) from exc
        with response:
            if response.status not in expected:
                raise RemoteCoreError(response.status, "unexpected_status", unavailable=True)
            if response.headers.get_content_type() != "application/json":
                _bad_response()
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            _bad_response()
        try:
            return _dict(json.loads(raw.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError):
            _bad_response()

    def get(self, path: str, query: Mapping[str, object] | None = None) -> dict[str, object]:
        return self._request("GET", path, query=query, expected={200})

    def command(
        self,
        path: str,
        args: Mapping[str, object],
        expect: Mapping[str, object],
        expected: set[int],
    ) -> dict[str, object]:
        result = self._request(
            "POST",
            path,
            body={"command_id": self._id(), "expect": dict(expect), "args": dict(args)},
            expected=expected,
        )
        self._order_details.clear()
        self._known_order_ids = []
        self._evaluations.clear()
        return result

    # -- reads / repository-shaped facade ---------------------------------

    def list_all(self) -> list[Inquiry]:
        rows: list[Inquiry] = []
        offset = 0
        while True:
            page = self.get(
                "/office/v1/inquiries", {"limit": _PAGE_SIZE, "offset": offset}
            )
            items = _list(page.get("inquiries"))
            rows.extend(_inquiry(_dict(item)) for item in items)
            total = _int(page.get("total_count"))
            offset += len(items)
            if offset >= total or not items:
                return rows

    def get_by_id(self, inquiry_id: str) -> Inquiry | None:
        try:
            return _inquiry(
                self.get(f"/office/v1/inquiries/{quote(inquiry_id, safe='')}")
            )
        except RemoteCoreError as exc:
            if exc.status == 404:
                return None
            raise

    def find_by_source_and_external_ref(
        self, inquiry_source: str, intake_external_ref: str
    ) -> Inquiry | None:
        return next(
            (
                inquiry
                for inquiry in self.list_all()
                if inquiry.inquiry_source == inquiry_source
                and inquiry.intake_external_ref == intake_external_ref
            ),
            None,
        )

    def list_orders(self) -> list[Order]:
        rows: list[Order] = []
        offset = 0
        while True:
            page = self.get(
                "/office/v1/orders", {"limit": _PAGE_SIZE, "offset": offset}
            )
            items = _list(page.get("orders"))
            for item in items:
                data = _dict(item)
                order = _order(data)
                rows.append(order)
                self._known_order_ids.append(order.order_id)
                reason = data.get("blocker_reason")
                self._evaluations[order.order_id] = ReadyToSendEvaluation(
                    order_id=order.order_id,
                    ready=_bool(data.get("ready")),
                    reasons=() if reason is None else (_str(reason),),
                )
            total = _int(page.get("total_count"))
            offset += len(items)
            if offset >= total or not items:
                return rows

    def _order_detail(self, order_id: str) -> dict[str, object] | None:
        if order_id in self._order_details:
            return self._order_details[order_id]
        try:
            detail = self.get(f"/office/v1/orders/{quote(order_id, safe='')}")
        except RemoteCoreError as exc:
            if exc.status == 404:
                return None
            raise
        self._order_details[order_id] = detail
        evaluation = _dict(detail.get("ready_to_send"))
        self._evaluations[order_id] = ReadyToSendEvaluation(
            order_id=order_id,
            ready=_bool(evaluation.get("ready")),
            reasons=tuple(_str(reason) for reason in _list(evaluation.get("reasons"))),
        )
        return detail

    def get_order(self, order_id: str) -> Order | None:
        detail = self._order_detail(order_id)
        return None if detail is None else _order(detail)

    def list_order_versions(self, order_id: str) -> list[OrderVersion]:
        detail = self._order_detail(order_id)
        if detail is None:
            return []
        return [_version(_dict(row)) for row in _list(detail.get("versions"))]

    def get_order_version(self, order_version_id: str) -> OrderVersion | None:
        """Global version lookup, matching the repo Protocol signature (no
        owning order_id parameter). The frozen contract has no by-version-id
        route — only ``GET /orders/{id}`` (embeds all versions) or
        ``print-data?version=`` (needs the order_id too) — so this first
        checks already-fetched order details, then falls back to fetching
        the remaining known orders (from the last ``list_orders()`` call)
        one at a time until the version turns up. Each order's detail is
        fetched at most once per request (cached in ``_order_details``), so
        repeated calls (e.g. WochenuebersichtService looping every order)
        cost at most one GET per order, not one per call."""
        for detail in self._order_details.values():
            for row in _list(detail.get("versions")):
                version = _version(_dict(row))
                if version.order_version_id == order_version_id:
                    return version
        for order_id in self._known_order_ids:
            if order_id in self._order_details:
                continue
            fetched = self._order_detail(order_id)
            if fetched is None:
                continue
            for row in _list(fetched.get("versions")):
                version = _version(_dict(row))
                if version.order_version_id == order_version_id:
                    return version
        return None

    def evaluation(self, order_id: str) -> ReadyToSendEvaluation:
        if order_id not in self._evaluations:
            self._order_detail(order_id)
        return self._evaluations.get(
            order_id,
            ReadyToSendEvaluation(
                order_id=order_id,
                ready=False,
                reasons=("ready_to_send_order_not_found",),
            ),
        )

    def print_data(self, order_id: str, version_id: str) -> tuple[Order, OrderVersion] | None:
        try:
            body = self.get(
                f"/office/v1/orders/{quote(order_id, safe='')}/print-data",
                {"version": version_id},
            )
        except RemoteCoreError as exc:
            if exc.status == 404:
                return None
            raise
        return _order(_dict(body.get("order"))), _version(_dict(body.get("version")))

    # Writes must never fall through repository semantics in remote mode: the
    # panel is wired to use the _Remote*Service facades below for every
    # mutation (named Core Office API commands only), never these repo-shaped
    # methods. Each stub matches its Protocol signature exactly — both so the
    # tripwire actually raises this message (a mismatched arity would raise a
    # plain TypeError instead) and so RemoteCoreClient stays structurally
    # assignable to InquiryRepository/OrderRepository for the read methods.
    def save(self, inquiry: Inquiry) -> None:
        self._write_forbidden()

    def update(self, inquiry: Inquiry) -> None:
        self._write_forbidden()

    def save_order_with_initial_version(
        self, order: Order, version: OrderVersion
    ) -> None:
        self._write_forbidden()

    def update_order(self, order: Order) -> None:
        self._write_forbidden()

    def append_order_version(self, order: Order, version: OrderVersion) -> None:
        self._write_forbidden()

    def update_order_version(self, version: OrderVersion) -> None:
        self._write_forbidden()

    def _write_forbidden(self) -> NoReturn:
        raise RuntimeError("remote panel writes only through Core Office API commands")


class _RemoteInquiryService:
    def __init__(self, client: RemoteCoreClient) -> None:
        self._client = client

    def create_inquiry(self, **values: Any) -> Inquiry:
        args = {
            "event_date": values["event_date"].isoformat(),
            "inquiry_source": values["inquiry_source"],
            "time_window_text": values["time_window_text"],
            "location_text": values["location_text"],
            "guest_count_estimate": values["guest_count_estimate"],
            "planning_mode": values["planning_mode"],
            "call_verification_required": values["call_verification_required"],
        }
        for key in (
            "intake_subject",
            "intake_message",
            "intake_summary",
            "intake_external_ref",
        ):
            value = values.get(key)
            if value is not None:
                args[key] = value
        result = self._client.command(
            "/office/v1/inquiries", args, {}, expected={201}
        )
        inquiry = self._client.get_by_id(_str(result.get("inquiry_id")))
        if inquiry is None:
            _bad_response()
        return inquiry

    def update_inquiry(self, inquiry_id: str, **values: Any) -> Inquiry:
        current = self._client.get_by_id(inquiry_id)
        if current is None:
            raise RemoteCoreError(404, "not_found")
        args: dict[str, object] = {
            "event_date": values["event_date"].isoformat(),
            "crm_stage": values["crm_stage"],
            "time_window_text": values["time_window_text"],
            "location_text": values["location_text"],
            "guest_count_estimate": values["guest_count_estimate"],
            "planning_mode": values["planning_mode"],
        }
        for key in (
            "intake_subject",
            "intake_message",
            "intake_summary",
            "intake_external_ref",
        ):
            if key in values:
                args[key] = values[key]
        expected_at = self._client.form_value("_expect_updated_at")
        self._client.command(
            f"/office/v1/inquiries/{quote(inquiry_id, safe='')}/update",
            args,
            {"updated_at": expected_at or current.updated_at.isoformat()},
            expected={200},
        )
        updated = self._client.get_by_id(inquiry_id)
        if updated is None:
            _bad_response()
        return updated

    def verify_customer_by_call(self, inquiry_id: str) -> Inquiry:
        self._client.command(
            f"/office/v1/inquiries/{quote(inquiry_id, safe='')}/verify",
            {},
            {},
            expected={200},
        )
        inquiry = self._client.get_by_id(inquiry_id)
        if inquiry is None:
            _bad_response()
        return inquiry


class _RemoteOrderService:
    def __init__(self, client: RemoteCoreClient) -> None:
        self._client = client

    def convert_inquiry_to_order(self, inquiry: Inquiry) -> tuple[Order, OrderVersion]:
        result = self._client.command(
            f"/office/v1/inquiries/{quote(inquiry.inquiry_id, safe='')}/convert",
            {},
            {},
            expected={201},
        )
        order_id = _str(result.get("order_id"))
        order = self._client.get_order(order_id)
        versions = self._client.list_order_versions(order_id)
        if order is None or not versions:
            _bad_response()
        return order, versions[0]

    def create_relevant_order_change_version(
        self, order: Order, **values: Any
    ) -> OrderVersion:
        versions = self._client.list_order_versions(order.order_id)
        latest = max((version.version_number for version in versions), default=0)
        expected_latest = self._client.form_value("_expect_latest_version_number")
        result = self._client.command(
            f"/office/v1/orders/{quote(order.order_id, safe='')}/versions",
            {
                "event_date": values["event_date"].isoformat(),
                "time_window_text": values["time_window_text"],
                "location_text": values["location_text"],
                "guest_count_estimate": values["guest_count_estimate"],
                "planning_mode": values["planning_mode"],
            },
            {
                "latest_version_number": (
                    int(expected_latest) if expected_latest is not None else latest
                )
            },
            expected={201},
        )
        version_id = _str(result.get("order_version_id"))
        for version in self._client.list_order_versions(order.order_id):
            if version.order_version_id == version_id:
                return version
        _bad_response()


class _RemoteOperationalCoreService:
    def __init__(self, client: RemoteCoreClient) -> None:
        self._client = client

    def evaluate_ready_to_send(self, order_id: str) -> ReadyToSendEvaluation:
        return self._client.evaluation(order_id)

    def request_ready_to_send(self, order_id: str) -> ReadyToSendEvaluation:
        result = self._client.command(
            f"/office/v1/orders/{quote(order_id, safe='')}/ready",
            {},
            {},
            expected={200},
        )
        evaluation = _dict(result.get("evaluation"))
        return ReadyToSendEvaluation(
            order_id=order_id,
            ready=_bool(evaluation.get("ready")),
            reasons=tuple(_str(v) for v in _list(evaluation.get("reasons"))),
        )

    def confirm_kitchen_print(
        self, order_id: str, order_version_id: str
    ) -> OrderVersion:
        self._client.command(
            f"/office/v1/orders/{quote(order_id, safe='')}/print-confirm",
            {"order_version_id": order_version_id},
            {},
            expected={200},
        )
        for version in self._client.list_order_versions(order_id):
            if version.order_version_id == order_version_id:
                return version
        _bad_response()

    def make_order_version_effective(
        self, order_id: str, order_version_id: str
    ) -> Order:
        current = self._client.get_order(order_id)
        if current is None:
            raise RemoteCoreError(404, "not_found")
        expected_effective = self._client.form_value("_expect_effective_version_id")
        expect_value = (
            current.effective_order_version_id
            if expected_effective is None
            else (expected_effective or None)
        )
        self._client.command(
            f"/office/v1/orders/{quote(order_id, safe='')}/effective",
            {"order_version_id": order_version_id},
            {"current_effective_order_version_id": expect_value},
            expected={200},
        )
        updated = self._client.get_order(order_id)
        if updated is None:
            _bad_response()
        return updated

    def cancel_order(self, order_id: str) -> Order:
        current = self._client.get_order(order_id)
        if current is None:
            raise RemoteCoreError(404, "not_found")
        expected_at = self._client.form_value("_expect_updated_at")
        self._client.command(
            f"/office/v1/orders/{quote(order_id, safe='')}/cancel",
            {},
            {"updated_at": expected_at or current.updated_at.isoformat()},
            expected={200},
        )
        updated = self._client.get_order(order_id)
        if updated is None:
            _bad_response()
        return updated
