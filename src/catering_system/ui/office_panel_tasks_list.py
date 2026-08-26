"""Aufgaben list presentation — manual and read-only system office tasks."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _e,
    _page,
)

_BERLIN = ZoneInfo("Europe/Berlin")


def _format_due(raw: object | None) -> str:
    if raw is None:
        return "–"
    if isinstance(raw, str):
        try:
            value = date.fromisoformat(raw)
        except ValueError:
            return raw
    elif isinstance(raw, datetime):
        value = raw.astimezone(_BERLIN).date()
    elif isinstance(raw, date):
        value = raw
    else:
        return "–"
    return f"{value.day:02d}.{value.month:02d}.{value.year}"


def _urgency_label(raw: object) -> str:
    if raw == "overdue":
        return "Überfällig"
    return "Normal"


def render_aufgaben_list(
    rows: list[dict[str, object]],
    *,
    context: OfficePageContext,
    assignee_options: list[dict[str, str]] | None = None,
    can_create_manual_task: bool = False,
    can_assign_manual_task: bool = False,
    create_form_fields: str = "",
) -> str:
    create_form = ""
    if can_create_manual_task:
        assignee_field = ""
        if can_assign_manual_task:
            options = ['<option value="">Nicht zugewiesen</option>']
            for option in assignee_options or []:
                options.append(
                    f'<option value="{_e(option["id"])}">'
                    f"{_e(option['display_name'])}</option>"
                )
            assignee_field = (
                '<p><label for="assigned_to_employee_id">Zuweisen an</label><br>'
                '<select id="assigned_to_employee_id" name="assigned_to_employee_id">'
                + "".join(options)
                + "</select></p>"
            )
        create_form = (
            "<section><h2>Neue Aufgabe</h2>"
            '<form method="post" action="/aufgaben/new">'
            f"{create_form_fields}"
            '<p><label for="manual_task_title">Titel</label><br>'
            '<input id="manual_task_title" name="title" required maxlength="200"></p>'
            '<p><label for="manual_task_description">Beschreibung</label><br>'
            '<textarea id="manual_task_description" name="description" '
            'maxlength="4000"></textarea></p>'
            '<p><label for="manual_task_due_date">Fällig</label><br>'
            '<input id="manual_task_due_date" name="due_date" type="date"></p>'
            f"{assignee_field}"
            '<p><button type="submit">Aufgabe anlegen</button></p>'
            "</form></section>"
        )
    table_rows = []
    for row in rows:
        action = ""
        if row["kind"] == "manual":
            if row.get("can_complete"):
                action = (
                    f'<form method="post" action="/aufgaben/{_e(row["task_id"])}/complete">'
                    f"{row.get('complete_form_fields', '')}"
                    '<button type="submit">Erledigt</button></form>'
                )
            else:
                action = "–"
        else:
            href = str(row["action_href"])
            action = f'<a href="{_e(href)}">{_e(str(row["action_label"]))}</a>'
        table_rows.append(
            "<tr>"
            f"<td>{_e(str(row['type_label']))}</td>"
            f"<td>{_e(_urgency_label(row['urgency']))}</td>"
            f"<td>{_e(str(row['title']))}</td>"
            f"<td>{_e(str(row['subtitle']))}</td>"
            f"<td>{_e(_format_due(row.get('due_at')))}</td>"
            f"<td>{_e(str(row.get('assigned_to', '–')))}</td>"
            f"<td>{action}</td>"
            "</tr>"
        )
    body = (
        '<p class="subtitle">Manuelle Aufgaben und abgeleitete Büro-Aufgaben '
        "aus Anfragen, Aufträgen und Zahlungserinnerungen.</p>"
        + create_form
        + "<h2>Offene Aufgaben</h2>"
        + "<table><tr><th>Typ</th><th>Dringlichkeit</th><th>Aufgabe</th>"
        "<th>Beschreibung/Bezug</th><th>Fällig</th><th>Zugewiesen</th><th>Aktion</th></tr>"
        + "".join(
            table_rows or ['<tr><td colspan="7">Keine offenen Aufgaben.</td></tr>']
        )
        + "</table>"
        + '<p><a href="/">← Zurück zur Arbeitszentrale</a></p>'
    )
    return _page("Aufgaben", body, active_section="tasks", context=context)
