"""Configurator handoff records for scoped one-time employee exchange."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

ConfiguratorHandoffOperation = Literal["prepare_first_offer"]


@dataclass(frozen=True)
class ConfiguratorHandoffRecord:
    id: str
    token_hash: str
    operation: ConfiguratorHandoffOperation
    inquiry_id: str
    issued_for_account_id: str
    issued_at: datetime
    expires_at: datetime
    consumed_at: datetime | None
    consumed_by_account_id: str | None


@dataclass(frozen=True)
class MintedConfiguratorHandoff:
    code: str
    record: ConfiguratorHandoffRecord
