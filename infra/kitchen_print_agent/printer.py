"""Printer adapter boundary — real CUPS implementation belongs in deployment slice."""

from __future__ import annotations

from typing import Protocol


class PrinterError(Exception):
    """Technical printer failure reported back to Core via reject."""


class PrinterAdapter(Protocol):
    def print_document(self, content_type: str, body: bytes) -> None: ...


class FakePrinterAdapter:
    """In-memory printer for tests and local development."""

    def __init__(self, *, fail_on_print: bool = False) -> None:
        self.fail_on_print = fail_on_print
        self.printed: list[tuple[str, bytes]] = []

    def print_document(self, content_type: str, body: bytes) -> None:
        if self.fail_on_print:
            raise PrinterError("simulated printer failure")
        self.printed.append((content_type, body))
