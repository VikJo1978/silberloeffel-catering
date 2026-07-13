# Kiosk pickup signal API

The courier app exposes the outstanding equipment-return feed consumed by the
kitchen kiosk. This is a machine-to-machine, read-only integration on the
Lenovo loopback interface.

## Route

```http
GET /api/overdue-pickups
Authorization: Bearer <service token>
```

The production kiosk calls
`http://127.0.0.1:8090/api/overdue-pickups`. The token is stored only in the
paired mode-`600` environment files and must never appear in command arguments,
logs, screenshots, chat, or documentation.

## Success response

`200 OK`, JSON, `Cache-Control: no-store`,
`X-Content-Type-Options: nosniff`, and an accurate `Content-Length`:

```json
{
  "date": "2026-07-13",
  "pickups": [
    {
      "event_date": "2026-07-10",
      "location_text": "Example venue",
      "courier_name": "Max",
      "items": [
        {"name": "Chafing-Dish", "quantity": 2},
        {"name": "Platten", "quantity": null}
      ]
    }
  ],
  "total_count": 1,
  "truncated": false
}
```

The feed contains every still-open return without an age cutoff, ordered
oldest first. Direct customer identity and contact fields are excluded, but
locations, dates, courier names, and equipment remain sensitive operational
data. The encoded response is capped at 256 KiB; truncation is explicit through
`total_count` and `truncated` and is shown prominently by the kiosk.

## Error behavior

Authentication is checked before query validation:

| Request | Response |
|---|---:|
| Missing or incorrect bearer | `401` |
| Any query parameter with a valid bearer | `400` |
| `POST` while the route is configured | `405` |
| Route without server-side token configuration | `404` |

Error bodies are constant where required and carry `no-store` and `nosniff`.
The kiosk never follows redirects and accepts only a strict `200` response.

## Kiosk resilience

The kiosk's rendering thread never waits for this API. A background refresher
fetches immediately and then every 60 seconds with a one-second timeout. It
keeps a validated in-memory cache, marks it stale after five minutes or at the
next Berlin calendar day, and renders a muted unavailability message instead
of blocking the Wochenübersicht. The fixed log line
`pickup signal refresh succeeded` appears only on the first success and on
recovery after failure.

The frozen implementation and review record is archived in
[KIOSK_PICKUP_SIGNAL_PACK_V1](../archive/packs/KIOSK_PICKUP_SIGNAL_PACK_V1.md).
