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
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any, NoReturn, cast
from urllib.parse import quote, urlencode, urlparse

from catering_system.domain.inquiry import (
    Inquiry,
    InquiryOfficeNextAction,
    validate_call_verification_status,
    validate_crm_stage,
    validate_customer_linkage,
    validate_planning_mode,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_payment_reminder import (
    OrderPaymentReminder,
    PaymentReminderView,
    validate_payment_method,
)
from catering_system.domain.ready_to_send import ReadyToSendEvaluation
from catering_system.services.inquiry_service import validate_inquiry_source

_MAX_RESPONSE_BYTES = 512 * 1024
_READ_TIMEOUT_SECONDS = 3
_COMMAND_TIMEOUT_SECONDS = 5
_PAGE_SIZE = 100

_INQUIRY_SUMMARY_KEYS = frozenset(
    {
        "inquiry_id",
        "event_date",
        "created_at",
        "updated_at",
        "inquiry_source",
        "crm_stage",
        "time_window_text",
        "location_text",
        "guest_count_estimate",
        "planning_mode",
        "call_verification_required",
        "call_verification_status",
    }
)
_INQUIRY_LIST_KEYS = _INQUIRY_SUMMARY_KEYS | {
    "intake_subject",
    "linked_order_id",
    "orders_total_count",
}
_INQUIRY_DETAIL_KEYS = _INQUIRY_LIST_KEYS | {
    "customer_linkage",
    "intake_message",
    "intake_summary",
    "intake_external_ref",
    "allows_conversion",
    "next_action",
    "orders",
    "orders_truncated",
    "offer_prefill",
}
_INQUIRY_DETAIL_OPTIONAL_KEYS = frozenset({"offer"})
_INQUIRY_OFFER_KEYS = frozenset(
    {"offer_id", "offer_version_id", "commercial_state"}
)
_INQUIRY_OFFER_OPTIONAL_KEYS = frozenset({"accepted_variant_id", "acceptance_id"})
_INQUIRY_NEXT_ACTIONS = frozenset(
    {"verify", "convert", "convert-accepted", "offer-pending"}
)
_OFFER_COMMERCIAL_STATES = frozenset(
    {
        "Prepared",
        "Sent",
        "Accepted",
        "Converted",
        "Rejected",
        "Withdrawn",
        "Superseded",
        "Expired",
    }
)
_ORDER_SUMMARY_KEYS = frozenset(
    {
        "order_id",
        "source_inquiry_id",
        "created_at",
        "updated_at",
        "candidate_order_version_id",
        "effective_order_version_id",
        "cancelled_at",
    }
)
_ORDER_LIST_KEYS = _ORDER_SUMMARY_KEYS | {"ready", "blocker_reason", "next_action"}
_ORDER_DETAIL_KEYS = _ORDER_SUMMARY_KEYS | {
    "ready_to_send",
    "payment_reminder",
    "versions",
    "versions_total_count",
    "versions_truncated",
}
_VERSION_KEYS = frozenset(
    {
        "order_version_id",
        "order_id",
        "version_number",
        "created_at",
        "event_date",
        "time_window_text",
        "location_text",
        "guest_count_estimate",
        "planning_mode",
        "kitchen_print_confirmed_at",
    }
)
_ERROR_CODES_BY_STATUS: dict[int, frozenset[str]] = {
    400: frozenset({"invalid_request"}),
    401: frozenset({"unauthorized"}),
    404: frozenset({"not_found"}),
    405: frozenset({"method_not_allowed"}),
    409: frozenset(
        {
            "command_id_conflict",
            "stale_state",
            "already_converted",
            "external_ref_conflict",
            "conversion_already_exists",
        }
    ),
    413: frozenset({"body_too_large"}),
    415: frozenset({"unsupported_media_type"}),
    422: frozenset(
        {
            "active_order_crm_stage_conflict",
            "inquiry_rejected",
            "verification_gate_blocked",
            "order_cancelled",
            "kitchen_print_not_confirmed",
            "version_not_owned",
            "invalid_payment_reminder",
            "conversion_blocked",
            "offer_blocks_conversion",
        }
    ),
    500: frozenset({"internal"}),
    503: frozenset({"core_busy"}),
}


class RemoteCoreError(ValueError):
    """Stable remote failure; never contains response payload or bearer data."""

    def __init__(self, status: int, code: str, *, unavailable: bool = False) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.unavailable = unavailable


@dataclass(frozen=True)
class InquiryDetailMeta:
    orders_total_count: int
    orders_truncated: bool
    next_action: InquiryOfficeNextAction | None = None
    offer: dict[str, object] | None = None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


def _bad_response() -> NoReturn:
    raise RemoteCoreError(502, "invalid_response", unavailable=True)


def _dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        _bad_response()
    return cast(dict[str, object], value)


def _optional_inquiry_next_action(value: object) -> InquiryOfficeNextAction | None:
    if value is None:
        return None
    action = _str(value)
    if action not in _INQUIRY_NEXT_ACTIONS:
        _bad_response()
    return cast(InquiryOfficeNextAction, action)


def _inquiry_offer_projection(value: object) -> dict[str, object]:
    row = _dict(value)
    keys = set(row)
    allowed = _INQUIRY_OFFER_KEYS | _INQUIRY_OFFER_OPTIONAL_KEYS
    if not _INQUIRY_OFFER_KEYS <= keys <= allowed:
        _bad_response()
    _uuid4(row["offer_id"])
    _uuid4(row["offer_version_id"])
    state = _str(row["commercial_state"])
    if state not in _OFFER_COMMERCIAL_STATES:
        _bad_response()
    if "accepted_variant_id" in row:
        _uuid4(row["accepted_variant_id"])
    if "acceptance_id" in row:
        _uuid4(row["acceptance_id"])
    return row


def _exact(data: Mapping[str, object], keys: frozenset[str] | set[str]) -> None:
    if set(data) != set(keys):
        _bad_response()


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        _bad_response()
    return value


def _str(value: object) -> str:
    if not isinstance(value, str):
        _bad_response()
    return value


def _uuid4(value: object) -> str:
    raw = _str(value)
    try:
        parsed = uuid.UUID(raw)
    except ValueError:
        _bad_response()
    if parsed.version != 4 or str(parsed) != raw:
        _bad_response()
    return raw


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return _str(value)


def _optional_uuid4(value: object) -> str | None:
    if value is None:
        return None
    return _uuid4(value)


def _bool(value: object) -> bool:
    if not isinstance(value, bool):
        _bad_response()
    return value


def _int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        _bad_response()
    return value


def _nonnegative_int(value: object) -> int:
    parsed = _int(value)
    if parsed < 0:
        _bad_response()
    return parsed


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _int(value)


def _guest_count(value: object) -> int | None:
    parsed = _optional_int(value)
    if parsed is not None and not 1 <= parsed <= 2000:
        _bad_response()
    return parsed


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


def _inquiry(
    data: Mapping[str, object], *, list_row: bool = False, detail: bool = False
) -> Inquiry:
    if detail:
        keys = set(data)
        allowed = _INQUIRY_DETAIL_KEYS | _INQUIRY_DETAIL_OPTIONAL_KEYS
        if not _INQUIRY_DETAIL_KEYS <= keys <= allowed:
            _bad_response()
    else:
        _exact(
            data,
            _INQUIRY_LIST_KEYS if list_row else _INQUIRY_SUMMARY_KEYS,
        )
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
        inquiry_id=_uuid4(data.get("inquiry_id")),
        event_date=_date(data.get("event_date")),
        created_at=_datetime(data.get("created_at")),
        updated_at=_datetime(data.get("updated_at")),
        inquiry_source=source,
        crm_stage=crm_stage,
        customer_linkage=linkage,
        time_window_text=_str(data.get("time_window_text")),
        location_text=_str(data.get("location_text")),
        guest_count_estimate=_guest_count(data.get("guest_count_estimate")),
        planning_mode=planning_mode,
        call_verification_required=_bool(data.get("call_verification_required")),
        call_verification_status=verification,
        intake_subject=_optional_str(data.get("intake_subject")),
        intake_message=_optional_str(data.get("intake_message")),
        intake_summary=_optional_str(data.get("intake_summary")),
        intake_external_ref=_optional_str(data.get("intake_external_ref")),
    )


