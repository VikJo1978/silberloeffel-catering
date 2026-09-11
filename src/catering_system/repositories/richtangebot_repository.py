"""Repository contract for preliminary Richtangebote."""

from __future__ import annotations

from typing import Protocol

from catering_system.domain.richtangebot import Richtangebot


class RichtangebotRepository(Protocol):
    def get(self, richtangebot_id: str) -> Richtangebot | None: ...

    def find_by_source_call_id(self, source_call_id: str) -> Richtangebot | None: ...

    def save(self, value: Richtangebot) -> None: ...

    def update(self, value: Richtangebot) -> None: ...

    def list_recent(self, *, limit: int = 100) -> list[Richtangebot]: ...
