"""Repository contract for the KI Telefonassistent inbox."""

from __future__ import annotations

from typing import Protocol

from catering_system.domain.ai_telefon_call import AiTelefonCall


class DuplicateAiTelefonCallError(ValueError):
    pass


class AiTelefonCallRepository(Protocol):
    def get(self, call_id: str) -> AiTelefonCall | None: ...

    def save(self, call: AiTelefonCall) -> None: ...

    def update(self, call: AiTelefonCall) -> None: ...

    def find_by_strato_id(self, strato_id: str) -> AiTelefonCall | None: ...

    def find_by_gmail_message_id(
        self, gmail_message_id: str
    ) -> AiTelefonCall | None: ...

    def list_recent(self, *, limit: int = 100) -> list[AiTelefonCall]: ...

    def count_new(self) -> int: ...
