"""Office panel — primary office write surface (OFFICE_PANEL_EXECUTION_PACK_V1).

Thin server-rendered skin over existing Core services; adds no domain semantics
(pack §1). LAN-only write surface with mandatory basic auth (§3, §7). Blocked
reasons are rendered from two separate vocabularies that are never merged (§5):
progression (B7) on inquiry views, operational gate on order views.
"""

from __future__ import annotations

import argparse
import os
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote

from catering_system.integration.auerswald_sync import fetch_missed_board

from catering_system.domain.inquiry import (
    ACTIVE_ORDER_CRM_STAGE,
    CRM_PIPELINE,
    PLANNING_MODES,
    Inquiry,
    InquiryOfficeState,
    inquiry_crm_stage_is_compatible_with_active_order,
    inquiry_shows_convert_accepted_button,
    inquiry_allows_convert_accepted_command,
    validate_crm_stage,
)
from catering_system.services.offer_service import OfferService
from catering_system.domain.offer import (
    ACCEPTANCE_CHANNELS,
    SENT_CHANNELS,
    AcceptanceChannel,
    SentChannel,
    offer_blocks_direct_inquiry_conversion,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.domain.order_payment_reminder import (
    PAYMENT_METHOD_LABELS,
    PAYMENT_METHODS,
    OrderPaymentReminder,
    validate_payment_method,
)
from catering_system.repositories.in_memory_offer_repository import (
    InMemoryOfferRepository,
)
from catering_system.repositories.in_memory_payment_reminder_repository import (
    InMemoryPaymentReminderRepository,
)
from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.offer_repository import OfferRepository
from catering_system.repositories.order_repository import OrderRepository
from catering_system.repositories.payment_reminder_repository import (
    PaymentReminderRepository,
)
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.operational_core_service import OperationalCoreService
from catering_system.services.order_service import OrderService
from catering_system.services.payment_reminder_service import PaymentReminderService
from catering_system.services.progression_service import ProgressionService
from catering_system.services.wochenuebersicht_service import WochenuebersichtService
from catering_system.ui import office_api_views as api_views
from catering_system.domain.work_center import WorkCenterSnapshot
from catering_system.services.contact_projection_service import ContactProjectionService
from catering_system.services.email_intake_projection_service import (
    EmailIntakeProjectionService,
)
from catering_system.services.calendar_projection_service import (
    CalendarProjectionService,
)
from catering_system.services.task_projection_service import TaskProjectionService
from catering_system.services.work_center_service import WorkCenterService
from catering_system.ui.office_panel_dashboard import (
    WorkCenterDashboardUi,
    render_work_center_arbeitszentrale,
)
from catering_system.ui.office_panel_contact_detail import render_kontakt_detail
from catering_system.ui.office_panel_contacts_list import render_kontakte_list
from catering_system.ui.office_panel_email_detail import render_email_detail
from catering_system.ui.office_panel_emails_list import render_email_list
from catering_system.ui.office_panel_calendar_list import render_kalender_list
from catering_system.ui.office_panel_tasks_list import render_aufgaben_list
from catering_system.ui.office_panel_offer_detail import (
    OfferDetailFormFields,
    render_offer_detail,
)
from catering_system.ui.office_panel_offers_list import render_angebote_list
from catering_system.ui.office_panel_inquiry_detail import (
    InquiryDetailFormFields,
    render_inquiry_detail,
)
from catering_system.ui.office_panel_order_detail import (
    OrderDetailFormFields,
    render_order_detail,
    version_change_prefill,
)
from catering_system.ui.office_panel_proposal import (
    parse_proposal_payload,
    render_proposal_preview,
    render_proposal_preview_form,
)
from catering_system.ui.office_panel_offer_prefill import (
    build_offer_prefill_url,
    normalize_configurator_url,
)
from catering_system.ui.office_panel_views import (
    CALL_VERIFICATION_STATUS_LABELS,
    PROGRESSION_BLOCKER_LABELS,
    READY_TO_SEND_BLOCKER_LABELS,
    SOURCE_LABELS,
    OfficePageContext,
    _csrf_input,
    _e,
    _EMPTY_PAGE_CONTEXT,
    parse_datetime_local_berlin,
    format_datetime_utc_iso,
    _crm_stage_select,
    _page,
    _planning_mode_select,
    _progression_blocker_label,
    _ready_to_send_blocker_label,
    _source_label,
    _verification_label,
    render_print_sheet,
    render_buffet_cards,
)

if TYPE_CHECKING:
    from catering_system.repositories.core_transaction import CoreCommandExecutor
    from catering_system.ui.remote_core_client import RemoteCoreClient

__all__ = [
    "CALL_VERIFICATION_STATUS_LABELS",
    "PROGRESSION_BLOCKER_LABELS",
    "READY_TO_SEND_BLOCKER_LABELS",
    "SOURCE_LABELS",
    "parse_proposal_payload",
    "render_print_sheet",
    "render_buffet_cards",
    "render_proposal_preview",
    "render_proposal_preview_form",
]

# Office-visible subset of InquirySource (domain/inquiry.py) — deliberately
# narrower than InquiryService._ALLOWED_SOURCES (INQUIRY_INTAKE_CONTEXT_FIELDS
# _IMPLEMENTATION_PACK_V1 §3/§6): phone/wix_form stay legacy/adapter-only
# (src/catering_system/intake/phone_adapter.py, wix_form_adapter.py already
# write them through the validated path), missed_call/ai_telefonist stay
# adapter-only until their own integration exists — nothing writes them yet,
# so offering them here would be misleading.
_OFFICE_SOURCES = ("manual", "phone_by_office", "email", "website_form", "configurator")

# -- Rückrufe: read-only pull from the separate auerswald-sync call-log
# service (own repo/server, NOT Core, NOT EspoCRM). Pre-inquiry office signal
# only — never writes into Core, never creates an Inquiry automatically. The
# only write this makes is the office-initiated "erledigt" resolve, which
# goes to auerswald-sync's own /missed/resolve, not to Core.


def fetch_rueckruf_count(url: str, user: str, password: str) -> int | None:
    """Sidebar badge count. Same source/call as the Rückrufliste page itself
    (fetch_missed_board) — not a second data source or a new business rule,
    just its length. None means "show no badge": unconfigured, unreachable,
    or genuinely zero open callbacks all render the same (nothing to flag)."""
    items, error = fetch_missed_board(url, user, password)
    if error or not items:
        return None
    return len(items)


_RUECKRUF_SUBTITLE = (
    '<p class="subtitle">Verpasste Anrufe sowie Anrufe außerhalb der Bürozeiten, '
    "die einen Rückruf erfordern.</p>"
)


def render_rueckruf(
    items: list[dict] | None,
    error: str | None,
    *,
    context: OfficePageContext = _EMPTY_PAGE_CONTEXT,
) -> str:
    if error:
        body = _RUECKRUF_SUBTITLE + (
            f'<p class="blocked">Rückrufliste nicht erreichbar: {_e(error)}</p>'
            "<p>Prüfe AUERSWALD_SYNC_URL / erreichbarkeit des auerswald-sync Servers.</p>"
        )
        return _page(
            "Offene Rückrufe", body, active_section="callbacks", context=context
        )
    if not items:
        body = _RUECKRUF_SUBTITLE + "<p>Keine offenen Rückrufe.</p>"
        return _page(
            "Offene Rückrufe", body, active_section="callbacks", context=context
        )
    rows = []
    for it in items:
        contact = _e(it["contact_name"]) if it.get("contact_found") else "Unbekannt"
        rows.append(
            "<tr>"
            f"<td>{_e(it.get('date', ''))}</td>"
            f"<td>{_e(it.get('time', ''))}</td>"
            f"<td>{_e(it.get('phone', ''))}</td>"
            f"<td>{_e(it.get('reason', ''))}</td>"
            f"<td>{contact}</td>"
            "<td>"
            '<form class="inline" method="post" action="/rueckruf/resolve">'
            f"{_csrf_input(context)}"
            f'<input type="hidden" name="call_id" value="{_e(it.get("call_id", ""))}">'
            "<button>Erledigt</button></form>"
            "</td></tr>"
        )
    body = _RUECKRUF_SUBTITLE + (
        "<table><tr><th>Datum</th><th>Zeit</th><th>Nummer</th>"
        "<th>Grund</th><th>Kontakt</th><th></th></tr>" + "".join(rows) + "</table>"
    )
    return _page("Offene Rückrufe", body, active_section="callbacks", context=context)


class OfficePanel:
    """Route handling and rendering; kept separate from the HTTP handler for testability."""

    def __init__(
        self,
        inquiry_repo: InquiryRepository,
        order_repo: OrderRepository,
        kiosk_url: str = "",
        configurator_url: str = "",
        *,
        remote: "RemoteCoreClient | None" = None,
        command_executor: "CoreCommandExecutor | None" = None,
        payment_reminder_repo: PaymentReminderRepository | None = None,
        offer_repo: OfferRepository | None = None,
        ui_version: str = "legacy",
    ) -> None:
        if ui_version not in {"legacy", "v2"}:
            raise ValueError("ui_version must be 'legacy' or 'v2'")
        self._inquiries = inquiry_repo
        self._orders = order_repo
        self._offers = offer_repo or InMemoryOfferRepository()
        # Phase 2 dual mode (PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1 §7): when
        # `remote` is given, `inquiry_repo`/`order_repo` are the same
        # RemoteCoreClient instance, used here only for its repo-shaped reads
        # (list_all, get_by_id, list_orders, get_order, list_order_versions,
        # get_order_version — everything render_queue/render_inquiry/
        # render_order already call directly). Writes must never run
        # InquiryService/OrderService/OperationalCoreService business logic
        # against the remote client (that would reproduce Core's business
        # rules — id minting, defaults, timestamps — on Proxmox); instead we
        # swap in the client's own command-backed facades, which call the
        # frozen Core Office API's named commands. Direct mode (remote=None)
        # is completely unchanged — same objects, same construction, byte-
        # identical behavior.
        if remote is None:
            self.inquiry_service = InquiryService(inquiry_repo)
            self.order_service = OrderService(order_repo)
            self.core = OperationalCoreService(order_repo)
            self.payment_reminder_service = PaymentReminderService(
                payment_reminder_repo or InMemoryPaymentReminderRepository(),
                order_repo,
                today=api_views.berlin_today,
            )
        else:
            # Structurally duck-typed, not the same concrete class — the
            # remote facades implement exactly the method surface this
            # module and office_panel_http.py call (create_inquiry,
            # update_inquiry, verify_customer_by_call, convert_inquiry_to_
            # order, create_relevant_order_change_version, evaluate_ready_
            # to_send, request_ready_to_send, confirm_kitchen_print,
            # make_order_version_effective, cancel_order), verified by the
            # remote-mode behavioral test suite.
            self.inquiry_service = remote.inquiry_service  # type: ignore[assignment]
            self.order_service = remote.order_service  # type: ignore[assignment]
            self.core = remote.core  # type: ignore[assignment]
            self.payment_reminder_service = remote.payment_reminder_service  # type: ignore[assignment]
        self._remote = remote
        self._command_executor = command_executor
        self._ui_version = ui_version
        # Pure-read derivations: safe to run over the remote client's repo-
        # shaped reads in both modes, since they only ever call
        # get_order/get_order_version/list_orders/list_order_versions —
        # never a write.
        self.progression = ProgressionService(order_repo)
        self.wochenuebersicht = WochenuebersichtService(order_repo)
        # Single source of truth for the "full week" deep link — the kitchen
        # kiosk (catering_system.ui.kiosk_server) already owns that view via
        # the same WochenuebersichtService (OFFICE_PANEL_EXECUTION_PACK_V1
        # §6: Wochenübersicht stays derived-only, panel may at most link to
        # it). Empty -> no link shown, same graceful-degrade convention as
        # the Rückrufe integration.
        self.kiosk_url = kiosk_url
        # Optional read-only handoff to the separate proposal-phase editor.
        # The payload travels in a URL fragment (never an HTTP request) and
        # opening it performs no Core write.
        self.configurator_url = normalize_configurator_url(configurator_url)

    @staticmethod
    def _missed_calls_open(
        rueckruf_items: list[dict] | None, rueckruf_error: str | None
    ) -> int:
        if rueckruf_error or rueckruf_items is None:
            return 0
        return len(rueckruf_items)

    def build_work_center_snapshot(self, missed_calls_open: int) -> WorkCenterSnapshot:
        if self._remote is not None:
            raw = self._remote.work_center()
            return WorkCenterSnapshot(
                rueckrufe_open=cast(int, raw["rueckrufe_open"]),
                missed_calls_open=missed_calls_open,
                offers_waiting=cast(int, raw["offers_waiting"]),
                offers_accepted=cast(int, raw["offers_accepted"]),
                upcoming_orders=cast(int, raw["upcoming_orders"]),
                open_tasks=cast(int, raw["open_tasks"]),
                today_calendar_entries=cast(int, raw["today_calendar_entries"]),
            )
        return WorkCenterService(
            self._inquiries,
            self._offers,
            self._orders,
            today=api_views.berlin_today,
            missed_calls_open=lambda: missed_calls_open,
            task_projection_service=self._task_projection_service(),
            calendar_projection_service=self._calendar_projection_service(),
        ).snapshot()

    def _calendar_projection_service(self) -> CalendarProjectionService:
        return CalendarProjectionService(
            self._inquiries,
            self._offers,
            self._orders,
            today=api_views.berlin_today,
        )

    def _task_projection_service(self) -> TaskProjectionService:
        return TaskProjectionService(
            self._inquiries,
            self._offers,
            self._orders,
            self.payment_reminder_service,
            today=api_views.berlin_today,
        )

    def _task_list_rows(self) -> list[dict[str, object]]:
        if self._remote is not None:
            body = self._remote.list_tasks()
            return cast(list[dict[str, object]], body["tasks"])
        return api_views.task_list_view(self._task_projection_service().list_tasks())

    def render_aufgaben(
        self, *, context: OfficePageContext = _EMPTY_PAGE_CONTEXT
    ) -> str:
        return render_aufgaben_list(self._task_list_rows(), context=context)

    def _calendar_list_rows(self) -> list[dict[str, object]]:
        operating_today = api_views.berlin_today()
        from_date = operating_today
        to_date = operating_today + timedelta(days=90)
        if self._remote is not None:
            body = self._remote.list_calendar(from_date, to_date)
            return cast(list[dict[str, object]], body["entries"])
        return api_views.calendar_list_view(
            self._calendar_projection_service().list_entries(from_date, to_date)
        )

    def render_kalender(
        self, *, context: OfficePageContext = _EMPTY_PAGE_CONTEXT
    ) -> str:
        return render_kalender_list(self._calendar_list_rows(), context=context)

    def _render_v2_arbeitszentrale(
        self,
        *,
        missed_calls_open: int,
        context: OfficePageContext,
    ) -> str:
        operating_today = api_views.berlin_today()
        iso = operating_today.isocalendar()
        week = self.wochenuebersicht.get_week_overview(iso.year, iso.week)
        snapshot = self.build_work_center_snapshot(missed_calls_open)
        return render_work_center_arbeitszentrale(
            snapshot,
            ui=WorkCenterDashboardUi(
                context=context,
                today=operating_today,
                week_order_count=len(week.entries),
            ),
        )

    def _offer_list_rows(self) -> list[dict[str, object]]:
        if self._remote is not None:
            body = self._remote.list_offers()
            return cast(list[dict[str, object]], body["offers"])
        inquiries_by_id = {
            inquiry.inquiry_id: inquiry for inquiry in self._inquiries.list_all()
        }
        return api_views.offer_list_view(
            self._offers.list_all(),
            inquiries_by_id,
            today=api_views.berlin_today(),
        )

    def render_angebote(
        self, *, context: OfficePageContext = _EMPTY_PAGE_CONTEXT
    ) -> str:
        rows = self._offer_list_rows()
        inquiries_by_id = {
            inquiry.inquiry_id: inquiry for inquiry in self._inquiries.list_all()
        }
        titles_by_inquiry = {
            inquiry_id: (inquiry.intake_subject or inquiry.location_text or "–")
            for inquiry_id, inquiry in inquiries_by_id.items()
        }
        return render_angebote_list(
            rows,
            titles_by_inquiry,
            context=context,
        )

    def render_offer(
        self, offer_id: str, *, context: OfficePageContext = _EMPTY_PAGE_CONTEXT
    ) -> str | None:
        if self._remote is not None:
            detail = self._remote.offer_detail(offer_id)
            if detail is None:
                return None
        else:
            offer = self._offers.get(offer_id)
            if offer is None:
                return None
            detail = api_views.offer_detail(offer, today=api_views.berlin_today())
        forms = OfferDetailFormFields(
            csrf_input=_csrf_input(context),
            command_fields=self._command_fields(),
        )
        return render_offer_detail(detail, context=context, forms=forms)

    def _offer_detail_dict(self, offer_id: str) -> dict[str, object]:
        if self._remote is not None:
            detail = self._remote.offer_detail(offer_id)
            if detail is None:
                raise KeyError(offer_id)
            return detail
        offer = self._offers.get(offer_id)
        if offer is None:
            raise KeyError(offer_id)
        return api_views.offer_detail(offer, today=api_views.berlin_today())

    @staticmethod
    def _require_form_text(form: dict[str, str], key: str, *, max_len: int) -> str:
        value = form.get(key, "").strip()
        if not value:
            raise ValueError(f"{key} is required")
        if len(value) > max_len:
            raise ValueError(f"{key} exceeds length limit")
        return value

    @staticmethod
    def _require_channel(
        form: dict[str, str], key: str, allowed: tuple[str, ...]
    ) -> str:
        channel = form.get(key, "").strip()
        if channel not in allowed:
            raise ValueError(f"invalid {key}")
        return channel

    def mark_offer_sent(self, offer_id: str, form: dict[str, str]) -> None:
        detail = self._offer_detail_dict(offer_id)
        if str(detail["commercial_state"]) != "Prepared":
            raise ValueError("sent recording blocked")
        offer_version_id = str(detail["offer_version_id"])
        sent_at = parse_datetime_local_berlin(form.get("sent_at", ""))
        channel = self._require_channel(form, "channel", SENT_CHANNELS)
        recipient_reference = self._require_form_text(
            form, "recipient_reference", max_len=500
        )
        evidence_reference = self._require_form_text(
            form, "evidence_reference", max_len=1000
        )

        def work() -> None:
            offer_service = OfferService(
                self._offers,
                self._inquiries,
                self._orders,
                today=api_views.berlin_today,
            )
            offer_service.record_sent_evidence(
                offer_id,
                offer_version_id,
                sent_at=sent_at,
                channel=cast(SentChannel, channel),
                recipient_reference=recipient_reference,
                evidence_reference=evidence_reference,
                recorded_by="office-panel",
            )

        if self._remote is not None:
            self._remote.mark_offer_sent(
                offer_id,
                offer_version_id,
                sent_at=format_datetime_utc_iso(sent_at),
                channel=channel,
                recipient_reference=recipient_reference,
                evidence_reference=evidence_reference,
            )
            return
        if self._command_executor is not None:
            self._command_executor.run(work)
            return
        work()

    def record_offer_acceptance(self, offer_id: str, form: dict[str, str]) -> None:
        detail = self._offer_detail_dict(offer_id)
        if str(detail["commercial_state"]) != "Sent":
            raise ValueError("acceptance blocked")
        offer_version_id = str(detail["offer_version_id"])
        accepted_variant_id = self._require_form_text(
            form, "accepted_variant_id", max_len=36
        )
        accepted_at = parse_datetime_local_berlin(form.get("accepted_at", ""))
        channel = self._require_channel(form, "channel", ACCEPTANCE_CHANNELS)
        evidence_reference = self._require_form_text(
            form, "evidence_reference", max_len=1000
        )
        note_raw = form.get("note", "").strip()
        note = note_raw or None
        if note is not None and len(note) > 20000:
            raise ValueError("note exceeds length limit")

        def work() -> None:
            offer_service = OfferService(
                self._offers,
                self._inquiries,
                self._orders,
                today=api_views.berlin_today,
            )
            offer_service.record_acceptance_evidence(
                offer_id,
                offer_version_id,
                accepted_variant_id,
                accepted_at=accepted_at,
                channel=cast(AcceptanceChannel, channel),
                evidence_reference=evidence_reference,
                recorded_by="office-panel",
                note=note,
            )

        if self._remote is not None:
            self._remote.record_offer_acceptance(
                offer_id,
                offer_version_id,
                accepted_variant_id=accepted_variant_id,
                accepted_at=format_datetime_utc_iso(accepted_at),
                channel=channel,
                evidence_reference=evidence_reference,
                note=note,
            )
            return
        if self._command_executor is not None:
            self._command_executor.run(work)
            return
        work()

    def convert_accepted_offer(
        self, offer_id: str, form: dict[str, str]
    ) -> tuple[Order, OrderVersion]:
        detail = self._offer_detail_dict(offer_id)
        if str(detail["commercial_state"]) != "Accepted":
            raise ValueError("conversion blocked")
        offer_version_id = str(detail["offer_version_id"])
        accepted_variant_id = form.get("accepted_variant_id", "").strip()
        acceptance_id = form.get("acceptance_id", "").strip()
        if not accepted_variant_id or not acceptance_id:
            raise ValueError("conversion blocked")

        def work() -> tuple[Order, OrderVersion]:
            offer_service = OfferService(
                self._offers,
                self._inquiries,
                self._orders,
                today=api_views.berlin_today,
            )
            converted, order, order_version = offer_service.convert_accepted_offer(
                offer_id,
                offer_version_id,
                accepted_variant_id,
                acceptance_id,
            )
            commercial_version = next(
                item
                for item in converted.versions
                if item.offer_version_id == offer_version_id
            )
            self.payment_reminder_service.seed_from_conversion(
                order.order_id,
                commercial_version.payment_method,
            )
            self.inquiry_service.update_inquiry(
                str(detail["inquiry_id"]),
                crm_stage=ACTIVE_ORDER_CRM_STAGE,
            )
            return order, order_version

        if self._remote is not None:
            order_id, order_version_id = self._remote.convert_accepted_offer(
                offer_id,
                offer_version_id,
                accepted_variant_id=accepted_variant_id,
                acceptance_id=acceptance_id,
            )
            order = self._orders.get_order(order_id)
            order_version = self._orders.get_order_version(order_version_id)
            if order is None or order_version is None:
                raise ValueError("accepted offer conversion response incomplete")
            return order, order_version
        if self._command_executor is not None:
            return self._command_executor.run(work)
        return work()

    def _contact_list_rows(self) -> list[dict[str, object]]:
        if self._remote is not None:
            body = self._remote.list_contacts()
            return cast(list[dict[str, object]], body["contacts"])
        service = ContactProjectionService(
            self._inquiries,
            self._offers,
            self._orders,
            today=api_views.berlin_today,
        )
        return api_views.contact_list_view(service.list_contacts())

    def render_kontakte(
        self, *, context: OfficePageContext = _EMPTY_PAGE_CONTEXT
    ) -> str:
        return render_kontakte_list(self._contact_list_rows(), context=context)

    def render_kontakt(
        self, contact_key: str, *, context: OfficePageContext = _EMPTY_PAGE_CONTEXT
    ) -> str | None:
        if self._remote is not None:
            detail = self._remote.contact_detail(contact_key)
            if detail is None:
                return None
        else:
            service = ContactProjectionService(
                self._inquiries,
                self._offers,
                self._orders,
                today=api_views.berlin_today,
            )
            projection = service.contact_detail(contact_key)
            if projection is None:
                return None
            detail = api_views.contact_detail_view(
                projection.contact,
                list(projection.inquiries),
                list(projection.offers),
                list(projection.orders),
                today=api_views.berlin_today(),
            )
        return render_kontakt_detail(detail, context=context)

    def _email_list_rows(self) -> list[dict[str, object]]:
        if self._remote is not None:
            body = self._remote.list_emails()
            return cast(list[dict[str, object]], body["emails"])
        service = EmailIntakeProjectionService(
            self._inquiries,
            self._offers,
            self._orders,
        )
        return api_views.email_list_view(service.list_emails())

    def render_email(
        self, *, context: OfficePageContext = _EMPTY_PAGE_CONTEXT
    ) -> str:
        return render_email_list(self._email_list_rows(), context=context)

    def render_email_detail(
        self, inquiry_id: str, *, context: OfficePageContext = _EMPTY_PAGE_CONTEXT
    ) -> str | None:
        if self._remote is not None:
            detail = self._remote.email_detail(inquiry_id)
            if detail is None:
                return None
        else:
            service = EmailIntakeProjectionService(
                self._inquiries,
                self._offers,
                self._orders,
            )
            projection = service.email_detail(inquiry_id)
            if projection is None:
                return None
            detail = api_views.email_detail_view(projection)
        return render_email_detail(detail, context=context)

    def begin_request(self, form: dict[str, str] | None = None) -> None:
        """No-op in direct mode. In remote mode, resets the RemoteCoreClient's
        per-request read caches and stashes the submitted form (if any) so the
        write facades can read back `_command_id`/`_expect_*` hidden fields
        (pack §6.1/§6.3). The HTTP handler calls this once per request, before
        any panel render/write method, for both GET (empty form) and POST."""
        if self._remote is not None:
            self._remote.begin_request(form)

    def _command_fields(self, expect: dict[str, str] | None = None) -> str:
        """Hidden idempotency fields for a rendered mutating form. Empty in
        direct mode — direct-mode HTML must stay byte-identical (pack §7). In
        remote mode, mints a fresh command_id for this render (baked into the
        served page, so a resubmission of the SAME loaded form — a double
        click, or a retry after an indeterminate network failure — always
        carries the same id and the same preconditions) plus one
        `_expect_<key>` field per precondition the command route requires."""
        if self._remote is None:
            return ""
        command_id = self._remote.new_page_command_id()
        fields = f'<input type="hidden" name="_command_id" value="{_e(command_id)}">'
        for key, value in (expect or {}).items():
            fields += f'<input type="hidden" name="_expect_{key}" value="{_e(value)}">'
        return fields

    def _next_step_action(
        self,
        order: Order,
        *,
        context: OfficePageContext = _EMPTY_PAGE_CONTEXT,
    ) -> str:
        """UI action-target resolution for existing routes only — not new
        order semantics. Picks the target OrderVersion (candidate_order_
        version_id if set and real, else the highest version_number — a
        display fallback, not new truth; documented in domain/order.py as
        exactly this: an "office-side progression hint") and returns
        whichever of the two existing, ordered actions applies. Order
        matters: operational_core_service.make_order_version_effective()
        itself refuses a version whose kitchen print isn't confirmed yet
        (raises ValueError) — so print-confirm must be offered first, never
        "Wirksam machen" for an unprinted version, even if that version's
        READY_TO_SEND reason would otherwise be reported as
        no_effective_version rather than kitchen_print_not_confirmed."""
        versions = self._orders.list_order_versions(order.order_id)
        if not versions:
            return ""
        version = next(
            (
                v
                for v in versions
                if v.order_version_id == order.candidate_order_version_id
            ),
            None,
        )
        if version is None:
            version = max(versions, key=lambda v: v.version_number)
        expect: dict[str, str] = {}
        if version.kitchen_print_confirmed_at is None:
            label, action = "Druck bestätigen", "print-confirm"
        elif version.order_version_id != order.effective_order_version_id:
            label, action = "Wirksam machen", "effective"
            expect = {"effective_version_id": order.effective_order_version_id or ""}
        else:
            return ""
        return (
            f'<form class="inline" method="post" action="/order/{_e(order.order_id)}/{action}">'
            f"{_csrf_input(context)}{self._command_fields(expect)}"
            f'<input type="hidden" name="order_version_id" value="{_e(version.order_version_id)}">'
            f"<button>{label}</button></form>"
        )

    def _inquiry_office_state(
        self,
        inquiry: Inquiry,
        linked_orders: list[Order],
        *,
        inquiry_id: str | None = None,
    ) -> InquiryOfficeState:
        inquiry_id = inquiry_id or inquiry.inquiry_id
        if self._remote is not None:
            meta = self._remote.inquiry_detail_meta(inquiry_id)
            if meta.next_action is not None or meta.offer is not None:
                from catering_system.domain.inquiry import InquiryOfferProjection

                offer_projection = None
                if meta.offer is not None:
                    raw_offer = meta.offer
                    offer_projection = InquiryOfferProjection(
                        offer_id=str(raw_offer["offer_id"]),
                        offer_version_id=str(raw_offer["offer_version_id"]),
                        commercial_state=raw_offer["commercial_state"],  # type: ignore[arg-type]
                        accepted_variant_id=(
                            str(raw_offer["accepted_variant_id"])
                            if raw_offer.get("accepted_variant_id") is not None
                            else None
                        ),
                        acceptance_id=(
                            str(raw_offer["acceptance_id"])
                            if raw_offer.get("acceptance_id") is not None
                            else None
                        ),
                    )
                has_order = bool(linked_orders)
                has_active_order = any(
                    order.cancelled_at is None for order in linked_orders
                )
                if has_active_order and not has_order:
                    raise ValueError("an active order is also an existing order")
                if inquiry.crm_stage == "Abgelehnt / verloren" or has_active_order:
                    is_open = False
                else:
                    is_open = not has_order
                return InquiryOfficeState(
                    is_open=is_open,
                    next_action=meta.next_action,
                    offer=offer_projection,
                )
        offer = self._offers.get_by_source_inquiry_id(inquiry_id)
        return api_views.inquiry_office_state(
            inquiry,
            linked_orders,
            offer=offer,
            today=api_views.berlin_today(),
        )

    def _inquiry_primary_action_html(
        self,
        inquiry_id: str,
        state: InquiryOfficeState,
        *,
        context: OfficePageContext,
    ) -> str:
        if state.next_action == "verify":
            return (
                f'<form class="inline" method="post" action="/inquiry/{_e(inquiry_id)}/verify">'
                f"{_csrf_input(context)}{self._command_fields()}"
                "<button>Telefonisch verifiziert</button></form>"
            )
        if state.next_action == "convert":
            return (
                f'<form class="inline" method="post" action="/inquiry/{_e(inquiry_id)}/convert">'
                f"{_csrf_input(context)}{self._command_fields()}"
                "<button>In Auftrag umwandeln</button></form>"
            )
        if state.next_action == "offer-pending":
            return '<span class="muted">Angebot ausstehend</span>'
        if state.next_action == "convert-accepted":
            return '<span class="muted">Angebot angenommen</span>'
        return ""

    # -- queue -----------------------------------------------------------

    def render_queue(
        self,
        rueckruf_items: list[dict] | None,
        *,
        rueckruf_error: str | None = None,
        context: OfficePageContext = _EMPTY_PAGE_CONTEXT,
    ) -> str:
        missed_calls_open = self._missed_calls_open(rueckruf_items, rueckruf_error)
        if self._ui_version == "v2":
            return self._render_v2_arbeitszentrale(
                missed_calls_open=missed_calls_open,
                context=context,
            )
        if self._remote is not None:
            return self._render_remote_queue(
                self._remote.queue_view(),
                rueckruf_items,
                rueckruf_error=rueckruf_error,
                context=context,
            )
        orders = self._orders.list_orders()
        orders_by_inquiry: dict[str, list[Order]] = {}
        for o in orders:
            orders_by_inquiry.setdefault(o.source_inquiry_id, []).append(o)

        # -- Heute / Aufmerksamkeit: counts from data already loaded above,
        # no new service calls. Every number here maps onto an existing,
        # already-accepted concept (progression B7 / operational gate) —
        # this is a summary view, not a new domain concept.
        all_inquiries = self._inquiries.list_all()
        open_inquiries = []
        for inquiry in all_inquiries:
            linked = orders_by_inquiry.get(inquiry.inquiry_id, [])
            state = self._inquiry_office_state(inquiry, linked)
            if state.is_open:
                open_inquiries.append((inquiry, state))
        active_orders = [o for o in orders if o.cancelled_at is None]
        ohne_druck = [
            o
            for o in active_orders
            if not any(
                v.kitchen_print_confirmed_at is not None
                for v in self._orders.list_order_versions(o.order_id)
            )
        ]
        nicht_wirksam = [
            o for o in active_orders if o.effective_order_version_id is None
        ]
        evaluations = {
            o.order_id: self.core.evaluate_ready_to_send(o.order_id)
            for o in active_orders
        }
        blockiert = [o for o in active_orders if not evaluations[o.order_id].ready]
        storniert = [o for o in orders if o.cancelled_at is not None]
        # Reuses the same request-local count already fetched for the sidebar
        # badge — no second auerswald-sync request. None = not configured/unreachable -> card omitted, same
        # as the sidebar badge; unlike the other cards, 0 is a real fetched
        # value here (they never depend on an external service, so 0 always
        # means "confirmed empty").
        rueckruf_card = (
            f'<a href="/rueckruf"><strong>{context.rueckruf_count}</strong> Rückrufe offen</a>'
            if context.rueckruf_count is not None
            else ""
        )
        storniert_card = (
            f"<span><strong>{len(storniert)}</strong> Stornierte Aufträge prüfen</span>"
            if storniert
            else ""
        )
        attention = (
            "<h2>Was braucht Aufmerksamkeit?</h2>"
            '<div class="attention">'
            + rueckruf_card
            + f'<a href="#anfragen"><strong>{len(open_inquiries)}</strong> Offene Anfragen prüfen</a>'
            f'<a href="#auftraege"><strong>{len(ohne_druck)}</strong> Druckbestätigung fehlt</a>'
            f'<a href="#auftraege"><strong>{len(nicht_wirksam)}</strong> Aufträge noch nicht wirksam</a>'
            f'<a href="#auftraege"><strong>{len(blockiert)}</strong> Versandfreigabe blockiert</a>'
            + storniert_card
            + "</div>"
        )

        operating_today = date.today()
        iso = operating_today.isocalendar()
        week = self.wochenuebersicht.get_week_overview(iso.year, iso.week)
        week_rows = [
            f"<tr><td>{_e(e.event_date.isoformat())}</td><td>{_e(e.time_window_text)}</td>"
            f"<td>{_e(e.location_text)}</td>"
            f"<td>{_e(str(e.guest_count_estimate) if e.guest_count_estimate is not None else '–')}</td>"
            f'<td><a href="/order/{_e(e.order_id)}">{_e(e.order_id[:8])}</a></td></tr>'
            for e in week.entries
        ]
        kiosk_link = (
            f' <a href="{_e(self.kiosk_url)}">Vollständige Wochenübersicht (Küche)</a>'
            if self.kiosk_url
            else ""
        )
        diese_woche = (
            f'<h2 id="diese-woche">Diese Woche (KW {iso.week}/{iso.year})</h2>'
            "<table><tr><th>Datum</th><th>Zeitfenster</th><th>Ort</th><th>Gäste</th><th>Auftrag</th></tr>"
            + "".join(
                week_rows
                or [
                    '<tr><td colspan="5">keine wirksamen Aufträge diese Woche</td></tr>'
                ]
            )
            + "</table>"
            + kiosk_link
        )

        # -- three action queues (§11 addendum): top 5 rows each, one
        # primary action per row, full lists live at /rueckruf, /anfragen,
        # /auftraege. rueckruf_items is None when auerswald-sync is
        # unconfigured/unreachable -> the whole queue is omitted, same
        # graceful-degrade convention as the sidebar badge (not an error
        # page, the rest of the Startseite still renders).
        rueckruf_section = ""
        if rueckruf_items is not None:
            rows = []
            for it in rueckruf_items[:5]:
                contact = (
                    _e(it["contact_name"]) if it.get("contact_found") else "Unbekannt"
                )
                phone = it.get("phone", "")
                rows.append(
                    f"<li>{_e(it.get('date', ''))} {_e(it.get('time', ''))} — "
                    f"{_e(phone)} ({contact}) "
                    '<form class="inline" method="post" action="/rueckruf/resolve">'
                    f"{_csrf_input(context)}"
                    f'<input type="hidden" name="call_id" value="{_e(it.get("call_id", ""))}">'
                    "<button>Erledigt</button></form> "
                    f'<a href="/inquiry/new?phone={quote(phone)}">Anfrage erfassen</a></li>'
                )
            rueckruf_section = (
                "<h2>Rückruf nötig</h2>"
                + (
                    f"<ul>{''.join(rows)}</ul>"
                    if rows
                    else "<p>keine offenen Rückrufe.</p>"
                )
                + '<p><a href="/rueckruf">Alle anzeigen</a></p>'
            )

        offene_anfragen_rows = []
        for inq, state in open_inquiries[:5]:
            action = self._inquiry_primary_action_html(
                inq.inquiry_id, state, context=context
            )
            offene_anfragen_rows.append(
                f'<li><a href="/inquiry/{_e(inq.inquiry_id)}">{_e(inq.event_date.isoformat())} · '
                f"{_e(inq.location_text)}</a> — {_e(inq.crm_stage)} {action}</li>"
            )
        offene_anfragen_section = (
            "<h2>Offene Anfragen</h2>"
            + (
                f"<ul>{''.join(offene_anfragen_rows)}</ul>"
                if offene_anfragen_rows
                else "<p>keine offenen Anfragen.</p>"
            )
            + '<p><a href="/anfragen">Alle anzeigen</a></p>'
        )

        auftraege_rows = []
        for o in blockiert[:5]:
            ev = evaluations[o.order_id]
            reason = (
                _e(_ready_to_send_blocker_label(ev.reasons[0])) if ev.reasons else "–"
            )
            action = self._next_step_action(o, context=context)
            auftraege_rows.append(
                f'<li><a href="/order/{_e(o.order_id)}">{_e(o.order_id[:8])}</a> — {reason} {action}</li>'
            )
        auftraege_section = (
            "<h2>Aufträge mit nächstem Schritt</h2>"
            + (
                f"<ul>{''.join(auftraege_rows)}</ul>"
                if auftraege_rows
                else "<p>keine offenen Schritte.</p>"
            )
            + '<p><a href="/auftraege">Alle anzeigen</a></p>'
        )

        body = (
            attention
            + diese_woche
            + rueckruf_section
            + offene_anfragen_section
            + auftraege_section
            + '<p><a href="/inquiry/new">+ Neue Anfrage erfassen</a></p>'
        )
        return _page("Büro-Übersicht", body, active_section="home", context=context)

    def _render_remote_queue(
        self,
        view: dict[str, object],
        rueckruf_items: list[dict] | None,
        *,
        rueckruf_error: str | None = None,
        context: OfficePageContext,
    ) -> str:
        """Render the frozen QueueView without recomputing Core semantics.

        In remote mode the authoritative Berlin operating day, attention
        counts and next actions are supplied by Core in one read.  This keeps
        the Proxmox panel from recreating business rules or issuing an N+1
        graph of list/detail calls.
        """
        attention_view = cast(dict[str, int], view["attention"])
        rueckruf_card = (
            f'<a href="/rueckruf"><strong>{context.rueckruf_count}</strong> Rückrufe offen</a>'
            if context.rueckruf_count is not None
            else ""
        )
        storniert = attention_view["storniert"]
        storniert_card = (
            f"<span><strong>{storniert}</strong> Stornierte Aufträge prüfen</span>"
            if storniert
            else ""
        )
        attention = (
            "<h2>Was braucht Aufmerksamkeit?</h2>"
            '<div class="attention">'
            + rueckruf_card
            + f'<a href="#anfragen"><strong>{attention_view["neue_anfragen"]}</strong> Offene Anfragen prüfen</a>'
            f'<a href="#auftraege"><strong>{attention_view["druck_fehlt"]}</strong> Druckbestätigung fehlt</a>'
            f'<a href="#auftraege"><strong>{attention_view["nicht_wirksam"]}</strong> Aufträge noch nicht wirksam</a>'
            f'<a href="#auftraege"><strong>{attention_view["versand_blockiert"]}</strong> Versandfreigabe blockiert</a>'
            + storniert_card
            + "</div>"
        )

        week = cast(dict[str, Any], view["week"])
        week_rows = [
            f"<tr><td>{_e(entry['event_date'])}</td><td>{_e(entry['time_window_text'])}</td>"
            f"<td>{_e(entry['location_text'])}</td>"
            f"<td>{_e(str(entry['guest_count_estimate']) if entry['guest_count_estimate'] is not None else '–')}</td>"
            f'<td><a href="/order/{_e(entry["order_id"])}">{_e(entry["order_id"][:8])}</a></td></tr>'
            for entry in cast(list[dict[str, Any]], week["entries"])
        ]
        kiosk_link = (
            f' <a href="{_e(self.kiosk_url)}">Vollständige Wochenübersicht (Küche)</a>'
            if self.kiosk_url
            else ""
        )
        truncation_warning = (
            '<p class="blocked"><strong>Unvollständige Ansicht:</strong> '
            f"Diese Woche zeigt {len(week_rows)} von {week['total_count']} Aufträgen. "
            "Bitte die vollständige Wochenübersicht öffnen.</p>"
            if week["truncated"]
            else ""
        )
        diese_woche = (
            f'<h2 id="diese-woche">Diese Woche (KW {week["iso_week"]}/{week["iso_year"]})</h2>'
            + truncation_warning
            + "<table><tr><th>Datum</th><th>Zeitfenster</th><th>Ort</th><th>Gäste</th><th>Auftrag</th></tr>"
            + "".join(
                week_rows
                or [
                    '<tr><td colspan="5">keine wirksamen Aufträge diese Woche</td></tr>'
                ]
            )
            + "</table>"
            + kiosk_link
        )

        rueckruf_section = ""
        if rueckruf_items is not None:
            rows = []
            for item in rueckruf_items[:5]:
                contact = (
                    _e(item["contact_name"])
                    if item.get("contact_found")
                    else "Unbekannt"
                )
                phone = item.get("phone", "")
                rows.append(
                    f"<li>{_e(item.get('date', ''))} {_e(item.get('time', ''))} — "
                    f"{_e(phone)} ({contact}) "
                    '<form class="inline" method="post" action="/rueckruf/resolve">'
                    f"{_csrf_input(context)}"
                    f'<input type="hidden" name="call_id" value="{_e(item.get("call_id", ""))}">'
                    "<button>Erledigt</button></form> "
                    f'<a href="/inquiry/new?phone={quote(phone)}">Anfrage erfassen</a></li>'
                )
            rueckruf_section = (
                "<h2>Rückruf nötig</h2>"
                + (
                    f"<ul>{''.join(rows)}</ul>"
                    if rows
                    else "<p>keine offenen Rückrufe.</p>"
                )
                + '<p><a href="/rueckruf">Alle anzeigen</a></p>'
            )

        inquiry_rows = []
        for inquiry in cast(list[dict[str, Any]], view["neue_anfragen_top"]):
            action_name = inquiry["next_action"]
            inquiry_id = str(inquiry["inquiry_id"])
            if action_name == "verify":
                action = (
                    f'<form class="inline" method="post" action="/inquiry/{_e(inquiry_id)}/verify">'
                    f"{_csrf_input(context)}{self._command_fields()}"
                    "<button>Telefonisch verifiziert</button></form>"
                )
            elif action_name == "convert":
                action = (
                    f'<form class="inline" method="post" action="/inquiry/{_e(inquiry_id)}/convert">'
                    f"{_csrf_input(context)}{self._command_fields()}"
                    "<button>In Auftrag umwandeln</button></form>"
                )
            elif action_name == "offer-pending":
                action = '<span class="muted">Angebot ausstehend</span>'
            elif action_name == "convert-accepted":
                action = '<span class="muted">Angebot angenommen</span>'
            else:
                action = ""
            inquiry_rows.append(
                f'<li><a href="/inquiry/{_e(inquiry["inquiry_id"])}">{_e(inquiry["event_date"])} · '
                f"{_e(inquiry['location_text'])}</a> — {_e(inquiry['crm_stage'])} {action}</li>"
            )
        offene_anfragen_section = (
            "<h2>Offene Anfragen</h2>"
            + (
                f"<ul>{''.join(inquiry_rows)}</ul>"
                if inquiry_rows
                else "<p>keine offenen Anfragen.</p>"
            )
            + '<p><a href="/anfragen">Alle anzeigen</a></p>'
        )

        order_rows = []
        for order in cast(list[dict[str, Any]], view["auftraege_top"]):
            reason = (
                _e(_ready_to_send_blocker_label(order["blocker_reason"]))
                if order["blocker_reason"] is not None
                else "–"
            )
            action_view = cast(dict[str, str] | None, order["next_action"])
            action = ""
            if action_view is not None:
                action_name = action_view["action"]
                label = (
                    "Druck bestätigen"
                    if action_name == "print-confirm"
                    else "Wirksam machen"
                )
                expect = (
                    {"effective_version_id": order["effective_order_version_id"] or ""}
                    if action_name == "effective"
                    else None
                )
                action = (
                    f'<form class="inline" method="post" action="/order/{_e(order["order_id"])}/{action_name}">'
                    f"{_csrf_input(context)}{self._command_fields(expect)}"
                    f'<input type="hidden" name="order_version_id" value="{_e(action_view["order_version_id"])}">'
                    f"<button>{label}</button></form>"
                )
            order_rows.append(
                f'<li><a href="/order/{_e(order["order_id"])}">{_e(order["order_id"][:8])}</a> — {reason} {action}</li>'
            )
        auftraege_section = (
            "<h2>Aufträge mit nächstem Schritt</h2>"
            + (
                f"<ul>{''.join(order_rows)}</ul>"
                if order_rows
                else "<p>keine offenen Schritte.</p>"
            )
            + '<p><a href="/auftraege">Alle anzeigen</a></p>'
        )
        body = (
            attention
            + diese_woche
            + rueckruf_section
            + offene_anfragen_section
            + auftraege_section
            + '<p><a href="/inquiry/new">+ Neue Anfrage erfassen</a></p>'
        )
        return _page("Büro-Übersicht", body, active_section="home", context=context)

    # -- full lists (moved out of the Startseite, §11 addendum §13) ------

    def render_anfragen(
        self, q: str = "", *, context: OfficePageContext = _EMPTY_PAGE_CONTEXT
    ) -> str:
        needle = q.strip().lower()

        def _matches(*fields: str) -> bool:
            if not needle:
                return True
            return any(needle in f.lower() for f in fields)

        orders = self._orders.list_orders()
        orders_by_inquiry: dict[str, list[Order]] = {}
        for o in orders:
            orders_by_inquiry.setdefault(o.source_inquiry_id, []).append(o)

        search_box = (
            '<form method="get" action="/anfragen" class="searchbox">'
            f'<input type="text" name="q" value="{_e(q)}" placeholder="Suche: ID, Ort, Datum…">'
            '<button type="submit">Suchen</button>'
            + (' <a href="/anfragen">Zurücksetzen</a>' if q else "")
            + "</form>"
        )

        rows = []
        for inq in self._inquiries.list_all():
            linked_orders = orders_by_inquiry.get(inq.inquiry_id, [])
            has_order = (
                f'<a href="/order/{_e(linked_orders[0].order_id)}">Auftrag öffnen</a>'
                if linked_orders
                else "–"
            )
            if not _matches(
                inq.inquiry_id,
                inq.location_text,
                inq.event_date.isoformat(),
                inq.crm_stage,
                inq.inquiry_source,
                inq.intake_subject or "",
            ):
                continue
            betreff_raw = inq.intake_subject or ""
            betreff = (
                betreff_raw[:40] + "…" if len(betreff_raw) > 40 else betreff_raw
            ) or "–"
            verif_text = _e(_verification_label(inq.call_verification_status))
            verif_cell = (
                f'<span class="blocked">{verif_text}</span>'
                if inq.call_verification_required
                and inq.call_verification_status != "verified"
                else verif_text
            )
            rows.append(
                f"<tr><td>{_e(inq.event_date.isoformat())}</td><td>{_e(inq.location_text)}</td>"
                f"<td>{_e(_source_label(inq.inquiry_source))}</td><td>{_e(betreff)}</td>"
                f"<td>{_e(inq.crm_stage)}</td><td>{verif_cell}</td>"
                f"<td>{has_order}</td>"
                f'<td><a href="/inquiry/{_e(inq.inquiry_id)}">{_e(inq.inquiry_id[:8])}</a></td></tr>'
            )

        body = (
            search_box + '<p><a href="/inquiry/new">+ Neue Anfrage erfassen</a></p>'
            "<table><tr><th>Datum</th><th>Ort</th><th>Kanal</th><th>Betreff</th>"
            "<th>CRM-Stufe</th><th>Verifizierung</th><th>Auftrag</th><th>ID</th></tr>"
            + "".join(rows or ['<tr><td colspan="8">keine</td></tr>'])
            + "</table>"
        )
        return _page("Anfragen", body, active_section="inquiries", context=context)

    def render_auftraege(
        self, q: str = "", *, context: OfficePageContext = _EMPTY_PAGE_CONTEXT
    ) -> str:
        needle = q.strip().lower()

        def _matches(*fields: str) -> bool:
            if not needle:
                return True
            return any(needle in f.lower() for f in fields)

        search_box = (
            '<form method="get" action="/auftraege" class="searchbox">'
            f'<input type="text" name="q" value="{_e(q)}" placeholder="Suche: ID, Ort, Datum…">'
            '<button type="submit">Suchen</button>'
            + (' <a href="/auftraege">Zurücksetzen</a>' if q else "")
            + "</form>"
        )

        rows = []
        for o in self._orders.list_orders():
            if not _matches(o.order_id, o.source_inquiry_id):
                continue
            if o.cancelled_at is not None:
                status = '<span class="cancelled">STORNIERT</span>'
                blocker = "–"
            else:
                ev = self.core.evaluate_ready_to_send(o.order_id)
                if ev.ready:
                    status = '<span class="ok">bereit</span>'
                    blocker = "–"
                else:
                    status = '<span class="blocked">blockiert</span>'
                    blocker = (
                        _e(_ready_to_send_blocker_label(ev.reasons[0]))
                        if ev.reasons
                        else "–"
                    )
            eff = (
                "bestätigt" if o.effective_order_version_id else "noch nicht bestätigt"
            )
            rows.append(
                f"<tr><td>{status}</td><td>{blocker}</td>"
                f"<td>{_e(o.source_inquiry_id[:8])}</td><td>{_e(eff)}</td>"
                f'<td><a href="/order/{_e(o.order_id)}">{_e(o.order_id[:8])}</a></td></tr>'
            )

        body = (
            search_box + "<table><tr><th>Freigabe</th><th>Blocker</th>"
            "<th>Anfrage</th><th>Bestätigt</th><th>ID</th></tr>"
            + "".join(rows or ['<tr><td colspan="5">keine</td></tr>'])
            + "</table>"
        )
        return _page("Aufträge", body, active_section="orders", context=context)

    # -- inquiries -------------------------------------------------------

    def render_inquiry_form(
        self,
        phone: str = "",
        event_date: str = "",
        guest_count_estimate: str = "",
        inquiry_source: str = "",
        intake_subject: str = "",
        intake_message: str = "",
        intake_summary: str = "",
        intake_external_ref: str = "",
        *,
        context: OfficePageContext = _EMPTY_PAGE_CONTEXT,
    ) -> str:
        src_opts = "".join(
            f'<option value="{s}"{" selected" if s == inquiry_source else ""}>{s}</option>'
            for s in _OFFICE_SOURCES
        )
        # Rückruf -> Inquiry hint only (§11 addendum §14): Inquiry has no
        # phone/contact field at all (domain/inquiry.py), so this is never
        # written anywhere — it's page context for the office worker, shown
        # once, not a prefilled form field bound to any Inquiry attribute.
        phone_hint = f'<p class="subtitle">Anruf von: {_e(phone)}</p>' if phone else ""
        # event_date / guest_count_estimate / inquiry_source / intake_*:
        # optional prefill hints, from either the proposal preview's GET hint
        # (event_date/guest_count_estimate only, PROPOSAL_PREVIEW_MANUAL_
        # INQUIRY_PACK_V1 §4) or the POST prepare step (all seven,
        # PROPOSAL_PREVIEW_INTAKE_MAPPING_IMPLEMENTATION_PACK_V1 §5/§6).
        # Prefill only — every field stays editable and the submitted form
        # values are what create_inquiry sees; hints never override office
        # input and are never written anywhere by themselves.
        body = (
            phone_hint
            + f"""<form method="post" action="/inquiry/new">{_csrf_input(context)}{self._command_fields()}<fieldset>
<p><label>Datum*</label><input type="date" name="event_date" value="{_e(event_date)}" required></p>
<p><label>Kanal</label><select name="inquiry_source">{src_opts}</select></p>
<p><label>Zeitfenster</label><input name="time_window_text"></p>
<p><label>Ort</label><input name="location_text"></p>
<p><label>Gäste (ca.)</label><input name="guest_count_estimate" inputmode="numeric" value="{_e(guest_count_estimate)}"></p>
<p><label>Planungsmodus</label>{_planning_mode_select(PLANNING_MODES[0])}</p>
<p><label>Rückruf-Verifizierung nötig</label><input type="checkbox" name="call_verification_required" value="1"></p>
<p class="subtitle">Intake-Kontext — keine Auftrags-/Küchenfreigabe.</p>
<p><label>Betreff</label><input name="intake_subject" value="{_e(intake_subject)}"></p>
<p><label>Nachricht</label><textarea name="intake_message" rows="4">{_e(intake_message)}</textarea></p>
<p><label>Zusammenfassung</label><textarea name="intake_summary" rows="3">{_e(intake_summary)}</textarea></p>
<p><label>Externe Referenz</label><input name="intake_external_ref" value="{_e(intake_external_ref)}"></p>
<p><button type="submit">Anfrage anlegen</button></p>
</fieldset></form>"""
        )
        return _page("Neue Anfrage", body, active_section="inquiries", context=context)

    def create_inquiry(self, form: dict[str, str]) -> Inquiry:
        required = form.get("call_verification_required") == "1"
        return self.inquiry_service.create_inquiry(
            event_date=date.fromisoformat(form["event_date"]),
            inquiry_source=form.get("inquiry_source", "manual"),
            crm_stage=CRM_PIPELINE[0],
            customer_linkage={},
            time_window_text=form.get("time_window_text", ""),
            location_text=form.get("location_text", ""),
            guest_count_estimate=_opt_int(form.get("guest_count_estimate", "")),
            planning_mode=form.get("planning_mode", PLANNING_MODES[0]),
            call_verification_required=required,
            call_verification_status="pending" if required else "not_required",
            intake_subject=form.get("intake_subject", ""),
            intake_message=form.get("intake_message", ""),
            intake_summary=form.get("intake_summary", ""),
            intake_external_ref=form.get("intake_external_ref", ""),
        )

    def render_inquiry(
        self,
        inquiry_id: str,
        *,
        context: OfficePageContext = _EMPTY_PAGE_CONTEXT,
    ) -> str | None:
        inq = self._inquiries.get_by_id(inquiry_id)
        if inq is None:
            return None
        inquiry_truncation_warning = ""
        linked_orders_total_count: int | None = None
        linked_orders_truncated = False
        if self._remote is not None:
            linked_orders_total_count, linked_orders_truncated = (
                self._remote.inquiry_orders_meta(inquiry_id)
            )
            if linked_orders_truncated:
                inquiry_truncation_warning = (
                    '<p class="blocked"><strong>Unvollständige Ansicht:</strong> '
                    f"Die API-Detailansicht enthält nicht alle "
                    f"{linked_orders_total_count} "
                    "verknüpften Aufträge.</p>"
                )
        existing = [
            o for o in self._orders.list_orders() if o.source_inquiry_id == inquiry_id
        ]
        has_active_order = any(order.cancelled_at is None for order in existing)
        state = self._inquiry_office_state(
            inq,
            existing,
            inquiry_id=inquiry_id,
        )
        ev = self.progression.evaluate_inquiry_to_order_progression(inq)
        if self._ui_version == "v2":
            offer_url = (
                build_offer_prefill_url(self.configurator_url, inq)
                if self.configurator_url
                else None
            )
            detail = render_inquiry_detail(
                inq,
                existing,
                state,
                ev.reasons,
                forms=InquiryDetailFormFields(
                    csrf_input=_csrf_input(context),
                    primary_command_fields=(
                        self._command_fields()
                        if state.next_action in ("verify", "convert")
                        or inquiry_shows_convert_accepted_button(state)
                        else ""
                    ),
                    update_command_fields=self._command_fields(
                        {"updated_at": inq.updated_at.isoformat()}
                    ),
                ),
                linked_orders_total_count=linked_orders_total_count,
                linked_orders_truncated=linked_orders_truncated,
                offer_url=offer_url,
            )
            return _page(
                detail.title,
                detail.body,
                active_section="inquiries",
                context=context,
                show_title=False,
            )
        if existing:
            prog = '<p class="ok">Bereits in Auftrag umgewandelt.</p>'
        elif ev.blocked:
            reasons = "".join(
                f"<li>{_e(_progression_blocker_label(r))}</li>" for r in ev.reasons
            )
            prog = f'<p class="blocked">Konvertierung blockiert:</p><ul>{reasons}</ul>'
        else:
            prog = '<p class="ok">Konvertierung möglich.</p>'
        verify_btn = ""
        if state.next_action == "verify":
            verify_btn = (
                f'<form class="inline" method="post" action="/inquiry/{_e(inquiry_id)}/verify">'
                f"{_csrf_input(context)}{self._command_fields()}"
                "<button>Telefonisch verifiziert</button></form> "
            )
        convert = ""
        if existing:
            links = ", ".join(
                f'<a href="/order/{_e(o.order_id)}">{_e(o.order_id[:8])}</a>'
                + (" (storniert)" if o.cancelled_at is not None else "")
                for o in existing
            )
            convert += f"<p>Auftrag vorhanden: {links}</p>"
        if state.next_action == "convert":
            convert += (
                f'<form class="inline" method="post" action="/inquiry/{_e(inquiry_id)}/convert">'
                f"{_csrf_input(context)}{self._command_fields()}"
                "<button>In Auftrag umwandeln</button></form>"
            )
        elif state.next_action == "offer-pending":
            convert += '<p class="muted">Angebot ausstehend</p>'
        elif state.next_action == "convert-accepted":
            if (
                state.offer is not None
                and state.offer.commercial_state == "Converted"
            ):
                convert += (
                    '<p class="muted">Auftrag bereits erstellt — '
                    "verknüpften Auftrag unten öffnen.</p>"
                )
            elif inquiry_shows_convert_accepted_button(state):
                convert += (
                    f'<form class="inline" method="post" '
                    f'action="/inquiry/{_e(inquiry_id)}/convert-accepted" '
                    'onsubmit="return confirm('
                    "'Dieses angenommene Angebot wird jetzt in einen Auftrag umgewandelt.'"
                    ');">'
                    f"{_csrf_input(context)}{self._command_fields()}"
                    "<button>Angenommenes Angebot in Auftrag überführen</button>"
                    "</form>"
                )
        guests = (
            str(inq.guest_count_estimate)
            if inq.guest_count_estimate is not None
            else ""
        )
        # Intake context: only shown as table rows when present, so an old
        # Inquiry from before this pack doesn't grow four "–" rows for
        # nothing (INQUIRY_INTAKE_CONTEXT_FIELDS_IMPLEMENTATION_PACK_V1 §6).
        intake_rows = "".join(
            f"<tr><th>{label}</th><td>{_e(value)}</td></tr>"
            for label, value in (
                ("Betreff", inq.intake_subject),
                ("Nachricht", inq.intake_message),
                ("Zusammenfassung", inq.intake_summary),
                ("Externe Referenz", inq.intake_external_ref),
            )
            if value
        )
        # Website-only context banner (WEBSITE_FORM_INQUIRY_OFFICE_UX_PACK_V1
        # §5) — reuses .proposal-banner, no new style. Never shown for any
        # other source.
        website_banner = (
            '<p class="proposal-banner">Website-Anfrage — noch kein Auftrag. '
            "Nur Intake-Kontext, keine Küchenfreigabe.</p>"
            if inq.inquiry_source == "website_form"
            else ""
        )
        offer_prefill = ""
        if self.configurator_url:
            offer_url = build_offer_prefill_url(self.configurator_url, inq)
            offer_prefill = (
                "<h2>Angebot</h2>"
                f'<p><a href="{_e(offer_url)}"><strong>Angebot mit '
                "Anfragedaten vorbereiten →</strong></a></p>"
                '<p class="subtitle">Füllt nur einen bearbeitbaren '
                "Angebotsentwurf vor. Kein Auftrag, keine Freigabe und keine "
                "Nachricht an den Kunden.</p>"
            )
        crm_stage_field = (
            f'{_e(ACTIVE_ORDER_CRM_STAGE)}<input type="hidden" name="crm_stage" '
            f'value="{_e(ACTIVE_ORDER_CRM_STAGE)}">'
            if has_active_order
            else _crm_stage_select(inq.crm_stage)
        )
        body = (
            inquiry_truncation_warning
            + website_banner
            + f"""<table>
<tr><th>Datum</th><td>{_e(inq.event_date.isoformat())}</td></tr>
<tr><th>Kanal</th><td>{_e(_source_label(inq.inquiry_source))}</td></tr>
<tr><th>Zeitfenster</th><td>{_e(inq.time_window_text)}</td></tr>
<tr><th>Ort</th><td>{_e(inq.location_text)}</td></tr>
<tr><th>Gäste</th><td>{_e(guests or "–")}</td></tr>
<tr><th>CRM-Stufe</th><td>{_e(inq.crm_stage)}</td></tr>
<tr><th>Verifizierung</th><td>{_e(_verification_label(inq.call_verification_status))}</td></tr>
{intake_rows}</table>
<h2>Vorgangsprüfung (Progression)</h2>{prog}
<p>{verify_btn}{convert}</p>
{offer_prefill}
<h2>Anfrage bearbeiten</h2>
<form method="post" action="/inquiry/{_e(inquiry_id)}/update">{_csrf_input(context)}{self._command_fields({"updated_at": inq.updated_at.isoformat()})}<fieldset>
<p><label>Datum</label><input type="date" name="event_date" value="{_e(inq.event_date.isoformat())}"></p>
<p><label>Zeitfenster</label><input name="time_window_text" value="{_e(inq.time_window_text)}"></p>
<p><label>Ort</label><input name="location_text" value="{_e(inq.location_text)}"></p>
<p><label>Gäste (ca.)</label><input name="guest_count_estimate" value="{_e(guests)}"></p>
<p><label>Planungsmodus</label>{_planning_mode_select(inq.planning_mode)}</p>
<p><label>CRM-Stufe</label>{crm_stage_field}</p>
<p class="subtitle">Intake-Kontext — keine Auftrags-/Küchenfreigabe.</p>
<p><label>Betreff</label><input name="intake_subject" value="{_e(inq.intake_subject or "")}"></p>
<p><label>Nachricht</label><textarea name="intake_message" rows="4">{_e(inq.intake_message or "")}</textarea></p>
<p><label>Zusammenfassung</label><textarea name="intake_summary" rows="3">{_e(inq.intake_summary or "")}</textarea></p>
<p><label>Externe Referenz</label><input name="intake_external_ref" value="{_e(inq.intake_external_ref or "")}"></p>
<p><button type="submit">Speichern</button></p>
</fieldset></form>"""
        )
        return _page(
            f"Anfrage {inq.inquiry_id[:8]}",
            body,
            active_section="inquiries",
            context=context,
        )

    def update_inquiry(self, inquiry_id: str, form: dict[str, str]) -> None:
        crm_stage = validate_crm_stage(form.get("crm_stage", CRM_PIPELINE[0]))
        has_active_order = any(
            order.source_inquiry_id == inquiry_id and order.cancelled_at is None
            for order in self._orders.list_orders()
        )
        if (
            self._remote is None
            and has_active_order
            and not inquiry_crm_stage_is_compatible_with_active_order(crm_stage)
        ):
            raise ValueError("active order requires Bestätigt / Auftrag CRM stage")
        self.inquiry_service.update_inquiry(
            inquiry_id,
            event_date=date.fromisoformat(form["event_date"]),
            time_window_text=form.get("time_window_text", ""),
            location_text=form.get("location_text", ""),
            guest_count_estimate=_opt_int(form.get("guest_count_estimate", "")),
            planning_mode=form.get("planning_mode", PLANNING_MODES[0]),
            crm_stage=crm_stage,
            intake_subject=form.get("intake_subject", ""),
            intake_message=form.get("intake_message", ""),
            intake_summary=form.get("intake_summary", ""),
            intake_external_ref=form.get("intake_external_ref", ""),
        )

    def convert_inquiry_to_order(self, inquiry_id: str) -> tuple[Order, OrderVersion]:
        """Run the truthful gate and stage transition as one direct command.

        Remote mode delegates the same atomic command to Core Office API.
        """

        def work() -> tuple[Order, OrderVersion]:
            inquiry = self._inquiries.get_by_id(inquiry_id)
            if inquiry is None:
                raise KeyError(inquiry_id)
            linked_orders = [
                order
                for order in self._orders.list_orders()
                if order.source_inquiry_id == inquiry_id
            ]
            has_active_order = any(
                order.cancelled_at is None for order in linked_orders
            )
            state = self._inquiry_office_state(
                inquiry,
                linked_orders,
                inquiry_id=inquiry_id,
            )
            if has_active_order:
                raise ValueError("inquiry already converted")
            if inquiry.crm_stage == "Abgelehnt / verloren":
                raise ValueError("rejected inquiry cannot be converted")
            offer = self._offers.get_by_source_inquiry_id(inquiry_id)
            if offer is not None and offer_blocks_direct_inquiry_conversion(
                offer, today=api_views.berlin_today()
            ):
                raise ValueError("offer blocks conversion")
            if state.next_action != "convert":
                raise ValueError("inquiry conversion gate is not satisfied")
            order, version = self.order_service.convert_inquiry_to_order(inquiry)
            if self._remote is None:
                self.inquiry_service.update_inquiry(
                    inquiry_id,
                    crm_stage="Bestätigt / Auftrag",
                )
            return order, version

        if self._remote is not None:
            inquiry = self._inquiries.get_by_id(inquiry_id)
            if inquiry is None:
                raise KeyError(inquiry_id)
            return self.order_service.convert_inquiry_to_order(inquiry)
        if self._command_executor is not None:
            return self._command_executor.run(work)
        return work()

    def convert_accepted_offer_for_inquiry(
        self, inquiry_id: str
    ) -> tuple[Order, OrderVersion]:
        """Run the accepted-offer conversion through the existing Core command path."""

        def work() -> tuple[Order, OrderVersion]:
            inquiry = self._inquiries.get_by_id(inquiry_id)
            if inquiry is None:
                raise KeyError(inquiry_id)
            linked_orders = [
                order
                for order in self._orders.list_orders()
                if order.source_inquiry_id == inquiry_id
            ]
            state = self._inquiry_office_state(
                inquiry,
                linked_orders,
                inquiry_id=inquiry_id,
            )
            if not inquiry_allows_convert_accepted_command(state):
                offer = self._offers.get_by_source_inquiry_id(inquiry_id)
                link = offer.conversion_link if offer is not None else None
                if link is not None:
                    order = self._orders.get_order(link.order_id)
                    versions = self._orders.list_order_versions(link.order_id)
                    order_version = next(
                        (item for item in versions if item.version_number == 1),
                        None,
                    )
                    if order is not None and order_version is not None:
                        return order, order_version
                raise ValueError("accepted offer conversion gate is not satisfied")
            assert state.offer is not None
            projection = state.offer
            if (
                projection.accepted_variant_id is None
                or projection.acceptance_id is None
            ):
                raise ValueError("accepted offer conversion gate is not satisfied")
            offer_service = OfferService(
                self._offers,
                self._inquiries,
                self._orders,
                today=api_views.berlin_today,
            )
            converted, order, order_version = offer_service.convert_accepted_offer(
                projection.offer_id,
                projection.offer_version_id,
                projection.accepted_variant_id,
                projection.acceptance_id,
            )
            commercial_version = next(
                item
                for item in converted.versions
                if item.offer_version_id == projection.offer_version_id
            )
            self.payment_reminder_service.seed_from_conversion(
                order.order_id,
                commercial_version.payment_method,
            )
            self.inquiry_service.update_inquiry(
                inquiry_id,
                crm_stage=ACTIVE_ORDER_CRM_STAGE,
            )
            return order, order_version

        if self._remote is not None:
            inquiry = self._inquiries.get_by_id(inquiry_id)
            if inquiry is None:
                raise KeyError(inquiry_id)
            linked_orders = [
                order
                for order in self._orders.list_orders()
                if order.source_inquiry_id == inquiry_id
            ]
            state = self._inquiry_office_state(
                inquiry,
                linked_orders,
                inquiry_id=inquiry_id,
            )
            if not inquiry_allows_convert_accepted_command(state):
                offer = self._offers.get_by_source_inquiry_id(inquiry_id)
                link = offer.conversion_link if offer is not None else None
                if link is not None:
                    order = self._orders.get_order(link.order_id)
                    versions = self._orders.list_order_versions(link.order_id)
                    order_version = next(
                        (item for item in versions if item.version_number == 1),
                        None,
                    )
                    if order is not None and order_version is not None:
                        return order, order_version
                raise ValueError("accepted offer conversion gate is not satisfied")
            assert state.offer is not None
            projection = state.offer
            if (
                projection.accepted_variant_id is None
                or projection.acceptance_id is None
            ):
                raise ValueError("accepted offer conversion gate is not satisfied")
            order_id, order_version_id = self._remote.convert_accepted_offer(
                projection.offer_id,
                projection.offer_version_id,
                accepted_variant_id=projection.accepted_variant_id,
                acceptance_id=projection.acceptance_id,
            )
            order = self._orders.get_order(order_id)
            order_version = self._orders.get_order_version(order_version_id)
            if order is None or order_version is None:
                raise ValueError("accepted offer conversion response incomplete")
            return order, order_version
        if self._command_executor is not None:
            return self._command_executor.run(work)
        return work()

    # -- orders ----------------------------------------------------------

    def render_order(
        self,
        order_id: str,
        *,
        context: OfficePageContext = _EMPTY_PAGE_CONTEXT,
    ) -> str | None:
        order = self._orders.get_order(order_id)
        if order is None:
            return None
        versions = self._orders.list_order_versions(order_id)
        versions_total_count = len(versions)
        versions_truncated = False
        if self._remote is not None:
            versions_total_count, versions_truncated = self._remote.order_versions_meta(
                order_id
            )
        cancelled = order.cancelled_at is not None
        ev = self.core.evaluate_ready_to_send(order_id)
        payment = self.payment_reminder_service.view(order_id)
        if self._ui_version == "v2":
            print_confirm_fields: dict[str, str] = {}
            effective_fields: dict[str, str] = {}
            if not cancelled:
                for version in versions:
                    if version.kitchen_print_confirmed_at is None:
                        print_confirm_fields[version.order_version_id] = (
                            self._command_fields()
                        )
                    if (
                        version.kitchen_print_confirmed_at is not None
                        and version.order_version_id != order.effective_order_version_id
                    ):
                        effective_fields[version.order_version_id] = (
                            self._command_fields(
                                {
                                    "effective_version_id": (
                                        order.effective_order_version_id or ""
                                    )
                                }
                            )
                        )
            latest_version_number = versions_total_count or max(
                (version.version_number for version in versions), default=0
            )
            change_prefill = version_change_prefill(
                order,
                versions,
                latest_version_number=latest_version_number,
            )
            detail = render_order_detail(
                order,
                versions,
                ev,
                payment,
                api_views.resolve_next_action(order, versions),
                forms=OrderDetailFormFields(
                    csrf_input=_csrf_input(context),
                    print_confirm_command_fields=print_confirm_fields,
                    effective_command_fields=effective_fields,
                    ready_command_fields=(
                        self._command_fields() if not cancelled else ""
                    ),
                    cancel_command_fields=(
                        self._command_fields(
                            {"updated_at": order.updated_at.isoformat()}
                        )
                        if not cancelled
                        else ""
                    ),
                    version_command_fields=(
                        self._command_fields(
                            {"latest_version_number": str(latest_version_number)}
                        )
                        if not cancelled
                        else ""
                    ),
                    payment_command_fields=(
                        self._command_fields(
                            {
                                "payment_reminder_updated_at": (
                                    payment.updated_at.isoformat()
                                    if payment.updated_at
                                    else ""
                                )
                            }
                        )
                        if not cancelled
                        else ""
                    ),
                    version_change_prefill=change_prefill if not cancelled else None,
                ),
                versions_total_count=versions_total_count,
                versions_truncated=versions_truncated,
            )
            return _page(
                detail.title,
                detail.body,
                active_section="orders",
                context=context,
                show_title=False,
            )
        rows = []
        for v in versions:
            printed = (
                v.kitchen_print_confirmed_at.isoformat()
                if v.kitchen_print_confirmed_at
                else "–"
            )
            marks = []
            if v.order_version_id == order.effective_order_version_id:
                marks.append("wirksam")
            if v.order_version_id == order.candidate_order_version_id:
                marks.append("Kandidat")
            actions = [
                f'<a href="/order/{_e(order_id)}/print?version={_e(v.order_version_id)}">Küchenzettel</a>',
                f'<a href="/order/{_e(order_id)}/buffet-cards?version={_e(v.order_version_id)}">Buffetschilder</a>',
            ]
            if not cancelled:
                if v.kitchen_print_confirmed_at is None:
                    actions.append(
                        f'<form class="inline" method="post" action="/order/{_e(order_id)}/print-confirm">'
                        f"{_csrf_input(context)}{self._command_fields()}"
                        f'<input type="hidden" name="order_version_id" value="{_e(v.order_version_id)}">'
                        "<button>Druck bestätigen</button></form>"
                    )
                if (
                    v.kitchen_print_confirmed_at is not None
                    and v.order_version_id != order.effective_order_version_id
                ):
                    actions.append(
                        f'<form class="inline" method="post" action="/order/{_e(order_id)}/effective">'
                        f"{_csrf_input(context)}"
                        f"{self._command_fields({'effective_version_id': order.effective_order_version_id or ''})}"
                        f'<input type="hidden" name="order_version_id" value="{_e(v.order_version_id)}">'
                        "<button>Wirksam machen</button></form>"
                    )
            rows.append(
                f"<tr><td>v{v.version_number}</td><td>{_e(v.event_date.isoformat())}</td>"
                f"<td>{_e(v.time_window_text)}</td><td>{_e(v.location_text)}</td>"
                f"<td>{_e(str(v.guest_count_estimate) if v.guest_count_estimate is not None else '–')}</td>"
                f"<td>{_e(printed)}</td><td>{_e(', '.join(marks) or '–')}</td>"
                f"<td>{' '.join(actions)}</td></tr>"
            )
        if ev.ready:
            release = '<p class="ok">READY_TO_SEND: bereit.</p>'
        else:
            reasons = "".join(
                f"<li>{_e(_ready_to_send_blocker_label(r))}</li>" for r in ev.reasons
            )
            release = (
                f'<p class="blocked">Versandfreigabe blockiert:</p><ul>{reasons}</ul>'
            )
        payment_rows = [
            f"<p><strong>Zahlungsart:</strong> {_e(payment.payment_method_label)}</p>"
        ]
        if payment.invoice_state_label is not None:
            payment_rows.append(
                f"<p><strong>Rechnung:</strong> {_e(payment.invoice_state_label)}</p>"
            )
        if payment.invoice_number:
            payment_rows.append(
                f"<p><strong>Rechnungsnummer:</strong> {_e(payment.invoice_number)}</p>"
            )
        for label, value in (
            ("Versendet am", payment.sent_on),
            ("Fällig am", payment.due_on),
            ("Bezahlt am", payment.paid_on),
        ):
            if value is not None:
                payment_rows.append(
                    f"<p><strong>{label}:</strong> {_e(value.isoformat())}</p>"
                )
        payment_rows.append(
            f"<p><strong>Zahlungsstatus:</strong> {_e(payment.payment_state_label)}</p>"
        )
        if payment.next_step:
            payment_rows.append(
                f"<p><strong>Nächster Schritt:</strong> {_e(payment.next_step)}</p>"
            )
        payment_form = ""
        if not cancelled:
            options = ['<option value="">Bitte wählen</option>']
            for method in PAYMENT_METHODS:
                selected = " selected" if payment.payment_method == method else ""
                options.append(
                    f'<option value="{method}"{selected}>'
                    f"{_e(PAYMENT_METHOD_LABELS[method])}</option>"
                )
            expect = {
                "payment_reminder_updated_at": (
                    payment.updated_at.isoformat() if payment.updated_at else ""
                )
            }
            payment_form = f"""
<form method="post" action="/order/{_e(order_id)}/payment-reminder">{_csrf_input(context)}{self._command_fields(expect)}<fieldset>
<p><label>Zahlungsart*</label><select name="payment_method" required>{"".join(options)}</select></p>
<p><label><input type="checkbox" name="invoice_created" value="1"{" checked" if payment.invoice_created else ""}> Rechnung in der Buchhaltung erstellt</label></p>
<p><label>Rechnungsnummer</label><input name="invoice_number" maxlength="200" value="{_e(payment.invoice_number or "")}"></p>
<p><label>Versendet am</label><input type="date" name="sent_on" value="{payment.sent_on.isoformat() if payment.sent_on else ""}"></p>
<p><label>Fällig am</label><input type="date" name="due_on" value="{payment.due_on.isoformat() if payment.due_on else ""}"></p>
<p><label>Bezahlt am</label><input type="date" name="paid_on" value="{payment.paid_on.isoformat() if payment.paid_on else ""}"></p>
<p><label><input type="checkbox" name="cash_received" value="1"{" checked" if payment.cash_received else ""}> Barzahlung erhalten</label></p>
<p><button type="submit">Zahlungshinweis speichern</button></p>
</fieldset></form>"""
        header = '<p class="cancelled">STORNIERT</p>' if cancelled else ""
        actions_block = ""
        if not cancelled:
            latest_version_number = versions_total_count or max(
                (v.version_number for v in versions), default=0
            )
            prefill = version_change_prefill(
                order,
                versions,
                latest_version_number=latest_version_number,
            )
            assert prefill is not None
            actions_block = f"""
<p>
<form class="inline" method="post" action="/order/{_e(order_id)}/ready">{_csrf_input(context)}{self._command_fields()}<button>Freigabe anfordern</button></form>
<form class="inline" method="post" action="/order/{_e(order_id)}/cancel">{_csrf_input(context)}{self._command_fields({"updated_at": order.updated_at.isoformat()})}<button>Auftrag stornieren</button></form>
</p>
<h2>Neue Version</h2>
<form method="post" action="/order/{_e(order_id)}/version">{_csrf_input(context)}{self._command_fields({"latest_version_number": str(latest_version_number)})}<input type="hidden" name="latest_version_number" value="{_e(prefill.latest_version_number)}"><fieldset>
<p><label>Datum*</label><input type="date" name="event_date" required value="{_e(prefill.event_date)}"></p>
<p><label>Zeitfenster</label><input name="time_window_text" value="{_e(prefill.time_window_text)}"></p>
<p><label>Ort</label><input name="location_text" value="{_e(prefill.location_text)}"></p>
<p><label>Gäste (ca.)</label><input name="guest_count_estimate" inputmode="numeric" value="{_e(prefill.guest_count_estimate)}"></p>
<p><label>Planungsmodus</label>{_planning_mode_select(prefill.planning_mode)}</p>
<p><button type="submit">Version anlegen</button></p>
</fieldset></form>"""
        truncation_warning = (
            '<p class="blocked"><strong>Unvollständige Ansicht:</strong> '
            f"Es werden {len(versions)} von {versions_total_count} Versionen "
            "angezeigt.</p>"
            if versions_truncated
            else ""
        )
        body = f"""{header}{truncation_warning}
<p>Anfrage: <a href="/inquiry/{_e(order.source_inquiry_id)}">{_e(order.source_inquiry_id[:8])}</a></p>
<h2>Versionen</h2>
<table><tr><th>Nr</th><th>Datum</th><th>Zeitfenster</th><th>Ort</th><th>Gäste</th>
<th>Druck bestätigt</th><th>Status</th><th>Aktionen</th></tr>{"".join(rows)}</table>
<h2>Zahlung</h2>{"".join(payment_rows)}{payment_form}
<h2>Freigabe (READY_TO_SEND)</h2>{release}
{actions_block}"""
        return _page(
            f"Auftrag {order.order_id[:8]}",
            body,
            active_section="orders",
            context=context,
        )

    def save_payment_reminder(self, order_id: str, form: dict[str, str]) -> None:
        def optional_date(name: str) -> date | None:
            raw = form.get(name, "").strip()
            return date.fromisoformat(raw) if raw else None

        reminder = OrderPaymentReminder(
            order_id=order_id,
            payment_method=validate_payment_method(form.get("payment_method", "")),
            invoice_created=form.get("invoice_created") == "1",
            invoice_number=form.get("invoice_number", "").strip() or None,
            sent_on=optional_date("sent_on"),
            due_on=optional_date("due_on"),
            paid_on=optional_date("paid_on"),
            cash_received=form.get("cash_received") == "1",
        )

        def work() -> None:
            self.payment_reminder_service.save(reminder)

        if self._remote is not None:
            work()
        elif self._command_executor is not None:
            self._command_executor.run(work)
        else:
            work()

    def create_version(self, order_id: str, form: dict[str, str]) -> None:
        order = self._orders.get_order(order_id)
        if order is None:
            raise ValueError(f"no order with id {order_id!r}")
        if self._remote is None:
            versions = self._orders.list_order_versions(order_id)
            latest = max((version.version_number for version in versions), default=0)
            expected_raw = (
                form.get("_expect_latest_version_number", "").strip()
                or form.get("latest_version_number", "").strip()
            )
            if expected_raw and int(expected_raw) != latest:
                raise ValueError(
                    "Der Auftrag wurde zwischenzeitlich geändert. "
                    "Bitte laden Sie die Seite neu."
                )

        def work() -> None:
            version = self.order_service.create_relevant_order_change_version(
                order,
                event_date=date.fromisoformat(form["event_date"]),
                time_window_text=form.get("time_window_text", ""),
                location_text=form.get("location_text", ""),
                guest_count_estimate=_opt_int(form.get("guest_count_estimate", "")),
                planning_mode=form.get("planning_mode", PLANNING_MODES[0]),
            )
            if self._remote is None:
                self.order_service.set_candidate_order_version(
                    order_id, version.order_version_id
                )

        if self._remote is not None:
            work()
        elif self._command_executor is not None:
            self._command_executor.run(work)
        else:
            work()


def _opt_int(raw: str) -> int | None:
    raw = raw.strip()
    if not raw:
        return None
    return int(raw)


def make_office_panel_handler(
    inquiry_repo: InquiryRepository,
    order_repo: OrderRepository,
    password: str,
    auerswald_url: str = "",
    auerswald_user: str = "",
    auerswald_password: str = "",
    kiosk_url: str = "",
    configurator_url: str = "",
    *,
    remote: "RemoteCoreClient | None" = None,
    command_executor: "CoreCommandExecutor | None" = None,
    payment_reminder_repo: PaymentReminderRepository | None = None,
    offer_repo: OfferRepository | None = None,
    ui_version: str = "legacy",
) -> type[BaseHTTPRequestHandler]:
    """Compatibility wrapper; HTTP routing lives in office_panel_http."""
    from catering_system.ui.office_panel_http import (
        make_office_panel_handler as make_handler,
    )

    return make_handler(
        inquiry_repo,
        order_repo,
        password,
        auerswald_url,
        auerswald_user,
        auerswald_password,
        kiosk_url,
        configurator_url,
        remote=remote,
        command_executor=command_executor,
        payment_reminder_repo=payment_reminder_repo,
        offer_repo=offer_repo,
        ui_version=ui_version,
    )


def create_office_panel_server(
    inquiry_repo: InquiryRepository,
    order_repo: OrderRepository,
    password: str,
    host: str = "0.0.0.0",
    port: int = 8081,
    auerswald_url: str = "",
    auerswald_user: str = "",
    auerswald_password: str = "",
    kiosk_url: str = "",
    configurator_url: str = "",
    *,
    remote: "RemoteCoreClient | None" = None,
    command_executor: "CoreCommandExecutor | None" = None,
    payment_reminder_repo: PaymentReminderRepository | None = None,
    offer_repo: OfferRepository | None = None,
    ui_version: str = "legacy",
) -> HTTPServer:
    """Compatibility wrapper; server construction lives in office_panel_http."""
    from catering_system.ui.office_panel_http import (
        create_office_panel_server as create_server,
    )

    return create_server(
        inquiry_repo,
        order_repo,
        password,
        host,
        port,
        auerswald_url,
        auerswald_user,
        auerswald_password,
        kiosk_url,
        configurator_url,
        remote=remote,
        command_executor=command_executor,
        payment_reminder_repo=payment_reminder_repo,
        offer_repo=offer_repo,
        ui_version=ui_version,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Office panel (LAN-only write surface)"
    )
    parser.add_argument(
        "--db",
        default="",
        help="Path to the Core SQLite database (direct mode only; omit when "
        "CORE_OFFICE_API_URL/CORE_OFFICE_API_TOKEN select remote mode)",
    )
    parser.add_argument(
        "--core-office-api-url",
        default=os.environ.get("CORE_OFFICE_API_URL", ""),
        help="Base URL of the frozen Core Office API (or set "
        "CORE_OFFICE_API_URL) — Phase 2 remote mode: set together with "
        "CORE_OFFICE_API_TOKEN (env only, never a flag) to run the panel "
        "without ever opening core.db",
    )
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument(
        "--password",
        default=os.environ.get("OFFICE_PANEL_PASSWORD", ""),
        help="Office password (or set OFFICE_PANEL_PASSWORD)",
    )
    parser.add_argument(
        "--auerswald-url",
        default=os.environ.get("AUERSWALD_SYNC_URL", ""),
        help="Base URL of the separate auerswald-sync call-log service "
        "(or set AUERSWALD_SYNC_URL) — read-only Rückrufe list, optional",
    )
    parser.add_argument(
        "--auerswald-user",
        default=os.environ.get("AUERSWALD_SYNC_USER", ""),
        help="Basic auth user for auerswald-sync (or set AUERSWALD_SYNC_USER)",
    )
    parser.add_argument(
        "--auerswald-password",
        default=os.environ.get("AUERSWALD_SYNC_PASSWORD", ""),
        help="Basic auth password for auerswald-sync (or set AUERSWALD_SYNC_PASSWORD)",
    )
    parser.add_argument(
        "--kiosk-url",
        default=os.environ.get("KIOSK_URL", ""),
        help="Base URL of the separate kitchen kiosk (or set KIOSK_URL) — "
        "single source of truth for the optional 'full week' deep link, optional",
    )
    parser.add_argument(
        "--configurator-url",
        default=os.environ.get("CONFIGURATOR_URL", ""),
        help="Base URL of the separate offer configurator (or set "
        "CONFIGURATOR_URL); empty keeps Inquiry-to-offer prefill dormant",
    )
    parser.add_argument(
        "--ui-version",
        choices=("legacy", "v2"),
        default=os.environ.get("OFFICE_UI_VERSION", "legacy"),
        help="Office presentation version (or set OFFICE_UI_VERSION); "
        "legacy is the safe rollout default",
    )
    args = parser.parse_args()
    if not args.password:
        raise SystemExit(
            "office panel refuses to start without a password "
            "(--password or OFFICE_PANEL_PASSWORD): it is a write surface (pack §7)"
        )

    # Phase 2 dual mode (pack §7): CORE_OFFICE_API_URL and CORE_OFFICE_API_TOKEN
    # must be set together (remote mode) or both left empty (direct mode) — a
    # half-configured pair is refused before anything else opens: no core.db,
    # no socket bound. The token is env-only, never a CLI flag, so it never
    # appears in argv/process listings (matching the Core Office API server's
    # own OFFICE_API_TOKEN convention).
    core_api_url = args.core_office_api_url
    core_api_token = os.environ.get("CORE_OFFICE_API_TOKEN", "")
    if bool(core_api_url) != bool(core_api_token):
        raise SystemExit(
            "CORE_OFFICE_API_URL and CORE_OFFICE_API_TOKEN must be set together "
            "(remote mode) or both left empty (direct mode)"
        )

    if core_api_url:
        from catering_system.ui.remote_core_client import RemoteCoreClient

        remote = RemoteCoreClient(core_api_url, core_api_token)
        server = create_office_panel_server(
            remote,
            remote,
            args.password,
            args.host,
            args.port,
            args.auerswald_url,
            args.auerswald_user,
            args.auerswald_password,
            args.kiosk_url,
            args.configurator_url,
            remote=remote,
            ui_version=args.ui_version,
        )
        print(
            f"Office panel on http://{args.host}:{args.port}/ (user: office) "
            f"— remote mode against {core_api_url}"
        )
    else:
        if not args.db:
            raise SystemExit(
                "--db is required in direct mode (or set CORE_OFFICE_API_URL "
                "and CORE_OFFICE_API_TOKEN for remote mode)"
            )
        from catering_system.repositories.core_transaction import (
            CoreCommandExecutor,
            open_core_connection,
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
        payment_reminder_repo = SQLitePaymentReminderRepository.from_connection(
            connection
        )

        server = create_office_panel_server(
            inquiry_repo,
            order_repo,
            args.password,
            args.host,
            args.port,
            args.auerswald_url,
            args.auerswald_user,
            args.auerswald_password,
            args.kiosk_url,
            args.configurator_url,
            command_executor=CoreCommandExecutor(connection),
            payment_reminder_repo=payment_reminder_repo,
            offer_repo=offer_repo,
            catalog_repo=catalog_repo,
            ui_version=args.ui_version,
        )
        print(f"Office panel on http://{args.host}:{args.port}/ (user: office)")
    server.serve_forever()


if __name__ == "__main__":
    main()
