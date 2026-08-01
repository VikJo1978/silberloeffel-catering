"""Shared HTML shell and presentation helpers for the office panel."""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date, datetime

from catering_system.domain.inquiry import CRM_PIPELINE, PLANNING_MODES
from catering_system.services.buffet_cards_service import BuffetCard, buffet_card_body
from catering_system.services.order_print_projection_service import OrderPrintProjection
from catering_system.ui.office_panel_shell import (
    OFFICE_PANEL_ICON_SPRITE,
    OFFICE_PANEL_STYLE,
    OfficeSection,
)

_LOGO_DATA_URI = "data:image/jpeg;base64,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"


def _e(text: object) -> str:
    return html.escape(str(text))


def parse_datetime_local_berlin(value: str) -> datetime:
    """Parse HTML ``datetime-local`` as Europe/Berlin wall time."""
    from catering_system.ui.office_api_views import BERLIN

    raw = value.strip()
    if not raw:
        raise ValueError("datetime is required")
    if len(raw) < 16 or raw[10] != "T":
        raise ValueError("invalid datetime-local value")
    parsed = datetime.strptime(raw[:16], "%Y-%m-%dT%H:%M")
    return parsed.replace(tzinfo=BERLIN)


def default_datetime_local_berlin() -> str:
    from catering_system.ui.office_api_views import BERLIN

    return datetime.now(BERLIN).strftime("%Y-%m-%dT%H:%M")


def format_datetime_utc_iso(value: datetime) -> str:
    """Office API timestamps must be UTC (pack §4.1)."""
    from datetime import UTC

    return value.astimezone(UTC).isoformat()


# UI-only display labels (OFFICE_PANEL_SAFE_UX_LABELS_AND_GROUPING_V1,
# 2026-07-07). Pure display mapping — the underlying Core/domain values are
# untouched, and the three vocabularies stay separate on purpose (§5,
# "vocabularies not merged"): call-verification status is its own simple
# status, READY_TO_SEND blocker reasons are the operational-gate vocabulary
# (order views only), and progression blocker reasons are the B7 vocabulary
# (inquiry-to-order conversion views only). Never merge these dicts.
CALL_VERIFICATION_STATUS_LABELS: dict[str, str] = {
    "not_required": "keine Rückrufprüfung nötig",
    "pending": "Rückrufprüfung ausstehend",
    "verified": "verifiziert",
    "failed": "Rückrufprüfung fehlgeschlagen",
    "blocked": "Rückrufprüfung blockiert",
}
READY_TO_SEND_BLOCKER_LABELS: dict[str, str] = {
    "ready_to_send_order_not_found": "Auftrag nicht gefunden",
    "order_cancelled": "Auftrag storniert",
    "no_effective_version": "keine wirksame Auftragsversion",
    "effective_version_not_resolvable": "wirksame Version nicht auffindbar",
    "kitchen_print_not_confirmed": "Druckbestätigung fehlt",
    "pending_order_version_change": "Änderung wartet auf Küchendruck",
    "operational_pause": "Betrieblich pausiert",
}
PROGRESSION_BLOCKER_LABELS: dict[str, str] = {
    "inquiry_call_verification_unsatisfied": "Rückrufprüfung noch nicht erfüllt",
    "inquiry_rejected": "Anfrage wurde abgelehnt",
    "inquiry_contact_missing_email": "E-Mail-Adresse fehlt",
    "inquiry_contact_missing_phone": "Telefonnummer fehlt",
    "inquiry_contact_missing_email_and_phone": (
        "E-Mail-Adresse und Telefonnummer fehlen"
    ),
}
# Kanal (inquiry_source) display labels — its own vocabulary, never merged
# with the three above (WEBSITE_FORM_INQUIRY_OFFICE_UX_PACK_V1 §4/§8).
# Legacy/adapter-only/future values (phone, wix_form, missed_call,
# ai_telefonist) deliberately have no label yet — fallback renders the raw
# value, same convention as the other three label dicts.
SOURCE_LABELS: dict[str, str] = {
    "website_form": "Website-Anfrage",
    "configurator": "Angebots-Import",
    "manual": "Manuell erfasst",
    "phone_by_office": "Telefon (Büro)",
    "email": "E-Mail",
}


def _verification_label(value: str) -> str:
    return CALL_VERIFICATION_STATUS_LABELS.get(value, value or "–")


def _source_label(value: str) -> str:
    return SOURCE_LABELS.get(value, value or "–")


def _ready_to_send_blocker_label(code: str) -> str:
    return READY_TO_SEND_BLOCKER_LABELS.get(code, f"technischer Blocker: {code}")


