"""Operational core domain events — OPERATIONAL_CORE_EXECUTION_PACK_V1 §6.2 (no bus)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class KitchenPrintConfirmed:
    order_id: str
    order_version_id: str


@dataclass(frozen=True)
class OrderVersionMadeEffective:
    order_id: str
    order_version_id: str


@dataclass(frozen=True)
class OrderVersionChangeProposed:
    order_id: str
    old_effective_order_version_id: str | None
    new_candidate_order_version_id: str
    actor_reference: str
    change_reason: str
    changed_fields: tuple[str, ...]
    occurred_at: datetime


@dataclass(frozen=True)
class OrderVersionCandidateSuperseded:
    order_id: str
    superseded_order_version_id: str
    new_candidate_order_version_id: str
    occurred_at: datetime


@dataclass(frozen=True)
class OrderReadyToSend:
    order_id: str


@dataclass(frozen=True)
class OrderReadyToSendBlocked:
    order_id: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class OrderCancelled:
    """STORNO_EXECUTION_PACK_V1 §2."""

    order_id: str
