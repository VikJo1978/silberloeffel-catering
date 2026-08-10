"""CUPS printer adapter tests — no real lp/CUPS required."""

from __future__ import annotations

import subprocess

import pytest
from kitchen_print_agent.errors import PrinterError
from kitchen_print_agent.printer import CupsPrinterAdapter

_PRINTER = "Brother_L2710DN_LAN"
_JOB_ID = f"{_PRINTER}-123"


def _completed(
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["lp"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _is_completed_lpstat(command: list[str]) -> bool:
    return command[:4] == ["lpstat", "-W", "completed", "-o"]


def _is_not_completed_lpstat(command: list[str]) -> bool:
    return command[:5] == ["lpstat", "-W", "not-completed", "-o"]


def test_successful_print_polls_completed_jobs_for_printer() -> None:
    calls: list[list[str]] = []

    def run_lp(command: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(list(command))
        if command[0] == "lp":
            return _completed(stdout=f"request id is {_JOB_ID} (1 file(s))")
        if _is_completed_lpstat(command):
            return _completed(stdout=f"{_JOB_ID} viktor 1024 Mon 10 Aug 2026")
        return _completed()

    adapter = CupsPrinterAdapter(_PRINTER, run_lp=run_lp, sleep=lambda _seconds: None)
    adapter.print_document("application/pdf", b"%PDF-1.4")

    assert calls[0][:3] == ["lp", "-d", _PRINTER]
    assert calls[1] == ["lpstat", "-W", "completed", "-o", _PRINTER]


def test_successful_print_parses_german_cups_job_id() -> None:
    calls: list[list[str]] = []

    def run_lp(command: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(list(command))
        if command[0] == "lp":
            return _completed(
                stdout=f"Anfrage-ID ist {_JOB_ID} (1 Datei(en))",
            )
        if _is_completed_lpstat(command):
            return _completed(stdout=f"{_JOB_ID} viktor 1024")
        return _completed()

    adapter = CupsPrinterAdapter(_PRINTER, run_lp=run_lp, sleep=lambda _seconds: None)
    adapter.print_document("application/pdf", b"%PDF-1.4")

    assert calls[1] == ["lpstat", "-W", "completed", "-o", _PRINTER]


def test_completed_listing_exact_job_id_match_succeeds() -> None:
    def run_lp(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[0] == "lp":
            return _completed(stdout=f"request id is {_JOB_ID} (1 file(s))")
        if _is_completed_lpstat(command):
            return _completed(
                stdout=(f"{_PRINTER}-122 viktor 1024\n{_JOB_ID} viktor 2048\n"),
            )
        return _completed()

    adapter = CupsPrinterAdapter(_PRINTER, run_lp=run_lp, sleep=lambda _seconds: None)
    adapter.print_document("application/pdf", b"%PDF-1.4")


def test_completed_listing_only_similar_job_id_fails() -> None:
    def run_lp(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[0] == "lp":
            return _completed(stdout=f"request id is {_JOB_ID} (1 file(s))")
        if _is_completed_lpstat(command):
            return _completed(stdout=f"{_PRINTER}-122 viktor 1024")
        if _is_not_completed_lpstat(command):
            return _completed(stdout=f"{_JOB_ID} viktor 1024 active")
        return _completed()

    ticks = [0.0, 0.0, 2.0]
    adapter = CupsPrinterAdapter(
        _PRINTER,
        run_lp=run_lp,
        sleep=lambda _seconds: None,
        monotonic=lambda: ticks.pop(0) if ticks else 2.0,
    )

    with pytest.raises(PrinterError) as exc_info:
        adapter.print_document("application/pdf", b"%PDF-1.4", timeout_seconds=1.0)

    assert exc_info.value.rejection_code == "printer_unavailable"


def test_completed_listing_longer_job_id_does_not_false_match() -> None:
    def run_lp(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[0] == "lp":
            return _completed(stdout=f"request id is {_JOB_ID} (1 file(s))")
        if _is_completed_lpstat(command):
            return _completed(stdout=f"{_PRINTER}-1234 viktor 1024")
        if _is_not_completed_lpstat(command):
            return _completed(stdout=f"{_JOB_ID} viktor 1024 active")
        return _completed()

    ticks = [0.0, 0.0, 2.0]
    adapter = CupsPrinterAdapter(
        _PRINTER,
        run_lp=run_lp,
        sleep=lambda _seconds: None,
        monotonic=lambda: ticks.pop(0) if ticks else 2.0,
    )

    with pytest.raises(PrinterError) as exc_info:
        adapter.print_document("application/pdf", b"%PDF-1.4", timeout_seconds=1.0)

    assert exc_info.value.rejection_code == "printer_unavailable"


def test_job_still_not_completed_fails_without_ack() -> None:
    def run_lp(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[0] == "lp":
            return _completed(stdout=f"request id is {_JOB_ID} (1 file(s))")
        if _is_completed_lpstat(command):
            return _completed(stdout="")
        if _is_not_completed_lpstat(command):
            return _completed(stdout=f"{_JOB_ID} viktor 1024 active")
        return _completed()

    ticks = [0.0, 0.0, 2.0]
    adapter = CupsPrinterAdapter(
        _PRINTER,
        run_lp=run_lp,
        sleep=lambda _seconds: None,
        monotonic=lambda: ticks.pop(0) if ticks else 2.0,
    )

    with pytest.raises(PrinterError) as exc_info:
        adapter.print_document("application/pdf", b"%PDF-1.4", timeout_seconds=1.0)

    assert exc_info.value.rejection_code == "printer_unavailable"


def test_lp_success_without_completed_job_fails_closed() -> None:
    def run_lp(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[0] == "lp":
            return _completed(stdout=f"request id is {_JOB_ID} (1 file(s))")
        if _is_completed_lpstat(command):
            return _completed(stdout="")
        if _is_not_completed_lpstat(command):
            return _completed(stdout=f"{_JOB_ID} viktor 1024 active")
        return _completed()

    adapter = CupsPrinterAdapter(_PRINTER, run_lp=run_lp, sleep=lambda _seconds: None)

    with pytest.raises(PrinterError) as exc_info:
        adapter.print_document("application/pdf", b"%PDF-1.4", timeout_seconds=0.01)

    assert exc_info.value.rejection_code == "printer_unavailable"


def test_status_text_is_diagnostic_only_and_completion_is_required() -> None:
    completed_checks = 0

    def run_lp(command: list[str]) -> subprocess.CompletedProcess[str]:
        nonlocal completed_checks
        if command[0] == "lp":
            return _completed(stdout="request id is Kitchen-12 (1 file(s))")
        if _is_completed_lpstat(command):
            completed_checks += 1
            if completed_checks == 1:
                return _completed(stdout="")
            return _completed(stdout="Kitchen-12 viktor 1024 Mon 10 Aug 2026")
        if command[:2] == ["lpstat", "-p"]:
            return _completed(stdout="printer Kitchen disabled since paper-out")
        if _is_not_completed_lpstat(command):
            return _completed(stdout="Kitchen-12 viktor 1024 active")
        return _completed()

    adapter = CupsPrinterAdapter("Kitchen", run_lp=run_lp, sleep=lambda _seconds: None)

    adapter.print_document("application/pdf", b"%PDF-1.4")


def test_terminal_status_text_without_completed_job_fails_after_timeout() -> None:
    def run_lp(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[0] == "lp":
            return _completed(stdout="request id is Kitchen-12 (1 file(s))")
        if _is_completed_lpstat(command):
            return _completed(stdout="")
        if command[:2] == ["lpstat", "-p"]:
            return _completed(stdout="printer Kitchen disabled since cancelled")
        if _is_not_completed_lpstat(command):
            return _completed(stdout="Kitchen-12 viktor 1024 active")
        return _completed()

    ticks = [0.0, 0.0, 2.0]
    adapter = CupsPrinterAdapter(
        "Kitchen",
        run_lp=run_lp,
        sleep=lambda _seconds: None,
        monotonic=lambda: ticks.pop(0) if ticks else 2.0,
    )

    with pytest.raises(PrinterError) as exc_info:
        adapter.print_document("application/pdf", b"%PDF-1.4", timeout_seconds=1.0)

    assert exc_info.value.rejection_code == "printer_unavailable"


def test_german_status_text_is_diagnostic_only() -> None:
    completed_checks = 0

    def run_lp(command: list[str]) -> subprocess.CompletedProcess[str]:
        nonlocal completed_checks
        if command[0] == "lp":
            return _completed(stdout="request id is Kitchen-12 (1 file(s))")
        if _is_completed_lpstat(command):
            completed_checks += 1
            if completed_checks == 1:
                return _completed(stdout="")
            return _completed(stdout="Kitchen-12 viktor 1024 Mon 10 Aug 2026")
        if command[:2] == ["lpstat", "-p"]:
            return _completed(stdout="Drucker Kitchen ist deaktiviert: Papierstau")
        if _is_not_completed_lpstat(command):
            return _completed(stdout="Kitchen-12 viktor 1024 active")
        return _completed()

    adapter = CupsPrinterAdapter("Kitchen", run_lp=run_lp, sleep=lambda _seconds: None)

    adapter.print_document("application/pdf", b"%PDF-1.4")


def test_missing_completed_job_fails_closed_with_german_diagnostic() -> None:
    def run_lp(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[0] == "lp":
            return _completed(stdout="request id is Kitchen-12 (1 file(s))")
        if _is_completed_lpstat(command):
            return _completed(stdout="")
        if command[:2] == ["lpstat", "-p"]:
            return _completed(stdout="Drucker Kitchen ist deaktiviert: Papierstau")
        if _is_not_completed_lpstat(command):
            return _completed(stdout="Kitchen-12 viktor 1024 active")
        return _completed()

    ticks = [0.0, 0.0, 2.0]
    adapter = CupsPrinterAdapter(
        "Kitchen",
        run_lp=run_lp,
        sleep=lambda _seconds: None,
        monotonic=lambda: ticks.pop(0) if ticks else 2.0,
    )

    with pytest.raises(PrinterError) as exc_info:
        adapter.print_document("application/pdf", b"%PDF-1.4", timeout_seconds=1.0)

    assert exc_info.value.rejection_code == "printer_unavailable"


def test_transient_active_job_completes_without_second_submission() -> None:
    calls: list[list[str]] = []
    completed_checks = 0

    def run_lp(command: list[str]) -> subprocess.CompletedProcess[str]:
        nonlocal completed_checks
        calls.append(list(command))
        if command[0] == "lp":
            return _completed(stdout="request id is Kitchen-12 (1 file(s))")
        if _is_completed_lpstat(command):
            completed_checks += 1
            if completed_checks == 1:
                return _completed(stdout="")
            return _completed(stdout="Kitchen-12 viktor 1024 Mon 10 Aug 2026")
        if _is_not_completed_lpstat(command):
            return _completed(stdout="Kitchen-12 viktor 1024 active")
        return _completed()

    adapter = CupsPrinterAdapter("Kitchen", run_lp=run_lp, sleep=lambda _seconds: None)

    adapter.print_document("application/pdf", b"%PDF-1.4")

    assert [call[0] for call in calls].count("lp") == 1


def test_queue_missing_maps_to_printer_unavailable() -> None:
    def run_lp(_command: list[str]) -> subprocess.CompletedProcess[str]:
        return _completed(returncode=1, stderr="lp: Unknown printer 'Kitchen'")

    adapter = CupsPrinterAdapter("Kitchen", run_lp=run_lp)

    with pytest.raises(PrinterError) as exc_info:
        adapter.print_document("application/pdf", b"%PDF-1.4")

    assert exc_info.value.rejection_code == "printer_unavailable"


def test_spool_reject_maps_to_spool_rejected() -> None:
    def run_lp(_command: list[str]) -> subprocess.CompletedProcess[str]:
        return _completed(returncode=1, stderr="job rejected by spooler")

    adapter = CupsPrinterAdapter("Kitchen", run_lp=run_lp)

    with pytest.raises(PrinterError) as exc_info:
        adapter.print_document("application/pdf", b"%PDF-1.4")

    assert exc_info.value.rejection_code == "spool_rejected"


def test_unsupported_format_maps_to_invalid_printer_configuration() -> None:
    calls: list[list[str]] = []

    def run_lp(_command: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(list(_command))
        return _completed(returncode=1, stderr="unsupported document format")

    adapter = CupsPrinterAdapter("Kitchen", run_lp=run_lp)

    with pytest.raises(PrinterError) as exc_info:
        adapter.print_document("text/html; charset=utf-8", b"<html>test</html>")

    assert exc_info.value.rejection_code == "invalid_printer_configuration"
    assert calls == []
