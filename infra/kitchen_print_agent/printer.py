"""Printer adapter boundary — Fake for tests, CUPS for deployment."""

from __future__ import annotations

import subprocess
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from kitchen_print_agent.errors import PrinterError

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


def _listing_contains_exact_job_id(text: str, job_id: str) -> bool:
    """Return True when an lpstat listing line starts with the exact job id."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        first_field = stripped.split(maxsplit=1)[0]
        if first_field == job_id:
            return True
    return False


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


class CupsPrinterAdapter:
    """Send document bytes to a CUPS queue via lp."""

    def __init__(
        self,
        printer_name: str,
        *,
        run_lp: Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
        | None = None,
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

    def print_document(
        self, content_type: str, body: bytes, *, timeout_seconds: float | None = None
    ) -> None:
        if content_type != _PDF_CONTENT_TYPE:
            raise PrinterError(
                f"unsupported print document content type: {content_type}",
                "invalid_printer_configuration",
            )
        temp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
                handle.write(body)
                temp_path = handle.name
            result = self._run_lp(
                ["lp", "-d", self._printer_name, temp_path],
            )
        except OSError as exc:
            raise PrinterError(str(exc), "printer_unavailable") from exc
        finally:
            if temp_path is not None:
                Path(temp_path).unlink(missing_ok=True)

        if result.returncode == 0:
            job_id = _extract_cups_job_id(f"{result.stdout}\n{result.stderr}")
            if job_id is None:
                raise PrinterError(
                    "lp accepted the job but did not report a CUPS job id",
                    "invalid_printer_configuration",
                )
            self._wait_for_completed_job(
                job_id,
                timeout_seconds=(
                    timeout_seconds
                    if timeout_seconds is not None
                    else _DEFAULT_WAIT_TIMEOUT_SECONDS
                ),
            )
            return

        message = (result.stderr or result.stdout or "lp failed").strip()
        raise PrinterError(message, _map_lp_failure(message))

    def _wait_for_completed_job(self, job_id: str, *, timeout_seconds: float) -> None:
        if timeout_seconds <= 0:
            raise PrinterError(
                f"CUPS job {job_id} did not complete before ACK deadline",
                "printer_unavailable",
            )
        deadline = self._monotonic() + timeout_seconds
        last_status = ""
        while self._monotonic() <= deadline:
            completed = self._run_lp(
                ["lpstat", "-W", "completed", "-o", self._printer_name],
            )
            completed_text = f"{completed.stdout}\n{completed.stderr}"
            if completed.returncode == 0 and _listing_contains_exact_job_id(
                completed_text, job_id
            ):
                return

            not_completed = self._run_lp(
                ["lpstat", "-W", "not-completed", "-o", self._printer_name],
            )
            not_completed_text = f"{not_completed.stdout}\n{not_completed.stderr}"
            printer = self._run_lp(["lpstat", "-p", self._printer_name, "-l"])
            printer_text = f"{printer.stdout}\n{printer.stderr}"
            combined = "\n".join(
                part for part in (not_completed_text, printer_text) if part
            )
            last_status = combined.strip() or last_status
            self._sleep(self._poll_interval_seconds)
        raise PrinterError(
            last_status or f"CUPS job {job_id} did not complete before ACK deadline",
            "printer_unavailable",
        )

    @staticmethod
    def _default_run_lp(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            check=False,
        )
