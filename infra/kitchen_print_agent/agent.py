"""Kitchen print agent polling loop — stateless runtime executor."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from typing import Protocol

from kitchen_print_agent.client import KitchenPrintAgentClient
from kitchen_print_agent.config import AgentConfig
from kitchen_print_agent.models import ClaimResponse
from kitchen_print_agent.printer import PrinterAdapter, PrinterError

_log = logging.getLogger(__name__)


class _ClaimClient(Protocol):
    def claim_next(self, command_id: str) -> ClaimResponse: ...

    def reject(
        self,
        print_job_id: str,
        command_id: str,
        rejection_code: str,
    ) -> object: ...


class KitchenPrintAgent:
    def __init__(
        self,
        config: AgentConfig,
        client: _ClaimClient,
        printer: PrinterAdapter,
        *,
        sleep: Callable[[float], None] = time.sleep,
        uuid_factory: Callable[[], str] | None = None,
    ) -> None:
        self._config = config
        self._client = client
        self._printer = printer
        self._sleep = sleep
        self._uuid_factory = uuid_factory or (lambda: str(uuid.uuid4()))
        self._running = False

    @classmethod
    def from_config(
        cls,
        config: AgentConfig,
        printer: PrinterAdapter,
        *,
        sleep: Callable[[float], None] = time.sleep,
        uuid_factory: Callable[[], str] | None = None,
    ) -> KitchenPrintAgent:
        client = KitchenPrintAgentClient(config.api_url, config.agent_token)
        return cls(
            config,
            client,
            printer,
            sleep=sleep,
            uuid_factory=uuid_factory,
        )

    def heartbeat(self) -> None:
        _log.debug(
            "kitchen print agent alive printer=%s api=%s",
            self._config.printer_name or "(unset)",
            self._config.api_url,
        )

    def run_once(self) -> bool:
        """Execute one poll iteration. Returns True when a job was claimed."""
        self.heartbeat()
        command_id = self._uuid_factory()
        result = self._client.claim_next(command_id)
        if result.document is None or result.print_job_id is None:
            return False

        try:
            self._printer.print_document(
                result.document.content_type,
                result.document.body,
            )
        except PrinterError:
            reject_command_id = self._uuid_factory()
            self._client.reject(
                result.print_job_id,
                reject_command_id,
                "printer_unavailable",
            )
        return True

    def run(self) -> None:
        self._running = True
        while self._running:
            self.run_once()
            self._sleep(self._config.poll_interval_seconds)

    def stop(self) -> None:
        self._running = False
