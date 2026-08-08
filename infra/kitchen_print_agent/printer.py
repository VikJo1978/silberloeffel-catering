"""Printer adapter boundary — Fake for tests, CUPS for deployment."""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from kitchen_print_agent.errors import PrinterError

_CONTENT_TYPE_SUFFIX = {
    "text/html; charset=utf-8": ".html",
    "text/html": ".html",
    "application/pdf": ".pdf",
}


class PrinterAdapter(Protocol):
    def print_document(self, content_type: str, body: bytes) -> None: ...


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

    def print_document(self, content_type: str, body: bytes) -> None:
        if self.fail_on_print:
            raise PrinterError("simulated printer failure", self.rejection_code)
        self.printed.append((content_type, body))


def _suffix_for_content_type(content_type: str) -> str:
    return _CONTENT_TYPE_SUFFIX.get(content_type, ".bin")


def _map_lp_failure(stderr: str) -> str:
    normalized = stderr.lower()
    if "unknown printer" in normalized or "does not exist" in normalized:
        return "printer_unavailable"
    if "job rejected" in normalized or "rejected" in normalized:
        return "spool_rejected"
    if "unsupported" in normalized or "format" in normalized:
        return "invalid_printer_configuration"
    return "printer_unavailable"


class CupsPrinterAdapter:
    """Send document bytes to a CUPS queue via lp."""

    def __init__(
        self,
        printer_name: str,
        *,
        run_lp: Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
        | None = None,
    ) -> None:
        if not printer_name:
            raise ValueError("printer_name is required for CupsPrinterAdapter")
        self._printer_name = printer_name
        self._run_lp = run_lp or self._default_run_lp

    def print_document(self, content_type: str, body: bytes) -> None:
        suffix = _suffix_for_content_type(content_type)
        temp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
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
            return

        message = (result.stderr or result.stdout or "lp failed").strip()
        raise PrinterError(message, _map_lp_failure(message))

    @staticmethod
    def _default_run_lp(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            check=False,
        )
