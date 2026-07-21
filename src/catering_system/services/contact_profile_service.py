"""Ensure and resolve immutable contact profiles from inquiry aliases."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from catering_system.domain.contact_profile import (
    ContactProfile,
    ContactProfileAlias,
    ContactProfileAliasType,
    collect_inquiry_aliases,
)
from catering_system.domain.contact_projection import ContactProjection
from catering_system.domain.inquiry import Inquiry
from catering_system.intake.intake_contact import parse_intake_contact
from catering_system.repositories.contact_profile_repository import (
    ContactProfileRepository,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ContactProfileService:
    def __init__(self, repository: ContactProfileRepository) -> None:
        self._repository = repository

    def resolve_root_profile_id(self, contact_profile_id: str) -> str:
        current_id = contact_profile_id
        seen: set[str] = set()
        while current_id not in seen:
            seen.add(current_id)
            profile = self._repository.get_profile(current_id)
            if profile is None:
                return current_id
            if profile.merged_into_id is None:
                return current_id
            current_id = profile.merged_into_id
        return current_id

    def profile_ids_for_notes(self, contact_profile_id: str) -> list[str]:
        root = self.resolve_root_profile_id(contact_profile_id)
        merged = self._repository.list_merged_into(root)
        # nested merges: one level is enough for V1; also include root
        ids = [root, *merged]
        extra: list[str] = []
        for profile_id in merged:
            extra.extend(self._repository.list_merged_into(profile_id))
        return list(dict.fromkeys([*ids, *extra]))

    def find_by_alias(
        self, alias_type: ContactProfileAliasType, alias_value: str
    ) -> str | None:
        profile_id = self._repository.find_profile_id_by_alias(alias_type, alias_value)
        if profile_id is None:
            return None
        return self.resolve_root_profile_id(profile_id)

    def ensure_for_inquiry(self, inquiry: Inquiry) -> str:
        aliases = collect_inquiry_aliases(inquiry)
        parsed = parse_intake_contact(inquiry)
        display_name = parsed["display_name"] or inquiry.intake_subject or "–"
        return self._ensure(
            aliases,
            display_name=str(display_name),
            email=parsed["email"],
            phone=parsed["phone"],
        )

    def ensure_for_projection(self, projection: ContactProjection) -> str:
        aliases: list[tuple[ContactProfileAliasType, str]] = [
            ("contact_key", projection.contact_key)
        ]
        if projection.email:
            aliases.append(("email", projection.email))
        if projection.phone:
            aliases.append(("phone", projection.phone))
        if projection.identity_source == "linkage_contact":
            aliases.append(
                (
                    "linkage_contact",
                    projection.contact_key.removeprefix("linkage:contact:"),
                )
            )
        elif projection.identity_source == "linkage_customer":
            aliases.append(
                (
                    "linkage_customer",
                    projection.contact_key.removeprefix("linkage:customer:"),
                )
            )
        for inquiry_id in projection.inquiry_ids:
            aliases.append(("inquiry", inquiry_id))
        return self._ensure(
            aliases,
            display_name=projection.display_name,
            email=projection.email,
            phone=projection.phone,
        )

    def search_profile_ids(self, q: str) -> list[str]:
        return [
            self.resolve_root_profile_id(profile_id)
            for profile_id in self._repository.search_profile_ids(q)
        ]

    def bind_contact_key(self, contact_key: str, contact_profile_id: str) -> None:
        root = self.resolve_root_profile_id(contact_profile_id)
        self._repository.upsert_alias(
            ContactProfileAlias(
                alias_type="contact_key",
                alias_value=contact_key,
                contact_profile_id=root,
            )
        )

    def _ensure(
        self,
        aliases: list[tuple[ContactProfileAliasType, str]],
        *,
        display_name: str,
        email: str | None,
        phone: str | None,
    ) -> str:
        found_roots: list[str] = []
        for alias_type, alias_value in aliases:
            profile_id = self._repository.find_profile_id_by_alias(
                alias_type, alias_value
            )
            if profile_id is None:
                continue
            root = self.resolve_root_profile_id(profile_id)
            if root not in found_roots:
                found_roots.append(root)

        now = _utc_now()
        if not found_roots:
            profile_id = str(uuid.uuid4())
            self._repository.create_profile(
                ContactProfile(
                    contact_profile_id=profile_id,
                    display_name=display_name or "–",
                    email=email,
                    phone=phone,
                    created_at=now,
                    updated_at=now,
                )
            )
            root = profile_id
        else:
            root = self._merge_roots(found_roots)
            current = self._repository.get_profile(root)
            if current is None:
                raise KeyError(root)
            self._repository.update_profile_fields(
                ContactProfile(
                    contact_profile_id=root,
                    display_name=display_name or current.display_name,
                    email=email or current.email,
                    phone=phone or current.phone,
                    created_at=current.created_at,
                    updated_at=now,
                    merged_into_id=None,
                )
            )

        for alias_type, alias_value in aliases:
            self._repository.upsert_alias(
                ContactProfileAlias(
                    alias_type=alias_type,
                    alias_value=alias_value,
                    contact_profile_id=root,
                )
            )
        return root

    def _merge_roots(self, roots: list[str]) -> str:
        if len(roots) == 1:
            return roots[0]
        profiles = []
        for profile_id in roots:
            profile = self._repository.get_profile(profile_id)
            if profile is None:
                continue
            profiles.append(profile)
        profiles.sort(key=lambda item: (item.created_at, item.contact_profile_id))
        winner = profiles[0].contact_profile_id
        for profile in profiles[1:]:
            if profile.contact_profile_id == winner:
                continue
            self._repository.mark_merged(
                profile.contact_profile_id, merged_into_id=winner
            )
        return winner
