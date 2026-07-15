"""Core Office API — the office panel's only path to core.db
(PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1, frozen 38930bf).

stdlib-only, single-threaded (sqlite3 thread affinity, WORKLOG Entry 048),
no outbound HTTP. Every route is a named business read or command mapping
onto the existing services and their gates — no generic CRUD. Bearer is
checked before anything else on every method; commands are atomic with
their idempotency-ledger record; domain events flush only post-commit.

Logs carry route, status, command_id and opaque Core IDs only — never
contacts, addresses, payloads, or tokens (pack §5).
"""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import re
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TypeVar
from urllib.parse import parse_qsl, urlparse

from catering_system.domain.inquiry import (
    ACTIVE_ORDER_CRM_STAGE,
    CRM_PIPELINE,
    derive_inquiry_office_state,
    inquiry_crm_stage_is_compatible_with_active_order,
    validate_crm_stage,
    validate_planning_mode,
)
from catering_system.domain.offer import ACCEPTANCE_CHANNELS, SENT_CHANNELS, AcceptanceChannel, SentChannel
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_payment_reminder import (
    OrderPaymentReminder,
    validate_payment_method,
)
from catering_system.repositories.core_transaction import (
    CoreBusyError,
    CoreCommandExecutor,
    DeferredEventSink,
    open_core_connection,
)
from catering_system.repositories.inquiry_repository import (
    DuplicateExternalReferenceError,
)
from catering_system.repositories.office_api_ledger import (
    OfficeCommandLedger,
    command_fingerprint,
)
from catering_system.repositories.sqlite_inquiry_repository import (
    SQLiteInquiryRepository,
)
from catering_system.repositories.sqlite_offer_repository import (
    SQLiteOfferRepository,
)
from catering_system.repositories.sqlite_order_repository import (
    SQLiteOrderRepository,
)
from catering_system.repositories.sqlite_payment_reminder_repository import (
    SQLitePaymentReminderRepository,
)
from catering_system.services.inquiry_service import (
    InquiryService,
    validate_inquiry_source,
)
from catering_system.services.offer_service import OfferService
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService
from catering_system.services.payment_reminder_service import PaymentReminderService
from catering_system.services.wochenuebersicht_service import WochenuebersichtService
from catering_system.ui import office_api_views as views

_log = logging.getLogger(__name__)

CLIENT_ID = "office-panel"  # per-client token identity (pack §6.1)
_MAX_BODY_BYTES = 64 * 1024
_MAX_PREPARE_OFFER_BODY_BYTES = 256 * 1024
_MAX_RESPONSE_BYTES = 512 * 1024  # pack §4.0 hard response cap
_MAX_Q_CHARS = 200
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_EnumValue = TypeVar("_EnumValue", bound=str)


class ApiError(Exception):
    def __init__(self, status: int, code: str, retry_after: bool = False) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.retry_after = retry_after


def _invalid() -> ApiError:
    return ApiError(400, "invalid_request")


# --- strict JSON / value validation ------------------------------------------


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def strict_json_loads(raw: bytes) -> dict[str, object]:
    try:
        document = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (ValueError, UnicodeDecodeError) as exc:
        raise _invalid() from exc
    if not isinstance(document, dict):
        raise _invalid()
    return document


def _v_str(value: object, max_len: int) -> str:
    if not isinstance(value, str) or len(value) > max_len:
        raise _invalid()
    return value


def _v_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise _invalid()
    return value


def _v_date(value: object) -> date:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise _invalid()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise _invalid() from exc


def _v_optional_date(value: object) -> date | None:
    return None if value is None else _v_date(value)


def _v_optional_str(value: object, max_len: int) -> str | None:
    if value is None:
        return None
    result = _v_str(value, max_len).strip()
    return result or None


def _v_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise _invalid()
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _invalid() from exc
    # pack §4.1: timestamps are ISO-8601 UTC with offset — a naive value or a
    # non-UTC offset is a type violation, not silently accepted (utcoffset() is
    # None for naive datetimes, so this rejects both).
    if parsed.utcoffset() != timedelta(0):
        raise _invalid()
    return parsed


