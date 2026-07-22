"""HTTP transport and routing for the office panel.

The UI composition and Core orchestration live in ``office_panel``. This module
owns only Basic Auth, request parsing, route dispatch and the HTTPServer wiring.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, quote, unquote, urlparse

from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.offer_repository import OfferRepository
from catering_system.repositories.catalog_repository import CatalogRepository
from catering_system.repositories.order_repository import OrderRepository
from catering_system.repositories.payment_reminder_repository import (
    PaymentReminderRepository,
)
from catering_system.repositories.contact_internal_note_repository import (
    ContactInternalNoteRepository,
)
from catering_system.repositories.contact_profile_repository import (
    ContactProfileRepository,
)
from catering_system.repositories.order_confirmation_document_repository import (
    OrderConfirmationDocumentRepository,
)
from catering_system.repositories.order_confirmation_outbound_repository import (
    OrderConfirmationOutboundRepository,
)
from catering_system.repositories.order_operational_pause_repository import (
    OrderOperationalPauseRepository,
)
from catering_system.integration.auerswald_sync import (
    fetch_missed_board,
    resolve_missed_call,
)
from catering_system.ui.office_panel import (
    OfficePageContext,
    OfficePanel,
    _e,
    _page,
    fetch_rueckruf_count,
    parse_proposal_payload,
    render_print_sheet,
    render_buffet_cards,
    render_proposal_preview,
    render_proposal_preview_form,
    render_rueckruf,
)
from catering_system.services.order_print_projection_service import (
    OrderPrintProjectionService,
    PrintProjectionNotFoundError,
)
from catering_system.services.order_confirmation_document_preview import (
    build_preview,
    render_preview_html,
)
from catering_system.services.order_confirmation_document_service import (
    OrderConfirmationDocumentNotFoundError,
)
from catering_system.services.buffet_cards_service import BuffetCardsService
from catering_system.ui.remote_core_client import RemoteCoreError

if TYPE_CHECKING:
    from catering_system.repositories.core_transaction import CoreCommandExecutor
    from catering_system.ui.remote_core_client import RemoteCoreClient

_CSRF_CONTEXT = b"catering-office-panel-csrf-v1"
_MAX_FORM_BODY_BYTES = 256 * 1024
_UNAVAILABLE_MESSAGE = "Core nicht erreichbar — nichts wurde gespeichert."

_INQUIRY_COMMAND_ERROR_LABELS: dict[str, str] = {
    "conversion_blocked": (
        "Das angenommene Angebot kann derzeit nicht in einen Auftrag umgewandelt werden."
    ),
    "already_converted": "Für diese Anfrage existiert bereits ein Auftrag.",
    "accepted_offer_required": (
        "Auftrag nur aus angenommenem Angebot — "
        "direkte Umwandlung aus der Anfrage ist nicht möglich."
    ),
    "verification_gate_blocked": (
        "Die Rückrufprüfung ist noch nicht erfüllt — "
        "eine Umwandlung ist noch nicht möglich."
    ),
    "offer_blocks_conversion": (
        "Der Angebotsprozess blockiert die direkte Umwandlung in einen Auftrag."
    ),
    "contact_information_incomplete": (
        "Kontaktdaten unvollständig — E-Mail-Adresse und Telefonnummer "
        "müssen vor dem nächsten Schritt vorliegen."
    ),
    "contact_conflict": (
        "Vorhandene Kontaktdaten können nicht ersetzt werden — "
        "es dürfen nur fehlende Angaben ergänzt werden."
    ),
    "invalid_contact_value": (
        "Die eingegebenen Kontaktdaten sind ungültig — bitte E-Mail-Adresse "
        "oder Telefonnummer prüfen."
    ),
}


_OFFER_COMMAND_ERROR_LABELS: dict[str, str] = {
    "sent_evidence_exists": (
        "Für diese Angebotsversion ist bereits ein Versand vermerkt."
    ),
    "acceptance_already_exists": "Für dieses Angebot ist bereits eine Annahme erfasst.",
    "invalid_variant": "Die gewählte Variante gehört nicht zu dieser Angebotsversion.",
    "acceptance_blocked": "Die Annahme kann in diesem Angebotsstatus nicht erfasst werden.",
    "sent_recording_blocked": (
        "Der Versand kann in diesem Angebotsstatus nicht vermerkt werden."
    ),
    "conversion_already_exists": "Dieses Angebot wurde bereits in einen Auftrag umgewandelt.",
    "conversion_blocked": (
        "Das angenommene Angebot kann derzeit nicht in einen Auftrag umgewandelt werden."
    ),
}


def office_command_error_message(code_or_text: str) -> str:
    if code_or_text in _INQUIRY_COMMAND_ERROR_LABELS:
        return _INQUIRY_COMMAND_ERROR_LABELS[code_or_text]
    if code_or_text in _OFFER_COMMAND_ERROR_LABELS:
        return _OFFER_COMMAND_ERROR_LABELS[code_or_text]
    lowered = code_or_text.lower()
    if "sent evidence already exists" in lowered:
        return _OFFER_COMMAND_ERROR_LABELS["sent_evidence_exists"]
    if "acceptance already exists" in lowered:
        return _OFFER_COMMAND_ERROR_LABELS["acceptance_already_exists"]
    if "accepted variant does not belong" in lowered:
        return _OFFER_COMMAND_ERROR_LABELS["invalid_variant"]
    if "acceptance blocked" in lowered or "acceptance blocks sent" in lowered:
        return _OFFER_COMMAND_ERROR_LABELS["acceptance_blocked"]
    if "sent recording blocked" in lowered:
        return _OFFER_COMMAND_ERROR_LABELS["sent_recording_blocked"]
    if "conversion link already exists" in lowered or "conversion already" in lowered:
        return _OFFER_COMMAND_ERROR_LABELS["conversion_already_exists"]
    if "accepted offer conversion gate" in lowered or "conversion blocked" in lowered:
        return _OFFER_COMMAND_ERROR_LABELS["conversion_blocked"]
    if "accepted offer required" in lowered:
        return _INQUIRY_COMMAND_ERROR_LABELS["accepted_offer_required"]
    if "offer blocks conversion" in lowered:
        return _INQUIRY_COMMAND_ERROR_LABELS["offer_blocks_conversion"]
    if "contact information incomplete" in lowered:
        return _INQUIRY_COMMAND_ERROR_LABELS["contact_information_incomplete"]
    if "already recorded and cannot change" in lowered:
        return _INQUIRY_COMMAND_ERROR_LABELS["contact_conflict"]
    if "contact email is empty or invalid" in lowered:
        return _INQUIRY_COMMAND_ERROR_LABELS["invalid_contact_value"]
    if "contact phone is empty or invalid" in lowered:
        return _INQUIRY_COMMAND_ERROR_LABELS["invalid_contact_value"]
    if "contact completion requires email or phone" in lowered:
        return _INQUIRY_COMMAND_ERROR_LABELS["invalid_contact_value"]
    if "intake requires email and phone" in lowered:
        return _INQUIRY_COMMAND_ERROR_LABELS["contact_information_incomplete"]
    if "inquiry conversion gate" in lowered or "verification" in lowered:
        return _INQUIRY_COMMAND_ERROR_LABELS["verification_gate_blocked"]
    if "already converted" in lowered or "active order blocks" in lowered:
        return _INQUIRY_COMMAND_ERROR_LABELS["already_converted"]
    return code_or_text


def inquiry_command_error_message(code_or_text: str) -> str:
    return office_command_error_message(code_or_text)


class FormBodyTooLargeError(ValueError):
    pass


def csrf_token_for_password(password: str) -> str:
    """Derive a stable form token without exposing the Basic Auth password."""
    return hmac.new(password.encode("utf-8"), _CSRF_CONTEXT, hashlib.sha256).hexdigest()


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
    confirmation_document_repo: OrderConfirmationDocumentRepository | None = None,
    confirmation_outbound_repo: OrderConfirmationOutboundRepository | None = None,
    pause_repository: OrderOperationalPauseRepository | None = None,
    contact_note_repo: ContactInternalNoteRepository | None = None,
    contact_profile_repo: ContactProfileRepository | None = None,
    offer_repo: OfferRepository | None = None,
    catalog_repo: CatalogRepository | None = None,
    ui_version: str = "legacy",
) -> type[BaseHTTPRequestHandler]:
    panel = OfficePanel(
        inquiry_repo,
        order_repo,
        kiosk_url,
        configurator_url,
        remote=remote,
        command_executor=command_executor,
        payment_reminder_repo=payment_reminder_repo,
        confirmation_document_repo=confirmation_document_repo,
        confirmation_outbound_repo=confirmation_outbound_repo,
        pause_repository=pause_repository,
        contact_note_repo=contact_note_repo,
        contact_profile_repo=contact_profile_repo,
        offer_repo=offer_repo,
        catalog_repo=catalog_repo,
        ui_version=ui_version,
    )
    expected = "Basic " + base64.b64encode(f"office:{password}".encode()).decode()
    csrf_token = csrf_token_for_password(password)

    class OfficePanelHandler(BaseHTTPRequestHandler):
        server_version = "OfficePanel/1.0"

        def _authorized(self) -> bool:
            return hmac.compare_digest(self.headers.get("Authorization", ""), expected)

        def _security_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
                "form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
            )
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")

        def end_headers(self) -> None:
            self._security_headers()
            super().end_headers()

        def _deny(self) -> None:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Office"')
            self.end_headers()

        def _html(self, page: str, status: int = 200) -> None:
            payload = page.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _redirect(self, location: str) -> None:
            self.send_response(303)
            self.send_header("Location", location)
            self.end_headers()

        def _fetch_page_context(self) -> OfficePageContext:
            return OfficePageContext(
                rueckruf_count=fetch_rueckruf_count(
                    auerswald_url, auerswald_user, auerswald_password
                ),
                csrf_token=csrf_token,
            )

        def _fetch_enriched_missed_board(self) -> tuple[list[dict] | None, str | None]:
            items, error = fetch_missed_board(
                auerswald_url, auerswald_user, auerswald_password
            )
            if items is not None:
                items = panel.enrich_rueckruf_items(items)
            return items, error

        def _error_page(self, message: str, status: int = 400) -> None:
            self._html(
                _page(
                    "Fehler",
                    f'<p class="blocked">{_e(message)}</p>',
                    active_section="home",
                    context=self._fetch_page_context(),
                ),
                status,
            )

        def _remote_error_page(self, exc: RemoteCoreError) -> None:
            """Pack §6.5 degradation: an unreachable/malformed Core Office API
            response must show this exact German message, never an empty or
            partial page — no read has returned by this point (the exception
            fired before any render function could build a body), and no
            write has happened either (§6.1: a command either returns 2xx or
            never took effect). Genuine remote business rejections (409/422 —
            not "unavailable") fall back to the same generic error rendering
            direct-mode ValueErrors already use."""
            if exc.unavailable:
                self._html(
                    _page(
                        "Fehler",
                        f'<p class="blocked">{_e(_UNAVAILABLE_MESSAGE)}</p>',
                        active_section="home",
                        context=self._fetch_page_context(),
                    ),
                    503,
                )
            else:
                self._error_page(
                    inquiry_command_error_message(exc.code),
                    status=exc.status,
                )

        def _form(self) -> dict[str, str]:
            cached = getattr(self, "_form_cache", None)
            if cached is not None:
                return cached
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("invalid Content-Length") from exc
            if length < 0:
                raise ValueError("invalid Content-Length")
            if length > _MAX_FORM_BODY_BYTES:
                raise FormBodyTooLargeError("form body too large")
            raw = self.rfile.read(length).decode("utf-8")
            parsed = {
                key: values[0]
                for key, values in parse_qs(raw, keep_blank_values=True).items()
            }
            self._form_cache = parsed
            return parsed

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

        def do_GET(self) -> None:  # noqa: N802
            if not self._authorized():
                self._deny()
                return
            panel.begin_request()
            try:
                self._route_get()
            except RemoteCoreError as exc:
                self._remote_error_page(exc)

        def _route_get(self) -> None:
            parsed = urlparse(self.path)
            parts = [part for part in parsed.path.split("/") if part]
            if parts == ["rueckruf"]:
                if remote is not None and not auerswald_url:
                    self._html(
                        render_rueckruf(
                            None,
                            "Rückruf-Liste: nur vor Ort verfügbar",
                            context=OfficePageContext(csrf_token=csrf_token),
                        )
                    )
                    return
                items, error = self._fetch_enriched_missed_board()
                context = OfficePageContext(
                    rueckruf_count=len(items) if items is not None else None,
                    csrf_token=csrf_token,
                )
                self._html(render_rueckruf(items, error, context=context))
                return
            if not parts:
                items, error = self._fetch_enriched_missed_board()
                context = OfficePageContext(
                    rueckruf_count=len(items) if items is not None else None,
                    csrf_token=csrf_token,
                )
                kalender_view = parse_qs(parsed.query).get("kalender", ["woche"])[0]
                self._html(
                    panel.render_queue(
                        items,
                        rueckruf_error=error,
                        context=context,
                        kalender_view=kalender_view,
                    )
                )
                return
            context = self._fetch_page_context()
            if parts == ["anfragen"]:
                search_query = parse_qs(parsed.query).get("q", [""])[0]
                self._html(panel.render_anfragen(search_query, context=context))
            elif parts == ["angebote"]:
                self._html(panel.render_angebote(context=context))
            elif parts == ["kontakte"]:
                query = parse_qs(parsed.query)
                search_query = query.get("q", [""])[0]
                status_filter = query.get("status", ["all"])[0]
                self._html(
                    panel.render_kontakte(search_query, status_filter, context=context)
                )
            elif parts == ["gerichte"]:
                self._html(panel.render_gerichte(context=context))
            elif parts == ["emails"] or parts == ["email"]:
                self._html(panel.render_email(context=context))
            elif parts == ["aufgaben"]:
                self._html(panel.render_aufgaben(context=context))
            elif parts == ["kalender"]:
                self._html(panel.render_kalender(context=context))
            elif parts == ["auftraege"]:
                search_query = parse_qs(parsed.query).get("q", [""])[0]
                self._html(panel.render_auftraege(search_query, context=context))
            elif parts == ["orders"]:
                query = parse_qs(parsed.query)
                self._html(
                    panel.render_orders(
                        query.get("q", [""])[0],
                        query.get("zeitraum", [""])[0],
                        context=context,
                    )
                )
            elif parts == ["proposal-preview"]:
                self._html(render_proposal_preview_form(context=context))
            elif parts == ["inquiry", "new"]:
                form_defaults = parse_qs(parsed.query)
                self._html(
                    panel.render_inquiry_form(
                        phone=form_defaults.get("phone", [""])[0],
                        event_date=form_defaults.get("event_date", [""])[0],
                        guest_count_estimate=form_defaults.get(
                            "guest_count_estimate", [""]
                        )[0],
                        context=context,
                    )
                )
            elif len(parts) == 2 and parts[0] == "inquiry":
                page = panel.render_inquiry(parts[1], context=context)
                self._html(page) if page else self.send_error(404)
            elif len(parts) == 2 and parts[0] == "order":
                page = panel.render_order(parts[1], context=context)
                self._html(page) if page else self.send_error(404)
            elif len(parts) == 2 and parts[0] == "offer":
                page = panel.render_offer(parts[1], context=context)
                self._html(page) if page else self.send_error(404)
            elif len(parts) == 2 and parts[0] == "kontakt":
                page = panel.render_kontakt(unquote(parts[1]), context=context)
                self._html(page) if page else self.send_error(404)
            elif len(parts) == 2 and parts[0] == "gerichte":
                page = panel.render_gericht(parts[1], context=context)
                self._html(page) if page else self.send_error(404)
            elif len(parts) == 3 and parts[0] == "gerichte" and parts[2] == "edit":
                page = panel.render_gericht_edit(parts[1], context=context)
                self._html(page) if page else self.send_error(404)
            elif len(parts) == 2 and parts[0] in ("emails", "email"):
                page = panel.render_email_detail(parts[1], context=context)
                self._html(page) if page else self.send_error(404)
            elif len(parts) == 3 and parts[0] == "order" and parts[2] == "print":
                self._print_sheet(parts[1], parsed.query)
            elif len(parts) == 3 and parts[0] == "order" and parts[2] == "buffet-cards":
                self._buffet_cards(parts[1], parsed.query)
            elif (
                len(parts) == 4
                and parts[0] == "order"
                and parts[2] == "confirmation-document"
                and parts[3] == "preview"
            ):
                self._confirmation_document_preview(parts[1])
            elif (
                len(parts) == 4
                and parts[0] == "order"
                and parts[2] == "confirmation-document"
                and parts[3] == "fake-outbox"
            ):
                self._confirmation_fake_outbox(parts[1])
            else:
                self.send_error(404)

        def _resolve_print_projection(self, order_id: str, version_id: str):
            if remote is not None:
                return remote.print_data(order_id, version_id)
            return OrderPrintProjectionService(
                order_repo,
                panel._offers,
            ).resolve(order_id, version_id, intent="preview")

        def _resolve_buffet_cards_view(self, order_id: str, version_id: str):
            if remote is not None:
                return remote.buffet_cards_data(order_id, version_id)
            return BuffetCardsService(
                order_repo,
                OrderPrintProjectionService(order_repo, panel._offers),
            ).resolve(order_id, version_id)

        def _print_sheet(self, order_id: str, query: str) -> None:
            version_id = parse_qs(query).get("version", [""])[0]
            if not version_id:
                self.send_error(404)
                return
            try:
                projection = self._resolve_print_projection(order_id, version_id)
            except PrintProjectionNotFoundError:
                self.send_error(404)
                return
            if projection is None:
                self.send_error(404)
                return
            self._html(render_print_sheet(projection))

        def _buffet_cards(self, order_id: str, query: str) -> None:
            version_id = parse_qs(query).get("version", [""])[0]
            if not version_id:
                self.send_error(404)
                return
            try:
                view = self._resolve_buffet_cards_view(order_id, version_id)
            except PrintProjectionNotFoundError:
                self.send_error(404)
                return
            if view is None:
                self.send_error(404)
                return
            self._html(
                render_buffet_cards(
                    view.projection,
                    view.cards,
                    effective_version_number=view.effective_version_number,
                )
            )

        def _confirmation_document_preview(self, order_id: str) -> None:
            try:
                if remote is not None:
                    html = remote.confirmation_document_service.preview_html(order_id)
                else:
                    snapshot = panel.confirmation_document_service.get_latest_snapshot(
                        order_id
                    )
                    if snapshot is None:
                        raise OrderConfirmationDocumentNotFoundError(order_id)
                    html = render_preview_html(build_preview(snapshot))
            except OrderConfirmationDocumentNotFoundError:
                self.send_error(404)
                return
            self._html(html)

        def _confirmation_fake_outbox(self, order_id: str) -> None:
            try:
                message = panel.confirmation_outbound_service.fake_outbox_message(
                    order_id
                )
            except Exception:
                self.send_error(404)
                return
            body = (
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<title>Testnachricht Fake Outbox</title></head><body>"
                "<p><strong>Testtransport — keine echte Zustellung.</strong></p>"
                f"<p>Betreff: {_e(message.subject)}</p>"
                "<h2>Text</h2>"
                f"<pre>{_e(message.text_body)}</pre>"
                "<h2>HTML</h2>"
                f"{message.html_body}"
                "</body></html>"
            )
            self._html(body)

        def do_POST(self) -> None:  # noqa: N802
            if not self._authorized():
                self._deny()
                return
            try:
                form = self._form()
            except FormBodyTooLargeError as exc:
                self._error_page(str(exc), status=413)
                return
            except (UnicodeDecodeError, ValueError) as exc:
                self._error_page(str(exc), status=400)
                return
            submitted_token = form.get("_csrf_token", "")
            if not hmac.compare_digest(submitted_token, csrf_token):
                self._error_page(
                    "Ungültiger oder fehlender CSRF-Sicherheitstoken.", status=403
                )
                return
            panel.begin_request(form)
            parts = [part for part in urlparse(self.path).path.split("/") if part]
            try:
                self._route_post(parts)
            except RemoteCoreError as exc:
                self._remote_error_page(exc)
            except (ValueError, KeyError) as exc:
                self._error_page(inquiry_command_error_message(str(exc)))

        def _route_post(self, parts: list[str]) -> None:
            if parts == ["inquiry", "new"]:
                inquiry = panel.create_inquiry(self._form())
                self._redirect(f"/inquiry/{inquiry.inquiry_id}")
            elif len(parts) == 3 and parts[0] == "inquiry":
                self._inquiry_action(parts[1], parts[2])
            elif len(parts) == 3 and parts[0] == "offer":
                self._offer_action(parts[1], parts[2])
            elif len(parts) == 3 and parts[0] == "order":
                self._order_action(parts[1], parts[2])
            elif (
                len(parts) == 4
                and parts[0] == "order"
                and parts[2] == "confirmation-document"
                and parts[3] == "send"
            ):
                panel.send_confirmation_test(parts[1], self._form())
                self._redirect(f"/order/{parts[1]}")
            elif parts == ["proposal-preview"]:
                payload = parse_proposal_payload(self._form().get("payload_json", ""))
                self._html(
                    render_proposal_preview(payload, context=self._fetch_page_context())
                )
            elif parts == ["proposal-preview", "prepare"]:
                payload = parse_proposal_payload(self._form().get("payload_json", ""))
                summary_lines = "\n".join(
                    f"{item['name']} × {item['quantity']}"
                    if item.get("quantity") is not None
                    else item["name"]
                    for item in payload["selected_items"]
                )
                self._html(
                    panel.render_inquiry_form(
                        event_date=payload["event_date"],
                        guest_count_estimate=str(payload["guest_count"]),
                        inquiry_source="configurator",
                        intake_subject=payload["title"],
                        intake_message=payload.get("notes") or "",
                        intake_summary=summary_lines,
                        intake_external_ref=payload.get("proposal_id") or "",
                        context=self._fetch_page_context(),
                    )
                )
            elif parts == ["rueckruf", "resolve"]:
                call_id = self._form()["call_id"]
                resolve_missed_call(
                    auerswald_url,
                    auerswald_user,
                    auerswald_password,
                    call_id,
                )
                self._redirect("/rueckruf")
            elif len(parts) == 3 and parts[0] == "gerichte" and parts[2] == "update":
                panel.update_catalog_dish(parts[1], self._form())
                self._redirect(f"/gerichte/{parts[1]}")
            elif len(parts) == 3 and parts[0] == "kontakt" and parts[2] == "notizen":
                contact_key = unquote(parts[1])
                panel.add_contact_note(contact_key, self._form())
                self._redirect(f"/kontakt/{quote(contact_key, safe='')}")
            else:
                self.send_error(404)

        def _inquiry_action(self, inquiry_id: str, action: str) -> None:
            if action == "update":
                panel.update_inquiry(inquiry_id, self._form())
                self._redirect(f"/inquiry/{inquiry_id}")
            elif action == "contact-completion":
                panel.complete_inquiry_contacts(inquiry_id, self._form())
                self._redirect(f"/inquiry/{inquiry_id}")
            elif action == "verify":
                panel.inquiry_service.verify_customer_by_call(inquiry_id)
                self._redirect(f"/inquiry/{inquiry_id}")
            elif action == "convert":
                order, _initial_version = panel.convert_inquiry_to_order(inquiry_id)
                self._redirect(f"/order/{order.order_id}")
            elif action == "convert-accepted":
                order, _initial_version = panel.convert_accepted_offer_for_inquiry(
                    inquiry_id
                )
                self._redirect(f"/order/{order.order_id}")
            else:
                self.send_error(404)

        def _offer_action(self, offer_id: str, action: str) -> None:
            form = self._form()
            if action == "mark-sent":
                panel.mark_offer_sent(offer_id, form)
                self._redirect(f"/offer/{offer_id}")
            elif action == "record-acceptance":
                panel.record_offer_acceptance(offer_id, form)
                self._redirect(f"/offer/{offer_id}")
            elif action == "convert":
                order, _version = panel.convert_accepted_offer(offer_id, form)
                self._redirect(f"/order/{order.order_id}")
            else:
                self.send_error(404)

        def _order_action(self, order_id: str, action: str) -> None:
            if action == "version":
                panel.create_version(order_id, self._form())
            elif action == "print-confirm":
                panel.core.confirm_kitchen_print(
                    order_id, self._form()["order_version_id"]
                )
            elif action == "effective":
                panel.core.make_order_version_effective(
                    order_id, self._form()["order_version_id"]
                )
            elif action == "ready":
                panel.core.request_ready_to_send(order_id)
            elif action == "cancel":
                panel.core.cancel_order(order_id)
            elif action == "payment-reminder":
                panel.save_payment_reminder(order_id, self._form())
            elif action == "confirmation-document":
                panel.prepare_confirmation_document(order_id, self._form())
            elif action == "pause":
                panel.pause_order(order_id, self._form())
            elif action == "resume":
                panel.resume_order(order_id, self._form())
            else:
                self.send_error(404)
                return
            self._redirect(f"/order/{order_id}")

    return OfficePanelHandler


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
    confirmation_document_repo: OrderConfirmationDocumentRepository | None = None,
    confirmation_outbound_repo: OrderConfirmationOutboundRepository | None = None,
    pause_repository: OrderOperationalPauseRepository | None = None,
    contact_note_repo: ContactInternalNoteRepository | None = None,
    contact_profile_repo: ContactProfileRepository | None = None,
    offer_repo: OfferRepository | None = None,
    catalog_repo: CatalogRepository | None = None,
    ui_version: str = "legacy",
) -> HTTPServer:
    """Create the intentionally single-threaded office HTTP server."""
    return HTTPServer(
        (host, port),
        make_office_panel_handler(
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
            confirmation_document_repo=confirmation_document_repo,
            confirmation_outbound_repo=confirmation_outbound_repo,
            pause_repository=pause_repository,
            contact_note_repo=contact_note_repo,
            contact_profile_repo=contact_profile_repo,
            offer_repo=offer_repo,
            catalog_repo=catalog_repo,
            ui_version=ui_version,
        ),
    )
