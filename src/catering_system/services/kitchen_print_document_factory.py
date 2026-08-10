"""Build immutable kitchen print artifacts from kitchen_job projections."""

from __future__ import annotations

from catering_system.domain.kitchen_print_job import KitchenPrintJob
from catering_system.repositories.kitchen_print_document_store import (
    KitchenPrintDocumentStore,
)
from catering_system.services.kitchen_print_document import (
    KitchenPrintDocument,
    build_kitchen_print_document,
)
from catering_system.services.order_print_projection_service import (
    OrderPrintProjectionService,
)


class KitchenPrintDocumentFactory:
    """Resolve kitchen_job projections and persist one artifact per print job."""

    def __init__(
        self,
        projection_service: OrderPrintProjectionService,
        document_store: KitchenPrintDocumentStore,
    ) -> None:
        self._projection_service = projection_service
        self._document_store = document_store

    def create_for_print_job(self, job: KitchenPrintJob) -> KitchenPrintDocument:
        existing = self._document_store.get_by_print_job_id(job.print_job_id)
        if existing is not None:
            return existing
        if job.accepted_at is None:
            raise ValueError("accepted kitchen print job is required")
        projection = self._projection_service.resolve(
            job.order_id,
            job.order_version_id,
            intent="kitchen_job",
        )
        document = build_kitchen_print_document(
            projection,
            job,
            now=job.accepted_at,
        )
        self._document_store.save(document)
        return document
