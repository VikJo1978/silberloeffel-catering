"""Aufgaben list presentation — manual and read-only system office tasks."""

from __future__ import annotations

import base64
import hashlib
from datetime import date, datetime
from zoneinfo import ZoneInfo

from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _e,
    _page,
)

_BERLIN = ZoneInfo("Europe/Berlin")
_PRIORITY_LABELS = {"HIGH": "Hoch", "NORMAL": "Normal", "LOW": "Niedrig"}
_SUBJECT_CATEGORY_LABELS = {
    "CONTACT": "Kontakt",
    "INQUIRY": "Anfrage",
    "OFFER": "Angebot",
    "ORDER": "Auftrag",
}

_SUBJECT_PICKER_SCRIPT_BODY = r"""
(() => {
  const picker = document.getElementById("manual_task_subject_picker");
  if (!picker) return;

  const search = document.getElementById("manual_task_subject_search");
  const hidden = document.getElementById("manual_task_subject");
  const selection = document.getElementById("manual_task_subject_selection");
  const summarySelection = document.getElementById(
    "manual_task_subject_summary_selection"
  );
  const results = document.getElementById("manual_task_subject_results");
  const empty = document.getElementById("manual_task_subject_empty");
  const categoryButtons = Array.from(
    picker.querySelectorAll("[data-subject-category-filter]")
  );
  const resultButtons = Array.from(
    picker.querySelectorAll("[data-subject-result]")
  );

  let activeCategory = "";

  const normalized = (value) => value.trim().toLocaleLowerCase("de");

  const setCategoryPressed = () => {
    categoryButtons.forEach((button) => {
      const category = button.dataset.subjectCategoryFilter || "";
      button.setAttribute(
        "aria-pressed",
        category !== "NONE" && category === activeCategory ? "true" : "false"
      );
    });
  };

  const updateResults = () => {
    const query = normalized(search.value);
    const shouldShow = Boolean(query || activeCategory);
    let visibleCount = 0;

    resultButtons.forEach((button) => {
      const category = button.dataset.subjectCategory || "";
      const searchable = normalized(button.dataset.subjectSearch || "");
      const categoryMatches = !activeCategory || category === activeCategory;
      const queryMatches = !query || searchable.includes(query);
      const visible = shouldShow && categoryMatches && queryMatches;
      button.hidden = !visible;
      if (visible) visibleCount += 1;
    });

    results.hidden = !shouldShow;
    empty.hidden = !shouldShow || visibleCount !== 0;
  };

  const chooseNone = () => {
    hidden.value = "";
    selection.textContent = "Ohne Bezug";
    summarySelection.textContent = "Ohne Bezug";
    search.value = "";
    activeCategory = "";
    setCategoryPressed();
    updateResults();
    picker.open = false;
  };

  categoryButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const category = button.dataset.subjectCategoryFilter || "";
      if (category === "NONE") {
        chooseNone();
        return;
      }
      activeCategory = activeCategory === category ? "" : category;
      setCategoryPressed();
      updateResults();
      search.focus();
    });
  });

  resultButtons.forEach((button) => {
    button.addEventListener("click", () => {
      hidden.value = button.dataset.subjectValue || "";
      const label = button.dataset.subjectLabel || "Ohne Bezug";
      selection.textContent = label;
      summarySelection.textContent = label;
      picker.open = false;
    });
  });

  search.addEventListener("input", updateResults);
  picker.addEventListener("toggle", () => {
    if (picker.open) search.focus();
  });

  setCategoryPressed();
  updateResults();
})();
"""

_SUBJECT_PICKER_SCRIPT = f"<script>{_SUBJECT_PICKER_SCRIPT_BODY}</script>"
SUBJECT_PICKER_SCRIPT_CSP_SOURCE = (
    "'sha256-"
    + base64.b64encode(
        hashlib.sha256(_SUBJECT_PICKER_SCRIPT_BODY.encode("utf-8")).digest()
    ).decode("ascii")
    + "'"
)


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


