# KIOSK_ORDER_FEED_RETURN_LOGISTICS_V2

Status: implementation slice for issue #171.

## Purpose

Extend the existing read-only `/api/order-feed` contract with the accepted
return-logistics planning fact needed by the Courier App. The route, selection
gates, exposure boundary and read-only semantics from
`KIOSK_ORDER_FEED_PACK_V1` remain unchanged.

The archived V1 pack stays frozen. This document is the explicit contract
evolution for the additive order field below.

## Response extension

Each order gains exactly one additional field:

```json
"return_logistics": {
  "mode": "SAME_DAY",
  "return_date": "2026-10-01",
  "pickup_window_text": "22:00-23:00"
}
```

or, for accepted facts created before structured return logistics existed:

```json
"return_logistics": null
```

Allowed non-null modes are `NEXT_WORKING_DAY` and `SAME_DAY`.

- `SAME_DAY`: `return_date` equals the effective order `event_date` and
  `pickup_window_text` is the accepted non-null customer request.
- `NEXT_WORKING_DAY`: `return_date` is the next Monday-Friday date after the
  event and `pickup_window_text` is `null`.
- Core currently has no holiday/business-calendar source. The projection
  therefore skips weekends only and must not pretend to know public holidays
  or company closure days. A future truthful calendar source may refine this
  rule in a separate contract change.

## Source and ownership

Selection remains derived exclusively through `WochenuebersichtService` so
cancelled, non-effective or unreleased orders cannot leak into the feed.

The new planning value is joined by `order_id` from the immutable
`OrderCommercialSnapshot.return_logistics` accepted at Offer -> Order
conversion. `WochenuebersichtEntry` remains unchanged and continues to mirror
only the effective `OrderVersion`.

## Data that must stay out

The feed must not expose:

- `same_day_fee_cents` or any other price;
- courier/driver identity;
- vehicle or assignment state;
- `PickupTask` state;
- checklist state;
- started/completed/overdue state.

Those execution facts remain Courier App owned.

## Compatibility

The route and envelope stay unchanged. Consumers that ignore unknown fields
continue to read the original five order fields. Updated consumers may parse
`return_logistics`; `null` is the explicit legacy/no-structured-fact case.

## Acceptance checks

- legacy order -> `return_logistics: null`;
- `SAME_DAY` -> event date + requested pickup window;
- `NEXT_WORKING_DAY` -> next Monday-Friday date, including weekend skipping;
- price does not cross the kiosk boundary;
- existing strict query, selection and security behavior stays unchanged;
- kiosk performs no writes and stores no new state.
