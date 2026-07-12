# Kiosk order feed API

The kitchen kiosk exposes one read-only JSON route so the separate courier
app (Tourenplanung) can list the released orders of a given date. The courier
app talks only to the kiosk; Core keeps exactly one reader. Frozen contract:
[KIOSK_ORDER_FEED_PACK_V1](../archive/packs/KIOSK_ORDER_FEED_PACK_V1.md).

## Route

```text
GET /api/order-feed?date=YYYY-MM-DD        (kiosk server, port 8082)
```

Exposure is the kiosk's own private LAN/Tailscale surface — never public,
never proxied. v1 has no application token; access relies on that trusted
boundary. Only the courier app's chef board calls this route; courier phone
links never do.

## Query contract (strict)

The query must contain exactly one parameter, `date`, with exactly one value
matching `YYYY-MM-DD` and naming a real calendar date. Everything else —
missing, empty, duplicated, malformed (`2026-7-4`, `20261001`,
`2026-10-01T00:00`), impossible dates, or any unknown extra parameter
(`?date=…&foo=bar`) — returns `400`.

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
      "guest_count_estimate": 25
    }
  ]
}
```

- `guest_count_estimate` is `null` when unknown; `orders` is `[]` for a date
  without deliveries.
- Ordering is deterministic: `(time_window_text, order_id)`.
- No version numbers, planning mode, or direct customer identity/contact
  fields. The payload is still sensitive operational data (event addresses,
  dates, time windows): keep it out of logs, chats, and screenshots.

## Selection semantics

An order appears iff it is not cancelled, has an effective version owned by
the order, and that version's `event_date` equals the requested date. An
effective version implies a confirmed kitchen print, so the feed can never
show an order the kitchen has not released. The implementation delegates to
the Wochenübersicht week read and filters by date — one set of gates.

## Other methods and paths

- `POST`/`PUT`/`DELETE`/`PATCH` → `405` (kiosk is read-only).
- `HEAD`/`OPTIONS` → `501` (no handler in `http.server`; documented,
  deliberately unchanged).
- Unknown paths → `404`.

## Smoke test (status codes only — never dump the JSON body)

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  "http://127.0.0.1:8082/api/order-feed?date=$(date +%F)"   # expect 200
curl -s -o /dev/null -w '%{http_code}\n' \
  "http://127.0.0.1:8082/api/order-feed"                    # expect 400
```