def _progression_blocker_label(code: str) -> str:
    return PROGRESSION_BLOCKER_LABELS.get(
        code, f"technischer Fortschritts-Blocker: {code}"
    )


@dataclass(frozen=True)
class OfficePageContext:
    """Request-local display data shared by the page shell and body renderer."""

    rueckruf_count: int | None = None
    csrf_token: str = ""
    current_user_name: str = ""
    current_user_role_label: str = ""
    password_change_path: str = ""
    logout_path: str = ""
    show_transition_banner: bool = False
    legacy_shared_access: bool = False


_EMPTY_PAGE_CONTEXT = OfficePageContext()


def _csrf_input(context: OfficePageContext) -> str:
    if not context.csrf_token:
        return ""
    return f'<input type="hidden" name="_csrf_token" value="{_e(context.csrf_token)}">'


def _nav_link(
    href: str,
    label: str,
    icon: str,
    section: OfficeSection,
    active_section: OfficeSection,
    *,
    badge: int | None = None,
) -> str:
    current = ' aria-current="page"' if section == active_section else ""
    badge_html = f'<span class="badge">{badge}</span>' if badge else ""
    return (
        f'<a class="office-nav-link" href="{href}"{current}>'
        f'<svg aria-hidden="true"><use href="#office-i-{icon}"></use></svg>'
        f"<span>{label}</span>{badge_html}</a>"
    )


def _page(
    title: str,
    body: str,
    *,
    active_section: OfficeSection,
    context: OfficePageContext = _EMPTY_PAGE_CONTEXT,
    show_title: bool = True,
    auto_refresh_seconds: int | None = None,
) -> str:
    nav = "".join(
        (
            _nav_link("/", "Arbeitszentrale", "grid", "home", active_section),
            '<div class="office-nav-label">Vertrieb</div>',
            _nav_link("/anfragen", "Anfragen", "doc", "inquiries", active_section),
            _nav_link("/angebote", "Angebote", "doc", "offers", active_section),
            _nav_link("/kontakte", "Kontakte", "users", "contacts", active_section),
            _nav_link("/emails", "E-Mail", "doc", "email", active_section),
            _nav_link("/aufgaben", "Aufgaben", "doc", "tasks", active_section),
            _nav_link("/kalender", "Kalender", "calendar", "calendar", active_section),
            '<div class="office-nav-label">Betrieb</div>',
            _nav_link("/auftraege", "Aufträge", "briefcase", "orders", active_section),
            _nav_link(
                "/#diese-woche",
                "Diese Woche",
                "calendar",
                "week",
                active_section,
            ),
            _nav_link(
                "/rueckruf",
                "Rückrufliste",
                "phone",
                "callbacks",
                active_section,
                badge=context.rueckruf_count,
            ),
            _nav_link(
                "/proposal-preview",
                "Angebots-Import",
                "import",
                "proposal",
                active_section,
            ),
            '<div class="office-nav-label">Verwaltung</div>',
            _nav_link("/gerichte", "Gerichte", "doc", "catalog", active_section),
        )
    )
    page_title = f"<h1>{_e(title)}</h1>" if show_title else ""
    account_meta = (
        '<div class="office-account-meta">'
        f"<strong>{_e(context.current_user_name or 'Office Panel')}</strong>"
        f"<span>{_e(context.current_user_role_label or 'Tägliche Arbeitszentrale')}</span>"
        "</div>"
    )
    account_actions = ""
    if context.password_change_path or context.logout_path:
        password_link = (
            f'<a class="office-account-link" href="{_e(context.password_change_path)}">'
            "Passwort ändern</a>"
            if context.password_change_path
            else ""
        )
        logout_form = (
            '<form class="office-account-form" method="post" '
            f'action="{_e(context.logout_path)}">{_csrf_input(context)}'
            '<button type="submit" class="office-account-link">Abmelden</button>'
            "</form>"
            if context.logout_path
            else ""
        )
        account_actions = (
            f'<div class="office-account-actions">{password_link}{logout_form}</div>'
        )
    transition_banner = (
        '<div class="office-global-banner">'
        "<strong>Übergangsmodus aktiv:</strong> "
        "Die Anmeldung mit dem gemeinsamen Office-Passwort ist noch möglich."
        "</div>"
        if context.show_transition_banner
        else ""
    )
    refresh_meta = (
        f'<meta http-equiv="refresh" content="{auto_refresh_seconds}">'
        if auto_refresh_seconds is not None
        else ""
    )
    return (
        '<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"{refresh_meta}"
        f"<title>{_e(title)}</title><style>{OFFICE_PANEL_STYLE}</style></head>"
        f"<body>{OFFICE_PANEL_ICON_SPRITE}"
        '<div class="office-app"><aside class="office-sidebar">'
        f'<a class="office-brand" href="/" aria-label="Silberlöffel Office Panel">'
        f'<img src="{_LOGO_DATA_URI}" alt="Silberlöffel Event Catering Service">'
        "</a>"
        '<div class="office-nav-label">Navigation</div>'
        f'<nav class="office-nav" aria-label="Office Panel">{nav}</nav>'
        '<div class="office-user"><strong>Office Panel</strong>'
        "<span>Tägliche Arbeitszentrale</span></div></aside>"
        '<main class="office-workspace">'
        f'<header class="office-topbar"><span class="office-crumb">{_e(title)}</span>'
        f'<div class="office-account">{account_meta}{account_actions}</div></header>'
        f'<div class="office-content">{transition_banner}{page_title}{body}</div>'
        "</main></div></body></html>"
    )