def _order(
    data: Mapping[str, object], *, list_row: bool = False, detail: bool = False
) -> Order:
    _exact(
        data,
        _ORDER_DETAIL_KEYS
        if detail
        else (_ORDER_LIST_KEYS if list_row else _ORDER_SUMMARY_KEYS),
    )
    return Order(
        order_id=_uuid4(data.get("order_id")),
        source_inquiry_id=_uuid4(data.get("source_inquiry_id")),
        created_at=_datetime(data.get("created_at")),
        updated_at=_datetime(data.get("updated_at")),
        candidate_order_version_id=_optional_uuid4(
            data.get("candidate_order_version_id")
        ),
        effective_order_version_id=_optional_uuid4(
            data.get("effective_order_version_id")
        ),
        cancelled_at=_optional_datetime(data.get("cancelled_at")),
    )


def _version(data: Mapping[str, object]) -> OrderVersion:
    _exact(data, _VERSION_KEYS)
    try:
        planning_mode = validate_planning_mode(_str(data["planning_mode"]))
    except (KeyError, ValueError):
        _bad_response()
    return OrderVersion(
        order_version_id=_uuid4(data.get("order_version_id")),
        order_id=_uuid4(data.get("order_id")),
        version_number=_nonnegative_int(data.get("version_number")),
        created_at=_datetime(data.get("created_at")),
        event_date=_date(data.get("event_date")),
        time_window_text=_str(data.get("time_window_text")),
        location_text=_str(data.get("location_text")),
        guest_count_estimate=_guest_count(data.get("guest_count_estimate")),
        planning_mode=planning_mode,
        kitchen_print_confirmed_at=_optional_datetime(
            data.get("kitchen_print_confirmed_at")
        ),
    )


