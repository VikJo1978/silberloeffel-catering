"""Kontakte list presentation — search + derived Interessent/Kunde status."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from catering_system.domain.contact_projection import (
    ContactStatusFilter,
    contact_status_label,
)
from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _e,
    _page,
)

_BERLIN = ZoneInfo("Europe/Berlin")


def _contact_line(email: object | None, phone: object | None) -> str:
    parts = [str(value) for value in (email, phone) if value]
    return " · ".join(parts) if parts else "–"


def _short_activity(raw: str) -> str:
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return raw
    local = value.astimezone(_BERLIN)
    return f"{local.day:02d}.{local.month:02d}.{local.year}"


def _kontakte_href(*, q: str, status: ContactStatusFilter) -> str:
    params: dict[str, str] = {}
    if q:
        params["q"] = q
    if status != "all":
        params["status"] = status
    if not params:
        return "/kontakte"
    return f"/kontakte?{urlencode(params)}"


def _status_filters(
    *,
    q: str,
    status: ContactStatusFilter,
    counts: dict[str, int],
) -> str:
    items: list[tuple[ContactStatusFilter, str]] = [
        ("all", f"Alle ({counts['all']})"),
        ("interessent", f"Interessenten ({counts['interessent']})"),
        ("kunde", f"Kunden ({counts['kunde']})"),
    ]
    links = []
    for value, label in items:
        href = _kontakte_href(q=q, status=value)
        if value == status:
            links.append(f"<strong>{_e(label)}</strong>")
        else:
            links.append(f'<a href="{_e(href)}">{_e(label)}</a>')
    return (
        '<nav class="contact-status-filters" aria-label="Status">'
        + " · ".join(links)
        + "</nav>"
    )


def _empty_message(*, q: str, status: ContactStatusFilter) -> str:
    if status == "interessent":
        base = "Keine Interessenten"
    elif status == "kunde":
        base = "Keine Kunden"
    else:
        base = "Keine Kontakte"
    if q:
        return f"{base} für „{_e(q)}“ gefunden."
    if status == "all":
        return "Keine Kontakte vorhanden."
    return f"{base} vorhanden."


def render_kontakte_list(
    rows: list[dict[str, object]],
    *,
    q: str = "",
    status: ContactStatusFilter = "all",
    counts: dict[str, int] | None = None,
    context: OfficePageContext,
) -> str:
    status_counts = counts or {
        "all": len(rows),
        "interessent": sum(
            1 for row in rows if row.get("contact_status") == "interessent"
        ),
        "kunde": sum(1 for row in rows if row.get("contact_status") == "kunde"),
    }
    status_hidden = (
        f'<input type="hidden" name="status" value="{_e(status)}">'
        if status != "all"
        else ""
    )
    search_box = (
        '<form method="get" action="/kontakte" class="searchbox">'
        '<label for="kontakte-q">Kontakte durchsuchen</label> '
        f'<input id="kontakte-q" type="text" name="q" value="{_e(q)}" '
        'placeholder="Name, E-Mail oder Telefon…">'
        f"{status_hidden}"
        '<button type="submit">Suchen</button>'
        + (
            f' <a href="{_e(_kontakte_href(q="", status=status))}">Zurücksetzen</a>'
            if q
            else ""
        )
        + "</form>"
    )
    table_rows = []
    for row in rows:
        contact_key = str(row["contact_key"])
        row_status = str(row.get("contact_status") or "interessent")
        label = contact_status_label(row_status)  # type: ignore[arg-type]
        table_rows.append(
            "<tr>"
            f"<td>{_e(str(row['display_name']))}</td>"
            f"<td>{_e(label)}</td>"
            f"<td>{_e(_contact_line(row.get('email'), row.get('phone')))}</td>"
            f"<td>{_e(str(row['inquiry_count']))}</td>"
            f"<td>{_e(str(row['active_orders']))}</td>"
            f"<td>{_e(_short_activity(str(row['last_activity'])))}</td>"
            f'<td><a href="/kontakt/{_e(quote(contact_key, safe=""))}">Öffnen</a></td>'
            "</tr>"
        )
    if not table_rows:
        table_body = (
            f'<tr><td colspan="7">{_empty_message(q=q, status=status)}</td></tr>'
        )
    else:
        table_body = "".join(table_rows)
    body = (
        '<p class="subtitle">Übersicht aus Anfragen — Status aus Aufträgen abgeleitet,'
        " nicht manuell editierbar.</p>"
        + search_box
        + _status_filters(q=q, status=status, counts=status_counts)
        + "<table><tr><th>Name</th><th>Status</th><th>Kontakt</th><th>Anfragen</th>"
        "<th>Aufträge</th><th>Letzte Aktivität</th><th></th></tr>"
        + table_body
        + "</table>"
        + '<p><a href="/">← Zurück zur Arbeitszentrale</a></p>'
    )
    return _page("Kontakte", body, active_section="contacts", context=context)


def format_contact_status_for_display(status: object) -> str:
    value = str(status or "interessent")
    if value in ("interessent", "kunde"):
        return contact_status_label(value)  # type: ignore[arg-type]
    return contact_status_label("interessent")
