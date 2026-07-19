"""Shared German labels for operational pause presentation surfaces."""

from __future__ import annotations

PAUSE_REASON_LABELS = {
    "manual_hold": "Manuelle Sperre",
    "customer_request": "Kundenwunsch",
    "payment_dispute": "Zahlungsstreit",
    "operational_review": "Betriebliche Prüfung",
    "other": "Sonstiges",
}


def pause_reason_label(reason_code: object) -> str:
    """Return a human-readable label, preserving unknown legacy values."""
    raw = "" if reason_code is None else str(reason_code)
    return PAUSE_REASON_LABELS.get(raw, raw)
