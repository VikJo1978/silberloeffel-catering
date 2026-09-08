"""Printer adapter boundary — Fake for tests, CUPS for deployment."""

from __future__ import annotations

import logging
import math
import plistlib
import subprocess
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol
from xml.parsers.expat import ExpatError

from kitchen_print_agent.errors import PrinterError

_log = logging.getLogger(__name__)

_PDF_CONTENT_TYPE = "application/pdf"
_DEFAULT_WAIT_TIMEOUT_SECONDS = 300.0
_DEFAULT_POLL_INTERVAL_SECONDS = 1.0


class PrinterAdapter(Protocol):
    def print_document(
        self, content_type: str, body: bytes, *, timeout_seconds: float | None = None
    ) -> None: ...


class FakePrinterAdapter:
    """In-memory printer for tests and local development."""

    def __init__(
        self,
        *,
        fail_on_print: bool = False,
        rejection_code: str = "printer_unavailable",
    ) -> None:
        self.fail_on_print = fail_on_print
        self.rejection_code = rejection_code
        self.printed: list[tuple[str, bytes]] = []

    def print_document(
        self, content_type: str, body: bytes, *, timeout_seconds: float | None = None
    ) -> None:
        if self.fail_on_print:
            raise PrinterError("simulated printer failure", self.rejection_code)
        self.printed.append((content_type, body))


def _map_lp_failure(stderr: str) -> str:
    normalized = stderr.lower()
    if (
        "unknown printer" in normalized
        or "does not exist" in normalized
        or "offline" in normalized
        or "unreachable" in normalized
        or "not connected" in normalized
    ):
        return "printer_unavailable"
    if "job rejected" in normalized or "rejected" in normalized:
        return "spool_rejected"
    if "unsupported" in normalized or "format" in normalized:
        return "invalid_printer_configuration"
    return "printer_unavailable"


def _extract_cups_job_id(text: str) -> str | None:
    tokens = text.replace("(", " ").replace(")", " ").split()
    for index, token in enumerate(tokens):
        if token.lower() in {"is", "ist"} and index + 1 < len(tokens):
            candidate = tokens[index + 1]
            if "-" in candidate and candidate.rsplit("-", 1)[1].isdigit():
                return candidate
    for token in tokens:
        candidate = token.strip(":,;")
        if "-" in candidate and candidate.rsplit("-", 1)[1].isdigit():
            return candidate
    return None


class CommandRunner(Protocol):
    def __call__(
        self, command: Sequence[str], *, timeout: float
    ) -> subprocess.CompletedProcess[str]: ...


def _reported_job_state(text: str, expected_id: int) -> int | None:
    """Read the exact job's IPP enum from ipptool's machine-readable plist."""
    try:
        report = plistlib.loads(text.encode("utf-8"))
        if not isinstance(report, dict) or report.get("Successful") is not True:
            return None
        tests = report.get("Tests")
        if not isinstance(tests, list) or len(tests) != 1:
            return None
        test = tests[0]
        if not isinstance(test, dict) or test.get("Successful") is not True:
            return None
        if test.get("StatusCode") != "successful-ok":
            return None
        attributes = test.get("ResponseAttributes")
        if not isinstance(attributes, list):
            return None
        jobs = [
            group
            for group in attributes
            if isinstance(group, dict) and "job-id" in group
        ]
        if len(jobs) != 1:
            return None
        job = jobs[0]
        state = job.get("job-state")
        if type(job["job-id"]) is not int or job["job-id"] != expected_id:
            return None
        if state == 9:
            reasons = job.get("job-state-reasons")
            reasons = [reasons] if isinstance(reasons, str) else reasons
            # A forwarding server may report completed while merely queued on
            # the device. Require a positive, unambiguous success reason.
            if not isinstance(reasons, list) or not reasons:
                return None
            if "job-completed-successfully" not in reasons or any(
                not isinstance(reason, str)
                or reason not in {"job-completed-successfully", "job-restartable"}
                for reason in reasons
            ):
                return None
        return state if type(state) is int and 3 <= state <= 9 else None
    except (ValueError, TypeError, ExpatError, plistlib.InvalidFileException):
        return None


