"""Inquiry aggregate — A1 internal scaffold."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, TypedDict, cast

InquirySource = Literal["wix_form", "email", "phone", "manual"]

# Frozen CRM pipeline (ordered; single source of truth for crm_stage).
CrmStage = Literal[
    "Neue Anfrage",
    "In Prüfung",
    "Vorschlag vorbereiten",
    "Angebot in Bearbeitung",
    "Angebot gesendet / Rückmeldung offen",
    "Bestätigt / Auftrag",
    "Abgelehnt / verloren",
]
CRM_PIPELINE: tuple[CrmStage, ...] = (
    "Neue Anfrage",
    "In Prüfung",
    "Vorschlag vorbereiten",
    "Angebot in Bearbeitung",
    "Angebot gesendet / Rückmeldung offen",
    "Bestätigt / Auftrag",
    "Abgelehnt / verloren",
)
CRM_STAGE_SET: frozenset[str] = frozenset(CRM_PIPELINE)

PlanningMode = Literal["caterer_suggestion", "self_select"]
PLANNING_MODES: tuple[PlanningMode, ...] = ("caterer_suggestion", "self_select")
PLANNING_MODE_SET: frozenset[str] = frozenset(PLANNING_MODES)

CallVerificationStatus = Literal[
    "not_required",
    "pending",
    "verified",
    "failed",
    "blocked",
]
CALL_VERIFICATION_STATUSES: tuple[CallVerificationStatus, ...] = (
    "not_required",
    "pending",
    "verified",
    "failed",
    "blocked",
)
CALL_VERIFICATION_STATUS_SET: frozenset[str] = frozenset(CALL_VERIFICATION_STATUSES)


class CustomerLinkage(TypedDict, total=False):
    customer_id: str
    contact_id: str
    placeholder: Literal[True]


ALLOWED_CUSTOMER_LINKAGE_KEYS: frozenset[str] = frozenset(
    {"customer_id", "contact_id", "placeholder"}
)


def validate_crm_stage(value: str) -> CrmStage:
    if value not in CRM_STAGE_SET:
        raise ValueError(
            f"crm_stage must be one of {sorted(CRM_STAGE_SET)}, got {value!r}"
        )
    return cast(CrmStage, value)


def validate_planning_mode(value: str) -> PlanningMode:
    if value not in PLANNING_MODE_SET:
        raise ValueError(
            f"planning_mode must be one of {sorted(PLANNING_MODE_SET)}, got {value!r}"
        )
    return cast(PlanningMode, value)


def validate_call_verification_status(value: str) -> CallVerificationStatus:
    if value not in CALL_VERIFICATION_STATUS_SET:
        raise ValueError(
            "call_verification_status must be one of "
            f"{sorted(CALL_VERIFICATION_STATUS_SET)}, got {value!r}"
        )
    return cast(CallVerificationStatus, value)


def validate_customer_linkage(value: dict[str, Any]) -> CustomerLinkage:
    if not isinstance(value, dict):
        raise TypeError("customer_linkage must be a dict")
    for key in value:
        if key not in ALLOWED_CUSTOMER_LINKAGE_KEYS:
            raise ValueError(
                f"customer_linkage keys must be subset of "
                f"{sorted(ALLOWED_CUSTOMER_LINKAGE_KEYS)}, got key {key!r}"
            )
    if value.get("placeholder") is not None and value.get("placeholder") is not True:
        raise ValueError("customer_linkage['placeholder'] is only allowed as the literal True")
    for sk in ("customer_id", "contact_id"):
        if sk in value and not isinstance(value[sk], str):
            raise ValueError(f"customer_linkage[{sk!r}] must be a str when present")
    return cast(CustomerLinkage, value)


@dataclass
class Inquiry:
    """Sales inquiry (A1)."""

    inquiry_id: str
    event_date: date
    created_at: datetime
    updated_at: datetime
    inquiry_source: InquirySource
    crm_stage: CrmStage
    customer_linkage: CustomerLinkage
    time_window_text: str
    location_text: str
    guest_count_estimate: int | None
    planning_mode: PlanningMode
    call_verification_required: bool
    call_verification_status: CallVerificationStatus


def inquiry_allows_order_conversion(inquiry: Inquiry) -> bool:
    """B5: Core gate — conversion allowed when verification not required or already verified."""
    if not inquiry.call_verification_required:
        return True
    return inquiry.call_verification_status == "verified"
