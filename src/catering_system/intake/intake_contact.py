"""Parse labelled intake contact context — shared read projection helper."""

from __future__ import annotations

from catering_system.domain.inquiry import Inquiry

_INTAKE_LABELS = frozenset(
    {"Firma", "Name", "Veranstaltungsart", "Telefon", "E-Mail", "Wunsch"}
)


def labelled_intake_context(message: str | None) -> tuple[dict[str, str], list[str]]:
    labelled: dict[str, str] = {}
    remaining: list[str] = []
    for raw_line in (message or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        label, separator, value = line.partition(":")
        label = label.strip()
        value = value.strip()
        if separator and label in _INTAKE_LABELS and value:
            labelled.setdefault(label, value)
        else:
            remaining.append(line)
    return labelled, remaining


def normalize_email(raw: str | None) -> str:
    value = (raw or "").strip()
    if not value or "@" not in value:
        return ""
    return value.casefold()


def normalize_phone(raw: str | None) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    plus = value.startswith("+")
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return ""
    if plus:
        return f"+{digits}"
    if digits.startswith("00"):
        return f"+{digits[2:]}"
    if digits.startswith("0"):
        return f"+49{digits[1:]}"
    return digits


def parse_intake_contact(inquiry: Inquiry) -> dict[str, str | None]:
    labelled, _remaining = labelled_intake_context(inquiry.intake_message)
    company = labelled.get("Firma", "").strip()
    person = labelled.get("Name", "").strip()
    email = normalize_email(labelled.get("E-Mail"))
    phone = normalize_phone(labelled.get("Telefon"))
    if company:
        display_name = company
    elif person:
        display_name = person
    elif inquiry.intake_subject:
        display_name = inquiry.intake_subject.strip()
    else:
        display_name = ""
    return {
        "display_name": display_name or None,
        "email": email or None,
        "phone": phone or None,
    }
