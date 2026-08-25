"""Aufgaben presentation for manual and system-derived office tasks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from catering_system.ui.office_panel_views import OfficePageContext, _e, _page

_BERLIN = ZoneInfo("Europe/Berlin")


@dataclass(frozen=True)
class ManualTaskViewRow:
    task_id: str
    title: str
    description: str
    due_at: datetime | None
    assigned_to_label: str
    subject_type: str
    subject_id: str | None


def _format_due(raw: object | None) -> str:
    if raw is None:
        return "–"
    if isinstance(raw, datetime):
        value = raw.astimezone(_BERLIN)
        return f"{value.day:02d}.{value.month:02d}.{value.year} {value.hour:02d}:{value.minute:02d}"
    if isinstance(raw, str):
        try:
            value = date.fromisoformat(raw)
        except ValueError:
            return raw
    elif isinstance(raw, date):
        value = raw
    else:
        return "–"
    return f"{value.day:02d}.{value.month:02d}.{value.year}"


def _urgency_label(raw: object) -> str:
    if raw == "overdue":
        return "Überfällig"
    return "Normal"


def _subject_label(row: ManualTaskViewRow) -> str:
    labels = {
        "ORDER": "Auftrag",
        "INQUIRY": "Anfrage",
        "CONTACT": "Kontakt",
    }
    if row.subject_type == "NONE" or row.subject_id is None:
        return "–"
    return f"{labels.get(row.subject_type, row.subject_type)} · {row.subject_id}"


def _manual_task_form(
    *,
    context: OfficePageContext,
    assignee_options: list[tuple[str, str]],
    can_assign: bool,
) -> str:
    assignee = ""
    if can_assign:
        options = ['<option value="">Nicht zugewiesen</option>']
        options.extend(
            f'<option value="{_e(account_id)}">{_e(label)}</option>'
            for account_id, label in assignee_options
        )
        assignee = (
            '<label>Zuständig<select name="assigned_to_employee_id">'
            + "".join(options)
            + "</select></label>"
        )
    return (
        "<section><h2>Neue Aufgabe</h2>"
        '<form method="post" action="/aufgaben/manual">'
        f'<input type="hidden" name="_csrf_token" value="{_e(context.csrf_token)}">'
        '<label>Titel<input name="title" maxlength="200" required></label>'
        '<label>Beschreibung<textarea name="description" maxlength="4000" rows="3"></textarea></label>'
        '<label>Fällig<input type="datetime-local" name="due_at"></label>'
        + assignee
        + '<label>Bezug<select name="subject_type">'
        '<option value="NONE">Kein Bezug</option>'
        '<option value="ORDER">Auftrag</option>'
        '<option value="INQUIRY">Anfrage</option>'
        '<option value="CONTACT">Kontakt</option>'
        "</select></label>"
        '<label>Bezug-ID (optional)<input name="subject_id" placeholder="UUID"></label>'
        '<button type="submit">Aufgabe anlegen</button>'
        "</form></section>"
    )


def render_aufgaben_list(
    rows: list[dict[str, object]],
    *,
    context: OfficePageContext,
    manual_tasks: list[ManualTaskViewRow] | None = None,
    can_create_manual: bool = False,
    can_complete_manual: bool = False,
    can_assign_manual: bool = False,
    assignee_options: list[tuple[str, str]] | None = None,
    show_system_tasks: bool = True,
) -> str:
    manual_tasks = manual_tasks or []
    assignee_options = assignee_options or []

    manual_rows = []
    for task in manual_tasks:
        action = ""
        if can_complete_manual:
            task_id = quote(task.task_id, safe="")
            action = (
                f'<form method="post" action="/aufgaben/manual/{task_id}/complete">'
                f'<input type="hidden" name="_csrf_token" value="{_e(context.csrf_token)}">'
                '<button type="submit">Erledigt</button></form>'
            )
        manual_rows.append(
            "<tr>"
            f"<td>{_e(task.title)}</td>"
            f"<td>{_e(task.description or '–')}</td>"
            f"<td>{_e(task.assigned_to_label)}</td>"
            f"<td>{_e(_subject_label(task))}</td>"
            f"<td>{_e(_format_due(task.due_at))}</td>"
            f"<td>{action}</td>"
            "</tr>"
        )

    body_parts = [
        '<p class="subtitle">Manuelle Aufgaben und automatisch abgeleitete Büro-Hinweise.</p>'
    ]
    if can_create_manual:
        body_parts.append(
            _manual_task_form(
                context=context,
                assignee_options=assignee_options,
                can_assign=can_assign_manual,
            )
        )
    if (
        manual_tasks
        or can_create_manual
        or "tasks.view" in context.employee_effective_permissions
    ):
        body_parts.extend(
            [
                "<section><h2>Manuelle Aufgaben</h2>",
                "<table><tr><th>Aufgabe</th><th>Beschreibung</th><th>Zuständig</th>"
                "<th>Bezug</th><th>Fällig</th><th></th></tr>",
                "".join(
                    manual_rows
                    or [
                        '<tr><td colspan="6">Keine offenen manuellen Aufgaben.</td></tr>'
                    ]
                ),
                "</table></section>",
            ]
        )

    if show_system_tasks:
        table_rows = []
        for row in rows:
            href = str(row["action_href"])
            table_rows.append(
                "<tr>"
                f"<td>{_e(_urgency_label(row['urgency']))}</td>"
                f"<td>{_e(str(row['title']))}</td>"
                f"<td>{_e(str(row['subtitle']))}</td>"
                f"<td>{_e(_format_due(row.get('due_at')))}</td>"
                f'<td><a href="{_e(href)}">{_e(str(row["action_label"]))}</a></td>'
                "</tr>"
            )
        body_parts.extend(
            [
                "<section><h2>Automatisch abgeleitete Aufgaben</h2>",
                '<p class="subtitle">Hinweise aus Anfragen, Aufträgen und Zahlungserinnerungen. Sie blockieren keine Entscheidung.</p>',
                "<table><tr><th>Dringlichkeit</th><th>Aufgabe</th><th>Bezug</th>"
                "<th>Fällig</th><th></th></tr>",
                "".join(
                    table_rows
                    or [
                        '<tr><td colspan="5">Keine offenen abgeleiteten Aufgaben.</td></tr>'
                    ]
                ),
                "</table></section>",
            ]
        )
    body_parts.append('<p><a href="/">← Zurück zur Arbeitszentrale</a></p>')
    return _page(
        "Aufgaben", "".join(body_parts), active_section="tasks", context=context
    )
