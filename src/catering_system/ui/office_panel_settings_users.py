"""Office Panel — Einstellungen → Benutzer & Rechte (AUTH-2C)."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from urllib.parse import quote

from catering_system.domain.employee_auth import (
    PERMISSION_REGISTRY,
    AuthenticatedEmployee,
    EmployeeAccountDetail,
    EmployeeAccountSummary,
    EmployeeRole,
    SecurityAuditEventView,
    manageable_roles_for,
    role_ceiling,
    validate_role,
)
from catering_system.services.employee_auth_service import (
    AccountConflictError,
    AccountNotFoundError,
    AuthorizationError,
    LastActiveSuperadminError,
)
from catering_system.ui.office_panel_views import (
    OfficePageContext,
    _csrf_input,
    _e,
    _page,
)

ROLE_LABELS: dict[str, str] = {
    "SUPERADMIN": "Superadmin",
    "ADMIN": "Administrator",
    "USER": "Benutzer",
    "VIEWER": "Leser",
}

PERMISSION_GROUP_LABELS: dict[str, str] = {
    "inquiries": "Anfragen",
    "customers": "Kunden",
    "offers": "Angebote",
    "orders": "Aufträge",
    "catalog": "Katalog",
    "prices": "Preise",
    "calendar": "Kalender",
    "queue": "Warteschlange",
    "documents": "Dokumente",
    "users": "Benutzer",
    "audit": "Audit",
    "settings": "Einstellungen",
}

PERMISSION_GROUP_ORDER: tuple[str, ...] = tuple(PERMISSION_GROUP_LABELS.keys())

PERMISSION_LABELS: dict[str, str] = {
    "inquiries.view": "Anfragen ansehen",
    "inquiries.create": "Anfragen anlegen",
    "inquiries.edit": "Anfragen bearbeiten",
    "inquiries.verify": "Anfragen verifizieren",
    "customers.view": "Kunden ansehen",
    "customers.edit": "Kunden bearbeiten",
    "offers.view": "Angebote ansehen",
    "offers.prepare": "Angebote vorbereiten",
    "offers.version.create": "Angebotsversionen anlegen",
    "offers.pdf.generate": "Angebots-PDF erzeugen",
    "offers.send": "Angebote versenden",
    "offers.status.change": "Angebotsstatus ändern",
    "offers.timing.acknowledge": "Angebots-Timing bestätigen",
    "orders.view": "Aufträge ansehen",
    "orders.version.create": "Auftragsversionen anlegen",
    "orders.print.confirm": "Küchendruck bestätigen",
    "orders.effective.set": "Wirksame Version setzen",
    "orders.ready.release": "Versandbereit freigeben",
    "orders.pause": "Aufträge pausieren",
    "orders.cancel": "Aufträge stornieren",
    "orders.payment.reminder": "Zahlungserinnerungen verwalten",
    "catalog.view": "Katalog ansehen",
    "catalog.edit": "Katalog bearbeiten",
    "prices.view": "Preise ansehen",
    "prices.edit": "Preise bearbeiten",
    "calendar.view": "Kalender ansehen",
    "queue.view": "Warteschlange ansehen",
    "documents.view": "Dokumente ansehen",
    "documents.prepare": "Dokumente vorbereiten",
    "documents.send": "Dokumente versenden",
    "users.view": "Benutzer ansehen",
    "users.create": "Benutzer anlegen",
    "users.edit": "Benutzer bearbeiten",
    "users.deactivate": "Benutzer deaktivieren",
    "users.reactivate": "Benutzer reaktivieren",
    "users.password.reset": "Passwort zurücksetzen",
    "users.permissions.assign": "Berechtigungen zuweisen",
    "users.roles.assign": "Rollen zuweisen",
    "audit.view": "Audit ansehen",
    "settings.view": "Einstellungen ansehen",
    "settings.edit": "Einstellungen bearbeiten",
}

_STATUS_FILTERS = (
    ("all", "Alle"),
    ("active", "Aktiv"),
    ("inactive", "Inaktiv"),
)

_ROLE_FILTERS = (
    ("all", "Alle Rollen"),
    ("SUPERADMIN", "Superadmin"),
    ("ADMIN", "Administrator"),
    ("USER", "Benutzer"),
    ("VIEWER", "Leser"),
)

_FLASH_MESSAGES: dict[str, str] = {
    "created": (
        "Benutzer wurde angelegt. Beim ersten Login muss das Passwort geändert werden."
    ),
    "saved": "Änderungen wurden gespeichert.",
    "deactivated": "Benutzer wurde deaktiviert.",
    "reactivated": "Benutzer wurde reaktiviert.",
    "password_reset": (
        "Temporäres Passwort wurde gesetzt. Alle Sitzungen wurden beendet; "
        "Passwortänderung ist beim nächsten Login erforderlich."
    ),
    "role_changed": "Rolle wurde geändert.",
    "permissions_saved": "Berechtigungen wurden gespeichert.",
}


class SettingsUsersAccessDenied(Exception):
    """Raised when the Office Panel user-management UI must not be shown."""


def show_users_nav_for(employee: AuthenticatedEmployee) -> bool:
    return "users.view" in employee.effective_permissions


def settings_users_error_message(exc: Exception) -> str:
    if isinstance(exc, AccountConflictError):
        return "Benutzername ist bereits vergeben."
    if isinstance(exc, LastActiveSuperadminError):
        return (
            "Der letzte aktive Superadmin kann nicht deaktiviert "
            "oder herabgestuft werden."
        )
    if isinstance(exc, AuthorizationError):
        message = str(exc)
        if "ADMIN may not manage" in message or "may not manage" in message:
            return "Diese Aktion ist für dieses Benutzerkonto nicht zulässig."
        if "missing permission" in message:
            return "Ihre Berechtigung reicht für diese Aktion nicht aus."
        if "may grant only own effective permissions" in message:
            return "Ihre Berechtigung reicht für diese Aktion nicht aus."
        return "Ihre Berechtigung reicht für diese Aktion nicht aus."
    if isinstance(exc, AccountNotFoundError):
        return "Benutzerkonto wurde nicht gefunden."
    if isinstance(exc, sqlite3.Error):
        return "Die Aktion konnte nicht ausgeführt werden."
    if isinstance(exc, ValueError):
        message = str(exc)
        if message.startswith("role must be one of"):
            return "Die ausgewählte Rolle ist nicht zulässig."
        if "temporary_password" in message or "password must be at least" in message:
            return "Das temporäre Passwort muss mindestens 8 Zeichen haben."
        if "permissions exceed" in message:
            return (
                "Die ausgewählten Berechtigungen sind für diese Rolle nicht zulässig."
            )
        if "password" in message.lower():
            return "Passwort konnte nicht gesetzt werden."
    return "Die Aktion konnte nicht ausgeführt werden."


def _format_timestamp(value: datetime | None) -> str:
    if value is None:
        return "–"
    return value.strftime("%d.%m.%Y · %H:%M")


def _permission_group(code: str) -> str:
    return code.split(".", 1)[0]


def _permission_label(code: str) -> str:
    return PERMISSION_LABELS.get(code, code.replace(".", " ").capitalize())


def permission_matrix_state(
    actor: AuthenticatedEmployee,
    *,
    target_role: EmployeeRole,
    target_read_only: bool,
    explicit_permissions: set[str],
    effective_permissions: set[str],
) -> tuple[set[str], dict[str, str]]:
    """Return selectable permission codes and disabled reasons for the matrix."""
    ceiling = role_ceiling(target_role)
    selectable: set[str] = set()
    disabled: dict[str, str] = {}
    actor_grants = (
        set(actor.effective_permissions)
        if actor.account.role == "ADMIN"
        else set(ceiling)
    )
    for code in PERMISSION_REGISTRY:
        if target_role == "VIEWER" and not code.endswith(".view"):
            disabled[code] = "Für Leser nur Leseberechtigungen"
            continue
        if code not in ceiling:
            disabled[code] = "Außerhalb der Rollenobergrenze"
            continue
        if target_read_only:
            disabled[code] = "Konto ist schreibgeschützt"
            continue
        if actor.account.role == "ADMIN" and code not in actor_grants:
            disabled[code] = "Nicht in Ihren Berechtigungen"
            continue
        selectable.add(code)
    return selectable, disabled


def parse_selected_permissions(selected: list[str], selectable: set[str]) -> set[str]:
    return {code for code in selected if code in selectable}


def _flash_banner(message_key: str) -> str:
    message = _FLASH_MESSAGES.get(message_key, "")
    if not message:
        return ""
    return f'<p class="office-flash success">{_e(message)}</p>'


def _error_banner(message: str) -> str:
    if not message:
        return ""
    return f'<p class="office-flash blocked">{_e(message)}</p>'


def _filter_links(
    base_path: str,
    *,
    status_filter: str,
    role_filter: str,
    filters: tuple[tuple[str, str], ...],
    param_name: str,
) -> str:
    links = []
    for value, label in filters:
        params = {"status": status_filter, "role": role_filter, param_name: value}
        query = "&".join(
            f"{key}={quote(str(param_value), safe='')}"
            for key, param_value in params.items()
            if param_value != "all"
        )
        current = status_filter if param_name == "status" else role_filter
        if value == current:
            links.append(f"<strong>{_e(label)}</strong>")
        else:
            links.append(f'<a href="{_e(base_path)}?{_e(query)}">{_e(label)}</a>')
    return '<p class="users-filter">' + " | ".join(links) + "</p>"


def _filter_accounts(
    accounts: list[EmployeeAccountSummary],
    *,
    status_filter: str,
    role_filter: str,
) -> list[EmployeeAccountSummary]:
    filtered = accounts
    if status_filter == "active":
        filtered = [item for item in filtered if item.is_active]
    elif status_filter == "inactive":
        filtered = [item for item in filtered if not item.is_active]
    if role_filter != "all":
        filtered = [item for item in filtered if item.role == role_filter]
    return filtered


def render_users_list(
    accounts: list[EmployeeAccountSummary],
    *,
    status_filter: str,
    role_filter: str,
    flash: str = "",
    context: OfficePageContext,
) -> str:
    rows_html = []
    for account in _filter_accounts(
        accounts, status_filter=status_filter, role_filter=role_filter
    ):
        status = "Aktiv" if account.is_active else "Inaktiv"
        must_change = "Ja" if account.must_change_password else "Nein"
        read_only = (
            '<span class="badge badge-muted">Nur Lesen</span>'
            if account.read_only
            else "–"
        )
        email = _e(account.email) if account.email else "–"
        rows_html.append(
            "<tr>"
            f"<td>{_e(account.display_name)}</td>"
            f"<td>{_e(account.username)}</td>"
            f"<td>{email}</td>"
            f"<td>{_e(ROLE_LABELS.get(account.role, account.role))}</td>"
            f"<td>{_e(status)}</td>"
            f"<td>{_e(must_change)}</td>"
            f"<td>{_e(_format_timestamp(account.last_login_at))}</td>"
            f"<td>{_e(_format_timestamp(account.updated_at))}</td>"
            f"<td>{read_only}</td>"
            f'<td><a href="/settings/users/{_e(quote(account.id, safe=""))}">'
            "Öffnen</a></td>"
            "</tr>"
        )
    body = (
        '<p class="subtitle">Mitarbeiterkonten und Berechtigungen verwalten.</p>'
        + _flash_banner(flash)
        + '<p><a href="/settings/users/new">Neuen Benutzer anlegen</a></p>'
        + _filter_links(
            "/settings/users",
            status_filter=status_filter,
            role_filter=role_filter,
            filters=_STATUS_FILTERS,
            param_name="status",
        )
        + _filter_links(
            "/settings/users",
            status_filter=status_filter,
            role_filter=role_filter,
            filters=_ROLE_FILTERS,
            param_name="role",
        )
        + "<table><tr><th>Anzeigename</th><th>Benutzername</th><th>E-Mail</th>"
        "<th>Rolle</th><th>Status</th><th>Passwortwechsel</th>"
        "<th>Letzte Anmeldung</th><th>Aktualisiert</th><th></th><th></th></tr>"
        + "".join(
            rows_html or ['<tr><td colspan="10">Keine Benutzer gefunden.</td></tr>']
        )
        + "</table>"
        + '<p><a href="/">← Zurück zur Arbeitszentrale</a></p>'
    )
    return _page(
        "Benutzer & Rechte",
        body,
        active_section="settings",
        context=context,
    )


_ROLE_VALUES: tuple[EmployeeRole, ...] = (
    "SUPERADMIN",
    "ADMIN",
    "USER",
    "VIEWER",
)


def _role_options(
    actor: AuthenticatedEmployee,
    *,
    selected: str,
    include_blank: bool = False,
) -> str:
    roles = sorted(
        manageable_roles_for(actor.account.role),
        key=lambda role: _ROLE_VALUES.index(role),
    )
    options = ['<option value="">—</option>'] if include_blank else []
    for role in roles:
        label = ROLE_LABELS.get(role, role)
        selected_attr = " selected" if role == selected else ""
        options.append(
            f'<option value="{_e(role)}"{selected_attr}>{_e(label)}</option>'
        )
    return "".join(options)


def render_user_new(
    *,
    actor: AuthenticatedEmployee,
    form: dict[str, str],
    selected_permissions: list[str] | None = None,
    error_message: str = "",
    context: OfficePageContext,
) -> str:
    role = form.get("role", "USER")
    try:
        target_role = validate_role(role)
    except ValueError:
        target_role = "USER"
    selectable, disabled = permission_matrix_state(
        actor,
        target_role=target_role,
        target_read_only=False,
        explicit_permissions=set(),
        effective_permissions=set(),
    )
    selected = parse_selected_permissions(selected_permissions or [], selectable)
    matrix = _permission_matrix_html(
        selectable=selectable,
        disabled=disabled,
        explicit=selected,
        effective=selected,
        field_prefix="permission",
    )
    body = (
        '<p class="subtitle">Neues Mitarbeiterkonto anlegen.</p>'
        + _error_banner(error_message)
        + '<form method="post" action="/settings/users" class="users-form">'
        + _csrf_input(context)
        + "<fieldset>"
        "<legend>Stammdaten</legend>"
        "<label>Benutzername<br>"
        f'<input name="username" required value="{_e(form.get("username", ""))}">'
        "</label><br>"
        "<label>Anzeigename<br>"
        f'<input name="display_name" required value="{_e(form.get("display_name", ""))}">'
        "</label><br>"
        "<label>E-Mail (optional)<br>"
        f'<input name="email" type="email" value="{_e(form.get("email", ""))}">'
        "</label><br>"
        "<label>Rolle<br>"
        f'<select name="role">{_role_options(actor, selected=role)}</select>'
        "</label><br>"
        "<label>Temporäres Passwort<br>"
        '<input name="temporary_password" type="password" autocomplete="new-password" required>'
        "</label>"
        "</fieldset>" + matrix + '<p><button type="submit">Benutzer anlegen</button> '
        '<a href="/settings/users">Abbrechen</a></p>'
        "</form>"
    )
    return _page(
        "Neuer Benutzer",
        body,
        active_section="settings",
        context=context,
    )


def _permission_matrix_html(
    *,
    selectable: set[str],
    disabled: dict[str, str],
    explicit: set[str],
    effective: set[str],
    field_prefix: str,
) -> str:
    sections: list[str] = ["<fieldset><legend>Berechtigungen</legend>"]
    grouped: dict[str, list[str]] = {key: [] for key in PERMISSION_GROUP_ORDER}
    for code in PERMISSION_REGISTRY:
        group = _permission_group(code)
        grouped.setdefault(group, []).append(code)
    for group_key in PERMISSION_GROUP_ORDER:
        codes = grouped.get(group_key, [])
        if not codes:
            continue
        sections.append(
            f'<div class="users-perm-group"><h3>{_e(PERMISSION_GROUP_LABELS.get(group_key, group_key))}</h3>'
        )
        for code in codes:
            label = _permission_label(code)
            effective_state = "wirksam" if code in effective else "nicht wirksam"
            if code in selectable:
                checked = " checked" if code in explicit else ""
                sections.append(
                    "<label class='users-perm-row'>"
                    f'<input type="checkbox" name="{_e(field_prefix)}" value="{_e(code)}"{checked}> '
                    f"<span><strong>{_e(label)}</strong> "
                    f'<span class="users-perm-code">{_e(code)}</span> '
                    f'<span class="users-perm-effective">{_e(effective_state)}</span>'
                    "</span></label>"
                )
            else:
                reason = disabled.get(code, "Nicht verfügbar")
                sections.append(
                    "<div class='users-perm-row users-perm-disabled'>"
                    f"<span><strong>{_e(label)}</strong> "
                    f'<span class="users-perm-code">{_e(code)}</span> '
                    f'<span class="users-perm-effective">{_e(effective_state)}</span> '
                    f'<span class="users-perm-note">{_e(reason)}</span>'
                    "</span></div>"
                )
        sections.append("</div>")
    sections.append("</fieldset>")
    return "".join(sections)


def _safe_metadata_lines(metadata: dict[str, object]) -> str:
    if not metadata:
        return "–"
    parts: list[str] = []
    for key, value in metadata.items():
        if key in {"password", "token", "csrf", "secret", "hash"}:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            text = "–" if value is None else str(value)
            parts.append(f"{key}: {text}")
        elif isinstance(value, list):
            parts.append(f"{key}: {', '.join(str(item) for item in value)}")
        elif isinstance(value, dict):
            inner = ", ".join(f"{k}={v}" for k, v in value.items())
            parts.append(f"{key}: {inner}")
    return _e("; ".join(parts)) if parts else "–"


def render_user_detail(
    *,
    actor: AuthenticatedEmployee,
    detail: EmployeeAccountDetail,
    audit_events: list[SecurityAuditEventView],
    flash: str = "",
    error_message: str = "",
    role_change_removed: list[str] | None = None,
    context: OfficePageContext,
) -> str:
    read_only_note = (
        '<p class="users-readonly-note"><strong>Nur Lesen:</strong> '
        "Dieses Konto kann von Ihrer Rolle aus nicht bearbeitet werden.</p>"
        if detail.read_only
        else ""
    )
    status = "Aktiv" if detail.is_active else "Inaktiv"
    must_change = "Ja" if detail.must_change_password else "Nein"
    email = _e(detail.email) if detail.email else "–"
    selectable, disabled = permission_matrix_state(
        actor,
        target_role=detail.role,
        target_read_only=detail.read_only,
        explicit_permissions=set(detail.explicit_permissions),
        effective_permissions=set(detail.effective_permissions),
    )
    removed_note = ""
    if role_change_removed:
        removed_note = (
            '<p class="office-flash">Entfernte Berechtigungen außerhalb der '
            "neuen Rollenobergrenze: " + _e(", ".join(role_change_removed)) + "</p>"
        )
    profile_form = (
        '<form method="post" '
        f'action="/settings/users/{_e(quote(detail.id, safe=""))}/profile" '
        'class="users-form">'
        + _csrf_input(context)
        + "<fieldset><legend>Profil</legend>"
        f"<p><strong>Konto-ID:</strong> {_e(detail.id)}</p>"
        "<label>Benutzername<br>"
        f'<input name="username" required value="{_e(detail.username)}">'
        "</label><br>"
        "<label>Anzeigename<br>"
        f'<input name="display_name" required value="{_e(detail.display_name)}">'
        "</label><br>"
        "<label>E-Mail<br>"
        f'<input name="email" type="email" value="{_e(detail.email or "")}">'
        "</label><br>"
        f"<p>Status: {_e(status)} · Passwortwechsel erforderlich: {_e(must_change)}</p>"
        f"<p>Erstellt: {_e(_format_timestamp(detail.created_at))} · "
        f"Aktualisiert: {_e(_format_timestamp(detail.updated_at))} · "
        f"Letzte Anmeldung: {_e(_format_timestamp(detail.last_login_at))}</p>"
        + (
            '<p><button type="submit">Profil speichern</button></p>'
            if not detail.read_only
            else "<p>Profil ist schreibgeschützt.</p>"
        )
        + "</fieldset></form>"
    )
    manageable = manageable_roles_for(actor.account.role)
    role_form = ""
    if detail.role in manageable and not detail.read_only:
        role_form = (
            '<form method="post" '
            f'action="/settings/users/{_e(quote(detail.id, safe=""))}/role" '
            'class="users-form">'
            + _csrf_input(context)
            + "<fieldset><legend>Rolle</legend>"
            "<label>Neue Rolle<br>"
            f'<select name="role">{_role_options(actor, selected=detail.role)}</select>'
            "</label><br>"
            '<p><button type="submit">Rolle speichern</button></p>'
            "</fieldset></form>"
        )
    elif detail.read_only:
        role_form = (
            "<fieldset><legend>Rolle</legend>"
            f"<p>{_e(ROLE_LABELS.get(detail.role, detail.role))} "
            "(schreibgeschützt)</p></fieldset>"
        )
    permissions_form = ""
    if (
        not detail.read_only
        and "users.permissions.assign" in actor.effective_permissions
    ):
        permissions_form = (
            '<form method="post" '
            f'action="/settings/users/{_e(quote(detail.id, safe=""))}/permissions" '
            'class="users-form">'
            + _csrf_input(context)
            + _permission_matrix_html(
                selectable=selectable,
                disabled=disabled,
                explicit=set(detail.explicit_permissions),
                effective=set(detail.effective_permissions),
                field_prefix="permission",
            )
            + '<p><button type="submit">Berechtigungen speichern</button></p>'
            "</form>"
        )
    else:
        permissions_form = (
            "<fieldset><legend>Berechtigungen</legend>"
            + _permission_matrix_html(
                selectable=set(),
                disabled={code: "Schreibgeschützt" for code in PERMISSION_REGISTRY},
                explicit=set(detail.explicit_permissions),
                effective=set(detail.effective_permissions),
                field_prefix="permission",
            )
            + "</fieldset>"
        )
    lifecycle = ""
    if not detail.read_only:
        if detail.is_active:
            lifecycle = (
                f'<p><a href="/settings/users/{_e(quote(detail.id, safe=""))}/deactivate">'
                "Benutzer deaktivieren…</a></p>"
            )
        else:
            lifecycle = (
                '<form method="post" '
                f'action="/settings/users/{_e(quote(detail.id, safe=""))}/reactivate" '
                'class="users-inline-form">'
                + _csrf_input(context)
                + "<p>Benutzer ist inaktiv. "
                "Reaktivierung erstellt keine Sitzung und setzt kein Passwort zurück.</p>"
                '<button type="submit">Benutzer reaktivieren</button>'
                "</form>"
            )
        lifecycle += (
            '<form method="post" '
            f'action="/settings/users/{_e(quote(detail.id, safe=""))}/reset-password" '
            'class="users-form">'
            + _csrf_input(context)
            + "<fieldset><legend>Passwort zurücksetzen</legend>"
            "<label>Temporäres Passwort<br>"
            '<input name="temporary_password" type="password" autocomplete="new-password" required>'
            "</label><br>"
            "<label>Temporäres Passwort wiederholen<br>"
            '<input name="temporary_password_confirm" type="password" autocomplete="new-password" required>'
            "</label><br>"
            "<p>Alle aktiven Sitzungen werden beendet; Passwortänderung ist "
            "beim nächsten Login erforderlich.</p>"
            '<p><button type="submit">Temporäres Passwort setzen</button></p>'
            "</fieldset></form>"
        )
    audit_rows = []
    for event in audit_events:
        actor_role = (
            ROLE_LABELS.get(event.actor_role_snapshot, event.actor_role_snapshot)
            if event.actor_role_snapshot
            else "–"
        )
        audit_rows.append(
            "<tr>"
            f"<td>{_e(_format_timestamp(event.occurred_at))}</td>"
            f"<td>{_e(event.action)}</td>"
            f"<td>{_e(event.outcome)}</td>"
            f"<td>{_e(event.actor_display_name_snapshot or '–')}</td>"
            f"<td>{_e(actor_role or '–')}</td>"
            f"<td>{_safe_metadata_lines(event.metadata)}</td>"
            "</tr>"
        )
    audit_table = (
        "<fieldset><legend>Letzte Sicherheitsereignisse</legend>"
        "<table><tr><th>Zeitpunkt</th><th>Aktion</th><th>Ergebnis</th>"
        "<th>Akteur</th><th>Rolle</th><th>Details</th></tr>"
        + "".join(
            audit_rows or ['<tr><td colspan="6">Keine Ereignisse vorhanden.</td></tr>']
        )
        + "</table></fieldset>"
    )
    body = (
        f"<h2>{_e(detail.display_name)}</h2>"
        + read_only_note
        + _flash_banner(flash)
        + _error_banner(error_message)
        + removed_note
        + f"<p>Benutzername: {_e(detail.username)} · E-Mail: {email} · "
        f"Rolle: {_e(ROLE_LABELS.get(detail.role, detail.role))}</p>"
        + profile_form
        + role_form
        + permissions_form
        + lifecycle
        + audit_table
        + '<p><a href="/settings/users">← Zurück zur Liste</a></p>'
    )
    return _page(
        "Benutzerkonto",
        body,
        active_section="settings",
        context=context,
        show_title=False,
    )


def render_user_deactivate_confirm(
    *,
    detail: EmployeeAccountDetail,
    context: OfficePageContext,
    error_message: str = "",
) -> str:
    body = (
        f"<h2>{_e(detail.display_name)} deaktivieren?</h2>"
        + _error_banner(error_message)
        + "<p>Der Benutzer wird deaktiviert, nicht gelöscht. "
        "Alle aktiven Sitzungen werden beendet.</p>" + '<form method="post" '
        f'action="/settings/users/{_e(quote(detail.id, safe=""))}/deactivate" '
        'class="users-form">'
        + _csrf_input(context)
        + '<p><button type="submit">Deaktivierung bestätigen</button> '
        f'<a href="/settings/users/{_e(quote(detail.id, safe=""))}">Abbrechen</a></p>'
        "</form>"
    )
    return _page(
        "Benutzer deaktivieren",
        body,
        active_section="settings",
        context=context,
        show_title=False,
    )
