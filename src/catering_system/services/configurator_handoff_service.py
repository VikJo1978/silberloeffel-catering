"""Mint and inspect scoped one-time Configurator handoff codes."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from catering_system.domain.configurator_handoff import (
    ConfiguratorHandoffOperation,
    ConfiguratorHandoffRecord,
    MintedConfiguratorHandoff,
)
from catering_system.repositories.sqlite_configurator_handoff_repository import (
    SQLiteConfiguratorHandoffRepository,
)

HANDOFF_OPERATION_PREPARE_FIRST_OFFER: ConfiguratorHandoffOperation = (
    "prepare_first_offer"
)
HANDOFF_TTL = timedelta(minutes=10)


def handoff_token_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


class ConfiguratorHandoffService:
    def __init__(
        self,
        repository: SQLiteConfiguratorHandoffRepository,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self._now = now or (lambda: datetime.now(UTC))

    def mint_first_offer(
        self,
        *,
        inquiry_id: str,
        issued_for_account_id: str,
    ) -> MintedConfiguratorHandoff:
        issued_at = self._now()
        code = secrets.token_urlsafe(32)
        record = ConfiguratorHandoffRecord(
            id=str(uuid.uuid4()),
            token_hash=handoff_token_hash(code),
            operation=HANDOFF_OPERATION_PREPARE_FIRST_OFFER,
            inquiry_id=inquiry_id,
            issued_for_account_id=issued_for_account_id,
            issued_at=issued_at,
            expires_at=issued_at + HANDOFF_TTL,
            consumed_at=None,
            consumed_by_account_id=None,
        )
        self.repository.add(record)
        return MintedConfiguratorHandoff(code=code, record=record)

    def lookup(self, code: str) -> ConfiguratorHandoffRecord | None:
        return self.repository.get_by_token_hash(handoff_token_hash(code))

    def consume(
        self,
        *,
        record: ConfiguratorHandoffRecord,
        consumed_by_account_id: str,
    ) -> ConfiguratorHandoffRecord:
        consumed_at = self._now()
        if not self.repository.consume(
            handoff_id=record.id,
            consumed_at=consumed_at,
            consumed_by_account_id=consumed_by_account_id,
        ):
            raise RuntimeError("handoff was already consumed")
        return replace(
            record,
            consumed_at=consumed_at,
            consumed_by_account_id=consumed_by_account_id,
        )
