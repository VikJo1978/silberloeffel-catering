"""In-memory persistence for immutable kitchen print artifacts."""

from __future__ import annotations

from catering_system.services.kitchen_print_document import KitchenPrintDocument


class InMemoryKitchenPrintDocumentStore:
    def __init__(self) -> None:
        self._by_ref: dict[str, KitchenPrintDocument] = {}
        self._ref_by_job: dict[str, str] = {}

    def get(self, document_ref: str) -> KitchenPrintDocument | None:
        return self._by_ref.get(document_ref)

    def get_by_print_job_id(self, print_job_id: str) -> KitchenPrintDocument | None:
        document_ref = self._ref_by_job.get(print_job_id)
        if document_ref is None:
            return None
        return self._by_ref.get(document_ref)

    def save(self, document: KitchenPrintDocument) -> KitchenPrintDocument:
        existing_job_ref = self._ref_by_job.get(document.print_job_id)
        if existing_job_ref is not None:
            existing = self._by_ref[existing_job_ref]
            if existing != document:
                raise ValueError("print_job_id already has a different document")
            return existing
        if document.document_ref in self._by_ref:
            existing = self._by_ref[document.document_ref]
            if existing != document:
                raise ValueError("document_ref conflict")
            return existing
        self._by_ref[document.document_ref] = document
        self._ref_by_job[document.print_job_id] = document.document_ref
        return document
