"""Office Panel presentation for internal employee chat."""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _csrf_input,
    _e,
    _page,
)

_BERLIN = ZoneInfo("Europe/Berlin")
_REFERENCE_LABELS = {
    "ORDER": "Auftrag",
    "INQUIRY": "Anfrage",
    "CONTACT": "Kontakt",
}
_HTTP_URL_RE = re.compile(r"https?://[^\s<>'\"]+")
_TRAILING_URL_PUNCTUATION = ".,;:!?)"


def _as_list(value: object) -> list[dict[str, object]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _short_id(value: object) -> str:
    raw = str(value)
    return raw[:8] if raw else ""


def _int_value(value: object) -> int:
    return value if isinstance(value, int) else 0


def _format_time(raw: object) -> str:
    try:
        value = datetime.fromisoformat(str(raw))
    except ValueError:
        return str(raw)
    local = value.astimezone(_BERLIN)
    return f"{local.day:02d}.{local.month:02d}. {local.hour:02d}:{local.minute:02d}"


def _thread_title(
    summary_or_detail: dict[str, object], current_employee_id: str
) -> str:
    thread = _as_dict(summary_or_detail.get("thread", summary_or_detail))
    if thread.get("thread_type") == "GROUP":
        title = str(thread.get("title") or "").strip()
        return title or "Gruppenchat"
    participants = _as_list(summary_or_detail.get("participants"))
    for participant in participants:
        if str(participant.get("employee_id")) != current_employee_id:
            return str(participant.get("display_name") or "Direktchat")
    return "Direktchat"


def _participants_line(participants: list[dict[str, object]]) -> str:
    names = [str(participant.get("display_name") or "") for participant in participants]
    return " · ".join(name for name in names if name)


def _message_preview(summary: dict[str, object]) -> str:
    preview = summary.get("latest_message_preview")
    if not isinstance(preview, dict):
        return "Noch keine Nachrichten."
    body = str(preview.get("body") or "").strip()
    return body or "Verknüpfte Karte"


def _linkify_message_body(body: str) -> str:
    parts: list[str] = []
    position = 0
    for match in _HTTP_URL_RE.finditer(body):
        parts.append(_e(body[position : match.start()]))
        url = match.group(0)
        trailing = ""
        while url and url[-1] in _TRAILING_URL_PUNCTUATION:
            trailing = url[-1] + trailing
            url = url[:-1]
        if url:
            escaped_url = _e(url)
            parts.append(
                f'<a href="{escaped_url}" target="_blank" rel="noopener noreferrer">'
                f"{escaped_url}</a>"
            )
        parts.append(_e(trailing))
        position = match.end()
    parts.append(_e(body[position:]))
    return "".join(parts)


def _reference_href(reference_type: str, reference_id: str) -> str | None:
    if reference_type == "ORDER":
        return f"/order/{quote(reference_id, safe='')}"
    if reference_type == "INQUIRY":
        return f"/inquiry/{quote(reference_id, safe='')}"
    return None


def _reference_card(reference: dict[str, object]) -> str:
    reference_type = str(reference.get("reference_type") or "")
    reference_id = str(reference.get("reference_id") or "")
    label = _REFERENCE_LABELS.get(reference_type, reference_type or "Bezug")
    title = f"{label} {_short_id(reference_id)}"
    href = _reference_href(reference_type, reference_id)
    title_html = (
        f'<a href="{_e(href)}">{_e(title)}</a>' if href is not None else _e(title)
    )
    return (
        '<div class="chat-reference-row">'
        f"<span>{title_html}</span>"
        f'<span class="chat-reference-meta">{_e(reference_id)}</span>'
        "</div>"
    )


def _summary_row(summary: dict[str, object], current_employee_id: str) -> str:
    thread = _as_dict(summary["thread"])
    thread_id = str(thread["thread_id"])
    unread = _int_value(summary.get("unread_count"))
    row_class = "chat-thread-row unread" if unread else "chat-thread-row"
    badge = f'<span class="badge">{unread}</span>' if unread else ""
    return (
        f'<a class="{row_class}" href="/chat/{_e(quote(thread_id, safe=""))}">'
        '<span class="chat-thread-head">'
        f'<span class="chat-thread-title">{_e(_thread_title(summary, current_employee_id))}</span>'
        f'<span class="chat-meta">{_e(_format_time(summary["last_activity_at"]))}</span>'
        "</span>"
        f'<span class="chat-preview">{_e(_message_preview(summary))}</span>'
        f'<span class="chat-meta">{_e(_participants_line(_as_list(summary.get("participants"))))}{badge}</span>'
        "</a>"
    )


def render_chat_list(
    threads: list[dict[str, object]],
    *,
    search_results: list[dict[str, object]] | None = None,
    q: str = "",
    context: OfficePageContext,
) -> str:
    current_employee_id = context.employee_account_id
    sorted_threads = sorted(
        threads,
        key=lambda row: str(row.get("last_activity_at") or ""),
        reverse=True,
    )
    rows = "".join(_summary_row(row, current_employee_id) for row in sorted_threads)
    if not rows:
        rows = '<p class="chat-empty">Keine Nachrichten vorhanden.</p>'
    search_rows = ""
    if search_results is not None:
        search_rows = "".join(
            _summary_row(row, current_employee_id) for row in search_results
        )
        if not search_rows:
            search_rows = '<p class="chat-empty">Keine Treffer gefunden.</p>'
        search_rows = f'<h2>Suche</h2><div class="chat-thread-list">{search_rows}</div>'
    secondary_panel = search_rows or '<p class="chat-empty">Suchbegriff eingeben.</p>'
    body = (
        '<div class="chat-toolbar">'
        '<form method="get" action="/chat" class="searchbox">'
        '<label for="chat-q">Nachrichten durchsuchen</label> '
        f'<input id="chat-q" type="text" name="q" value="{_e(q)}">'
        '<button type="submit">Suchen</button>'
        + (' <a href="/chat">Zurücksetzen</a>' if q else "")
        + "</form>"
        + (
            '<a class="dashboard-button" href="/chat/new">Neuer Chat</a>'
            if context.can("chat.create")
            else ""
        )
        + "</div>"
        '<div class="chat-layout">'
        f'<section class="chat-thread-list">{rows}</section>'
        f'<section class="chat-panel">{secondary_panel}</section>'
        "</div>"
    )
    return _page("Nachrichten", body, active_section="chat", context=context)


def render_chat_new(
    employees: list[dict[str, object]],
    *,
    q: str,
    context: OfficePageContext,
    command_fields: str,
) -> str:
    employee_rows = []
    for employee in employees:
        employee_id = str(employee["employee_id"])
        if employee_id == context.employee_account_id:
            continue
        employee_rows.append(
            '<label class="chat-picker-row">'
            f"<span>{_e(employee['display_name'])}</span>"
            f'<input type="checkbox" name="participant_employee_id" value="{_e(employee_id)}">'
            "</label>"
        )
    picker = (
        "".join(employee_rows)
        or '<p class="chat-empty">Keine Mitarbeitenden gefunden.</p>'
    )
    body = (
        '<p class="subtitle"><a href="/chat">← Zurück zu Nachrichten</a></p>'
        '<div class="chat-create-grid">'
        '<section class="chat-panel">'
        '<form method="get" action="/chat/new" class="searchbox">'
        '<label for="chat-employee-q">Mitarbeitende suchen</label> '
        f'<input id="chat-employee-q" name="q" value="{_e(q)}">'
        '<button type="submit">Suchen</button>'
        "</form>"
        "</section>"
        '<section class="chat-panel">'
        '<form method="post" action="/chat/threads">'
        f"{_csrf_input(context)}{command_fields}"
        '<p><label for="thread-type">Typ</label><br>'
        '<select id="thread-type" name="thread_type">'
        '<option value="DIRECT">Direktchat</option>'
        '<option value="GROUP">Gruppe</option>'
        "</select></p>"
        '<p><label for="chat-title">Gruppentitel</label><br>'
        '<input id="chat-title" name="title"></p>'
        f'<div class="chat-picker-list">{picker}</div>'
        '<p><button type="submit">Chat erstellen</button></p>'
        "</form>"
        "</section></div>"
    )
    return _page("Neuer Chat", body, active_section="chat", context=context)


def _reply_quote(messages: list[dict[str, object]], reply_to_message_id: str) -> str:
    if not reply_to_message_id:
        return ""
    for message in messages:
        if str(message.get("message_id")) == reply_to_message_id:
            body = str(message.get("body") or "").strip() or "Verknüpfte Karte"
            return (
                '<div class="chat-reply-quote">'
                f"Antwort auf {_e(message.get('author_display_name') or '')}: {_e(body[:160])}"
                "</div>"
            )
    return ""


def _message_block(
    message: dict[str, object], messages: list[dict[str, object]]
) -> str:
    reply = _reply_quote(messages, str(message.get("reply_to_message_id") or ""))
    body = str(message.get("body") or "")
    mentions = _as_list(message.get("mentions"))
    mention_line = (
        '<p class="chat-meta">'
        + " ".join(f"@{_e(item.get('display_name') or '')}" for item in mentions)
        + "</p>"
        if mentions
        else ""
    )
    references = "".join(
        _reference_card(ref) for ref in _as_list(message.get("references"))
    )
    reference_list = (
        f'<div class="chat-reference-list">{references}</div>' if references else ""
    )
    thread_id = str(message.get("thread_id") or "")
    message_id = str(message.get("message_id") or "")
    return (
        '<article class="chat-message">'
        '<div class="chat-message-head">'
        f'<span class="chat-message-author">{_e(message.get("author_display_name") or "")}</span>'
        f'<span class="chat-meta">{_e(_format_time(message.get("created_at")))}</span>'
        "</div>"
        f"{reply}"
        + (
            f'<p class="chat-message-body">{_linkify_message_body(body)}</p>'
            if body
            else ""
        )
        + mention_line
        + reference_list
        + f'<p class="chat-meta"><a href="/chat/{_e(quote(thread_id, safe=""))}?reply_to={_e(quote(message_id, safe=""))}">Antworten</a></p>'
        "</article>"
    )


def _participant_picker(participants: list[dict[str, object]]) -> str:
    rows = []
    for participant in participants:
        rows.append(
            '<label class="chat-picker-row">'
            f"<span>@{_e(participant.get('display_name') or '')}</span>"
            f'<input type="checkbox" name="mention_employee_id" value="{_e(participant.get("employee_id") or "")}">'
            "</label>"
        )
    return "".join(rows) or '<p class="chat-empty">Keine Teilnehmer gefunden.</p>'


def _entity_picker(results: list[dict[str, object]]) -> str:
    rows = []
    for result in results:
        value = f"{result.get('reference_type')}:{result.get('reference_id')}"
        rows.append(
            '<label class="chat-picker-row">'
            "<span>"
            f"<strong>{_e(result.get('primary_label') or '')}</strong><br>"
            f'<span class="chat-reference-meta">{_e(result.get("secondary_label") or "")}</span>'
            "</span>"
            f'<input type="checkbox" name="reference" value="{_e(value)}">'
            "</label>"
        )
    return "".join(rows) or '<p class="chat-empty">Keine Verknüpfung gefunden.</p>'


def render_chat_detail(
    detail: dict[str, object],
    *,
    context: OfficePageContext,
    read_command_fields: str,
    send_command_fields: str,
    participant_results: list[dict[str, object]],
    mention_q: str,
    entity_results: list[dict[str, object]],
    reference_q: str,
    reference_type: str,
    reply_to_message_id: str,
) -> str:
    thread = _as_dict(detail["thread"])
    thread_id = str(thread["thread_id"])
    participants = _as_list(detail.get("participants"))
    messages = _as_list(detail.get("messages"))
    message_rows = "".join(_message_block(message, messages) for message in messages)
    if not message_rows:
        message_rows = '<p class="chat-empty">Keine Nachrichten vorhanden.</p>'
    last_message_id = str(messages[-1]["message_id"]) if messages else ""
    read_form = (
        '<form method="post" action="/chat/'
        f'{_e(quote(thread_id, safe=""))}/read" class="inline">'
        f"{_csrf_input(context)}{read_command_fields}"
        f'<input type="hidden" name="last_read_message_id" value="{_e(last_message_id)}">'
        '<button type="submit">Gelesen markieren</button></form>'
        if last_message_id
        else ""
    )
    query_base = f"/chat/{quote(thread_id, safe='')}"
    mention_query = urlencode({"mention_q": mention_q})
    reference_query = urlencode(
        {"reference_q": reference_q, "reference_type": reference_type}
    )
    reply_hidden = (
        f'<input type="hidden" name="reply_to_message_id" value="{_e(reply_to_message_id)}">'
        if reply_to_message_id
        else ""
    )
    body = (
        '<p class="subtitle"><a href="/chat">← Zurück zu Nachrichten</a></p>'
        '<div class="chat-toolbar">'
        f"<div><strong>{_e(_thread_title(detail, context.employee_account_id))}</strong>"
        f'<div class="chat-participants">{_e(_participants_line(participants))}</div></div>'
        f"{read_form}"
        "</div>"
        '<section class="chat-thread-view">'
        f"{message_rows}</section>"
        '<section class="chat-composer">'
        f"{_reply_quote(messages, reply_to_message_id)}"
        f'<form method="post" action="/chat/{_e(quote(thread_id, safe=""))}/messages">'
        f"{_csrf_input(context)}{send_command_fields}{reply_hidden}"
        '<p><label for="chat-body">Nachricht</label><br>'
        '<textarea id="chat-body" name="body"></textarea></p>'
        "<details><summary>@</summary>"
        f'<p><a href="{_e(query_base + ("?" + mention_query if mention_q else ""))}">Teilnehmer aktualisieren</a></p>'
        f"{_participant_picker(participant_results)}"
        "</details>"
        "<details><summary>+ Verknüpfen</summary>"
        '<p><label for="reference-type">Typ</label><br>'
        f'<select id="reference-type" name="reference_type"><option value="ORDER"{" selected" if reference_type == "ORDER" else ""}>Auftrag</option><option value="INQUIRY"{" selected" if reference_type == "INQUIRY" else ""}>Anfrage</option><option value="CONTACT"{" selected" if reference_type == "CONTACT" else ""}>Kontakt</option></select></p>'
        f'<p><a href="{_e(query_base + ("?" + reference_query if reference_q else ""))}">Verknüpfungen suchen</a></p>'
        f"{_entity_picker(entity_results)}"
        "</details>"
        '<div class="chat-composer-actions"><button type="submit">Senden</button></div>'
        "</form>"
        '<form method="get" action="'
        f'{_e(query_base)}" class="searchbox">'
        '<label for="mention-q">Teilnehmer suchen</label> '
        f'<input id="mention-q" name="mention_q" value="{_e(mention_q)}">'
        '<button type="submit">@</button></form>'
        '<form method="get" action="'
        f'{_e(query_base)}" class="searchbox">'
        '<label for="reference-q">Verknüpfung suchen</label> '
        f'<input id="reference-q" name="reference_q" value="{_e(reference_q)}">'
        f'<select name="reference_type"><option value="ORDER"{" selected" if reference_type == "ORDER" else ""}>Auftrag</option><option value="INQUIRY"{" selected" if reference_type == "INQUIRY" else ""}>Anfrage</option><option value="CONTACT"{" selected" if reference_type == "CONTACT" else ""}>Kontakt</option></select>'
        '<button type="submit">Suchen</button></form>'
        "</section>"
    )
    return _page(
        _thread_title(detail, context.employee_account_id),
        body,
        active_section="chat",
        context=context,
    )
