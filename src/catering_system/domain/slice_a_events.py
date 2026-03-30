"""Slice A domain events — minimal representation for pack §6.2 (no bus)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InquiryCreated:
    inquiry_id: str


@dataclass(frozen=True)
class InquiryUpdated:
    inquiry_id: str


@dataclass(frozen=True)
class CustomerCallVerified:
    inquiry_id: str
