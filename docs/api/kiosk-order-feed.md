# Kiosk order feed API

The kitchen kiosk exposes one read-only JSON route so the separate courier
app (Tourenplanung) can list the released orders of a given date. The courier
app talks only to the kiosk; Core keeps exactly one reader.

The original route/selection contract is frozen in
[KIOSK_ORDER_FEED_PACK_V1](../archive/packs/KIOSK_ORDER_FEED_PACK_V1.md).
Issue #171 evolves the order payload with the explicit planning-only extension
[KIOSK_ORDER_FEED_RETURN_LOGISTICS_V2](../proposals/KIOSK_ORDER_FEED_RETURN_LOGISTICS_V2.md).
Issue #175 adds canonical local planning timing in
[KIOSK_ORDER_FEED_LOGISTICS_TIMING_V3](../proposals/KIOSK_ORDER_FEED_LOGISTICS_TIMING_V3.md).

## Route

```text
GET /api/order-feed?date=YYYY-MM-DD        (kiosk server, port 8082)
```

Exposure is the kiosk's own private LAN/Tailscale surface, never public and
never proxied. The endpoint has no application token; access relies on that
trusted boundary. Only the courier app's chef board calls this route; courier
phone links never do.

## Query contract (strict)

The query must contain exactly one parameter, `date`, with exactly one value
matching `YYYY-MM-DD` and naming a real calendar date. Everything else,
including missing, empty, duplicated, malformed (`2026-7-4`, `20261001`,
`2026-10-01T00:00`), impossible dates, or any unknown extra parameter
(`?date=…&foo=bar`), returns `400`.

## Response

`200`, `Content-Type: application/json; charset=utf-8`:

```json
{
  "date": "2026-10-01",
  "orders": [
    {
      "order_id": "…",
      "event_date": "2026-10-01",
      "time_window_text": "mittags",
      "location_text": "Hamburg",
      "guest_count_estimate": 25,
      "delivery_window": {
        "date": "2026-10-01",
        "start_local": "18:00",
        "end_local": "19:00"
      },
      "return_logistics": {
        "mode": "SAME_DAY",
        "return_date": "2026-10-01",
        "pickup_window_text": "22:00-23:00",
        "pickup_window_start_local": "22:00",
        "pickup_window_end_local": "23:00"
      }
    }
  ]
}
```

`delivery_window` is `null` when the effective order version has no complete
canonical delivery date/start/end. `time_window_text` remains display text and
is never parsed to manufacture canonical timing.

`return_logistics` is `null` for accepted orders that predate the structured
issue #171 return fact.

For non-null values:

- `SAME_DAY`: `return_date` equals the order `event_date`; the accepted pickup
  display window is present. Canonical pickup start/end are projected only from
  accepted canonical fields and remain `null` when those fields are absent.
- `NEXT_WORKING_DAY`: `return_date` is the next Monday-Friday date,
  `pickup_window_text` is `null`, and canonical pickup start/end are `null`.
- `pickup_window_text` is never parsed to create canonical pickup times.
- Core currently has no holiday/business-calendar source, so the deterministic
  working-day rule skips weekends only. Public holidays or company closure
  days must not be guessed.
- `same_day_fee_cents` and all other prices stay out of this operational feed.
- Courier assignment, vehicle, `PickupTask`, checklist, completion and overdue
  state remain Courier App owned and are not projected by Core.

Canonical dates use `YYYY-MM-DD`; canonical local times use `HH:MM` without UTC
conversion. Missing canonical timing is an explicit unknown/incomplete planning
fact downstream, never a reason to guess from display text, order count or guest
count.

`guest_count_estimate` is `null` when unknown; `orders` is `[]` for a date
without deliveries. Ordering remains deterministic: `(time_window_text,
order_id)`.

No version numbers, planning mode, or direct customer identity/contact fields
are exposed. The payload is still sensitive operational data (event addresses,
dates, time windows): keep it out of logs, chats, and screenshots.

## Selection semantics

An order appears iff it is not cancelled, has an effective version owned by
the order, and that version's `event_date` equals the requested date. An
effective version implies a confirmed kitchen print, so the feed can never
show an order the kitchen has not released. The implementation delegates to
the Wochenübersicht week read and filters by date, keeping one set of gates.

`WochenuebersichtEntry` continues to mirror only the effective `OrderVersion`;
V3 extends that derived read model with the effective version's canonical
outbound timing. `return_logistics` remains a separate join by `order_id` from
the immutable accepted `OrderCommercialSnapshot` because return commercial
facts do not belong to `OrderVersion`.

An operationally paused order remains in the shared read model. The weekly
Kiosk HTML marks it as `PAUSIERT`; pause metadata does not alter the order-feed
planning facts.

## Other methods and paths

- `POST`/`PUT`/`DELETE`/`PATCH` -> `405` (kiosk is read-only).
- `HEAD`/`OPTIONS` -> `501` (no handler in `http.server`; deliberately unchanged).
- Unknown paths -> `404`.

## Smoke test (status codes only, never dump the JSON body)

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  "http://127.0.0.1:8082/api/order-feed?date=$(date +%F)"   # expect 200
curl -s -o /dev/null -w '%{http_code}\n' \
  "http://127.0.0.1:8082/api/order-feed"                    # expect 400
```
