# KIOSK_ORDER_FEED_PACK_V1 — kiosk read-endpoint for the courier app

Status: FROZEN — external review verdict "freeze approved", 2026-07-12.
Implementation follows this pack; changes to it require a new review round.

## 1. Purpose and scope

Add **one read-only JSON route** to the existing kitchen kiosk server so the
separate courier app (`~/courier-app`, Tourenplanung) can list the deliverable
orders of a given date. This is the endpoint that replaces the courier app's
`StubOrderFeed`.

Covered direction: **kiosk → courier app** only. The reverse signal (kiosk
displays overdue equipment pickups read *from* the courier app) is explicitly
out of scope and needs its own pack.

## 2. Fixed boundary decisions (owner, 2026-07-12)

- The courier app talks **only to the kiosk**, never to Core directly. Core
  keeps exactly one reader: the kiosk. This pack adds no new Core reader.
- The kiosk stays **read-only**: GET only, no new writes, no new stored state,
  no schema change, no migration.
- The kiosk remains private (LAN/Tailscale) and is never proxied to the
  public internet.

## 3. HTTP contract

```
GET /api/order-feed?date=YYYY-MM-DD        (kiosk server, port 8082)
```

Success — `200`, `Content-Type: application/json; charset=utf-8`:

```json
{
  "date": "2026-07-14",
  "orders": [
    {
      "order_id": "…",
      "event_date": "2026-07-14",
      "time_window_text": "11:30–12:00",
      "location_text": "…",
      "guest_count_estimate": 25
    }
  ]
}
```

- `guest_count_estimate` is `null` when unknown.
- Field set is **exactly** the courier app's `CoreOrderSummary` slice
  (`order_feed.py`), nothing more: no version numbers, no planning mode, no
  customer identity or contact fields (the underlying `WochenuebersichtEntry`
  read model carries none). The payload is still sensitive operational data —
  event addresses, dates, and time windows — and must be treated as such: no
  public exposure, no dumping into logs or chat (see §5 and §8).
- Deterministic ordering: `(time_window_text, order_id)`.
- **Strict query contract.** Accepted iff the query contains exactly one
  parameter, `date`, with exactly one value matching `YYYY-MM-DD` (four-digit
  year, two-digit month and day, valid calendar date). Missing, empty,
  duplicated, or any other shape (`2026-7-4`, `20260704`,
  `2026-07-04T00:00`, trailing junk) → `400`. Any unknown extra parameter
  (`?date=…&foo=bar`) → `400` as well.
- Other paths and methods keep today's kiosk behavior, now stated precisely:
  unknown path → `404`; `POST`/`PUT`/`DELETE`/`PATCH` → `405 kiosk is
  read-only`; `HEAD`/`OPTIONS` have no handler in `http.server` and return
  `501 Unsupported method` — this existing behavior is documented here and
  deliberately left unchanged by this pack.
- Existing kiosk response headers (`Cache-Control: no-store`, CSP, nosniff,
  frame deny) already apply via the shared `end_headers` and stay unchanged.
- The envelope object `{date, orders}` (rather than a bare array) is accepted
  by review: it echoes the queried date for log-free debugging.

## 4. Selection semantics — identical gates to the Wochenübersicht

An order appears for the requested date iff:

1. `cancelled_at IS NULL` (STORNO pack §3 — the kitchen must not deliver a
   cancelled order; the same holds for a courier);
2. an effective version exists and belongs to the order (existing
   Wochenübersicht ownership check);
3. the effective version's `event_date` equals the requested date.

Because a version can only become effective after its kitchen print is
confirmed (existing operational gate), the courier feed can never show an
order the kitchen has not released.

Implementation shape (review requirement): `get_day_overview(event_date)` on
`WochenuebersichtService` **delegates to the existing week read and filters
the returned entries by exact date**:

```python
calendar = event_date.isocalendar()
week = self.get_week_overview(calendar.year, calendar.week)
```

The selection rules live in one place and physically cannot diverge. Pure
read, no events.

## 5. Exposure and authentication

- Same binding and exposure as the kiosk display. Factually the kiosk listens
  on `0.0.0.0:8082` and is reachable both on the LAN and over Tailscale
  (`100.109.6.74`, verified HTTP 200) — "LAN only" in older docs understates
  this. The feed inherits exactly this private LAN/Tailscale surface and must
  never become public or be proxied.
