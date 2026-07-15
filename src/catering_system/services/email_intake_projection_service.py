"""Email intake projection read service — email-source inquiries only."""

from __future__ import annotations

from catering_system.domain.email_intake_projection import (
    EmailIntakeProjection,
    project_email_intake,
)
from catering_system.domain.inquiry import Inquiry
from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.offer_repository import OfferRepository
from catering_system.repositories.order_repository import OrderRepository


class EmailIntakeProjectionService:
    def __init__(
        self,
        inquiry_repository: InquiryRepository,
        offer_repository: OfferRepository,
        order_repository: OrderRepository,
    ) -> None:
        self._inquiries = inquiry_repository
        self._offers = offer_repository
        self._orders = order_repository

    def list_emails(self) -> list[EmailIntakeProjection]:
        rows = [
            self._project(inquiry)
            for inquiry in self._email_inquiries()
        ]
        rows.sort(key=lambda row: row.received_at, reverse=True)
        return rows

    def email_detail(self, inquiry_id: str) -> EmailIntakeProjection | None:
        inquiry = self._inquiries.get_by_id(inquiry_id)
        if inquiry is None or inquiry.inquiry_source != "email":
            return None
        return self._project(inquiry)

    def _email_inquiries(self) -> list[Inquiry]:
        return [
            inquiry
            for inquiry in self._inquiries.list_all()
            if inquiry.inquiry_source == "email"
        ]

    def _project(self, inquiry: Inquiry) -> EmailIntakeProjection:
        offer = self._offers.get_by_source_inquiry_id(inquiry.inquiry_id)
        orders = [
            order
            for order in self._orders.list_orders()
            if order.source_inquiry_id == inquiry.inquiry_id
        ]
        orders.sort(key=lambda order: order.created_at)
        return project_email_intake(inquiry, offer=offer, orders=orders)
