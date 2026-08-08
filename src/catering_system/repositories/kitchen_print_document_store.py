"""Persistence protocol for immutable kitchen print artifacts."""

from __future__ import annotations

from typing import Protocol

from catering_system.services.kitchen_print_document import KitchenPrintDocument


class KitchenPrintDocumentStore(Protocol):
    def get(self, document_ref: str) -> KitchenPrintDocument | None: ...

    def get_by_print_job_id(self, print_job_id: str) -> KitchenPrintDocument | None: ...

    def save(self, document: KitchenPrintDocument) -> None: ...
