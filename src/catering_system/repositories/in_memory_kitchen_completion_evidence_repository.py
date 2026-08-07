"""In-memory kitchen completion evidence for tests."""

from __future__ import annotations

from catering_system.domain.kitchen_completion_evidence import KitchenCompletionEvidence


class InMemoryKitchenCompletionEvidenceRepository:
    def __init__(self) -> None:
        self._by_version: dict[tuple[str, str], KitchenCompletionEvidence] = {}

    def get_by_order_version_id(
        self,
        order_id: str,
        order_version_id: str,
    ) -> KitchenCompletionEvidence | None:
        return self._by_version.get((order_id, order_version_id))

    def append(self, evidence: KitchenCompletionEvidence) -> None:
        key = (evidence.order_id, evidence.order_version_id)
        existing = self._by_version.get(key)
        if existing is not None:
            if existing != evidence:
                raise ValueError("kitchen completion evidence conflict")
            return
        self._by_version[key] = evidence
