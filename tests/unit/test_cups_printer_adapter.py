"""CUPS printer adapter tests — no real lp/CUPS required."""

from __future__ import annotations

import subprocess

import pytest
from kitchen_print_agent.errors import PrinterError
from kitchen_print_agent.printer import CupsPrinterAdapter


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


def test_successful_print_does_not_raise() -> None:
    calls: list[list[str]] = []

    def run_lp(command: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(list(command))
        return _completed()

    adapter = CupsPrinterAdapter("Kitchen", run_lp=run_lp)
    adapter.print_document("application/pdf", b"%PDF-1.4")

    assert calls
    assert calls[0][:3] == ["lp", "-d", "Kitchen"]
    assert calls[0][3].endswith(".pdf")


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
