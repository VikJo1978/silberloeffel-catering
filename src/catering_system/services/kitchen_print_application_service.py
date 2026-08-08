"""Kitchen print agent application orchestration (Phase 3B transport boundary)."""

from __future__ import annotations

from dataclasses import dataclass

from catering_system.domain.kitchen_print_job import KitchenPrintJob
from catering_system.services.kitchen_print_document import KitchenPrintDocument
from catering_system.services.kitchen_print_document_factory import (
    KitchenPrintDocumentFactory,
)
from catering_system.services.kitchen_print_service import KitchenPrintService


@dataclass(frozen=True)
class KitchenClaimResult:
    job: KitchenPrintJob
    document: KitchenPrintDocument


class KitchenPrintApplicationService:
    """Domain orchestration for agent transport — no HTTP or ledger concerns."""

    def __init__(
        self,
        print_service: KitchenPrintService,
        document_factory: KitchenPrintDocumentFactory,
    ) -> None:
        self._print_service = print_service
        self._document_factory = document_factory

    def claim_next_with_document(self) -> KitchenClaimResult | None:
        job = self._print_service.claim_next_eligible()
        if job is None:
            return None
        document = self._document_factory.create_for_print_job(job)
        return KitchenClaimResult(job=job, document=document)

    def reject_print_job(
        self, print_job_id: str, rejection_code: str
    ) -> KitchenPrintJob:
        return self._print_service.reject_print_job(print_job_id, rejection_code)
