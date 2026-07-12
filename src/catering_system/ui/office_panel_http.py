"""HTTP transport and routing for the office panel.

The UI composition and Core orchestration live in ``office_panel``. This module
owns only Basic Auth, request parsing, route dispatch and the HTTPServer wiring.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.order_repository import OrderRepository
from catering_system.ui.office_panel import (
    OfficePageContext,
    OfficePanel,
    _e,
    _page,
    fetch_missed_board,
    fetch_rueckruf_count,
    parse_proposal_payload,
    render_print_sheet,
    render_proposal_preview,
    render_proposal_preview_form,
    render_rueckruf,
    resolve_missed_call,
)

_CSRF_CONTEXT = b"catering-office-panel-csrf-v1"
_MAX_FORM_BODY_BYTES = 256 * 1024


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
) -> type[BaseHTTPRequestHandler]:
    panel = OfficePanel(inquiry_repo, order_repo, kiosk_url)
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
                "default-src 'none'; style-src 'unsafe-inline' "
                "https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
                "img-src data:; form-action 'self'; base-uri 'none'; "
                "frame-ancestors 'none'",
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

        def _error_page(self, message: str, status: int = 400) -> None:
            self._html(
                _page(
                    "Fehler",
                    f'<p class="blocked">{_e(message)}</p>',
                    context=self._fetch_page_context(),
                ),
                status,
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
            parsed = urlparse(self.path)
            parts = [part for part in parsed.path.split("/") if part]
            if parts == ["rueckruf"]:
                items, error = fetch_missed_board(
                    auerswald_url, auerswald_user, auerswald_password
                )
                context = OfficePageContext(
                    rueckruf_count=len(items) if items else None,
                    csrf_token=csrf_token,
                )
                self._html(render_rueckruf(items, error, context=context))
                return
            if not parts:
                items, _error = fetch_missed_board(
                    auerswald_url, auerswald_user, auerswald_password
                )
                context = OfficePageContext(
                    rueckruf_count=len(items) if items else None,
                    csrf_token=csrf_token,
                )
                self._html(panel.render_queue(items, context=context))
                return
            context = self._fetch_page_context()
            if parts == ["anfragen"]:
                search_query = parse_qs(parsed.query).get("q", [""])[0]
                self._html(panel.render_anfragen(search_query, context=context))
            elif parts == ["auftraege"]:
                search_query = parse_qs(parsed.query).get("q", [""])[0]
                self._html(panel.render_auftraege(search_query, context=context))
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
            elif len(parts) == 3 and parts[0] == "order" and parts[2] == "print":
                self._print_sheet(parts[1], parsed.query)
            else:
                self.send_error(404)

        def _print_sheet(self, order_id: str, query: str) -> None:
            version_id = parse_qs(query).get("version", [""])[0]
            order = order_repo.get_order(order_id)
            version = order_repo.get_order_version(version_id) if version_id else None
            if order is None or version is None or version.order_id != order_id:
                self.send_error(404)
                return
            self._html(render_print_sheet(order, version))

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
            parts = [part for part in urlparse(self.path).path.split("/") if part]
            try:
                self._route_post(parts)
            except (ValueError, KeyError) as exc:
                self._error_page(str(exc))

        def _route_post(self, parts: list[str]) -> None:
            if parts == ["inquiry", "new"]:
                inquiry = panel.create_inquiry(self._form())
                self._redirect(f"/inquiry/{inquiry.inquiry_id}")
            elif len(parts) == 3 and parts[0] == "inquiry":
                self._inquiry_action(parts[1], parts[2])
            elif len(parts) == 3 and parts[0] == "order":
                self._order_action(parts[1], parts[2])
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
            else:
                self.send_error(404)

        def _inquiry_action(self, inquiry_id: str, action: str) -> None:
            if action == "update":
                panel.update_inquiry(inquiry_id, self._form())
                self._redirect(f"/inquiry/{inquiry_id}")
            elif action == "verify":
                panel.inquiry_service.verify_customer_by_call(inquiry_id)
                self._redirect(f"/inquiry/{inquiry_id}")
            elif action == "convert":
                inquiry = inquiry_repo.get_by_id(inquiry_id)
                if inquiry is None:
                    self.send_error(404)
                    return
                order, _initial_version = panel.order_service.convert_inquiry_to_order(
                    inquiry
                )
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
        ),
    )
