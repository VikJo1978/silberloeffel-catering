"""Dispatch evidence persistence protocol."""

from __future__ import annotations

from typing import Protocol

from catering_system.domain.dispatch_evidence import DispatchEvidence


class DispatchEvidenceRepository(Protocol):
    def get_by_order_version_id(
        self,
        order_id: str,
        order_version_id: str,
    ) -> DispatchEvidence | None: ...

    def append(self, evidence: DispatchEvidence) -> None: ...