class CupsPrinterAdapter:
    """Submit and verify a job against the same local CUPS server."""

    def __init__(
        self,
        printer_name: str,
        *,
        run_lp: CommandRunner | None = None,
        poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not printer_name:
            raise ValueError("printer_name is required for CupsPrinterAdapter")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self._printer_name = printer_name
        self._run_lp = run_lp or self._default_run_lp
        self._poll_interval_seconds = poll_interval_seconds
        self._sleep = sleep
        self._monotonic = monotonic

    def _run_command(
        self, command: Sequence[str], deadline: float
    ) -> subprocess.CompletedProcess[str]:
        remaining = deadline - self._monotonic()
        if remaining <= 0:
            raise PrinterError("CUPS ACK deadline expired", "printer_unavailable")
        try:
            result = self._run_lp(command, timeout=remaining)
        except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
            raise PrinterError(
                "CUPS command failed or timed out", "printer_unavailable"
            ) from exc
        if self._monotonic() >= deadline:
            raise PrinterError("CUPS ACK deadline expired", "printer_unavailable")
        return result

    def print_document(
        self, content_type: str, body: bytes, *, timeout_seconds: float | None = None
    ) -> None:
        if content_type != _PDF_CONTENT_TYPE:
            raise PrinterError(
                f"unsupported print document content type: {content_type}",
                "invalid_printer_configuration",
            )
        timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else _DEFAULT_WAIT_TIMEOUT_SECONDS
        )
        if not math.isfinite(timeout) or timeout <= 0:
            raise PrinterError("CUPS ACK deadline expired", "printer_unavailable")
        deadline = self._monotonic() + timeout
        temp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
                handle.write(body)
                temp_path = handle.name
            result = self._run_command(
                ["lp", "-h", "localhost:631", "-d", self._printer_name, temp_path],
                deadline,
            )
        except OSError as exc:
            raise PrinterError(str(exc), "printer_unavailable") from exc
        finally:
            if temp_path is not None:
                Path(temp_path).unlink(missing_ok=True)
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "lp failed").strip()
            raise PrinterError(message, _map_lp_failure(message))
        job_id = _extract_cups_job_id(f"{result.stdout}\n{result.stderr}")
        if job_id is None or job_id.rsplit("-", 1)[0] != self._printer_name:
            raise PrinterError(
                "lp did not report a job id for the requested queue",
                "invalid_printer_configuration",
            )
        _log.info(
            "submitted kitchen print to CUPS cups_job_id=%s printer=%s",
            job_id,
            self._printer_name,
        )
        self._wait_for_completed_job(job_id, deadline=deadline)

    def _wait_for_completed_job(self, job_id: str, *, deadline: float) -> None:
        numeric_id = int(job_id.rsplit("-", 1)[1])
        test_file = str(Path(__file__).with_name("get-job-state.test"))
        while self._monotonic() < deadline:
            result = self._run_command(
                ["ipptool", "-X", f"ipp://localhost:631/jobs/{numeric_id}", test_file],
                deadline,
            )
            state = (
                _reported_job_state(result.stdout, numeric_id)
                if result.returncode == 0
                else None
            )
            if state == 9:  # RFC 8011 completed; canceled=7 and aborted=8 are failures.
                _log.info(
                    "completed kitchen print in CUPS cups_job_id=%s printer=%s",
                    job_id,
                    self._printer_name,
                )
                return
            if state in {7, 8}:
                raise PrinterError(
                    f"CUPS job {job_id} canceled or aborted", "spool_rejected"
                )
            if state is None:
                raise PrinterError(
                    f"Cannot verify CUPS job {job_id}", "printer_unavailable"
                )
            remaining = deadline - self._monotonic()
            if remaining > 0:
                self._sleep(min(self._poll_interval_seconds, remaining))
        raise PrinterError(
            f"CUPS job {job_id} did not complete before ACK deadline",
            "printer_unavailable",
        )

    @staticmethod
    def _default_run_lp(
        command: Sequence[str], *, timeout: float
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