def _planning_mode_select(selected: str) -> str:
    opts = "".join(
        f'<option value="{_e(m)}"{" selected" if m == selected else ""}>{_e(m)}</option>'
        for m in PLANNING_MODES
    )
    return f'<select name="planning_mode">{opts}</select>'


def _crm_stage_select(selected: str) -> str:
    opts = "".join(
        f'<option value="{_e(s)}"{" selected" if s == selected else ""}>{_e(s)}</option>'
        for s in CRM_PIPELINE
    )
    return f'<select name="crm_stage">{opts}</select>'


def _format_print_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def _render_menu_section(projection: OrderPrintProjection) -> str:
    positions = projection.commercial.positions
    if not positions:
        return '<p class="menu-empty">Kein Menü hinterlegt</p>'
    blocks: list[str] = []
    for line in positions:
        detail = line.description or line.composition
        detail_html = f'<p class="menu-detail">{_e(detail)}</p>' if detail else ""
        quantity_html = (
            f'<p class="menu-qty">Menge: {_e(line.quantity_display)}</p>'
            if line.quantity_display
            else ""
        )
        blocks.append(
            f'<div class="menu-item"><p class="menu-name">• {_e(line.name)}</p>'
            f"{detail_html}{quantity_html}</div>"
        )
    return "".join(blocks)


def render_print_sheet(projection: OrderPrintProjection) -> str:
    """Kitchen order sheet — read-only printable rendering from OrderPrintProjection."""
    event = projection.event
    guests = (
        str(event.guest_count_estimate)
        if event.guest_count_estimate is not None
        else "–"
    )
    cancelled_banner = (
        '<p class="cancelled">STORNIERT</p>'
        if event.order_cancelled_at is not None
        else ""
    )
    watermark = projection.flags.watermark
    watermark_html = (
        f'<p class="watermark">{_e(watermark)}</p>' if watermark is not None else ""
    )
    change_html = ""
    if event.change_reason is not None or event.changed_fields:
        fields = ", ".join(event.changed_fields) or "–"
        change_html = (
            '<div class="change-summary">'
            f'<p class="label">Änderungsgrund:</p><p class="value">'
            f"{_e(event.change_reason or '–')}</p>"
            f'<p class="label">Geänderte Felder:</p><p class="value">'
            f"{_e(fields)}</p></div>"
        )
    menu_html = _render_menu_section(projection)
    return f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"><title>Küchenzettel</title>