def _priority_label(raw: object) -> str:
    return _PRIORITY_LABELS.get(str(raw), "Normal")


def _subject_cell(row: dict[str, object]) -> str:
    label = str(row.get("subject_label") or "–")
    href = str(row.get("subject_href") or "")
    if href:
        return f'<a href="{_e(href)}">{_e(label)}</a>'
    return _e(label)


def _task_title_cell(row: dict[str, object]) -> str:
    title = _e(str(row["title"]))
    if row.get("kind") != "manual":
        return title
    task_id = str(row.get("task_id") or "")
    if not task_id:
        return title
    return f'<a href="/aufgaben/{_e(task_id)}">{title}</a>'


def _subject_picker(subject_options: list[dict[str, str]] | None) -> str:
    result_buttons: list[str] = []
    for option in subject_options or []:
        value = str(option.get("value", ""))
        category, separator, _subject_key = value.partition(":")
        if not separator or category not in _SUBJECT_CATEGORY_LABELS:
            continue
        label = str(option.get("label", ""))
        result_buttons.append(
            '<button type="button" class="task-subject-result" '
            "data-subject-result "
            f'data-subject-category="{_e(category)}" '
            f'data-subject-value="{_e(value)}" '
            f'data-subject-label="{_e(label)}" '
            f'data-subject-search="{_e(label)}" hidden>'
            f'<span class="task-subject-result-kind">'
            f"{_e(_SUBJECT_CATEGORY_LABELS[category])}</span>"
            f"<span>{_e(label)}</span></button>"
        )

    categories = (
        '<button type="button" data-subject-category-filter="NONE" '
        'aria-pressed="false">Ohne Bezug</button>'
        '<button type="button" data-subject-category-filter="CONTACT" '
        'aria-pressed="false">Kontakt</button>'
        '<button type="button" data-subject-category-filter="INQUIRY" '
        'aria-pressed="false">Anfrage</button>'
        '<button type="button" data-subject-category-filter="OFFER" '
        'aria-pressed="false">Angebot</button>'
        '<button type="button" data-subject-category-filter="ORDER" '
        'aria-pressed="false">Auftrag</button>'
    )
    return (
        '<details class="task-subject-picker" id="manual_task_subject_picker">'
        '<summary>Bezug <span id="manual_task_subject_summary_selection">'
        "Ohne Bezug</span></summary>"
        '<div class="task-subject-picker-body">'
        '<div class="task-subject-picker-controls">'
        '<label for="manual_task_subject_search">Bezug</label>'
        '<input id="manual_task_subject_search" type="search" '
        'placeholder="Kontakt, Anfrage, Angebot oder Auftrag suchen" '
        'autocomplete="off">'
        f'<div class="task-subject-categories" role="group" '
        f'aria-label="Bezug filtern">{categories}</div>'
        "</div>"
        '<input id="manual_task_subject" type="hidden" '
        'name="subject_reference" value="">'
        '<div class="task-subject-selection" id="manual_task_subject_selection">'
        "Ohne Bezug</div>"
        '<div class="task-subject-results" id="manual_task_subject_results" '
        'aria-live="polite" hidden>' + "".join(result_buttons) + "</div>"
        '<p class="task-subject-empty" id="manual_task_subject_empty" hidden>'
        "Keine Treffer.</p>"
        "</div></details>" + _SUBJECT_PICKER_SCRIPT
    )


