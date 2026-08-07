"""Kitchen completion evidence persistence protocol."""

from __future__ import annotations

from typing import Protocol

from catering_system.domain.kitchen_completion_evidence import KitchenCompletionEvidence


class KitchenCompletionEvidenceRepository(Protocol):
    def get_by_order_version_id(
        self,
        order_id: str,
        order_version_id: str,
    ) -> KitchenCompletionEvidence | None: ...

    def append(self, evidence: KitchenCompletionEvidence) -> None: ...
