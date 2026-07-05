"""Operational core domain events — OPERATIONAL_CORE_EXECUTION_PACK_V1 §6.2 (no bus)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KitchenPrintConfirmed:
    order_id: str
    order_version_id: str


@dataclass(frozen=True)
class OrderVersionMadeEffective:
    order_id: str
    order_version_id: str


@dataclass(frozen=True)
class OrderReadyToSend:
    order_id: str


@dataclass(frozen=True)
class OrderReadyToSendBlocked:
    order_id: str
    reasons: tuple[str, ...]
