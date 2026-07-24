"""Customer document create eligibility — CUSTOMER_DOCUMENT_PROJECTION_V1-C-1.

Sibling decision object to CustomerDocumentProjection (facts). Never embed
allowed/blockers on the projection itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DocumentBlockerCode = Literal[
    "MISSING_COMMERCIAL_SNAPSHOT",
    "MISSING_CUSTOMER_NAME",
    "MISSING_CUSTOMER_CONTACT",
    "INVALID_ORDER_STATE",
    "FULFILLMENT_MODE_REQUIRED",
    "DELIVERY_ADDRESS_REQUIRED_FOR_DELIVERY",
]

DOCUMENT_BLOCKER_CODES: tuple[DocumentBlockerCode, ...] = (
    "MISSING_COMMERCIAL_SNAPSHOT",
    "MISSING_CUSTOMER_NAME",
    "MISSING_CUSTOMER_CONTACT",
    "INVALID_ORDER_STATE",
    "FULFILLMENT_MODE_REQUIRED",
    "DELIVERY_ADDRESS_REQUIRED_FOR_DELIVERY",
)

_BLOCKER_SORT_ORDER: dict[DocumentBlockerCode, int] = {
    code: index for index, code in enumerate(DOCUMENT_BLOCKER_CODES)
}


@dataclass(frozen=True)
class DocumentBlocker:
    """One hard reason a customer document must not be created."""

    code: DocumentBlockerCode
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.code not in DOCUMENT_BLOCKER_CODES:
            raise ValueError(f"unsupported document blocker code: {self.code!r}")
        if self.detail is not None and not self.detail.strip():
            raise ValueError("detail must not be blank when provided")


@dataclass(frozen=True)
class CustomerDocumentEligibility:
    """Pure create decision for a customer-facing document."""

    allowed: bool
    blockers: tuple[DocumentBlocker, ...] = ()

    def __post_init__(self) -> None:
        if self.allowed != (self.blockers == ()):
            raise ValueError("allowed must equal (blockers == ())")


def sort_document_blockers(
    blockers: tuple[DocumentBlocker, ...],
) -> tuple[DocumentBlocker, ...]:
    """Stable deterministic order for tests and API surfaces."""
    return tuple(
        sorted(
            blockers,
            key=lambda item: (_BLOCKER_SORT_ORDER[item.code], item.detail or ""),
        )
    )


class CustomerDocumentCreationBlocked(Exception):
    """Controlled refusal to create a customer document.

    Carries the full eligibility decision so UI/API can show structured
    blocker codes without parsing exception text.
    """

    def __init__(self, eligibility: CustomerDocumentEligibility) -> None:
        if eligibility.allowed or not eligibility.blockers:
            raise ValueError(
                "CustomerDocumentCreationBlocked requires a blocked eligibility"
            )
        self.eligibility = eligibility
        self.blockers = eligibility.blockers
        codes = ", ".join(blocker.code for blocker in eligibility.blockers)
        super().__init__(f"customer document creation blocked: {codes}")

    @property
    def primary_code(self) -> DocumentBlockerCode:
        return self.blockers[0].code

    @property
    def codes(self) -> tuple[DocumentBlockerCode, ...]:
        return tuple(blocker.code for blocker in self.blockers)
