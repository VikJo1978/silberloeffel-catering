"""In-memory delivery completion evidence for tests."""

from __future__ import annotations

from catering_system.domain.delivery_completion_evidence import DeliveryCompletionEvidence


class InMemoryDeliveryCompletionEvidenceRepository:
    def __init__(self) -> None:
        self._by_version: dict[tuple[str, str], DeliveryCompletionEvidence] = {}

    def get_by_order_version_id(
        self,
        order_id: str,
        order_version_id: str,
    ) -> DeliveryCompletionEvidence | None:
        return self._by_version.get((order_id, order_version_id))

    def append(self, evidence: DeliveryCompletionEvidence) -> None:
        key = (evidence.order_id, evidence.order_version_id)
        existing = self._by_version.get(key)
        if existing is not None:
            if existing != evidence:
                raise ValueError("delivery completion evidence conflict")
            return
        self._by_version[key] = evidence
