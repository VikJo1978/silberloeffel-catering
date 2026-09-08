from __future__ import annotations

import logging
import plistlib
import subprocess
from datetime import UTC, datetime, timedelta

from kitchen_print_agent.agent import KitchenPrintAgent
from kitchen_print_agent.config import AgentConfig
from kitchen_print_agent.models import ClaimDocument, ClaimResponse
from kitchen_print_agent.printer import CupsPrinterAdapter, FakePrinterAdapter

_NOW = datetime(2026, 9, 8, 8, 0, tzinfo=UTC)
_JOB_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


class _Client:
    def __init__(self) -> None:
        self.acknowledged: list[str] = []
        self.rejected: list[tuple[str, str]] = []

    def claim_next(self, _command_id: str) -> ClaimResponse:
        return ClaimResponse(
            command_id="claim-command",
            print_job_id=_JOB_ID,
            ack_deadline_at=_NOW + timedelta(minutes=5),
            document=ClaimDocument(content_type="application/pdf", body=b"%PDF-test"),
        )

    def acknowledge(self, print_job_id: str, _command_id: str) -> object:
        self.acknowledged.append(print_job_id)
        return object()

    def reject(
        self,
        print_job_id: str,
        _command_id: str,
        rejection_code: str,
    ) -> object:
        self.rejected.append((print_job_id, rejection_code))
        return object()


def _config() -> AgentConfig:
    return AgentConfig(
        api_url="http://127.0.0.1:8086",
        agent_token="secret-not-logged",
        poll_interval_seconds=5,
        printer_name="Kitchen",
    )


def test_agent_logs_claim_and_ack_without_document_or_token(caplog) -> None:
    client = _Client()
    caplog.set_level(logging.INFO)
    agent = KitchenPrintAgent(
        _config(),
        client,
        FakePrinterAdapter(),
        clock=lambda: _NOW,
        uuid_factory=lambda: "command-id",
    )

    assert agent.run_once() is True

    text = caplog.text
    assert f"claimed kitchen print job print_job_id={_JOB_ID}" in text
    assert f"acknowledged kitchen print job print_job_id={_JOB_ID}" in text
    assert "secret-not-logged" not in text
    assert "%PDF-test" not in text


def test_agent_logs_rejection_code(caplog) -> None:
    client = _Client()
    caplog.set_level(logging.INFO)
    agent = KitchenPrintAgent(
        _config(),
        client,
        FakePrinterAdapter(fail_on_print=True, rejection_code="printer_unavailable"),
        clock=lambda: _NOW,
        uuid_factory=lambda: "command-id",
    )

    assert agent.run_once() is True

    assert (
        f"rejected kitchen print job print_job_id={_JOB_ID} code=printer_unavailable"
        in caplog.text
    )
    assert client.acknowledged == []


def test_cups_adapter_logs_submission_and_verified_completion(caplog) -> None:
    def runner(
        command: list[str] | tuple[str, ...], *, timeout: float
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "lp":
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="request id is Kitchen-42 (1 file(s))",
                stderr="",
            )
        report = plistlib.dumps(
            {
                "Successful": True,
                "Tests": [
                    {
                        "Successful": True,
                        "StatusCode": "successful-ok",
                        "ResponseAttributes": [
                            {
                                "job-id": 42,
                                "job-state": 9,
                                "job-state-reasons": "job-completed-successfully",
                            }
                        ],
                    }
                ],
            }
        ).decode()
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=report,
            stderr="",
        )

    caplog.set_level(logging.INFO)
    adapter = CupsPrinterAdapter("Kitchen", run_lp=runner)

    adapter.print_document("application/pdf", b"%PDF-test", timeout_seconds=10)

    assert (
        "submitted kitchen print to CUPS cups_job_id=Kitchen-42 printer=Kitchen"
        in caplog.text
    )
    assert (
        "completed kitchen print in CUPS cups_job_id=Kitchen-42 printer=Kitchen"
        in caplog.text
    )
    assert "%PDF-test" not in caplog.text