def _next_action(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    action = _dict(value)
    _exact(action, {"action", "order_version_id"})
    name = _str(action["action"])
    if name not in {"print-confirm", "effective"}:
        _bad_response()
    return {"action": name, "order_version_id": _uuid4(action["order_version_id"])}


def _ready_evaluation(value: object, order_id: str) -> ReadyToSendEvaluation:
    evaluation = _dict(value)
    _exact(evaluation, {"ready", "reasons"})
    return ReadyToSendEvaluation(
        order_id=order_id,
        ready=_bool(evaluation["ready"]),
        reasons=tuple(_str(reason) for reason in _list(evaluation["reasons"])),
    )


_PAYMENT_REMINDER_KEYS = frozenset(
    {
        "order_id",
        "payment_method",
        "payment_method_label",
        "invoice_created",
        "invoice_number",
        "sent_on",
        "due_on",
        "paid_on",
        "cash_received",
        "invoice_state_label",
        "payment_state_label",
        "next_step",
        "updated_at",
    }
)


def _payment_reminder(value: object, order_id: str) -> PaymentReminderView:
    data = _dict(value)
    _exact(data, _PAYMENT_REMINDER_KEYS)
    if _uuid4(data["order_id"]) != order_id:
        _bad_response()
    method_raw = data["payment_method"]
    try:
        method = (
            None if method_raw is None else validate_payment_method(_str(method_raw))
        )
    except ValueError:
        _bad_response()
    return PaymentReminderView(
        order_id=order_id,
        payment_method=method,
        payment_method_label=_str(data["payment_method_label"]),
        invoice_created=_bool(data["invoice_created"]),
        invoice_number=_optional_str(data["invoice_number"]),
        sent_on=None if data["sent_on"] is None else _date(data["sent_on"]),
        due_on=None if data["due_on"] is None else _date(data["due_on"]),
        paid_on=None if data["paid_on"] is None else _date(data["paid_on"]),
        cash_received=_bool(data["cash_received"]),
        invoice_state_label=_optional_str(data["invoice_state_label"]),
        payment_state_label=_str(data["payment_state_label"]),
        next_step=_optional_str(data["next_step"]),
        updated_at=(
            None if data["updated_at"] is None else _datetime(data["updated_at"])
        ),
    )


def _validate_offer_prefill(value: object) -> None:
    payload = _dict(value)
    _exact(payload, {"schema_version", "source", "inquiry_id", "transfer"})
    if _str(payload["schema_version"]) != "core_inquiry_offer_prefill_v1":
        _bad_response()
    if _str(payload["source"]) != "silberloeffel-core":
        _bad_response()
    _uuid4(payload["inquiry_id"])
    transfer = _dict(payload["transfer"])
    _exact(transfer, {"planning", "orderContextPrefill"})
    planning = _dict(transfer["planning"])
    _exact(
        planning,
        {
            "persons",
            "budget",
            "budgetEnabled",
            "desiredModules",
            "dietaryRequirements",
            "eventType",
            "serviceStyle",
        },
    )
    _guest_count(planning["persons"])
    if planning["budget"] is not None:
        _bad_response()
    _bool(planning["budgetEnabled"])
    if _list(planning["desiredModules"]):
        _bad_response()
    for key in ("dietaryRequirements", "eventType", "serviceStyle"):
        _str(planning[key])
    context = _dict(transfer["orderContextPrefill"])
    _exact(
        context,
        {
            "companyName",
            "contactPerson",
            "email",
            "phone",
            "eventDate",
            "eventTime",
            "location",
            "billingAddress",
            "remarks",
        },
    )
    for item in context.values():
        _str(item)
    _date(context["eventDate"])


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
        self._inquiry_detail_meta: dict[str, InquiryDetailMeta] = {}
        self._order_version_meta: dict[str, tuple[int, bool]] = {}
        self._known_order_ids: list[str] = []
        self._evaluations: dict[str, ReadyToSendEvaluation] = {}
        self.inquiry_service = _RemoteInquiryService(self)
        self.order_service = _RemoteOrderService(self)
        self.payment_reminder_service = _RemotePaymentReminderService(self)
        self.core = _RemoteOperationalCoreService(self)

    def begin_request(self, form: Mapping[str, str] | None = None) -> None:
        self._order_details.clear()
        self._inquiry_detail_meta.clear()
        self._order_version_meta.clear()
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
        timeout = _READ_TIMEOUT_SECONDS if method == "GET" else _COMMAND_TIMEOUT_SECONDS
        try:
            response = self._opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                raise RemoteCoreError(
                    502, "redirect_refused", unavailable=True
                ) from exc
            raw = exc.read(_MAX_RESPONSE_BYTES + 1)
            if (
                exc.headers.get_content_type() != "application/json"
                or len(raw) > _MAX_RESPONSE_BYTES
            ):
                _bad_response()
            try:
                parsed = _dict(json.loads(raw.decode("utf-8")))
                _exact(parsed, {"error"})
                code = _str(parsed["error"])
            except (UnicodeDecodeError, json.JSONDecodeError, RemoteCoreError) as error:
                raise RemoteCoreError(
                    502, "invalid_response", unavailable=True
                ) from error
            if code not in _ERROR_CODES_BY_STATUS.get(exc.code, frozenset()):
                _bad_response()
            raise RemoteCoreError(exc.code, code) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise RemoteCoreError(503, "unreachable", unavailable=True) from exc
        with response:
            if response.status not in expected:
                raise RemoteCoreError(
                    response.status, "unexpected_status", unavailable=True
                )
            if response.headers.get_content_type() != "application/json":
                _bad_response()
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            _bad_response()
        try:
            return _dict(json.loads(raw.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError):
            _bad_response()

    def get(
        self, path: str, query: Mapping[str, object] | None = None
    ) -> dict[str, object]:
        return self._request("GET", path, query=query, expected={200})

    def command(
        self,
        path: str,
        args: Mapping[str, object],
        expect: Mapping[str, object],
        expected: set[int],
        result_keys: set[str],
    ) -> dict[str, object]:
        command_id = self._id()
        result = self._request(
            "POST",
            path,
            body={
                "command_id": command_id,
                "expect": dict(expect),
                "args": dict(args),
            },
            expected=expected,
        )
        _exact(result, result_keys | {"command_id"})
        if _str(result["command_id"]) != command_id:
            _bad_response()
        self._order_details.clear()
        self._inquiry_detail_meta.clear()
        self._order_version_meta.clear()
        self._known_order_ids = []
        self._evaluations.clear()
        return result

    def convert_accepted_offer(
        self,
        offer_id: str,
        offer_version_id: str,
        *,
        accepted_variant_id: str,
        acceptance_id: str,
    ) -> tuple[str, str]:
        result = self.command(
            f"/office/v1/offers/{quote(offer_id, safe='')}/versions/"
            f"{quote(offer_version_id, safe='')}/convert-accepted",
            {
                "accepted_variant_id": accepted_variant_id,
                "acceptance_id": acceptance_id,
            },
            {},
            expected={201, 200},
            result_keys={
                "offer_id",
                "offer_version_id",
                "accepted_variant_id",
                "acceptance_id",
                "order_id",
                "order_version_id",
            },
        )
        if _uuid4(result["offer_id"]) != offer_id:
            _bad_response()
        if _uuid4(result["offer_version_id"]) != offer_version_id:
            _bad_response()
        return _uuid4(result["order_id"]), _uuid4(result["order_version_id"])

    # -- reads / repository-shaped facade ---------------------------------

    def queue_view(self) -> dict[str, object]:
        body = self.get("/office/v1/queue")
        _exact(body, {"attention", "week", "neue_anfragen_top", "auftraege_top"})
        attention = _dict(body["attention"])
        _exact(
            attention,
            {
                "neue_anfragen",
                "druck_fehlt",
                "nicht_wirksam",
                "versand_blockiert",
                "storniert",
            },
        )
        for value in attention.values():
            _nonnegative_int(value)

        week = _dict(body["week"])
        _exact(week, {"iso_year", "iso_week", "entries", "total_count", "truncated"})
        iso_year, iso_week = _int(week["iso_year"]), _int(week["iso_week"])
        try:
            date.fromisocalendar(iso_year, iso_week, 1)
        except ValueError:
            _bad_response()
        entries = _list(week["entries"])
        for raw in entries:
            entry = _dict(raw)
            _exact(
                entry,
                {
                    "order_id",
                    "event_date",
                    "time_window_text",
                    "location_text",
                    "guest_count_estimate",
                },
            )
            _uuid4(entry["order_id"])
            _date(entry["event_date"])
            _str(entry["time_window_text"])
            _str(entry["location_text"])
            _guest_count(entry["guest_count_estimate"])
        total = _nonnegative_int(week["total_count"])
        truncated = _bool(week["truncated"])
        if total < len(entries) or truncated != (total > len(entries)):
            _bad_response()

        inquiry_rows = _list(body["neue_anfragen_top"])
        if len(inquiry_rows) > 5:
            _bad_response()
        for raw in inquiry_rows:
            row = _dict(raw)
            row_keys = set(row)
            allowed = _INQUIRY_SUMMARY_KEYS | {"next_action", "offer"}
            if not (_INQUIRY_SUMMARY_KEYS | {"next_action"}) <= row_keys <= allowed:
                _bad_response()
            _inquiry({key: row[key] for key in _INQUIRY_SUMMARY_KEYS})
            if _str(row["next_action"]) not in _INQUIRY_NEXT_ACTIONS:
                _bad_response()
            if "offer" in row:
                _inquiry_offer_projection(row["offer"])

        order_rows = _list(body["auftraege_top"])
        if len(order_rows) > 5:
            _bad_response()
        for raw in order_rows:
            row = _dict(raw)
            _exact(row, _ORDER_SUMMARY_KEYS | {"blocker_reason", "next_action"})
            _order({key: row[key] for key in _ORDER_SUMMARY_KEYS})
            _optional_str(row["blocker_reason"])
            _next_action(row["next_action"])
        return body

    def work_center(self) -> dict[str, object]:
        body = self.get("/office/v1/work-center")
        _exact(
            body,
            {
                "rueckrufe_open",
                "missed_calls_open",
                "offers_waiting",
                "offers_accepted",
                "upcoming_orders",
                "open_tasks",
                "today_calendar_entries",
            },
        )
        for value in body.values():
            _nonnegative_int(value)
        return body

    def list_offers(self) -> dict[str, object]:
        body = self.get("/office/v1/offers")
        _exact(body, {"offers"})
        rows = _list(body["offers"])
        allowed_states = {
            "Prepared",
            "Sent",
            "Accepted",
            "Converted",
            "Expired",
            "Withdrawn",
            "Rejected",
            "Superseded",
        }
        for raw in rows:
            row = _dict(raw)
            _exact(row, {"offer_id", "inquiry_id", "state", "event_date", "valid_until"})
            _uuid4(row["offer_id"])
            _uuid4(row["inquiry_id"])
            state = _str(row["state"])
            if state not in allowed_states:
                _bad_response()
            _date(row["event_date"])
            _date(row["valid_until"])
        return body

    def offer_detail(self, offer_id: str) -> dict[str, object] | None:
        try:
            body = self.get(f"/office/v1/offers/{quote(offer_id, safe='')}")
        except RemoteCoreError as exc:
            if exc.status == 404:
                return None
            raise
        allowed_states = {
            "Prepared",
            "Sent",
            "Accepted",
            "Converted",
            "Expired",
            "Withdrawn",
            "Rejected",
            "Superseded",
        }
        _exact(
            body,
            {
                "offer_id",
                "inquiry_id",
                "commercial_state",
                "versions",
                "sent_evidence",
                "acceptance",
                "history",
            },
        )
        _uuid4(body["offer_id"])
        _uuid4(body["inquiry_id"])
        state = _str(body["commercial_state"])
        if state not in allowed_states:
            _bad_response()
        if "order_id" in body:
            _uuid4(body["order_id"])
        sent = body["sent_evidence"]
        if sent is not None:
            sent_row = _dict(sent)
            _exact(sent_row, {"sent_at", "channel"})
            _datetime(sent_row["sent_at"])
            _str(sent_row["channel"])
        acceptance = body["acceptance"]
        if acceptance is not None:
            acc_row = _dict(acceptance)
            _exact(acc_row, {"accepted_at", "channel", "accepted_variant_id"})
            _datetime(acc_row["accepted_at"])
            _str(acc_row["channel"])
            _uuid4(acc_row["accepted_variant_id"])
        for raw in _list(body["versions"]):
            version = _dict(raw)
            _exact(
                version,
                {
                    "version",
                    "state",
                    "event_date",
                    "valid_until",
                    "time_window_text",
                    "location_text",
                    "guest_count",
                    "planning_mode",
                    "variants",
                },
            )
            version_state = _str(version["state"])
            if version_state not in allowed_states:
                _bad_response()
            _date(version["event_date"])
            _date(version["valid_until"])
            _str(version["time_window_text"])
            _str(version["location_text"])
            if version["guest_count"] is not None:
                _nonnegative_int(version["guest_count"])
            _str(version["planning_mode"])
            for variant_raw in _list(version["variants"]):
                variant = _dict(variant_raw)
                _exact(variant, {"variant_id", "name"})
                _uuid4(variant["variant_id"])
                _str(variant["name"])
        for raw in _list(body["history"]):
            entry = _dict(raw)
            _exact(entry, {"at", "label"})
            _datetime(entry["at"])
            _str(entry["label"])
        return body

    def list_contacts(self) -> dict[str, object]:
        body = self.get("/office/v1/contacts")
        _exact(body, {"contacts"})
        allowed_sources = {
            "linkage_contact",
            "linkage_customer",
            "intake_email",
            "intake_phone",
            "inquiry",
        }
        for raw in _list(body["contacts"]):
            row = _dict(raw)
            _exact(
                row,
                {
                    "contact_key",
                    "identity_source",
                    "display_name",
                    "email",
                    "phone",
                    "inquiry_count",
                    "open_inquiries",
                    "active_orders",
                    "last_activity",
                },
            )
            _str(row["contact_key"])
            source = _str(row["identity_source"])
            if source not in allowed_sources:
                _bad_response()
            _str(row["display_name"])
            _optional_str(row["email"])
            _optional_str(row["phone"])
            _nonnegative_int(row["inquiry_count"])
            _nonnegative_int(row["open_inquiries"])
            _nonnegative_int(row["active_orders"])
            _datetime(row["last_activity"])
        return body

    def contact_detail(self, contact_key: str) -> dict[str, object] | None:
        try:
            body = self.get(
                f"/office/v1/contacts/{quote(contact_key, safe='')}"
            )
        except RemoteCoreError as exc:
            if exc.status == 404:
                return None
            raise
        allowed_sources = {
            "linkage_contact",
            "linkage_customer",
            "intake_email",
            "intake_phone",
            "inquiry",
        }
        allowed_offer_states = {
            "Prepared",
            "Sent",
            "Accepted",
            "Converted",
            "Expired",
            "Withdrawn",
            "Rejected",
            "Superseded",
        }
        _exact(
            body,
            {
                "contact_key",
                "identity_source",
                "display_name",
                "email",
                "phone",
                "inquiry_count",
                "open_inquiries",
                "active_orders",
                "last_activity",
                "inquiry_ids",
                "inquiries",
                "offers",
                "orders",
            },
        )
        if _str(body["contact_key"]) != contact_key:
            _bad_response()
        if _str(body["identity_source"]) not in allowed_sources:
            _bad_response()
        _datetime(body["last_activity"])
        for raw in _list(body["inquiry_ids"]):
            _uuid4(raw)
        for raw in _list(body["inquiries"]):
            row = _dict(raw)
            _exact(
                row,
                {
                    "inquiry_id",
                    "intake_subject",
                    "event_date",
                    "crm_stage",
                    "is_open",
                },
            )
            _uuid4(row["inquiry_id"])
            _optional_str(row["intake_subject"])
            _date(row["event_date"])
            _str(row["crm_stage"])
            _bool(row["is_open"])
        for raw in _list(body["offers"]):
            row = _dict(raw)
            _exact(row, {"offer_id", "inquiry_id", "state"})
            _uuid4(row["offer_id"])
            _uuid4(row["inquiry_id"])
            if _str(row["state"]) not in allowed_offer_states:
                _bad_response()
        for raw in _list(body["orders"]):
            row = _dict(raw)
            _exact(row, {"order_id", "inquiry_id", "cancelled_at"})
            _uuid4(row["order_id"])
            _uuid4(row["inquiry_id"])
            _optional_datetime(row["cancelled_at"])
        return body

    def list_emails(self) -> dict[str, object]:
        body = self.get("/office/v1/emails")
        _exact(body, {"emails"})
        for raw in _list(body["emails"]):
            row = _dict(raw)
            _exact(
                row,
                {
                    "email_id",
                    "inquiry_id",
                    "contact_key",
                    "sender_email",
                    "subject",
                    "preview",
                    "received_at",
                    "external_ref",
                    "linked_offer_id",
                    "linked_order_ids",
                },
            )
            inquiry_id = _uuid4(row["inquiry_id"])
            if _uuid4(row["email_id"]) != inquiry_id:
                _bad_response()
            _str(row["contact_key"])
            _optional_str(row["sender_email"])
            _str(row["subject"])
            _str(row["preview"])
            _datetime(row["received_at"])
            _optional_str(row["external_ref"])
            _optional_uuid4(row["linked_offer_id"])
            for order_id in _list(row["linked_order_ids"]):
                _uuid4(order_id)
        return body

    def email_detail(self, inquiry_id: str) -> dict[str, object] | None:
        try:
            body = self.get(f"/office/v1/emails/{quote(inquiry_id, safe='')}")
        except RemoteCoreError as exc:
            if exc.status == 404:
                return None
            raise
        _exact(
            body,
            {
                "email_id",
                "inquiry_id",
                "contact_key",
                "sender_email",
                "subject",
                "preview",
                "received_at",
                "external_ref",
                "linked_offer_id",
                "linked_order_ids",
            },
        )
        if _uuid4(body["inquiry_id"]) != inquiry_id:
            _bad_response()
        if _uuid4(body["email_id"]) != inquiry_id:
            _bad_response()
        _str(body["contact_key"])
        _optional_str(body["sender_email"])
        _str(body["subject"])
        _str(body["preview"])
        _datetime(body["received_at"])
        _optional_str(body["external_ref"])
        _optional_uuid4(body["linked_offer_id"])
        for order_id in _list(body["linked_order_ids"]):
            _uuid4(order_id)
        return body

    def list_tasks(self) -> dict[str, object]:
        body = self.get("/office/v1/tasks")
        _exact(body, {"tasks"})
        allowed_categories = {
            "verify",
            "convert",
            "convert_accepted",
            "order_print",
            "order_effective",
            "payment",
        }
        allowed_entities = {"inquiry", "offer", "order"}
        allowed_urgency = {"overdue", "normal"}
        for raw in _list(body["tasks"]):
            row = _dict(raw)
            _exact(
                row,
                {
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
                },
            )
            _str(row["task_id"])
            if _str(row["category"]) not in allowed_categories:
                _bad_response()
            _str(row["title"])
            _str(row["subtitle"])
            if _str(row["entity_type"]) not in allowed_entities:
                _bad_response()
            _str(row["entity_id"])
            _str(row["action_label"])
            _str(row["action_href"])
            if row["due_at"] is not None:
                _date(row["due_at"])
            if _str(row["urgency"]) not in allowed_urgency:
                _bad_response()
            _datetime(row["opened_at"])
        return body

    def _validate_page(
        self,
        page: dict[str, object],
        item_key: str,
        offset: int,
    ) -> list[object]:
        _exact(page, {item_key, "total_count", "limit", "offset"})
        if _int(page["limit"]) != _PAGE_SIZE or _int(page["offset"]) != offset:
            _bad_response()
        items = _list(page[item_key])
        total = _nonnegative_int(page["total_count"])
        if len(items) > _PAGE_SIZE or total < offset + len(items):
            _bad_response()
        return items

    def list_all(self) -> list[Inquiry]:
        rows: list[Inquiry] = []
        offset = 0
        while True:
            page = self.get(
                "/office/v1/inquiries", {"limit": _PAGE_SIZE, "offset": offset}
            )
            items = self._validate_page(page, "inquiries", offset)
            for item in items:
                data = _dict(item)
                rows.append(_inquiry(data, list_row=True))
                _optional_uuid4(data["linked_order_id"])
                _nonnegative_int(data["orders_total_count"])
            total = _int(page["total_count"])
            offset += len(items)
            if offset >= total or not items:
                if rows != sorted(
                    rows, key=lambda inquiry: (inquiry.event_date, inquiry.inquiry_id)
                ):
                    _bad_response()
                return rows

    def get_by_id(self, inquiry_id: str) -> Inquiry | None:
        try:
            detail = self.get(f"/office/v1/inquiries/{quote(inquiry_id, safe='')}")
            inquiry = _inquiry(detail, detail=True)
            detail_keys = set(detail)
            allowed = _INQUIRY_DETAIL_KEYS | _INQUIRY_DETAIL_OPTIONAL_KEYS
            if not _INQUIRY_DETAIL_KEYS <= detail_keys <= allowed:
                _bad_response()
            _optional_uuid4(detail["linked_order_id"])
            total = _nonnegative_int(detail["orders_total_count"])
            truncated = _bool(detail["orders_truncated"])
            orders = _list(detail["orders"])
            if total < len(orders) or truncated != (total > len(orders)):
                _bad_response()
            for raw in orders:
                row = _dict(raw)
                _exact(row, {"order_id", "cancelled_at"})
                _uuid4(row["order_id"])
                _optional_datetime(row["cancelled_at"])
            _bool(detail["allows_conversion"])
            next_action = _optional_inquiry_next_action(detail.get("next_action"))
            offer = (
                _inquiry_offer_projection(detail["offer"])
                if "offer" in detail
                else None
            )
            _validate_offer_prefill(detail["offer_prefill"])
            if _uuid4(_dict(detail["offer_prefill"])["inquiry_id"]) != inquiry_id:
                _bad_response()
            self._inquiry_detail_meta[inquiry_id] = InquiryDetailMeta(
                orders_total_count=total,
                orders_truncated=truncated,
                next_action=next_action,
                offer=offer,
            )
            return inquiry
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
            items = self._validate_page(page, "orders", offset)
            for item in items:
                data = _dict(item)
                order = _order(data, list_row=True)
                rows.append(order)
                self._known_order_ids.append(order.order_id)
                reason = data["blocker_reason"]
                _next_action(data["next_action"])
                self._evaluations[order.order_id] = ReadyToSendEvaluation(
                    order_id=order.order_id,
                    ready=_bool(data["ready"]),
                    reasons=() if reason is None else (_str(reason),),
                )
            total = _int(page["total_count"])
            offset += len(items)
            if offset >= total or not items:
                if rows != sorted(rows, key=lambda order: order.order_id):
                    _bad_response()
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
        _order(detail, detail=True)
        self._evaluations[order_id] = _ready_evaluation(
            detail["ready_to_send"], order_id
        )
        _payment_reminder(detail["payment_reminder"], order_id)
        versions = _list(detail["versions"])
        total = _nonnegative_int(detail["versions_total_count"])
        truncated = _bool(detail["versions_truncated"])
        if total < len(versions) or truncated != (total > len(versions)):
            _bad_response()
        parsed_versions = [_version(_dict(raw)) for raw in versions]
        for version in parsed_versions:
            if version.order_id != order_id:
                _bad_response()
        numbers = [version.version_number for version in parsed_versions]
        if numbers != sorted(numbers) or len(numbers) != len(set(numbers)):
            _bad_response()
        self._order_version_meta[order_id] = (total, truncated)
        return detail

    def get_order(self, order_id: str) -> Order | None:
        detail = self._order_detail(order_id)
        return None if detail is None else _order(detail, detail=True)

    def list_order_versions(self, order_id: str) -> list[OrderVersion]:
        detail = self._order_detail(order_id)
        if detail is None:
            return []
        return [_version(_dict(row)) for row in _list(detail.get("versions"))]

    def inquiry_detail_meta(self, inquiry_id: str) -> InquiryDetailMeta:
        return self._inquiry_detail_meta.get(
            inquiry_id,
            InquiryDetailMeta(orders_total_count=0, orders_truncated=False),
        )

    def inquiry_orders_meta(self, inquiry_id: str) -> tuple[int, bool]:
        meta = self.inquiry_detail_meta(inquiry_id)
        return meta.orders_total_count, meta.orders_truncated

    def order_versions_meta(self, order_id: str) -> tuple[int, bool]:
        return self._order_version_meta.get(order_id, (0, False))

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

    def payment_reminder_view(self, order_id: str) -> PaymentReminderView:
        detail = self._order_detail(order_id)
        if detail is None:
            raise RemoteCoreError(404, "not_found")
        return _payment_reminder(detail["payment_reminder"], order_id)

    def print_data(
        self, order_id: str, version_id: str
    ) -> tuple[Order, OrderVersion] | None:
        try:
            body = self.get(
                f"/office/v1/orders/{quote(order_id, safe='')}/print-data",
                {"version": version_id},
            )
        except RemoteCoreError as exc:
            if exc.status == 404:
                return None
            raise
        _exact(body, {"order", "version"})
        order = _order(_dict(body["order"]))
        version = _version(_dict(body["version"]))
        if order.order_id != order_id or version.order_id != order_id:
            _bad_response()
        return order, version

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
            "/office/v1/inquiries",
            args,
            {},
            expected={201},
            result_keys={"inquiry_id", "updated_at"},
        )
        timestamp = _datetime(result["updated_at"])
        # Only the id is consumed before the redirect.  Returning the
        # submitted snapshot avoids a post-commit GET which could fail after
        # the write and produce the false message "nothing was saved".
        return Inquiry(
            inquiry_id=_uuid4(result["inquiry_id"]),
            event_date=values["event_date"],
            created_at=timestamp,
            updated_at=timestamp,
            inquiry_source=validate_inquiry_source(values["inquiry_source"]),
            crm_stage=validate_crm_stage(values["crm_stage"]),
            customer_linkage=validate_customer_linkage(values["customer_linkage"]),
            time_window_text=values["time_window_text"],
            location_text=values["location_text"],
            guest_count_estimate=values["guest_count_estimate"],
            planning_mode=validate_planning_mode(values["planning_mode"]),
            call_verification_required=values["call_verification_required"],
            call_verification_status=validate_call_verification_status(
                values["call_verification_status"]
            ),
            intake_subject=values.get("intake_subject"),
            intake_message=values.get("intake_message"),
            intake_summary=values.get("intake_summary"),
            intake_external_ref=values.get("intake_external_ref"),
        )

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
        result = self._client.command(
            f"/office/v1/inquiries/{quote(inquiry_id, safe='')}/update",
            args,
            {"updated_at": expected_at or current.updated_at.isoformat()},
            expected={200},
            result_keys={"inquiry_id", "updated_at"},
        )
        if _uuid4(result["inquiry_id"]) != inquiry_id:
            _bad_response()
        return replace(
            current,
            event_date=values["event_date"],
            crm_stage=validate_crm_stage(values["crm_stage"]),
            time_window_text=values["time_window_text"],
            location_text=values["location_text"],
            guest_count_estimate=values["guest_count_estimate"],
            planning_mode=validate_planning_mode(values["planning_mode"]),
            updated_at=_datetime(result["updated_at"]),
            intake_subject=values.get("intake_subject", current.intake_subject),
            intake_message=values.get("intake_message", current.intake_message),
            intake_summary=values.get("intake_summary", current.intake_summary),
            intake_external_ref=values.get(
                "intake_external_ref", current.intake_external_ref
            ),
        )

    def verify_customer_by_call(self, inquiry_id: str) -> Inquiry:
        current = self._client.get_by_id(inquiry_id)
        if current is None:
            raise RemoteCoreError(404, "not_found")
        result = self._client.command(
            f"/office/v1/inquiries/{quote(inquiry_id, safe='')}/verify",
            {},
            {},
            expected={200},
            result_keys={"inquiry_id", "updated_at"},
        )
        if _uuid4(result["inquiry_id"]) != inquiry_id:
            _bad_response()
        return replace(
            current,
            call_verification_status="verified",
            updated_at=_datetime(result["updated_at"]),
        )


class _RemoteOrderService:
    def __init__(self, client: RemoteCoreClient) -> None:
        self._client = client

    def convert_inquiry_to_order(self, inquiry: Inquiry) -> tuple[Order, OrderVersion]:
        result = self._client.command(
            f"/office/v1/inquiries/{quote(inquiry.inquiry_id, safe='')}/convert",
            {},
            {},
            expected={201},
            result_keys={"order_id", "order_version_id"},
        )
        order_id = _uuid4(result["order_id"])
        version_id = _uuid4(result["order_version_id"])
        # These snapshots are redirect-only return values; Core remains the
        # authority and the following GET request renders the persisted data.
        order = Order(
            order_id=order_id,
            source_inquiry_id=inquiry.inquiry_id,
            created_at=inquiry.updated_at,
            updated_at=inquiry.updated_at,
        )
        version = OrderVersion(
            order_version_id=version_id,
            order_id=order_id,
            version_number=1,
            created_at=inquiry.updated_at,
            event_date=inquiry.event_date,
            time_window_text=inquiry.time_window_text,
            location_text=inquiry.location_text,
            guest_count_estimate=inquiry.guest_count_estimate,
            planning_mode=inquiry.planning_mode,
        )
        return order, version

    def create_relevant_order_change_version(
        self, order: Order, **values: Any
    ) -> OrderVersion:
        versions = self._client.list_order_versions(order.order_id)
        total_count, _truncated = self._client.order_versions_meta(order.order_id)
        latest = total_count or max(
            (version.version_number for version in versions), default=0
        )
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
            result_keys={"order_version_id", "version_number"},
        )
        return OrderVersion(
            order_version_id=_uuid4(result["order_version_id"]),
            order_id=order.order_id,
            version_number=_int(result["version_number"]),
            created_at=order.updated_at,
            event_date=values["event_date"],
            time_window_text=values["time_window_text"],
            location_text=values["location_text"],
            guest_count_estimate=values["guest_count_estimate"],
            planning_mode=validate_planning_mode(values["planning_mode"]),
        )