def _v_guest_count(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise _invalid()
    if not 1 <= value <= 2000:
        raise _invalid()
    return value


def _v_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise _invalid()
    return value


def _v_enum(value: object, validator: Callable[[str], _EnumValue]) -> _EnumValue:
    if not isinstance(value, str):
        raise _invalid()
    try:
        return validator(value)
    except (ValueError, TypeError) as exc:
        raise _invalid() from exc


def _v_sent_channel(value: object) -> SentChannel:
    if not isinstance(value, str) or value not in SENT_CHANNELS:
        raise _invalid()
    channel: SentChannel = value
    return channel


def _v_acceptance_channel(value: object) -> AcceptanceChannel:
    if not isinstance(value, str) or value not in ACCEPTANCE_CHANNELS:
        raise _invalid()
    channel: AcceptanceChannel = value
    return channel


def _v_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise _invalid()
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise _invalid() from exc
    # pack §4.3: command_id is a uuid4; every Core-minted id is uuid4 too, so
    # requiring version 4 tightens the contract without rejecting any real id.
    if parsed.version != 4:
        raise _invalid()
    return value


def _exact_keys(mapping: dict[str, object], keys: set[str]) -> None:
    if set(mapping) != keys:
        raise _invalid()


_ABSENT = object()


def _v_intake(
    args: dict[str, object], key: str, cap: int, keep: str | None
) -> str | None:
    """Optional intake string arg (pack §4.4). An omitted key returns `keep`
    — "" on create (the pack default), the current stored value on update so
    an unsent field is preserved, never wiped. An explicit JSON `null` or any
    non-string is a type violation → 400 (exact types, no coercion); an empty
    string is a deliberate clear."""
    value = args.get(key, _ABSENT)
    if value is _ABSENT:
        return keep
    return _v_str(value, cap)


# --- API core ----------------------------------------------------------------


class OfficeApi:
    """All routes against one shared connection; commands run inside the
    CoreCommandExecutor so precondition + write + ledger are atomic."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self.inquiries = SQLiteInquiryRepository.from_connection(connection)
        self.orders = SQLiteOrderRepository.from_connection(connection)
        self.offers = SQLiteOfferRepository.from_connection(connection)
        self.payment_reminders = SQLitePaymentReminderRepository.from_connection(
            connection
        )
        self.ledger = OfficeCommandLedger(connection)
        self.events = DeferredEventSink()
        self.executor = CoreCommandExecutor(connection, self.events)
        self.inquiry_service = InquiryService(self.inquiries, event_sink=self.events)
        self.order_service = OrderService(self.orders)
        self.offer_service = OfferService(
            self.offers,
            self.inquiries,
            self.orders,
            today=views.berlin_today,
        )
        self.payment_reminder_service = PaymentReminderService(
            self.payment_reminders,
            self.orders,
            today=views.berlin_today,
        )
        self.core = OperationalCoreService(self.orders, event_sink=self.events)
        self.week_service = WochenuebersichtService(self.orders)

    # -- reads -----------------------------------------------------------

    def queue_view(self) -> dict[str, object]:
        orders = self.orders.list_orders()
        inquiries = self.inquiries.list_all()
        orders_by_inquiry: dict[str, list[Order]] = {}
        for order in orders:
            orders_by_inquiry.setdefault(order.source_inquiry_id, []).append(order)
        open_inquiries = []
        for inquiry in inquiries:
            state = derive_inquiry_office_state(
                inquiry,
                has_order=inquiry.inquiry_id in orders_by_inquiry,
                has_active_order=any(
                    order.cancelled_at is None
                    for order in orders_by_inquiry.get(inquiry.inquiry_id, [])
                ),
            )
            if state.is_open:
                open_inquiries.append((inquiry, state))
        active = [o for o in orders if o.cancelled_at is None]
        without_print = [
            o
            for o in active
            if not any(
                v.kitchen_print_confirmed_at is not None
                for v in self.orders.list_order_versions(o.order_id)
            )
        ]
        not_effective = [o for o in active if o.effective_order_version_id is None]
        blocked = [
            o for o in active if not self.core.evaluate_ready_to_send(o.order_id).ready
        ]
        cancelled = [o for o in orders if o.cancelled_at is not None]

        iso = views.berlin_today().isocalendar()
        week = self.week_service.get_week_overview(iso.year, iso.week)
        return {
            "attention": {
                # Compatibility key for the local, not-yet-deployed Phase 2
                # transport. Its value now means truthful open inquiries.
                "neue_anfragen": len(open_inquiries),
                "druck_fehlt": len(without_print),
                "nicht_wirksam": len(not_effective),
                "versand_blockiert": len(blocked),
                "storniert": len(cancelled),
            },
            "week": views.week_view(week),
            "neue_anfragen_top": [
                views.inquiry_top_row(inquiry, state)
                for inquiry, state in open_inquiries[: views.TOP_ROWS_CAP]
            ],
            "auftraege_top": [
                views.order_top_row(
                    o,
                    self.orders.list_order_versions(o.order_id),
                    self.core.evaluate_ready_to_send(o.order_id),
                )
                for o in blocked[: views.TOP_ROWS_CAP]
            ],
        }

    def list_inquiries(self, q: str, limit: int, offset: int) -> dict[str, object]:
        orders_by_inquiry: dict[str, list[Order]] = {}
        for order in self.orders.list_orders():
            orders_by_inquiry.setdefault(order.source_inquiry_id, []).append(order)
        matching = [i for i in self.inquiries.list_all() if views.inquiry_matches(i, q)]
        page = matching[offset : offset + limit]
        return {
            "inquiries": [
                views.inquiry_list_row(i, orders_by_inquiry.get(i.inquiry_id, []))
                for i in page
            ],
            "total_count": len(matching),
            "limit": limit,
            "offset": offset,
        }

    def list_orders(self, q: str, limit: int, offset: int) -> dict[str, object]:
        matching = [o for o in self.orders.list_orders() if views.order_matches(o, q)]
        page = matching[offset : offset + limit]
        return {
            "orders": [
                views.order_list_row(
                    o,
                    self.orders.list_order_versions(o.order_id),
                    self.core.evaluate_ready_to_send(o.order_id),
                )
                for o in page
            ],
            "total_count": len(matching),
            "limit": limit,
            "offset": offset,
        }

    def inquiry_detail(self, inquiry_id: str) -> dict[str, object]:
        inquiry = self.inquiries.get_by_id(inquiry_id)
        if inquiry is None:
            raise ApiError(404, "not_found")
        linked = [
            o for o in self.orders.list_orders() if o.source_inquiry_id == inquiry_id
        ]
        return views.inquiry_detail(inquiry, linked)

    def order_detail(self, order_id: str) -> dict[str, object]:
        order = self.orders.get_order(order_id)
        if order is None:
            raise ApiError(404, "not_found")
        return views.order_detail(
            order,
            self.orders.list_order_versions(order_id),
            self.core.evaluate_ready_to_send(order_id),
            self.payment_reminder_service.view(order_id),
        )

    def print_data(self, order_id: str, version_id: str) -> dict[str, object]:
        order = self.orders.get_order(order_id)
        version = self.orders.get_order_version(version_id)
        if order is None or version is None or version.order_id != order_id:
            raise ApiError(404, "not_found")  # no unknown/unowned distinction
        return {
            "order": views.order_summary(order),
            "version": views.order_version_shape(version),
        }

    # -- command helpers ---------------------------------------------------

    def _require_inquiry(self, inquiry_id: str):  # noqa: ANN202
        inquiry = self.inquiries.get_by_id(inquiry_id)
        if inquiry is None:
            raise ApiError(404, "not_found")
        return inquiry

    def _require_order(self, order_id: str) -> Order:
        order = self.orders.get_order(order_id)
        if order is None:
            raise ApiError(404, "not_found")
        return order

    def _require_active_order(self, order_id: str) -> Order:
        order = self._require_order(order_id)
        if order.cancelled_at is not None:
            # API-level gate codifying current UI behavior (pack §4.5)
            raise ApiError(422, "order_cancelled")
        return order

    def _owned_version(self, order_id: str, version_id: str) -> OrderVersion:
        version = self.orders.get_order_version(version_id)
        if version is None or version.order_id != order_id:
            raise ApiError(422, "version_not_owned")
        return version

    def _active_order_for_inquiry(self, inquiry_id: str) -> Order | None:
        for order in self.orders.list_orders():
            if order.source_inquiry_id == inquiry_id and order.cancelled_at is None:
                return order
        return None

    # -- commands (run inside the executor transaction) --------------------

    def cmd_create_inquiry(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        required = _v_bool(args["call_verification_required"])
        try:
            inquiry = self.inquiry_service.create_inquiry(
                event_date=_v_date(args["event_date"]),
                inquiry_source=_v_enum(args["inquiry_source"], validate_inquiry_source),
                crm_stage=CRM_PIPELINE[0],
                customer_linkage={},
                time_window_text=_v_str(args["time_window_text"], 500),
                location_text=_v_str(args["location_text"], 500),
                guest_count_estimate=_v_guest_count(args["guest_count_estimate"]),
                planning_mode=_v_enum(args["planning_mode"], validate_planning_mode),
                call_verification_required=required,
                call_verification_status=("pending" if required else "not_required"),
                intake_subject=_v_intake(args, "intake_subject", 1000, ""),
                intake_message=_v_intake(args, "intake_message", 5000, ""),
                intake_summary=_v_intake(args, "intake_summary", 2000, ""),
                intake_external_ref=_v_intake(args, "intake_external_ref", 200, ""),
            )
        except DuplicateExternalReferenceError as exc:
            raise ApiError(409, "external_ref_conflict") from exc
        return 201, {
            "inquiry_id": inquiry.inquiry_id,
            "updated_at": inquiry.updated_at.isoformat(),
        }

    def cmd_update_inquiry(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        current = self._require_inquiry(path_ids["id"])
        if _v_datetime(expect["updated_at"]) != current.updated_at:
            raise ApiError(409, "stale_state")
        crm_stage = _v_enum(args["crm_stage"], validate_crm_stage)
        if self._active_order_for_inquiry(current.inquiry_id) is not None and not (
            inquiry_crm_stage_is_compatible_with_active_order(crm_stage)
        ):
            raise ApiError(422, "active_order_crm_stage_conflict")
        try:
            updated = self.inquiry_service.update_inquiry(
                current.inquiry_id,
                event_date=_v_date(args["event_date"]),
                crm_stage=crm_stage,
                time_window_text=_v_str(args["time_window_text"], 500),
                location_text=_v_str(args["location_text"], 500),
                guest_count_estimate=_v_guest_count(args["guest_count_estimate"]),
                planning_mode=_v_enum(args["planning_mode"], validate_planning_mode),
                intake_subject=_v_intake(
                    args, "intake_subject", 1000, current.intake_subject
                ),
                intake_message=_v_intake(
                    args, "intake_message", 5000, current.intake_message
                ),
                intake_summary=_v_intake(
                    args, "intake_summary", 2000, current.intake_summary
                ),
                intake_external_ref=_v_intake(
                    args, "intake_external_ref", 200, current.intake_external_ref
                ),
            )
        except DuplicateExternalReferenceError as exc:
            raise ApiError(409, "external_ref_conflict") from exc
        return 200, {
            "inquiry_id": updated.inquiry_id,
            "updated_at": updated.updated_at.isoformat(),
        }

    def cmd_verify(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        self._require_inquiry(path_ids["id"])
        updated = self.inquiry_service.verify_customer_by_call(path_ids["id"])
        return 200, {
            "inquiry_id": updated.inquiry_id,
            "updated_at": updated.updated_at.isoformat(),
        }

    def cmd_convert(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        inquiry = self._require_inquiry(path_ids["id"])
        linked_orders = [
            order
            for order in self.orders.list_orders()
            if order.source_inquiry_id == inquiry.inquiry_id
        ]
        has_active_order = any(order.cancelled_at is None for order in linked_orders)
        state = derive_inquiry_office_state(
            inquiry,
            has_order=bool(linked_orders),
            has_active_order=has_active_order,
        )
        if has_active_order:
            raise ApiError(409, "already_converted")
        if inquiry.crm_stage == "Abgelehnt / verloren":
            raise ApiError(422, "inquiry_rejected")
        if state.next_action != "convert":
            raise ApiError(422, "verification_gate_blocked")
        try:
            order, version = self.order_service.convert_inquiry_to_order(inquiry)
        except sqlite3.IntegrityError:
            # Recognized only when the re-query confirms the cause (pack §4.5)
            if self._active_order_for_inquiry(inquiry.inquiry_id) is not None:
                raise ApiError(409, "already_converted") from None
            raise
        except ValueError as exc:
            raise ApiError(422, "verification_gate_blocked") from exc
        self.inquiry_service.update_inquiry(
            inquiry.inquiry_id,
            crm_stage="Bestätigt / Auftrag",
        )
        return 201, {
            "order_id": order.order_id,
            "order_version_id": version.order_version_id,
        }

    def cmd_prepare_offer(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        snapshot = args.get("snapshot")
        if not isinstance(snapshot, dict):
            raise _invalid()
        try:
            offer = self.offer_service.prepare_offer_version(
                path_ids["id"], snapshot
            )
        except KeyError as exc:
            raise ApiError(404, "not_found") from exc
        except ValueError as exc:
            message = str(exc)
            if "snapshot inquiry_id mismatch" in message:
                raise ApiError(422, "inquiry_id_mismatch") from exc
            if "active order blocks offer preparation" in message:
                raise ApiError(409, "active_order_exists") from exc
            if "offer already exists for inquiry" in message:
                raise ApiError(409, "offer_already_exists") from exc
            raise ApiError(422, "invalid_snapshot") from exc
        except sqlite3.IntegrityError:
            if self.offers.get_by_source_inquiry_id(path_ids["id"]) is not None:
                raise ApiError(409, "offer_already_exists") from None
            raise
        version = offer.versions[0]
        return 201, {
            "offer_id": offer.offer_id,
            "offer_version_id": version.offer_version_id,
            "snapshot_id": version.snapshot_id,
        }

    def cmd_mark_sent(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        offer_id = path_ids["offer_id"]
        offer_version_id = path_ids["version_id"]
        try:
            offer = self.offer_service.record_sent_evidence(
                offer_id,
                offer_version_id,
                sent_at=_v_datetime(args["sent_at"]),
                channel=_v_sent_channel(args["channel"]),
                recipient_reference=_v_str(args["recipient_reference"], 500),
                evidence_reference=_v_str(args["evidence_reference"], 1000),
                recorded_by=CLIENT_ID,
            )
        except KeyError as exc:
            raise ApiError(404, "not_found") from exc
        except ValueError as exc:
            message = str(exc)
            if "sent evidence already exists" in message:
                raise ApiError(409, "sent_evidence_exists") from exc
            if "not a version of offer" in message:
                raise ApiError(422, "version_not_owned") from exc
            if "acceptance blocks sent recording" in message:
                raise ApiError(422, "sent_recording_blocked") from exc
            if "sent recording blocked" in message:
                raise ApiError(422, "sent_recording_blocked") from exc
            raise ApiError(422, "invalid_sent_evidence") from exc
        except sqlite3.IntegrityError:
            if self.offers.get(offer_id) is None:
                raise ApiError(404, "not_found") from None
            raise ApiError(409, "sent_evidence_exists") from None
        evidence = next(
            item
            for item in offer.sent_evidence
            if item.offer_version_id == offer_version_id
        )
        return 200, {
            "offer_id": offer.offer_id,
            "offer_version_id": offer_version_id,
            "sent_at": evidence.sent_at.isoformat(),
        }

    def cmd_record_acceptance(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        offer_id = path_ids["offer_id"]
        offer_version_id = path_ids["version_id"]
        try:
            offer = self.offer_service.record_acceptance_evidence(
                offer_id,
                offer_version_id,
                _v_uuid(args["accepted_variant_id"]),
                accepted_at=_v_datetime(args["accepted_at"]),
                channel=_v_acceptance_channel(args["channel"]),
                evidence_reference=_v_str(args["evidence_reference"], 1000),
                recorded_by=CLIENT_ID,
                note=_v_optional_str(args.get("note"), 20000),
            )
        except KeyError as exc:
            raise ApiError(404, "not_found") from exc
        except ValueError as exc:
            message = str(exc)
            if "acceptance already exists" in message:
                raise ApiError(409, "acceptance_already_exists") from exc
            if "not a version of offer" in message:
                raise ApiError(422, "version_not_owned") from exc
            if "accepted variant does not belong" in message:
                raise ApiError(422, "invalid_variant") from exc
            if "conversion link blocks acceptance" in message:
                raise ApiError(422, "acceptance_blocked") from exc
            if "acceptance blocked" in message:
                raise ApiError(422, "acceptance_blocked") from exc
            raise ApiError(422, "invalid_acceptance_evidence") from exc
        except sqlite3.IntegrityError:
            if self.offers.get(offer_id) is None:
                raise ApiError(404, "not_found") from None
            raise ApiError(409, "acceptance_already_exists") from None
        assert offer.acceptance_evidence is not None
        acceptance = offer.acceptance_evidence
        return 200, {
            "offer_id": offer.offer_id,
            "offer_version_id": offer_version_id,
            "accepted_variant_id": acceptance.accepted_variant_id,
            "acceptance_id": acceptance.acceptance_id,
        }

    def cmd_convert_accepted(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        offer_id = path_ids["offer_id"]
        offer_version_id = path_ids["version_id"]
        accepted_variant_id = _v_uuid(args["accepted_variant_id"])
        acceptance_id = _v_uuid(args["acceptance_id"])
        existing = self.offers.get(offer_id)
        if existing is None:
            raise ApiError(404, "not_found")
        replay = existing.conversion_link is not None
        try:
            offer, order, order_version = self.offer_service.convert_accepted_offer(
                offer_id,
                offer_version_id,
                accepted_variant_id,
                acceptance_id,
            )
        except KeyError as exc:
            raise ApiError(404, "not_found") from exc
        except ValueError as exc:
            message = str(exc)
            if "active order blocks conversion" in message:
                raise ApiError(409, "already_converted") from exc
            if "conversion link already exists" in message:
                raise ApiError(409, "conversion_already_exists") from exc
            if "not a version of offer" in message:
                raise ApiError(422, "version_not_owned") from exc
            if "accepted variant does not belong" in message:
                raise ApiError(422, "invalid_variant") from exc
            if "conversion blocked" in message:
                raise ApiError(422, "conversion_blocked") from exc
            if "inquiry conversion blocked" in message:
                raise ApiError(422, "verification_gate_blocked") from exc
            raise ApiError(422, "conversion_blocked") from exc
        except sqlite3.IntegrityError:
            offer_check = self.offers.get(offer_id)
            if offer_check is None:
                raise ApiError(404, "not_found") from None
            link = offer_check.conversion_link
            if link is not None:
                if (
                    link.offer_version_id == offer_version_id
                    and link.variant_id == accepted_variant_id
                    and link.acceptance_id == acceptance_id
                ):
                    loaded_order = self.orders.get_order(link.order_id)
                    versions = self.orders.list_order_versions(link.order_id)
                    loaded_version = next(
                        (item for item in versions if item.version_number == 1), None
                    )
                    if loaded_order is None or loaded_version is None:
                        raise ApiError(409, "conversion_already_exists") from None
                    offer = offer_check
                    order = loaded_order
                    order_version = loaded_version
                    replay = True
                else:
                    raise ApiError(409, "conversion_already_exists") from None
            elif self._active_order_for_inquiry(offer_check.source_inquiry_id) is not None:
                raise ApiError(409, "already_converted") from None
            else:
                raise
        offer_version = next(
            item
            for item in offer.versions
            if item.offer_version_id == offer_version_id
        )
        self.payment_reminder_service.seed_from_conversion(
            order.order_id,
            offer_version.payment_method,
        )
        self.inquiry_service.update_inquiry(
            offer.source_inquiry_id,
            crm_stage=ACTIVE_ORDER_CRM_STAGE,
        )
        status = 200 if replay else 201
        return status, {
            "offer_id": offer.offer_id,
            "offer_version_id": offer_version_id,
            "accepted_variant_id": accepted_variant_id,
            "acceptance_id": acceptance_id,
            "order_id": order.order_id,
            "order_version_id": order_version.order_version_id,
        }

    def cmd_create_version(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        order = self._require_active_order(path_ids["id"])
        versions = self.orders.list_order_versions(order.order_id)
        latest = max((v.version_number for v in versions), default=0)
        if _v_int(expect["latest_version_number"]) != latest:
            raise ApiError(409, "stale_state")
        try:
            version = self.order_service.create_relevant_order_change_version(
                order,
                event_date=_v_date(args["event_date"]),
                time_window_text=_v_str(args["time_window_text"], 500),
                location_text=_v_str(args["location_text"], 500),
                guest_count_estimate=_v_guest_count(args["guest_count_estimate"]),
                planning_mode=_v_enum(args["planning_mode"], validate_planning_mode),
            )
        except ValueError as exc:
            raise ApiError(422, "order_cancelled") from exc
        return 201, {
            "order_version_id": version.order_version_id,
            "version_number": version.version_number,
        }

    def cmd_print_confirm(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        order = self._require_active_order(path_ids["id"])
        version = self._owned_version(order.order_id, _v_uuid(args["order_version_id"]))
        confirmed = self.core.confirm_kitchen_print(
            order.order_id, version.order_version_id
        )
        assert confirmed.kitchen_print_confirmed_at is not None
        return 200, {
            "order_id": order.order_id,
            "order_version_id": confirmed.order_version_id,
            "kitchen_print_confirmed_at": (
                confirmed.kitchen_print_confirmed_at.isoformat()
            ),
        }

    def cmd_effective(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        order = self._require_active_order(path_ids["id"])
        expected_pointer = expect["current_effective_order_version_id"]
        if expected_pointer is not None and not isinstance(expected_pointer, str):
            raise _invalid()
        if expected_pointer != order.effective_order_version_id:
            raise ApiError(409, "stale_state")
        version = self._owned_version(order.order_id, _v_uuid(args["order_version_id"]))
        try:
            updated = self.core.make_order_version_effective(
                order.order_id, version.order_version_id
            )
        except ValueError as exc:
            raise ApiError(422, "kitchen_print_not_confirmed") from exc
        return 200, {
            "order_id": updated.order_id,
            "effective_order_version_id": updated.effective_order_version_id,
            "updated_at": updated.updated_at.isoformat(),
        }

    def cmd_ready(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        # Unknown order is NOT 404 here: the service reports it as a reason
        # (current behavior, pack §4.4).
        evaluation = self.core.request_ready_to_send(path_ids["id"])
        return 200, {
            "evaluation": {
                "ready": evaluation.ready,
                "reasons": list(evaluation.reasons),
            }
        }

    def cmd_cancel(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        order = self._require_order(path_ids["id"])
        if _v_datetime(expect["updated_at"]) != order.updated_at:
            raise ApiError(409, "stale_state")
        cancelled = self.core.cancel_order(order.order_id)
        assert cancelled.cancelled_at is not None
        return 200, {
            "order_id": cancelled.order_id,
            "cancelled_at": cancelled.cancelled_at.isoformat(),
            "updated_at": cancelled.updated_at.isoformat(),
        }

    def cmd_payment_reminder(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        order = self._require_active_order(path_ids["id"])
        current = self.payment_reminders.get(order.order_id)
        expected_at = expect["updated_at"]
        if expected_at is not None and not isinstance(expected_at, str):
            raise _invalid()
        actual_at = (
            current.updated_at.isoformat()
            if current is not None and current.updated_at is not None
            else None
        )
        if expected_at != actual_at:
            raise ApiError(409, "stale_state")
        try:
            view = self.payment_reminder_service.save(
                OrderPaymentReminder(
                    order_id=order.order_id,
                    payment_method=_v_enum(
                        args["payment_method"], validate_payment_method
                    ),
                    invoice_created=_v_bool(args["invoice_created"]),
                    invoice_number=_v_optional_str(args["invoice_number"], 200),
                    sent_on=_v_optional_date(args["sent_on"]),
                    due_on=_v_optional_date(args["due_on"]),
                    paid_on=_v_optional_date(args["paid_on"]),
                    cash_received=_v_bool(args["cash_received"]),
                )
            )
        except ValueError as exc:
            raise ApiError(422, "invalid_payment_reminder") from exc
        assert view.updated_at is not None
        return 200, {
            "order_id": order.order_id,
            "updated_at": view.updated_at.isoformat(),
        }


# --- command specs: exact args/expect keys per route (pack §4.4) --------------


@dataclass(frozen=True)
class _ArgKeys:
    required: frozenset[str]
    optional: frozenset[str] = frozenset()


@dataclass(frozen=True)
class _CommandSpec:
    handler: str
    args_keys: _ArgKeys
    expect_keys: set[str]


_INTAKE_OPTIONAL = frozenset(
    {"intake_subject", "intake_message", "intake_summary", "intake_external_ref"}
)
_CREATE_ARGS = _ArgKeys(
    required=frozenset(
        {
            "event_date",
            "inquiry_source",
            "time_window_text",
            "location_text",
            "guest_count_estimate",
            "planning_mode",
            "call_verification_required",
        }
    ),
    optional=_INTAKE_OPTIONAL,
)
_UPDATE_ARGS = _ArgKeys(
    required=frozenset(
        {
            "event_date",
            "crm_stage",
            "time_window_text",
            "location_text",
            "guest_count_estimate",
            "planning_mode",
        }
    ),
    optional=_INTAKE_OPTIONAL,
)
_VERSION_ARGS = _ArgKeys(
    required=frozenset(
        {
            "event_date",
            "time_window_text",
            "location_text",
            "guest_count_estimate",
            "planning_mode",
        }
    )
)
_NO_ARGS = _ArgKeys(required=frozenset())
_SNAPSHOT_ARGS = _ArgKeys(required=frozenset({"snapshot"}))
_MARK_SENT_ARGS = _ArgKeys(
    required=frozenset(
        {
            "sent_at",
            "channel",
            "recipient_reference",
            "evidence_reference",
        }
    )
)
_RECORD_ACCEPTANCE_ARGS = _ArgKeys(
    required=frozenset(
        {
            "accepted_variant_id",
            "accepted_at",
            "channel",
            "evidence_reference",
        }
    ),
    optional=frozenset({"note"}),
)
_CONVERT_ACCEPTED_ARGS = _ArgKeys(
    required=frozenset({"accepted_variant_id", "acceptance_id"})
)
_VERSION_ID_ARGS = _ArgKeys(required=frozenset({"order_version_id"}))
_PAYMENT_REMINDER_ARGS = _ArgKeys(
    required=frozenset(
        {
            "payment_method",
            "invoice_created",
            "invoice_number",
            "sent_on",
            "due_on",
            "paid_on",
            "cash_received",
        }
    )
)

_COMMANDS: dict[str, _CommandSpec] = {
    "create_inquiry": _CommandSpec("cmd_create_inquiry", _CREATE_ARGS, set()),
    "update_inquiry": _CommandSpec("cmd_update_inquiry", _UPDATE_ARGS, {"updated_at"}),
    "verify": _CommandSpec("cmd_verify", _NO_ARGS, set()),
    "convert": _CommandSpec("cmd_convert", _NO_ARGS, set()),
    "prepare-offer": _CommandSpec("cmd_prepare_offer", _SNAPSHOT_ARGS, set()),
    "mark-sent": _CommandSpec("cmd_mark_sent", _MARK_SENT_ARGS, set()),
    "record-acceptance": _CommandSpec(
        "cmd_record_acceptance", _RECORD_ACCEPTANCE_ARGS, set()
    ),
    "convert-accepted": _CommandSpec(
        "cmd_convert_accepted", _CONVERT_ACCEPTED_ARGS, set()
    ),
    "versions": _CommandSpec(
        "cmd_create_version", _VERSION_ARGS, {"latest_version_number"}
    ),
    "print-confirm": _CommandSpec("cmd_print_confirm", _VERSION_ID_ARGS, set()),
    "effective": _CommandSpec(
        "cmd_effective", _VERSION_ID_ARGS, {"current_effective_order_version_id"}
    ),
    "ready": _CommandSpec("cmd_ready", _NO_ARGS, set()),
    "cancel": _CommandSpec("cmd_cancel", _NO_ARGS, {"updated_at"}),
    "payment-reminder": _CommandSpec(
        "cmd_payment_reminder", _PAYMENT_REMINDER_ARGS, {"updated_at"}
    ),
}

# route table: (regex, template, {method: kind})
_ROUTES: tuple[tuple[re.Pattern[str], str, dict[str, str]], ...] = (
    (re.compile(r"^/office/v1/queue$"), "/office/v1/queue", {"GET": "queue"}),
    (
        re.compile(r"^/office/v1/inquiries$"),
        "/office/v1/inquiries",
        {"GET": "list_inquiries", "POST": "create_inquiry"},
    ),
    (
        re.compile(r"^/office/v1/inquiries/(?P<id>[^/]+)$"),
        "/office/v1/inquiries/{id}",
        {"GET": "inquiry_detail"},
    ),
    (
        re.compile(r"^/office/v1/inquiries/(?P<id>[^/]+)/update$"),
        "/office/v1/inquiries/{id}/update",
        {"POST": "update_inquiry"},
    ),
    (
        re.compile(r"^/office/v1/inquiries/(?P<id>[^/]+)/verify$"),
        "/office/v1/inquiries/{id}/verify",
        {"POST": "verify"},
    ),
    (
        re.compile(r"^/office/v1/inquiries/(?P<id>[^/]+)/convert$"),
        "/office/v1/inquiries/{id}/convert",
        {"POST": "convert"},
    ),
    (
        re.compile(r"^/office/v1/inquiries/(?P<id>[^/]+)/prepare-offer$"),
        "/office/v1/inquiries/{id}/prepare-offer",
        {"POST": "prepare-offer"},
    ),
    (
        re.compile(
            r"^/office/v1/offers/(?P<offer_id>[^/]+)/versions/"
            r"(?P<version_id>[^/]+)/mark-sent$"
        ),
        "/office/v1/offers/{offer_id}/versions/{version_id}/mark-sent",
        {"POST": "mark-sent"},
    ),
    (
        re.compile(
            r"^/office/v1/offers/(?P<offer_id>[^/]+)/versions/"
            r"(?P<version_id>[^/]+)/record-acceptance$"
        ),
        "/office/v1/offers/{offer_id}/versions/{version_id}/record-acceptance",
        {"POST": "record-acceptance"},
    ),
    (
        re.compile(
            r"^/office/v1/offers/(?P<offer_id>[^/]+)/versions/"
            r"(?P<version_id>[^/]+)/convert-accepted$"
        ),
        "/office/v1/offers/{offer_id}/versions/{version_id}/convert-accepted",
        {"POST": "convert-accepted"},
    ),
    (
        re.compile(r"^/office/v1/orders$"),
        "/office/v1/orders",
        {"GET": "list_orders"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)$"),
        "/office/v1/orders/{id}",
        {"GET": "order_detail"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/print-data$"),
        "/office/v1/orders/{id}/print-data",
        {"GET": "print_data"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/versions$"),
        "/office/v1/orders/{id}/versions",
        {"POST": "versions"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/print-confirm$"),
        "/office/v1/orders/{id}/print-confirm",
        {"POST": "print-confirm"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/effective$"),
        "/office/v1/orders/{id}/effective",
        {"POST": "effective"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/ready$"),
        "/office/v1/orders/{id}/ready",
        {"POST": "ready"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/cancel$"),
        "/office/v1/orders/{id}/cancel",
        {"POST": "cancel"},
    ),
    (
        re.compile(r"^/office/v1/orders/(?P<id>[^/]+)/payment-reminder$"),
        "/office/v1/orders/{id}/payment-reminder",
        {"POST": "payment-reminder"},
    ),
)


def _resolve_route(path: str) -> tuple[str, dict[str, str], dict[str, str]] | None:
    for pattern, template, methods in _ROUTES:
        match = pattern.match(path)
        if match:
            return template, dict(match.groupdict()), methods
    return None


def make_office_api_handler(api: OfficeApi, token: str) -> type[BaseHTTPRequestHandler]:
    expected_auth = f"Bearer {token}"

    class OfficeApiHandler(BaseHTTPRequestHandler):
        server_version = "CoreOfficeAPI/1.0"
        # HTTP/1.0 on purpose: auth-first responses may leave a request body
        # undrained, which under keep-alive corrupts the next request on the
        # same connection (observed in the courier repo); 1.0 closes it.

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

        # -- plumbing --------------------------------------------------

        def _respond(
            self,
            status: int,
            body: dict[str, object],
            *,
            retry_after: bool = False,
            suppress_body: bool = False,
        ) -> None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            # pack §4.0: hard 512 KiB response cap. Pagination and embedded-list
            # caps keep it constructively unreachable, but long legacy Core texts
            # could still bloat a read past it — fail closed rather than emit an
            # oversized body. Checked before any byte is sent, so the caller's
            # try/except turns it into a clean 500 internal.
            if len(payload) > _MAX_RESPONSE_BYTES:
                raise ApiError(500, "internal")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if retry_after:
                self.send_header("Retry-After", "1")
            self.end_headers()
            if not suppress_body:
                self.wfile.write(payload)

        def _error(self, status: int, code: str, *, retry_after: bool = False) -> None:
            self._respond(status, {"error": code}, retry_after=retry_after)

        def _authorized(self) -> bool:
            presented = self.headers.get("Authorization", "")
            return hmac.compare_digest(presented, expected_auth)

        def _auth_or_401(self) -> bool:
            if self._authorized():
                return True
            self._error(401, "unauthorized")
            return False

        def _read_command_body(self, max_bytes: int) -> bytes:
            content_type = self.headers.get("Content-Type", "")
            if content_type.split(";")[0].strip() != "application/json":
                raise ApiError(415, "unsupported_media_type")
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                raise _invalid()
            try:
                length = int(raw_length)
            except ValueError as exc:
                raise _invalid() from exc
            if length <= 0:
                raise _invalid()
            if length > max_bytes:
                raise ApiError(413, "body_too_large")
            body = self.rfile.read(length)
            if len(body) != length:
                raise _invalid()
            return body

        def _reject_get_body(self) -> None:
            raw_length = self.headers.get("Content-Length")
            if raw_length is not None and raw_length not in ("", "0"):
                raise _invalid()

        def _query(self, allowed: set[str]) -> dict[str, str]:
            raw = urlparse(self.path).query
            pairs = parse_qsl(raw, keep_blank_values=True)
            seen: dict[str, str] = {}
            for key, value in pairs:
                if key not in allowed or key in seen:
                    raise _invalid()
                seen[key] = value
            return seen

        def _pagination(self, params: dict[str, str]) -> tuple[int, int]:
            try:
                limit = int(params.get("limit", str(views.LIST_LIMIT_DEFAULT)))
                offset = int(params.get("offset", "0"))
            except ValueError as exc:
                raise _invalid() from exc
            if not 1 <= limit <= views.LIST_LIMIT_MAX or offset < 0:
                raise _invalid()
            return limit, offset

        # -- HTTP methods ----------------------------------------------

        def do_GET(self) -> None:  # noqa: N802
            self._handle("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._handle("POST")

        def do_PUT(self) -> None:  # noqa: N802
            self._method_not_allowed_or_404()

        def do_DELETE(self) -> None:  # noqa: N802
            self._method_not_allowed_or_404()

        def do_PATCH(self) -> None:  # noqa: N802
            self._method_not_allowed_or_404()

        def do_HEAD(self) -> None:  # noqa: N802
            # Explicit handler (pack §4.0): auth first, then 405/404 with
            # full headers; body suppressed but Content-Length preserved.
            if not self._authorized():
                payload = json.dumps({"error": "unauthorized"}).encode("utf-8")
                self.send_response(401)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                return
            path = urlparse(self.path).path
            code = 405 if _resolve_route(path) is not None else 404
            error = "method_not_allowed" if code == 405 else "not_found"
            self._respond(code, {"error": error}, suppress_body=True)

        def do_OPTIONS(self) -> None:  # noqa: N802
            if not self._auth_or_401():
                return
            path = urlparse(self.path).path
            if _resolve_route(path) is not None:
                self._error(405, "method_not_allowed")
            else:
                self._error(404, "not_found")

        def _method_not_allowed_or_404(self) -> None:
            if not self._auth_or_401():
                return
            path = urlparse(self.path).path
            if _resolve_route(path) is not None:
                self._error(405, "method_not_allowed")
            else:
                self._error(404, "not_found")

        def _handle(self, method: str) -> None:
            if not self._auth_or_401():
                return
            path = urlparse(self.path).path
            resolved = _resolve_route(path)
            if resolved is None:
                self._error(404, "not_found")
                return
            template, path_ids, methods = resolved
            kind = methods.get(method)
            if kind is None:
                self._error(405, "method_not_allowed")
                return
            try:
                if method == "GET":
                    self._get(kind, path_ids)
                else:
                    self._command(template, kind, path_ids)
            except CoreBusyError:
                _log.info("command busy route=%s", template)
                self._error(503, "core_busy", retry_after=True)
            except ApiError as exc:
                self._error(exc.status, exc.code)
            except Exception:
                _log.exception("internal error route=%s", template)
                self._error(500, "internal")

        def _get(self, kind: str, path_ids: dict[str, str]) -> None:
            self._reject_get_body()
            if kind == "queue":
                self._query(set())
                self._respond(200, api.queue_view())
            elif kind == "list_inquiries":
                params = self._query({"q", "limit", "offset"})
                q = _v_str(params.get("q", ""), _MAX_Q_CHARS).strip().lower()
                limit, offset = self._pagination(params)
                self._respond(200, api.list_inquiries(q, limit, offset))
            elif kind == "list_orders":
                params = self._query({"q", "limit", "offset"})
                q = _v_str(params.get("q", ""), _MAX_Q_CHARS).strip().lower()
                limit, offset = self._pagination(params)
                self._respond(200, api.list_orders(q, limit, offset))
            elif kind == "inquiry_detail":
                self._query(set())
                self._respond(200, api.inquiry_detail(path_ids["id"]))
            elif kind == "order_detail":
                self._query(set())
                self._respond(200, api.order_detail(path_ids["id"]))
            elif kind == "print_data":
                params = self._query({"version"})
                if "version" not in params:
                    raise _invalid()
                self._respond(
                    200, api.print_data(path_ids["id"], _v_uuid(params["version"]))
                )

        def _command(self, template: str, kind: str, path_ids: dict[str, str]) -> None:
            spec = _COMMANDS[kind]
            max_body = (
                _MAX_PREPARE_OFFER_BODY_BYTES
                if kind == "prepare-offer"
                else _MAX_BODY_BYTES
            )
            raw = self._read_command_body(max_body)
            envelope = strict_json_loads(raw)
            _exact_keys(envelope, {"command_id", "expect", "args"})
            command_id = _v_uuid(envelope["command_id"])
            expect = envelope["expect"]
            args = envelope["args"]
            if not isinstance(expect, dict) or not isinstance(args, dict):
                raise _invalid()
            _exact_keys(expect, spec.expect_keys)
            arg_spec = spec.args_keys
            provided = set(args)
            if not arg_spec.required <= provided:
                raise _invalid()
            if provided - arg_spec.required - arg_spec.optional:
                raise _invalid()

            fingerprint = command_fingerprint(
                template, path_ids, args, expect, CLIENT_ID
            )
            handler = getattr(api, spec.handler)

            def work() -> tuple[int, str]:
                recorded = api.ledger.get(command_id)
                if recorded is not None:
                    if not hmac.compare_digest(recorded.fingerprint, fingerprint):
                        raise ApiError(409, "command_id_conflict")
                    return recorded.result_status, recorded.result_body
                status, result = handler(path_ids, args, expect)
                body = json.dumps(
                    {"command_id": command_id, **result}, ensure_ascii=False
                )
                api.ledger.record(command_id, fingerprint, status, body)
                return status, body

            status, body = api.executor.run(work)
            _log.info(
                "command committed route=%s status=%s command_id=%s",
                template,
                status,
                command_id,
            )
            payload = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)

    return OfficeApiHandler


def create_office_api_server(
    db_path: str, token: str, host: str = "127.0.0.1", port: int = 0
) -> HTTPServer:
    """Build connection, repositories and server in the calling thread —
    single-threaded on purpose (sqlite3 thread affinity, Entry 048)."""
    api = OfficeApi(open_core_connection(db_path))
    return HTTPServer((host, port), make_office_api_handler(api, token))


def main() -> None:
    import os

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        description="Core Office API (PROXMOX pack, Phase 1 — dormant)"
    )
    parser.add_argument("--db", required=True, help="Path to the Core SQLite database")
    parser.add_argument("--host", default="100.109.6.74")
    parser.add_argument("--port", type=int, default=8084)
    args = parser.parse_args()

    token = os.environ.get("OFFICE_API_TOKEN", "")
    if not token:
        raise SystemExit(
            "OFFICE_API_TOKEN is required (root-owned EnvironmentFile, pack §5); "
            "refusing to start unauthenticated"
        )

    server = create_office_api_server(args.db, token, args.host, args.port)
    print(f"Core Office API on http://{args.host}:{args.port}/office/v1/")
    server.serve_forever()


if __name__ == "__main__":
    main()