<style>
body{{font-family:monospace;font-size:1.25rem;margin:2rem;max-width:40rem;line-height:1.5}}
hr{{border:none;border-top:2px solid #000;margin:1.25rem 0}}
.brand{{font-size:1.5rem;font-weight:bold;letter-spacing:0.08em}}
.label{{margin:0.75rem 0 0.15rem;font-weight:bold}}
.value{{margin:0 0 0.5rem}}
.menu-title{{font-weight:bold;margin:0.5rem 0}}
.menu-item{{margin:0.75rem 0 1rem}}
.menu-name{{margin:0}}
.menu-detail,.menu-qty{{margin:0.15rem 0 0 1.25rem}}
.menu-empty{{margin:0.5rem 0;font-style:italic}}
.stand{{margin-top:1rem}}
.cancelled{{color:#a00;font-size:2rem;border:4px solid #a00;padding:0.5rem;text-align:center}}
.watermark{{color:#666;font-size:2rem;border:3px dashed #666;padding:0.5rem;text-align:center;margin-bottom:1rem}}
button{{font-size:1rem;margin-top:1.5rem;padding:0.5rem 1rem}}
</style></head><body>
{cancelled_banner}
{watermark_html}
{change_html}
<p class="brand">SILBERLÖFFEL</p>
<hr>
<p class="label">Datum:</p>
<p class="value">{_e(_format_print_date(event.event_date))}</p>
<p class="label">Ort:</p>
<p class="value">{_e(event.location_text)}</p>
<p class="label">Gäste:</p>
<p class="value">{_e(guests)}</p>
<hr>
<p class="menu-title">MENÜ</p>
{menu_html}
<hr>
<p class="stand">Stand:<br>Version {event.version_number}</p>
<p><button onclick="window.print()">Drucken</button></p>
</body></html>"""


def _buffet_card_html(card: BuffetCard, version_number: int) -> str:
    body = buffet_card_body(card)
    body_html = (
        "".join(f"<p>{_e(line)}</p>" for line in body.splitlines() if line.strip())
        if body
        else ""
    )
    return (
        '<section class="buffet-card">'
        '<p class="brand">SILBERLÖFFEL</p>'
        '<hr class="rule">'
        f'<h2 class="dish">{_e(card.name)}</h2>'
        f"{body_html}"
        '<hr class="rule">'
        f'<p class="stand">Version {version_number}</p>'
        "</section>"
    )


def _buffet_banner_html(
    projection: OrderPrintProjection,
    *,
    effective_version_number: int | None,
) -> str:
    watermark = projection.flags.watermark
    if watermark == "ÄNDERUNG – NOCH NICHT WIRKSAM":
        return (
            '<div class="buffet-banner">'
            '<p class="watermark">ÄNDERUNG – NOCH NICHT WIRKSAM</p>'
            f'<p class="stand-label">Stand Version {projection.event.version_number}</p>'
            "</div>"
        )
    if watermark == "ENTWURF":
        return (
            '<div class="buffet-banner">'
            '<p class="watermark">ENTWURF</p>'
            f'<p class="stand-label">Stand Version {projection.event.version_number}</p>'
            "</div>"
        )
    if watermark == "VERALTET" and effective_version_number is not None:
        return (
            '<div class="buffet-banner">'
            '<p class="watermark stale">VERALTET</p>'
            '<p class="stand-label">Aktueller Küchenstand:<br>'
            f"Version {effective_version_number}</p>"
            "</div>"
        )
    return ""


def render_buffet_cards(
    projection: OrderPrintProjection,
    cards: tuple[BuffetCard, ...] | list[BuffetCard],
    *,
    effective_version_number: int | None = None,
) -> str:
    """Guest buffet cards — one HTML page, one card per menu position."""
    version_number = projection.event.version_number
    banner_html = _buffet_banner_html(
        projection,
        effective_version_number=effective_version_number,
    )
    if not cards:
        cards_html = '<p class="menu-empty">Kein Menü hinterlegt</p>'
    else:
        cards_html = "".join(_buffet_card_html(card, version_number) for card in cards)
    return f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"><title>Buffetschilder</title>
<style>
body{{font-family:serif;font-size:1.4rem;margin:2rem;color:#000;background:#fff}}
.buffet-card{{border:2px solid #000;padding:2rem;margin:0 0 2rem;max-width:32rem}}
.brand{{font-size:1.1rem;font-weight:bold;letter-spacing:0.12em;margin:0 0 1rem;text-align:center}}
.rule{{border:none;border-top:2px solid #000;margin:1rem 0}}
.dish{{font-size:1.8rem;font-weight:normal;margin:0.5rem 0 1rem;text-align:center}}
.dish + p{{margin:0.25rem 0;text-align:center;line-height:1.4}}
.stand{{margin:0;text-align:center;font-size:1rem}}
.menu-empty{{font-style:italic;margin:2rem 0}}
.buffet-banner{{margin-bottom:2rem;text-align:center}}
.watermark{{font-size:1.6rem;font-weight:bold;border:3px dashed #666;padding:0.5rem;margin:0 0 0.5rem}}
.watermark.stale{{border-style:solid}}
.stand-label{{margin:0;font-size:1.1rem}}
button{{font-family:sans-serif;font-size:1rem;margin-top:1rem;padding:0.5rem 1rem}}
@media print{{button{{display:none}} .buffet-card{{page-break-inside:avoid}}}}
</style></head><body>
{banner_html}
{cards_html}
<p><button onclick="window.print()">Drucken</button></p>
</body></html>"""
