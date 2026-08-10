"""Agent-layer printer errors — carry Core allowlisted rejection codes."""

from __future__ import annotations


class PrinterError(Exception):
    """Technical printer failure reported back to Core via reject."""

    def __init__(self, message: str, rejection_code: str) -> None:
        super().__init__(message)
        self.rejection_code = rejection_code