- **v1 has no application token** (accepted by review); access relies on the
  existing trusted LAN/Tailscale boundary, exactly as for the kiosk HTML
  page, and the payload is a subset of what that page already shows.
  Tailscale authenticates devices; the plain LAN segment does not — the
  boundary is trusted, not an authentication mechanism.
- Only the courier app's chef board calls this endpoint; courier phone links
  never do.

## 6. Non-goals

- No writes in either direction.
- No overdue-pickup signal (separate pack).
- No week/range queries, no pagination — one date per request.
- No change to Core services, repositories, office panel, kiosk HTML, or the
  kiosk's `HEAD`/`OPTIONS` handling.
- No public exposure and no Cloudflare involvement.

## 7. Tests (extend `tests/unit/test_kiosk_server.py` and service tests)

Service level:
- date match included; other-date, cancelled, no-effective-version, and
  foreign-effective-version orders excluded;
- `get_day_overview` result is exactly the date-filtered subset of
  `get_week_overview` for the same week;
- deterministic ordering;
- `guest_count_estimate=None` passes through.

Handler level:
- happy path returns the exact JSON shape above;
- `400` cases: missing `date`, empty `date`, duplicated `date` parameter,
  unknown extra parameter (`?date=…&foo=bar`), malformed values (`2026-7-4`,
  `20260704`, `2026-07-04T00:00`, impossible calendar date);
- `POST` on the new route → `405`; `HEAD`/`OPTIONS` → `501` (unchanged
  existing behavior, asserted so a future change is a conscious one);
- `/` HTML route and unknown-path `404` behavior unchanged;
- security headers present on the JSON response.

## 8. Operational notes

- The kiosk stays single-threaded on purpose (WORKLOG Entry 048 — the shared
  sqlite3 connection must remain on the serving thread). One more GET route
  changes nothing there. [ASSUMPTION] The chef board fetches the feed on page
  load / manual refresh, not in a hot polling loop; ≤1 request per minute is
  the expected ceiling.
- Rollout: implement + tests locally → CI green → deploy via the Lenovo
  production runbook → restart `catering-kiosk` only.
- Production smoke test must not print real event addresses to the terminal
  or any journal. Check the status code only:

  ```bash
  curl -s -o /dev/null -w '%{http_code}\n' \
    "http://127.0.0.1:8082/api/order-feed?date=$(date +%F)"   # expect 200
  curl -s -o /dev/null -w '%{http_code}\n' \
    "http://127.0.0.1:8082/api/order-feed"                    # expect 400
  ```

- The courier app's `HttpOrderFeed` implementation happens in its own
  repository afterwards and is not part of this pack.

## 9. Review record

External review 2026-07-12, verdict "approve with changes"; all requested
changes are incorporated above:

1. removed the "privacy by construction" claim — payload remains sensitive
   operational data (§3);
2. exposure corrected to LAN **and Tailscale**, matching the actual
   `0.0.0.0:8082` binding (§5);
3. active draft moved out of `docs/archive/packs/` to `docs/proposals/`;
4. `get_day_overview` delegates to `get_week_overview` + date filter (§4);
5. strict `YYYY-MM-DD` date validation, including empty/duplicated parameter
   → `400` (§3, §7);
6. `HEAD`/`OPTIONS` behavior documented as the real `501`, not `405` (§3,
   §6, §7);
7. production smoke test checks status codes only, never dumps JSON with
   real addresses (§8).

Accepted without change: 5-field `CoreOrderSummary` contract, effective-only
and non-cancelled selection, no migrations, `{date, orders}` envelope,
`/api/order-feed` route name, no bearer token in v1.

Second review round, 2026-07-12, verdict **freeze approved** after three
corrections, all incorporated above:

1. `get_week_overview` call shape fixed — two arguments from
   `isocalendar()`, not the raw tuple (§4);
2. "network boundary is the authentication" replaced with the accurate
   trusted-boundary wording (§5);
3. unknown extra query parameters (`?date=…&foo=bar`) → `400`, with a test
   (§3, §7).
