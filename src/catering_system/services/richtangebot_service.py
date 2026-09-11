"""Application service for non-binding Richtangebote created from KI calls."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Callable

from catering_system.domain.ai_telefon_call import AiTelefonCall
from catering_system.domain.richtangebot import Richtangebot, validate_richtangebot
from catering_system.repositories.richtangebot_repository import RichtangebotRepository

Clock = Callable[[], datetime]
IdFactory = Callable[[], str]


class RichtangebotCannotCreate(ValueError):
    pass


class RichtangebotService:
    def __init__(
        self,
        repository: RichtangebotRepository,
        *,
        now: Clock | None = None,
        id_factory: IdFactory | None = None,
    ) -> None:
        self._repository = repository
        self._now = now or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))

    def get(self, richtangebot_id: str) -> Richtangebot | None:
        return self._repository.get(richtangebot_id)

    def list_recent(self, *, limit: int = 100) -> list[Richtangebot]:
        return self._repository.list_recent(limit=limit)

    def create_from_call(self, call: AiTelefonCall) -> Richtangebot:
        existing = self._repository.find_by_source_call_id(call.call_id)
        if existing is not None:
            return existing
        if not can_create_richtangebot(call):
            raise RichtangebotCannotCreate("call_has_insufficient_commercial_context")

        now = self._now()
        event_time_text = call.event_time_text
        if not event_time_text and call.event_start is None:
            event_time_text = "noch offen"

        value = validate_richtangebot(
            Richtangebot(
                richtangebot_id=self._id_factory(),
                source_call_id=call.call_id,
                created_at=now,
                updated_at=now,
                contact_name=call.contact_name,
                caller_phone=call.caller_phone,
                email=call.email,
                event_type=call.event_type,
                event_date=call.event_date,
                event_date_text=call.event_period if call.event_date is None else "",
                event_start=call.event_start,
                event_time_text=event_time_text,
                guest_count=call.guest_count,
                guest_count_min=call.guest_count_min,
                guest_count_max=call.guest_count_max,
                location=call.location,
                budget_per_person_cents=call.budget_per_person_cents,
                customer_request=call.customer_request,
            )
        )
        self._repository.save(value)
        return value


def can_create_richtangebot(call: AiTelefonCall) -> bool:
    if not (call.contact_name or call.caller_phone or call.email):
        return False
    return bool(
        call.event_type
        or call.event_date
        or call.event_period
        or call.event_start
        or call.event_time_text
        or call.guest_count
        or call.guest_count_min
        or call.guest_count_max
        or call.location
        or call.budget_per_person_cents is not None
        or call.customer_request
    )
