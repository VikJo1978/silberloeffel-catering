"""In-memory dispatch evidence for tests."""

from __future__ import annotations

from catering_system.domain.dispatch_evidence import DispatchEvidence


class InMemoryDispatchEvidenceRepository:
    def __init__(self) -> None:
        self._by_version: dict[tuple[str, str], DispatchEvidence] = {}

    def get_by_order_version_id(
        self,
        order_id: str,
        order_version_id: str,
    ) -> DispatchEvidence | None:
        return self._by_version.get((order_id, order_version_id))

    def append(self, evidence: DispatchEvidence) -> None:
        key = (evidence.order_id, evidence.order_version_id)
        existing = self._by_version.get(key)
        if existing is not None:
            if existing != evidence:
                raise ValueError("dispatch evidence conflict")
            return
        self._by_version[key] = evidence
