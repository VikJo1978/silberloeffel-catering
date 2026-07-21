"""In-memory contact profiles — tests and direct-mode fallback."""

from __future__ import annotations

from catering_system.domain.contact_profile import (
    ContactProfile,
    ContactProfileAlias,
    ContactProfileAliasType,
)
from catering_system.intake.intake_contact import normalize_phone


class InMemoryContactProfileRepository:
    def __init__(self) -> None:
        self._profiles: dict[str, ContactProfile] = {}
        self._aliases: dict[tuple[str, str], str] = {}

    def create_profile(self, profile: ContactProfile) -> None:
        if profile.contact_profile_id in self._profiles:
            raise KeyError(profile.contact_profile_id)
        self._profiles[profile.contact_profile_id] = profile

    def get_profile(self, contact_profile_id: str) -> ContactProfile | None:
        return self._profiles.get(contact_profile_id)

    def update_profile_fields(self, profile: ContactProfile) -> None:
        current = self._profiles[profile.contact_profile_id]
        self._profiles[profile.contact_profile_id] = ContactProfile(
            contact_profile_id=current.contact_profile_id,
            display_name=profile.display_name,
            email=profile.email,
            phone=profile.phone,
            created_at=current.created_at,
            updated_at=profile.updated_at,
            merged_into_id=current.merged_into_id,
        )

    def mark_merged(self, contact_profile_id: str, *, merged_into_id: str) -> None:
        current = self._profiles[contact_profile_id]
        self._profiles[contact_profile_id] = ContactProfile(
            contact_profile_id=current.contact_profile_id,
            display_name=current.display_name,
            email=current.email,
            phone=current.phone,
            created_at=current.created_at,
            updated_at=current.updated_at,
            merged_into_id=merged_into_id,
        )

    def list_merged_into(self, contact_profile_id: str) -> list[str]:
        return [
            profile_id
            for profile_id, profile in self._profiles.items()
            if profile.merged_into_id == contact_profile_id
        ]

    def find_profile_id_by_alias(
        self, alias_type: ContactProfileAliasType, alias_value: str
    ) -> str | None:
        return self._aliases.get((alias_type, alias_value))

    def upsert_alias(self, alias: ContactProfileAlias) -> None:
        self._aliases[(alias.alias_type, alias.alias_value)] = alias.contact_profile_id

    def search_profile_ids(self, q: str) -> list[str]:
        needle = q.strip().casefold()
        if not needle:
            return [
                profile_id
                for profile_id, profile in self._profiles.items()
                if profile.merged_into_id is None
            ]
        phone = normalize_phone(q)
        matches: list[str] = []
        for profile_id, profile in self._profiles.items():
            if profile.merged_into_id is not None:
                continue
            name = profile.display_name.casefold()
            email = (profile.email or "").casefold()
            profile_phone = profile.phone or ""
            if (
                needle in name
                or needle in email
                or needle in profile_phone.casefold()
                or (phone and phone == profile_phone)
            ):
                matches.append(profile_id)
        return matches
