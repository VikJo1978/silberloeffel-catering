"""CUPS completion must be exact, positive, and inside the ACK deadline."""

from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path
from collections.abc import Sequence

import pytest
from kitchen_print_agent.errors import PrinterError
from kitchen_print_agent.printer import CupsPrinterAdapter, _reported_job_state


def report(state: object = 9, job_id: object = 12, *, successful: bool = True) -> str:
    return plistlib.dumps(
        {
            "Successful": successful,
            "Tests": [
                {
                    "Successful": successful,
                    "StatusCode": "successful-ok",
                    "ResponseAttributes": [
                        {"attributes-charset": "utf-8"},
                        {
                            "job-id": job_id,
                            "job-state": state,
                            "job-state-reasons": "job-completed-successfully",
                        },
                    ],
                }
            ],
        }
    ).decode()


def completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.mark.parametrize(
    "announcement",
    ["request id is Kitchen-12 (1 file(s))", "Anfrage-ID ist Kitchen-12 (1 Datei(en))"],
)
def test_processing_then_completed_submits_once(announcement):
    calls = []
    timeouts = []
    states = iter([3, 5, 9])
    clock = Clock()

    def run(command, *, timeout):
        calls.append(list(command))
        timeouts.append(timeout)
        if command[0] == "lp":
            assert Path(command[-1]).read_bytes() == b"%PDF"
            return completed(announcement)
        return completed(report(next(states)))

    adapter = CupsPrinterAdapter(
        "Kitchen", run_lp=run, monotonic=clock.monotonic, sleep=clock.sleep
    )
    adapter.print_document("application/pdf", b"%PDF", timeout_seconds=10)
    assert calls[0][:5] == ["lp", "-h", "localhost:631", "-d", "Kitchen"]
    assert all(
        call[:3] == ["ipptool", "-X", "ipp://localhost:631/jobs/12"]
        for call in calls[1:]
    )
    assert len(calls) == 4
    assert timeouts == [10, 10, 9, 8]
    assert not Path(calls[0][-1]).exists()


@pytest.mark.parametrize("state", [7, 8])
def test_canceled_or_aborted_never_succeeds(state):
    def run(command, *, timeout):
        return completed(
            "request id is Kitchen-12" if command[0] == "lp" else report(state)
        )

    with pytest.raises(PrinterError) as error:
        CupsPrinterAdapter("Kitchen", run_lp=run).print_document(
            "application/pdf", b"%PDF"
        )
    assert error.value.rejection_code == "spool_rejected"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not xml",
        "Kitchen-12 owner 1024",
        report(9, 123),
        report(9, "12"),
        report(True),
        report(10),
        report(9, successful=False),
        "<plist><dict>",
    ],
)
def test_unverifiable_response_fails_closed(text):
    def run(command, *, timeout):
        return completed("request id is Kitchen-12" if command[0] == "lp" else text)

    with pytest.raises(PrinterError) as error:
        CupsPrinterAdapter("Kitchen", run_lp=run).print_document(
            "application/pdf", b"%PDF"
        )
    assert error.value.rejection_code == "printer_unavailable"


def test_active_job_expires_without_resubmission():
    clock = Clock()
    calls = []

    def run(command, *, timeout):
        calls.append(command[0])
        return completed(
            "request id is Kitchen-12" if command[0] == "lp" else report(5)
        )

    adapter = CupsPrinterAdapter(
        "Kitchen", run_lp=run, monotonic=clock.monotonic, sleep=clock.sleep
    )
    with pytest.raises(PrinterError):
        adapter.print_document("application/pdf", b"%PDF", timeout_seconds=0.5)
    assert clock.now == 0.5
    assert calls == ["lp", "ipptool"]


@pytest.mark.parametrize("command_name", ["lp", "ipptool"])
def test_real_subprocess_boundary_has_timeout_and_cleans_file(
    monkeypatch, command_name
):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert 0 < kwargs["timeout"] <= 2
        if command[0] == command_name:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return completed("request id is Kitchen-12")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(PrinterError) as error:
        CupsPrinterAdapter("Kitchen").print_document(
            "application/pdf", b"%PDF", timeout_seconds=2
        )
    assert error.value.rejection_code == "printer_unavailable"
    assert not Path(calls[0][-1]).exists()


def test_late_success_cannot_ack():
    clock = Clock()

    def run(command, *, timeout):
        if command[0] == "lp":
            return completed("request id is Kitchen-12")
        clock.now = 11
        return completed(report())

    with pytest.raises(PrinterError):
        CupsPrinterAdapter(
            "Kitchen", run_lp=run, monotonic=clock.monotonic
        ).print_document("application/pdf", b"%PDF", timeout_seconds=10)


@pytest.mark.parametrize(
    "message,code",
    [
        ("unknown printer", "printer_unavailable"),
        ("job rejected", "spool_rejected"),
        ("unsupported format", "invalid_printer_configuration"),
    ],
)
def test_submission_failure_mapping(message, code):
    def run(command: Sequence[str], *, timeout: float):
        return completed(returncode=1, stderr=message)

    with pytest.raises(PrinterError) as error:
        CupsPrinterAdapter("Kitchen", run_lp=run).print_document(
            "application/pdf", b"%PDF"
        )
    assert error.value.rejection_code == code


@pytest.mark.parametrize("announcement", ["accepted", "request id is WrongQueue-12"])
def test_missing_or_wrong_queue_job_id_rejected(announcement):
    with pytest.raises(PrinterError) as error:
        CupsPrinterAdapter(
            "Kitchen", run_lp=lambda command, timeout: completed(announcement)
        ).print_document("application/pdf", b"%PDF")
    assert error.value.rejection_code == "invalid_printer_configuration"


def test_unsupported_content_never_submits():
    calls = []
    with pytest.raises(PrinterError) as error:
        CupsPrinterAdapter(
            "Kitchen", run_lp=lambda command, timeout: calls.append(command)
        ).print_document("text/html", b"html")
    assert error.value.rejection_code == "invalid_printer_configuration"
    assert calls == []


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_deadline_never_submits(timeout):
    calls = []
    with pytest.raises(PrinterError):
        CupsPrinterAdapter(
            "Kitchen", run_lp=lambda command, timeout: calls.append(command)
        ).print_document("application/pdf", b"%PDF", timeout_seconds=timeout)
    assert calls == []


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"Successful": True, "Tests": []},
        {"Successful": True, "Tests": ["invalid"]},
        {
            "Successful": True,
            "Tests": [{"Successful": True, "StatusCode": "server-error"}],
        },
    ],
)
def test_plist_shape_validation(payload):
    assert _reported_job_state(plistlib.dumps(payload).decode(), 12) is None


@pytest.mark.parametrize(
    "reasons",
    [
        "job-completed-with-errors",
        "job-completed-with-warnings",
        "queued-in-device",
        "none",
        [],
        ["job-completed-successfully", "queued-in-device"],
        ["job-completed-successfully", {}],
    ],
)
def test_completed_without_unambiguous_success_is_rejected(reasons):
    payload = plistlib.loads(report().encode())
    payload["Tests"][0]["ResponseAttributes"][1]["job-state-reasons"] = reasons
    assert _reported_job_state(plistlib.dumps(payload).decode(), 12) is None
