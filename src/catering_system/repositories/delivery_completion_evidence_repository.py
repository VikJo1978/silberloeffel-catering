"""Delivery completion evidence persistence protocol."""

from __future__ import annotations

from typing import Protocol

from catering_system.domain.delivery_completion_evidence import DeliveryCompletionEvidence


class DeliveryCompletionEvidenceRepository(Protocol):
    def get_by_order_version_id(
        self,
        order_id: str,
        order_version_id: str,
    ) -> DeliveryCompletionEvidence | None: ...

    def append(self, evidence: DeliveryCompletionEvidence) -> None: ...
