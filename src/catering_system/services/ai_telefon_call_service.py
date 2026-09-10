"""Application service for STRATO AI telephone calls before they become CRM facts."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Callable

from catering_system.domain.ai_telefon_call import (
    AiTelefonCall,
    validate_ai_telefon_call,
)
from catering_system.repositories.ai_telefon_call_repository import (
    AiTelefonCallRepository,
    DuplicateAiTelefonCallError,
)
from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.services.inquiry_service import InquiryService
from catering_system.services.manual_task_service import ManualTaskService

Clock = Callable[[], datetime]
IdFactory = Callable[[], str]


class AiTelefonCallCannotConvert(ValueError):
    pass


class AiTelefonCallService:
    def __init__(
        self,
        repository: AiTelefonCallRepository,
        *,
        inquiry_repository: InquiryRepository | None = None,
        inquiry_service: InquiryService | None = None,
        manual_task_service: ManualTaskService | None = None,
        now: Clock | None = None,
        id_factory: IdFactory | None = None,
    ) -> None:
        self._repository = repository
        self._inquiry_repository = inquiry_repository
        self._inquiry_service = inquiry_service
        self._manual_task_service = manual_task_service
        self._now = now or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))

    def ingest(
        self,
        *,
        strato_id: str,
        gmail_message_id: str,
        caller_phone: str,
        contact_name: str,
        email: str,
        subject: str,
        summary: str,
        raw_message: str,
        event_type: str = "",
        event_date=None,
        event_period: str = "",
        event_start=None,
        guest_count: int | None = None,
        location: str = "",
        budget_per_person_cents: int | None = None,
        fulfillment_mode: str = "UNKNOWN",
        customer_request: str = "",
        callback_requested: bool | None = None,
        callback_date=None,
        callback_time=None,
        received_at: datetime | None = None,
    ) -> AiTelefonCall:
        existing = self._repository.find_by_strato_id(strato_id)
        if existing is not None:
            return existing
        existing = self._repository.find_by_gmail_message_id(gmail_message_id)
        if existing is not None:
            return existing

        now = self._now()
        call = validate_ai_telefon_call(
            AiTelefonCall(
                call_id=self._id_factory(),
                strato_id=strato_id,
                gmail_message_id=gmail_message_id,
                caller_phone=caller_phone,
                contact_name=contact_name,
                email=email,
                subject=subject,
                summary=summary,
                raw_message=raw_message,
                event_type=event_type,
                event_date=event_date,
                event_period=event_period,
                event_start=event_start,
                guest_count=guest_count,
                location=location,
                budget_per_person_cents=budget_per_person_cents,
                fulfillment_mode=fulfillment_mode,  # type: ignore[arg-type]
                customer_request=customer_request,
                callback_requested=callback_requested,
                callback_date=callback_date,
                callback_time=callback_time,
                received_at=received_at or now,
                updated_at=now,
            )
        )
        try:
            self._repository.save(call)
        except DuplicateAiTelefonCallError:
            replay = self._repository.find_by_strato_id(strato_id)
            if replay is None:
                replay = self._repository.find_by_gmail_message_id(gmail_message_id)
            if replay is None:
                raise
            return replay
        return call

    def get(self, call_id: str) -> AiTelefonCall | None:
        return self._repository.get(call_id)

    def list_recent(self, *, limit: int = 100) -> list[AiTelefonCall]:
        return self._repository.list_recent(limit=limit)

    def count_new(self) -> int:
        return self._repository.count_new()

    def mark_done(self, call_id: str) -> AiTelefonCall:
        current = self._require_call(call_id)
        if current.status == "DONE":
            return current
        updated = validate_ai_telefon_call(
            replace(current, status="DONE", updated_at=self._now())
        )
        self._repository.update(updated)
        return updated

    def convert_to_inquiry(self, call_id: str) -> AiTelefonCall:
        current = self._require_call(call_id)
        if current.result_type == "INQUIRY" and current.result_id is not None:
            return current
        if self._inquiry_service is None or self._inquiry_repository is None:
            raise AiTelefonCallCannotConvert("inquiry conversion is not configured")
        if current.event_date is None:
            raise AiTelefonCallCannotConvert("event_date_required")
        if not current.contact_name:
            raise AiTelefonCallCannotConvert("contact_name_required")
        if not current.caller_phone:
            raise AiTelefonCallCannotConvert("phone_required")

        existing = self._inquiry_repository.find_by_source_and_external_ref(
            "ai_telefonist", current.strato_id
        )
        if existing is None:
            message_lines = [current.summary]
            if current.event_period:
                message_lines.append(f"Zeitraum: {current.event_period}")
            if current.budget_per_person_cents is not None:
                budget = current.budget_per_person_cents / 100
                message_lines.append(f"Budget: {budget:.2f} EUR pro Person")
            if current.customer_request:
                message_lines.append(f"Wünsche: {current.customer_request}")
            if current.callback_requested:
                callback = "Rückruf gewünscht"
                if current.callback_date:
                    callback += f" am {current.callback_date.isoformat()}"
                if current.callback_time:
                    callback += f" um {current.callback_time.strftime('%H:%M')}"
                message_lines.append(callback)

            inquiry = self._inquiry_service.create_inquiry(
                event_date=current.event_date,
                inquiry_source="ai_telefonist",
                crm_stage="Neue Anfrage",
                customer_linkage={},
                time_window_text=(
                    f"ab {current.event_start.strftime('%H:%M')} Uhr"
                    if current.event_start
                    else ""
                ),
                location_text=current.location,
                guest_count_estimate=current.guest_count,
                planning_mode="caterer_suggestion",
                call_verification_required=True,
                call_verification_status="pending",
                intake_subject=current.subject or current.contact_name,
                intake_message="\n".join(message_lines),
                intake_summary=current.summary,
                intake_external_ref=current.strato_id,
                contact_email=current.email or None,
                contact_phone=current.caller_phone,
                contact_name=current.contact_name,
                fulfillment_mode=current.fulfillment_mode,
                event_start_local=current.event_start,
            )
        else:
            inquiry = existing

        now = self._now()
        updated = validate_ai_telefon_call(
            replace(
                current,
                status="PROCESSED",
                result_type="INQUIRY",
                result_id=inquiry.inquiry_id,
                processed_at=current.processed_at or now,
                updated_at=now,
            )
        )
        self._repository.update(updated)
        return updated

    def convert_to_task(
        self,
        call_id: str,
        *,
        created_by_employee_id: str,
        assigned_to_employee_id: str | None = None,
    ) -> AiTelefonCall:
        current = self._require_call(call_id)
        if current.result_type == "TASK" and current.result_id is not None:
            return current
        if self._manual_task_service is None:
            raise AiTelefonCallCannotConvert("task conversion is not configured")

        title = (
            current.subject
            or f"Telefonanruf: {current.contact_name or current.caller_phone}"
        )
        description_lines = [current.summary]
        if current.caller_phone:
            description_lines.append(f"Telefon: {current.caller_phone}")
        if current.strato_id:
            description_lines.append(f"STRATO-ID: {current.strato_id}")
        task = self._manual_task_service.create_task(
            title=title,
            description="\n\n".join(description_lines),
            created_by_employee_id=created_by_employee_id,
            assigned_to_employee_id=assigned_to_employee_id,
            subject_type="NONE",
            subject_id=None,
            priority="NORMAL",
        )
        now = self._now()
        updated = validate_ai_telefon_call(
            replace(
                current,
                status="PROCESSED",
                result_type="TASK",
                result_id=task.task_id,
                processed_at=current.processed_at or now,
                updated_at=now,
            )
        )
        self._repository.update(updated)
        return updated

    def link_existing(
        self,
        call_id: str,
        *,
        linked_type: str,
        linked_id: str,
    ) -> AiTelefonCall:
        current = self._require_call(call_id)
        now = self._now()
        updated = validate_ai_telefon_call(
            replace(
                current,
                status="PROCESSED",
                result_type="LINKED",
                result_id=linked_id,
                linked_type=linked_type,  # type: ignore[arg-type]
                linked_id=linked_id,
                processed_at=current.processed_at or now,
                updated_at=now,
            )
        )
        self._repository.update(updated)
        return updated

    def _require_call(self, call_id: str) -> AiTelefonCall:
        call = self._repository.get(call_id)
        if call is None:
            raise KeyError(call_id)
        return call