class _RemotePaymentReminderService:
    def __init__(self, client: RemoteCoreClient) -> None:
        self._client = client

    def view(self, order_id: str) -> PaymentReminderView:
        return self._client.payment_reminder_view(order_id)

    def save(self, reminder: OrderPaymentReminder) -> PaymentReminderView:
        expected_at = self._client.form_value("_expect_payment_reminder_updated_at")
        current = self.view(reminder.order_id)
        result = self._client.command(
            f"/office/v1/orders/{quote(reminder.order_id, safe='')}/payment-reminder",
            {
                "payment_method": reminder.payment_method,
                "invoice_created": reminder.invoice_created,
                "invoice_number": reminder.invoice_number,
                "sent_on": reminder.sent_on.isoformat() if reminder.sent_on else None,
                "due_on": reminder.due_on.isoformat() if reminder.due_on else None,
                "paid_on": reminder.paid_on.isoformat() if reminder.paid_on else None,
                "cash_received": reminder.cash_received,
            },
            {
                "updated_at": (
                    expected_at
                    if expected_at
                    else (
                        current.updated_at.isoformat() if current.updated_at else None
                    )
                )
            },
            expected={200},
            result_keys={"order_id", "updated_at"},
        )
        if _uuid4(result["order_id"]) != reminder.order_id:
            _bad_response()
        return replace(current, updated_at=_datetime(result["updated_at"]))


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
            result_keys={"evaluation"},
        )
        return _ready_evaluation(result["evaluation"], order_id)

    def confirm_kitchen_print(
        self, order_id: str, order_version_id: str
    ) -> OrderVersion:
        versions = self._client.list_order_versions(order_id)
        current = next(
            (
                version
                for version in versions
                if version.order_version_id == order_version_id
            ),
            None,
        )
        if current is None:
            raise RemoteCoreError(422, "version_not_owned")
        result = self._client.command(
            f"/office/v1/orders/{quote(order_id, safe='')}/print-confirm",
            {"order_version_id": order_version_id},
            {},
            expected={200},
            result_keys={
                "order_id",
                "order_version_id",
                "kitchen_print_confirmed_at",
            },
        )
        if (
            _uuid4(result["order_id"]) != order_id
            or _uuid4(result["order_version_id"]) != order_version_id
        ):
            _bad_response()
        return replace(
            current,
            kitchen_print_confirmed_at=_datetime(result["kitchen_print_confirmed_at"]),
        )

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
        result = self._client.command(
            f"/office/v1/orders/{quote(order_id, safe='')}/effective",
            {"order_version_id": order_version_id},
            {"current_effective_order_version_id": expect_value},
            expected={200},
            result_keys={"order_id", "effective_order_version_id", "updated_at"},
        )
        if (
            _uuid4(result["order_id"]) != order_id
            or _uuid4(result["effective_order_version_id"]) != order_version_id
        ):
            _bad_response()
        return replace(
            current,
            effective_order_version_id=order_version_id,
            updated_at=_datetime(result["updated_at"]),
        )

    def cancel_order(self, order_id: str) -> Order:
        current = self._client.get_order(order_id)
        if current is None:
            raise RemoteCoreError(404, "not_found")
        expected_at = self._client.form_value("_expect_updated_at")
        result = self._client.command(
            f"/office/v1/orders/{quote(order_id, safe='')}/cancel",
            {},
            {"updated_at": expected_at or current.updated_at.isoformat()},
            expected={200},
            result_keys={"order_id", "cancelled_at", "updated_at"},
        )
        if _uuid4(result["order_id"]) != order_id:
            _bad_response()
        return replace(
            current,
            cancelled_at=_datetime(result["cancelled_at"]),
            updated_at=_datetime(result["updated_at"]),
        )
