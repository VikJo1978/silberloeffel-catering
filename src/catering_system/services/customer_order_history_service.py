"""Project factual order history for one explicitly identified customer."""

from __future__ import annotations

from catering_system.domain.customer_order_history import (
    CustomerOrderHistoryDish,
    CustomerOrderHistoryEntry,
)
from catering_system.domain.inquiry import FulfillmentMode
from catering_system.domain.offer import Offer, OfferVariant, OfferVersion
from catering_system.domain.order import Order, OrderVersion
from catering_system.repositories.customer_identity_repository import (
    CustomerIdentityRepository,
)
from catering_system.repositories.inquiry_repository import InquiryRepository
from catering_system.repositories.offer_repository import OfferRepository
from catering_system.repositories.order_repository import OrderRepository


class CustomerOrderHistoryCustomerNotFoundError(KeyError):
    """The requested CustomerIdentity does not exist."""


class CustomerOrderHistoryService:
    """Read-only join over existing Core facts; persists no derived history."""

    def __init__(
        self,
        customer_identities: CustomerIdentityRepository,
        inquiries: InquiryRepository,
        orders: OrderRepository,
        offers: OfferRepository,
    ) -> None:
        self._customer_identities = customer_identities
        self._inquiries = inquiries
        self._orders = orders
        self._offers = offers

    def list_for_customer(self, customer_id: str) -> list[CustomerOrderHistoryEntry]:
        if self._customer_identities.get_by_id(customer_id) is None:
            raise CustomerOrderHistoryCustomerNotFoundError(customer_id)

        inquiries = {
            inquiry.inquiry_id: inquiry
            for inquiry in self._inquiries.list_all()
            if inquiry.customer_id == customer_id
        }
        entries: list[CustomerOrderHistoryEntry] = []
        for order in self._orders.list_orders():
            inquiry = inquiries.get(order.source_inquiry_id)
            if inquiry is None:
                continue
            versions = self._orders.list_order_versions(order.order_id)
            version = self._history_version(order, versions)
            if version is None:
                continue
            context = self._orders.get_operational_context(version.order_version_id)
            fulfillment_mode: FulfillmentMode = (
                context.fulfillment_mode
                if context is not None
                else inquiry.fulfillment_mode
            )
            offer = self._offers.get_by_source_inquiry_id(inquiry.inquiry_id)
            commercial = self._accepted_commercial(order, offer)
            entries.append(
                CustomerOrderHistoryEntry(
                    order_id=order.order_id,
                    source_inquiry_id=inquiry.inquiry_id,
                    order_version_id=version.order_version_id,
                    event_date=version.event_date,
                    guest_count=version.guest_count_estimate,
                    fulfillment_mode=fulfillment_mode,
                    accepted_offer_id=(commercial[0].offer_id if commercial else None),
                    accepted_offer_version_id=(
                        commercial[1].offer_version_id if commercial else None
                    ),
                    accepted_variant_id=(
                        commercial[2].variant_id if commercial else None
                    ),
                    accepted_variant_label=(commercial[2].label if commercial else None),
                    dishes=(
                        tuple(
                            CustomerOrderHistoryDish(
                                position_id=position.position_id,
                                name=position.name,
                                kind=position.kind,
                                catalog_item_id=position.catalog_item_id,
                                gross_total_cents=position.gross_total_cents,
                            )
                            for position in commercial[2].positions
                            if position.kind in {"catalog", "custom"}
                        )
                        if commercial
                        else ()
                    ),
                    gross_total_cents=(
                        sum(
                            position.gross_total_cents
                            for position in commercial[2].positions
                        )
                        if commercial
                        else None
                    ),
                    order_created_at=order.created_at,
                    cancelled_at=order.cancelled_at,
                )
            )
        return sorted(
            entries,
            key=lambda entry: (
                entry.event_date,
                entry.order_created_at,
                entry.order_id,
            ),
            reverse=True,
        )

    @staticmethod
    def _history_version(
        order: Order, versions: list[OrderVersion]
    ) -> OrderVersion | None:
        if not versions:
            return None
        by_id = {version.order_version_id: version for version in versions}
        if order.effective_order_version_id is not None:
            effective = by_id.get(order.effective_order_version_id)
            if effective is not None:
                return effective
        if order.candidate_order_version_id is not None:
            candidate = by_id.get(order.candidate_order_version_id)
            if candidate is not None:
                return candidate
        return max(versions, key=lambda version: version.version_number)

    @staticmethod
    def _accepted_commercial(
        order: Order, offer: Offer | None
    ) -> tuple[Offer, OfferVersion, OfferVariant] | None:
        if offer is None or offer.conversion_link is None:
            return None
        link = offer.conversion_link
        if link.order_id != order.order_id:
            return None
        version = next(
            (
                candidate
                for candidate in offer.versions
                if candidate.offer_version_id == link.offer_version_id
            ),
            None,
        )
        if version is None:
            return None
        variant = next(
            (
                candidate
                for candidate in version.variants
                if candidate.variant_id == link.variant_id
            ),
            None,
        )
        if variant is None:
            return None
        return offer, version, variant
