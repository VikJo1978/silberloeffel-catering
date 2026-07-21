"""Repository contract for immutable contact profiles and aliases."""

from __future__ import annotations

from typing import Protocol

from catering_system.domain.contact_profile import (
    ContactProfile,
    ContactProfileAlias,
    ContactProfileAliasType,
)


class ContactProfileRepository(Protocol):
    def create_profile(self, profile: ContactProfile) -> None: ...

    def get_profile(self, contact_profile_id: str) -> ContactProfile | None: ...

    def update_profile_fields(self, profile: ContactProfile) -> None: ...

    def mark_merged(self, contact_profile_id: str, *, merged_into_id: str) -> None: ...

    def list_merged_into(self, contact_profile_id: str) -> list[str]: ...

    def find_profile_id_by_alias(
        self, alias_type: ContactProfileAliasType, alias_value: str
    ) -> str | None: ...

    def upsert_alias(self, alias: ContactProfileAlias) -> None: ...

    def search_profile_ids(self, q: str) -> list[str]: ...