def render_aufgabe_detail(
    row: dict[str, object],
    *,
    context: OfficePageContext,
) -> str:
    description = str(row.get("description") or "").strip()
    description_html = (
        _e(description).replace("\n", "<br>") if description else "Keine Beschreibung."
    )
    subject_label = str(row.get("subject_label") or "–")
    subject_href = str(row.get("subject_href") or "")
    subject_html = _e(subject_label)
    if subject_href:
        subject_html = (
            f'{_e(subject_label)} <a href="{_e(subject_href)}">Bezug öffnen</a>'
        )

    complete_action = ""
    if row.get("can_complete"):
        complete_action = (
            f'<form method="post" action="/aufgaben/{_e(str(row["task_id"]))}/complete">'
            f"{row.get('complete_form_fields', '')}"
            '<button type="submit">Als erledigt markieren</button></form>'
        )

    body = (
        '<p class="subtitle">Manuelle Aufgabe</p>'
        f'<section class="task-detail-card"><h2>{_e(str(row["title"]))}</h2>'
        '<dl class="task-detail-meta">'
        f"<dt>Status</dt><dd>Offen</dd>"
        f"<dt>Wichtigkeit</dt><dd>{_e(_priority_label(row.get('priority', 'NORMAL')))}</dd>"
        f"<dt>Fällig</dt><dd>{_e(_format_due(row.get('due_at')))}</dd>"
        f"<dt>Zugewiesen</dt><dd>{_e(str(row.get('assigned_to') or '–'))}</dd>"
        f"<dt>Bezug</dt><dd>{subject_html}</dd>"
        "</dl>"
        "<h3>Beschreibung</h3>"
        f'<div class="task-detail-description">{description_html}</div>'
        f"{complete_action}</section>"
        '<p><a href="/aufgaben">← Zurück zu Aufgaben</a></p>'
        '<p><a href="/">← Zurück zur Arbeitszentrale</a></p>'
    )
    return _page("Aufgabe", body, active_section="tasks", context=context)


def render_aufgaben_list(
    rows: list[dict[str, object]],
    *,
    context: OfficePageContext,
    assignee_options: list[dict[str, str]] | None = None,
    subject_options: list[dict[str, str]] | None = None,
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
        subject_field = _subject_picker(subject_options)
        create_form = (
            "<section><h2>Neue Aufgabe</h2>"
            '<form method="post" action="/aufgaben/new">'
            f"{create_form_fields}"
            '<p><label for="manual_task_title">Titel</label><br>'
            '<input id="manual_task_title" name="title" required maxlength="200"></p>'
            '<p><label for="manual_task_description">Beschreibung</label><br>'
            '<textarea id="manual_task_description" name="description" '
            'maxlength="4000"></textarea></p>'
            '<p><label for="manual_task_priority">Wichtigkeit</label><br>'
            '<select id="manual_task_priority" name="priority">'
            '<option value="HIGH">Hoch</option>'
            '<option value="NORMAL" selected>Normal</option>'
            '<option value="LOW">Niedrig</option>'
            "</select></p>"
            '<p><label for="manual_task_due_date">Fällig</label><br>'
            '<input id="manual_task_due_date" name="due_date" type="date"></p>'
            f"{subject_field}"
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
            f"<td>{_e(_priority_label(row.get('priority', 'NORMAL')))}</td>"
            f"<td>{_task_title_cell(row)}</td>"
            f"<td>{_e(str(row.get('description', '–')))}</td>"
            f"<td>{_subject_cell(row)}</td>"
            f"<td>{_e(_format_due(row.get('due_at')))}</td>"
            f"<td>{_e(str(row.get('assigned_to', '–')))}</td>"
            f"<td>{action}</td>"
            "</tr>"
        )
    body = (
        '<p class="subtitle">Manuelle Aufgaben und abgeleitete Büro-Aufgaben '
        "aus Anfragen, Angeboten, Aufträgen und Zahlungserinnerungen.</p>"
        + create_form
        + "<h2>Offene Aufgaben</h2>"
        + "<table><tr><th>Typ</th><th>Wichtigkeit</th><th>Aufgabe</th>"
        "<th>Beschreibung</th><th>Bezug</th><th>Fällig</th><th>Zugewiesen</th>"
        "<th>Aktion</th></tr>"
        + "".join(
            table_rows or ['<tr><td colspan="8">Keine offenen Aufgaben.</td></tr>']
        )
        + "</table>"
        + '<p><a href="/">← Zurück zur Arbeitszentrale</a></p>'
    )
    return _page("Aufgaben", body, active_section="tasks", context=context)
