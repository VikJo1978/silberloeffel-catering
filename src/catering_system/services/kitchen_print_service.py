"""Phase 3 / Slice 3A kitchen print attempt use cases.

This service owns durable attempts and their additive technical/domain facts.
It does not render UI, expose HTTP, talk to a printer, select an effective
version, or change READY_TO_SEND semantics.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from catering_system.domain.kitchen_print_job import (
    KITCHEN_PRINT_REJECTION_CODES,
    KitchenPrintJob,
    KitchenPrintPolicy,
)
from catering_system.domain.operational_core_events import (
    KitchenPrintConfirmed,
    OrderVersionMadeEffective,
)
from catering_system.domain.order import Order, OrderVersion
from catering_system.repositories.kitchen_print_job_repository import (
    KitchenPrintJobRepository,
)
from catering_system.repositories.order_repository import OrderRepository


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class KitchenPrintService:
    def __init__(
        self,
        order_repository: OrderRepository,
        print_job_repository: KitchenPrintJobRepository,
        *,
        policy: KitchenPrintPolicy | None = None,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[], str] = lambda: str(uuid4()),
        event_sink: Callable[[object], None] | None = None,
    ) -> None:
        self._orders = order_repository
        self._jobs = print_job_repository
        self._policy = policy if policy is not None else KitchenPrintPolicy()
        self._clock = clock
        self._id_factory = id_factory
        self._event_sink = event_sink

    def get_print_job(self, print_job_id: str) -> KitchenPrintJob | None:
        return self._jobs.get(print_job_id)

    def claim_next_eligible(self) -> KitchenPrintJob | None:
        """Atomically accept the oldest repository-eligible print attempt.

        Repository eligibility covers only open attempts inside the acceptance
        window. Domain validation (order ownership, cancellation) runs here
        after the atomic claim; a cancelled owner order becomes an explicit
        ``accepted_at`` + ``rejected_at`` fact via ``order_cancelled``.
        """

        now = self._clock()
        job = self._jobs.claim_next_eligible(now, self._policy)
        if job is None:
            return None
        order = self._orders.get_order(job.order_id)
        if order is None:
            raise ValueError(f"no order with id {job.order_id!r}")
        version = self._orders.get_order_version(job.order_version_id)
        if version is None or version.order_id != job.order_id:
            raise ValueError(
                f"order_version_id {job.order_version_id!r} is not a version "
                f"of order {job.order_id!r}"
            )
        if order.cancelled_at is not None:
            self.reject_print_job(job.print_job_id, "order_cancelled")
            return None
        return job

    def list_print_jobs_for_version(
        self, order_version_id: str
    ) -> list[KitchenPrintJob]:
        return self._jobs.list_for_version(order_version_id)

    def is_ack_overdue(self, job: KitchenPrintJob) -> bool:
        return (
            job.accepted_at is not None
            and job.ack_deadline_at is not None
            and job.acknowledged_at is None
            and job.rejected_at is None
            and job.superseded_at is None
            and self._clock() >= job.ack_deadline_at
        )

    def request_print(
        self,
        order_id: str,
        order_version_id: str,
        *,
        print_job_id: str | None = None,
    ) -> KitchenPrintJob:
        """Create the first tracked attempt for one owned OrderVersion."""

        if print_job_id is not None:
            existing = self._jobs.get(print_job_id)
            if existing is not None:
                if (
                    existing.order_id == order_id
                    and existing.order_version_id == order_version_id
                    and existing.attempt_number == 1
                    and existing.supersedes_print_job_id is None
                ):
                    return existing
                raise ValueError("print_job_id already exists with different facts")
        self._active_owned_version(order_id, order_version_id)
        if self._jobs.list_for_version(order_version_id):
            raise ValueError("print attempts already exist; use reprint")
        now = self._clock()
        job = KitchenPrintJob(
            print_job_id=print_job_id or self._id_factory(),
            order_id=order_id,
            order_version_id=order_version_id,
            attempt_number=1,
            requested_at=now,
            accept_deadline_at=now + self._policy.acceptance_timeout,
        )
        self._jobs.save(job)
        return job

    def accept_print_job(self, print_job_id: str) -> KitchenPrintJob:
        """Record technical acceptance; never records domain confirmation."""

        job, _order, _version = self._active_job_context(print_job_id)
        if job.accepted_at is not None:
            return job
        if job.rejected_at is not None:
            raise ValueError("rejected print job cannot be accepted")
        if job.superseded_at is not None:
            raise ValueError("superseded print job cannot be accepted")
        now = self._clock()
        if now >= job.accept_deadline_at:
            raise ValueError("print job acceptance deadline has passed")
        accepted = replace(
            job,
            accepted_at=now,
            ack_deadline_at=now + self._policy.acknowledgment_timeout,
        )
        self._jobs.update(accepted)
        return accepted

    def reject_print_job(
        self, print_job_id: str, rejection_code: str
    ) -> KitchenPrintJob:
        """Record a technical refusal with a narrow, non-PII reason code."""

        job, _order, _version = self._active_job_context(
            print_job_id, allow_cancelled=True
        )
        if rejection_code not in KITCHEN_PRINT_REJECTION_CODES:
            raise ValueError(f"unsupported rejection_code {rejection_code!r}")
        if job.rejected_at is not None:
            if job.rejection_code == rejection_code:
                return job
            raise ValueError("print job already has a different rejection fact")
        if job.acknowledged_at is not None:
            raise ValueError("confirmed print job cannot be rejected")
        if job.superseded_at is not None:
            raise ValueError("superseded print job cannot be rejected")
        rejected = replace(
            job,
            rejected_at=self._clock(),
            rejection_code=rejection_code,
        )
        self._jobs.update(rejected)
        return rejected

    def acknowledge_print_job(
        self, print_job_id: str
    ) -> tuple[KitchenPrintJob, OrderVersion]:
        """Atomically acknowledge one attempt and confirm its OrderVersion.

        ACK after the configured deadline is deliberately allowed: lateness is
        a derived attention state, not an expiry of the real confirmation.
        Repeated ACK returns the original facts without re-stamping or emitting
        a duplicate KitchenPrintConfirmed event.
        """

        job, order, version = self._active_job_context(print_job_id)
        if job.acknowledged_at is not None:
            stored_version = self._orders.get_order_version(job.order_version_id)
            assert stored_version is not None
            return job, stored_version
        if job.accepted_at is None:
            raise ValueError("print job must be technically accepted before ACK")
        if job.rejected_at is not None:
            raise ValueError("rejected print job cannot be acknowledged")
        if job.superseded_at is not None:
            raise ValueError("superseded print job cannot be acknowledged")

        now = self._clock()
        assert job.ack_deadline_at is not None
        if now >= job.ack_deadline_at:
            raise ValueError("print job ACK deadline has passed")
        acknowledged = replace(job, acknowledged_at=now)
        confirmation_was_new = version.kitchen_print_confirmed_at is None
        confirmed_version = (
            replace(version, kitchen_print_confirmed_at=now)
            if confirmation_was_new
            else version
        )
        activated_order = self._activation_after_successful_print(order, version, now)
        activation_applied = self._jobs.acknowledge_and_confirm(
            acknowledged,
            confirmed_version,
            expected_order=order,
            activated_order=activated_order,
        )
        if confirmation_was_new and self._event_sink is not None:
            self._event_sink(
                KitchenPrintConfirmed(
                    order_id=job.order_id,
                    order_version_id=job.order_version_id,
                )
            )
        if activation_applied and self._event_sink is not None:
            self._event_sink(
                OrderVersionMadeEffective(
                    order_id=job.order_id,
                    order_version_id=job.order_version_id,
                )
            )
        return acknowledged, confirmed_version

    @staticmethod
    def _activation_after_successful_print(
        order: Order, version: OrderVersion, now: datetime
    ) -> Order | None:
        if order.cancelled_at is not None:
            return None
        if order.candidate_order_version_id == version.order_version_id:
            return replace(
                order,
                effective_order_version_id=version.order_version_id,
                candidate_order_version_id=None,
                updated_at=now,
            )
        if (
            order.effective_order_version_id is None
            and order.candidate_order_version_id is None
            and version.version_number == 1
            and version.parent_order_version_id is None
        ):
            return replace(
                order,
                effective_order_version_id=version.order_version_id,
                updated_at=now,
            )
        return None

    def reprint(
        self,
        previous_print_job_id: str,
        *,
        new_print_job_id: str | None = None,
    ) -> KitchenPrintJob:
        """Create a new attempt and add supersession to a prior live attempt."""

        if new_print_job_id is not None:
            existing = self._jobs.get(new_print_job_id)
            retry_previous = self._jobs.get(previous_print_job_id)
            if existing is not None:
                if (
                    retry_previous is not None
                    and existing.order_id == retry_previous.order_id
                    and existing.order_version_id == retry_previous.order_version_id
                    and existing.attempt_number == retry_previous.attempt_number + 1
                    and existing.supersedes_print_job_id == previous_print_job_id
                ):
                    return existing
                raise ValueError("new_print_job_id already exists with different facts")
        previous, _order, _version = self._active_job_context(previous_print_job_id)
        attempts = self._jobs.list_for_version(previous.order_version_id)
        if not attempts or attempts[-1].print_job_id != previous.print_job_id:
            raise ValueError("reprint must name the latest print attempt")
        now = self._clock()
        previous_is_live = (
            previous.acknowledged_at is None
            and previous.rejected_at is None
            and previous.superseded_at is None
        )
        updated_previous = (
            replace(previous, superseded_at=now) if previous_is_live else None
        )
        new_job = KitchenPrintJob(
            print_job_id=new_print_job_id or self._id_factory(),
            order_id=previous.order_id,
            order_version_id=previous.order_version_id,
            attempt_number=previous.attempt_number + 1,
            requested_at=now,
            accept_deadline_at=now + self._policy.acceptance_timeout,
            supersedes_print_job_id=previous.print_job_id,
        )
        self._jobs.save_reprint(previous, updated_previous, new_job)
        return new_job

    def _active_job_context(
        self, print_job_id: str, *, allow_cancelled: bool = False
    ) -> tuple[KitchenPrintJob, Order, OrderVersion]:
        job = self._jobs.get(print_job_id)
        if job is None:
            raise ValueError(f"no print job with id {print_job_id!r}")
        order, version = self._active_owned_version(
            job.order_id, job.order_version_id, allow_cancelled=allow_cancelled
        )
        return job, order, version

    def _active_owned_version(
        self, order_id: str, order_version_id: str, *, allow_cancelled: bool = False
    ) -> tuple[Order, OrderVersion]:
        order = self._orders.get_order(order_id)
        if order is None:
            raise ValueError(f"no order with id {order_id!r}")
        if not allow_cancelled and order.cancelled_at is not None:
            raise ValueError(
                f"order {order_id!r} is cancelled (Storno); print commands refused"
            )
        version = self._orders.get_order_version(order_version_id)
        if version is None or version.order_id != order_id:
            raise ValueError(
                f"order_version_id {order_version_id!r} is not a version "
                f"of order {order_id!r}"
            )
        return order, version
