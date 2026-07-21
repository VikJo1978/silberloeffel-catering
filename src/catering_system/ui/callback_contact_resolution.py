"""Resolve missed-call callbacks against local Core contact projections."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from urllib.parse import quote

from catering_system.intake.intake_contact import normalize_phone

_AMBIGUOUS_LABEL = "Mehrdeutig – Kundenprüfung"
_UNKNOWN_LABEL = "Unbekannt"


def build_phone_contact_index(
    contacts: Sequence[Mapping[str, object]],
) -> dict[str, list[Mapping[str, object]]]:
    """Index local contacts by canonical normalized phone."""

    index: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for contact in contacts:
        phone = normalize_phone(str(contact.get("phone") or ""))
        if not phone:
            continue
        index[phone].append(contact)
    return dict(index)


def resolve_core_contact_fields(
    item: Mapping[str, object],
    phone_index: Mapping[str, list[Mapping[str, object]]],
) -> dict[str, object]:
    """Derive Office Panel contact display fields from Core truth."""

    phone = normalize_phone(
        str(item.get("normalized_phone") or item.get("phone") or "")
    )
    if not phone:
        return {"core_contact_label": _UNKNOWN_LABEL, "core_contact_href": None}

    matches = phone_index.get(phone, [])
    if not matches:
        return {"core_contact_label": _UNKNOWN_LABEL, "core_contact_href": None}
    if len(matches) > 1:
        return {"core_contact_label": _AMBIGUOUS_LABEL, "core_contact_href": None}

    contact = matches[0]
    contact_key = str(contact["contact_key"])
    display_name = str(contact.get("display_name") or "–")
    return {
        "core_contact_label": display_name,
        "core_contact_href": f"/kontakt/{quote(contact_key, safe='')}",
    }


def enrich_missed_board_with_core_contacts(
    items: list[dict],
    contacts: Sequence[Mapping[str, object]],
) -> list[dict]:
    """Attach Core-derived contact fields; Auerswald contact fields stay untouched."""

    phone_index = build_phone_contact_index(contacts)
    enriched: list[dict] = []
    for item in items:
        resolved = resolve_core_contact_fields(item, phone_index)
        enriched.append({**item, **resolved})
    return enriched
