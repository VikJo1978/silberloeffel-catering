"""In-memory persistence for Phase 3 kitchen print attempt facts."""

from __future__ import annotations

from dataclasses import replace

from catering_system.domain.kitchen_print_job import (
    KitchenPrintJob,
    validate_kitchen_print_job_transition,
)
from catering_system.domain.order import OrderVersion
from catering_system.repositories.order_repository import OrderRepository


class InMemoryKitchenPrintJobRepository:
    def __init__(self, order_repository: OrderRepository) -> None:
        self._orders = order_repository
        self._jobs: dict[str, KitchenPrintJob] = {}

    def save(self, job: KitchenPrintJob) -> None:
        self._validate_new_job(job)
        next_jobs = dict(self._jobs)
        next_jobs[job.print_job_id] = job
        self._jobs = next_jobs

    def get(self, print_job_id: str) -> KitchenPrintJob | None:
        return self._jobs.get(print_job_id)

    def list_for_version(self, order_version_id: str) -> list[KitchenPrintJob]:
        return sorted(
            (
                job
                for job in self._jobs.values()
                if job.order_version_id == order_version_id
            ),
            key=lambda job: job.attempt_number,
        )

    def list_for_order(self, order_id: str) -> list[KitchenPrintJob]:
        return sorted(
            (job for job in self._jobs.values() if job.order_id == order_id),
            key=lambda job: (job.order_version_id, job.attempt_number),
        )

    def update(self, job: KitchenPrintJob) -> None:
        previous = self._jobs.get(job.print_job_id)
        if previous is None:
            raise KeyError(job.print_job_id)
        validate_kitchen_print_job_transition(previous, job)
        next_jobs = dict(self._jobs)
        next_jobs[job.print_job_id] = job
        self._jobs = next_jobs

    def save_reprint(
        self,
        previous: KitchenPrintJob,
        updated_previous: KitchenPrintJob | None,
        new_job: KitchenPrintJob,
    ) -> None:
        stored = self._jobs.get(previous.print_job_id)
        if stored != previous:
            raise ValueError("stale previous print job")
        if updated_previous is not None:
            validate_kitchen_print_job_transition(previous, updated_previous)
        self._validate_new_job(
            new_job,
            replacing=previous.print_job_id if updated_previous is not None else None,
        )
        if new_job.supersedes_print_job_id != previous.print_job_id:
            raise ValueError("reprint must reference the previous print job")
        next_jobs = dict(self._jobs)
        if updated_previous is not None:
            next_jobs[previous.print_job_id] = updated_previous
        next_jobs[new_job.print_job_id] = new_job
        self._jobs = next_jobs

    def acknowledge_and_confirm(
        self, job: KitchenPrintJob, confirmed_version: OrderVersion
    ) -> None:
        previous_job = self._jobs.get(job.print_job_id)
        if previous_job is None:
            raise KeyError(job.print_job_id)
        validate_kitchen_print_job_transition(previous_job, job)
        if job.acknowledged_at is None:
            raise ValueError("atomic confirmation requires acknowledged_at")
        if (
            confirmed_version.order_id != job.order_id
            or confirmed_version.order_version_id != job.order_version_id
        ):
            raise ValueError("confirmed version does not belong to print job")
        previous_version = self._orders.get_order_version(job.order_version_id)
        if previous_version is None:
            raise KeyError(job.order_version_id)
        if previous_version.kitchen_print_confirmed_at is None:
            expected = replace(
                previous_version,
                kitchen_print_confirmed_at=job.acknowledged_at,
            )
            if confirmed_version != expected:
                raise ValueError("confirmation facts must share one timestamp")
        elif confirmed_version != previous_version:
            raise ValueError("existing kitchen confirmation is not revocable")

        # Both writes have been fully validated. The OrderRepository update is
        # the only operation that can fail; the dict swap after it cannot leave
        # a partial in-memory state.
        self._orders.update_order_version(confirmed_version)
        next_jobs = dict(self._jobs)
        next_jobs[job.print_job_id] = job
        self._jobs = next_jobs

    def _validate_new_job(
        self, job: KitchenPrintJob, *, replacing: str | None = None
    ) -> None:
        if job.print_job_id in self._jobs:
            raise KeyError(job.print_job_id)
        order = self._orders.get_order(job.order_id)
        version = self._orders.get_order_version(job.order_version_id)
        if order is None or version is None or version.order_id != order.order_id:
            raise ValueError("print job order/version ownership is invalid")
        if job.supersedes_print_job_id is None:
            if job.attempt_number != 1:
                raise ValueError("first print attempt must be attempt 1")
        else:
            previous = self._jobs.get(job.supersedes_print_job_id)
            if (
                previous is None
                or previous.order_version_id != job.order_version_id
                or job.attempt_number != previous.attempt_number + 1
            ):
                raise ValueError("reprint attempt chain is invalid")
        for existing in self._jobs.values():
            if existing.order_version_id != job.order_version_id:
                continue
            if existing.attempt_number == job.attempt_number:
                raise ValueError("attempt_number already exists for order version")
            if _is_live(existing) and existing.print_job_id != replacing:
                raise ValueError("order version already has a live print job")


def _is_live(job: KitchenPrintJob) -> bool:
    return (
        job.acknowledged_at is None
        and job.rejected_at is None
        and job.superseded_at is None
    )
