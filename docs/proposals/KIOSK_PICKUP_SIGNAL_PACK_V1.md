# KIOSK_PICKUP_SIGNAL_PACK_V1 — kiosk shows overdue pickups from the courier app

Status: FROZEN — round-3 verdict "architecture approved, freeze after
mechanical fixes", all round-3 items incorporated (§10), 2026-07-13.
Implementation follows this pack; changes to it require a new review round.
The courier-app token fixes demanded in rounds 2–3 are code, not pack, and
are committed locally there (`1e5509a`, `8eb1627`; that repository has no
remote).

## 1. Purpose and scope

The kitchen kiosk gains one **read-only section**: equipment ("Geschirr")
that was left at clients on past deliveries and that no pickup has collected
yet. The data comes from the courier app — the second and final direction of
the kiosk↔courier-app integration (the first, the order feed, is live since
2026-07-13, `docs/api/kiosk-order-feed.md`).

Covered here: the kiosk-side changes in this repository, the HTTP contract
the courier app must serve, and the counterpart changes the courier app needs
to honor that contract (they are real changes — the current courier-app code
does not yet match it, see §4).

## 2. Fixed boundary decisions (owner, 2026-07-12)

- The courier app and Core never talk to each other. Core's only reader
  remains the kiosk; the kiosk becomes the only Core-side reader of the
  courier app. Nothing in this pack touches Core, its services, or its
  repositories.
- Both sides stay read-only toward each other: the kiosk issues GET only and
  writes nothing anywhere; the courier app's route reads its own SQLite only.
- The kiosk display must never be degraded by the courier app: if the feed is
  down, slow, or malformed, the Wochenübersicht renders exactly as today.

## 3. HTTP contract (courier app serves, kiosk consumes)

```
GET /api/overdue-pickups        (courier dispatch server, default port 8090)
Authorization: Bearer <token>
```

Success — `200`, `Content-Type: application/json; charset=utf-8`:

```json
{
  "date": "2026-07-13",
  "total_count": 1,
  "truncated": false,
  "pickups": [
    {
      "location_text": "Musterstraße 1, Hamburg",
      "event_date": "2026-07-10",
      "items": [
        {"name": "Chafing-Dish", "quantity": 2},
        {"name": "Platten", "quantity": null}
      ],
      "courier_name": "Max"
    }
  ]
}
```

- `date` is the courier app's own Berlin today — the day the "overdue"
  judgment is relative to.
- **Authentication is mandatory from v1** (round-1 decision): the dispatch
  server is planned to become reachable by courier phones, so its port cannot
  be assumed LAN/Tailscale-only forever. Missing or wrong token → `401` with
  a constant body; the response must not distinguish "no token" from "wrong
  token". Comparison is constant-time.
- **Check order is fixed (round-2): bearer first, query second.** Without a
  valid token the answer is always the same `401`, even for garbage query
  strings — an unauthenticated caller learns nothing about the route's
  parameter handling. With a valid token, any query at all → `400`
  (the route takes no parameters). `POST` → `405`. Unknown paths keep the
  dispatch server's `404`.
- `items` is a structured list (round-1 decision): `name` is the checklist
  item name, `quantity` is `null` when the courier recorded no count. The
  kiosk only joins them for display and never interprets them.
- `courier_name` is the courier **currently assigned** to the source
  delivery — reassignment changes it; `null` when none is recorded.
- **Completeness over recency (round-1 decision): every open return appears,
  with no age cutoff.** The courier app's internal 7-day lookback
  (`_LOOKBACK_DAYS` in `kiosk_signal.py`) must NOT apply to this route —
  dishes forgotten for eight days are precisely the ones this signal exists
  for. Any archiving rule, if ever wanted, is a separate explicitly
  owner-confirmed decision, not a silent filter.
- **Hard response limits without breaking the completeness promise
  (round-2):** the binding server-side limit is on the **encoded JSON**: at
  most 256 KiB. Per-value caps: `location_text`, `name`, and `courier_name`
  truncated to 200 characters, at most 20 items per pickup (excess items
  dropped count as truncation). If the full list does not fit, the server
  drops trailing pickups (they are the newest — ordering is oldest-first)
  until it fits and sets `truncated: true`; `total_count` always carries the
  real number of open returns. Silent truncation is forbidden:
  `truncated`/`total_count` exist precisely so nothing disappears unnoticed.
  The kiosk client refuses bodies over 256 KiB and treats any limit
  violation as malformed. For scale: a maximal entry (20 items of 200
  characters plus the other fields) is ~5 KiB, so 256 KiB holds tens of
  maximal entries and hundreds of realistic ones — `truncated: true` in
  practice means something is very wrong, and the kiosk says so (§5.3).
- Deterministic ordering: `(event_date, location_text, assignment_id)` —
  **oldest first**, because the oldest forgotten equipment is the most at
  risk. The internal `assignment_id` is only the stable third sort key on
  the serving side; it is **not** part of the payload.
- Response headers (round-3): `Cache-Control: no-store`,
  `X-Content-Type-Options: nosniff`, and a correct `Content-Length`.
- The payload is sensitive operational data (client addresses); same handling
  rules as the order feed: never public, never proxied, never dumped into
  logs or chat.

## 4. Counterpart changes required in the courier app

The pack is honest about the gap between this contract and today's code
(round-1 blocker): the route implementation there must

1. build `items` from the assignment's checklist entries (only entries with
   `returned == false`); `OverduePickup` today carries no items at all;
2. drop the 7-day lookback for this route's selection;
3. sort `(event_date, location_text, assignment_id)` ascending — the current
   internal listing is newest-first; the id stays server-side only;
4. document that `courier_name` is the currently assigned courier;
5. require the bearer token from the `KIOSK_SIGNAL_TOKEN` environment
   variable (fed by a root-readable env file, never a CLI argument),
   constant-time comparison, bearer checked before anything else,
   `401` otherwise;
6. enforce the §3 encoding limit and per-value caps, emitting
   `total_count`/`truncated` honestly.

## 5. Kiosk-side changes (this repository)

1. **Configuration (round-2 rework — the secret never appears in argv):**
   - URL: CLI `--pickup-signal-url` or env `PICKUP_SIGNAL_URL`;
   - token: **only** env `PICKUP_SIGNAL_TOKEN` (populated by the systemd
     `EnvironmentFile`, §6) — there is no CLI flag for it, so it can never
     land in a process list or shell history;
   - both set → feature active; both absent → **dormant** (no client, no
     thread, no request, page byte-identical to today's); exactly one set →
     startup error. The feature cannot be enabled unauthenticated.
2. **No synchronous fetch during rendering** (round-1 blocker: both servers
   are single-threaded, and a kiosk render waiting on the courier app while
   the courier app's board render waits on the kiosk's order feed would stall
   both until timeout). The kiosk runs one **background refresher thread**;
   the render path reads the cache only and never blocks, so the kiosk's
   serving thread never waits on the courier app and the cycle is broken.
   The refresher thread touches no SQLite — the thread-affinity rule (WORKLOG
   Entry 048) is untouched.
   **Refresher lifecycle (round-2, normative and tested):**
   - the first fetch happens immediately at thread start, not after the
     first interval;
   - the loop waits via `stop_event.wait(60)` — never bare `sleep`;
   - cache age is measured with `time.monotonic()`, immune to wall-clock
     jumps;
   - shutdown sets the stop event and `join`s the thread;
   - **Berlin-midnight rollover:** a cached payload whose `date` is not the
     current Berlin operational day is stale *immediately*, not five more
     minutes — yesterday's pickup list must not survive into today's view;
   - a response whose `date` differs from the kiosk's current Berlin day is
     treated as malformed (cache not updated);
   - **observability (round-3):** on the first successful fetch and on every
     recovery after a failure, the refresher logs the fixed line
     `pickup signal refresh succeeded` — no payload, no token, no URL. This
     is the only positive log line (steady-state successes stay silent) and
     is what the production smoke test greps for; the muted display line
     alone proves nothing about the authenticated path.
   - Considered alternative (reviewer's round-1 suggestion): a separate
     private signal-listener process on the courier-app side. Rejected for
     v1: it adds a systemd unit, a port, and a second SQLite reader on the
     Lenovo, while the cache thread achieves the same non-blocking property
     inside the existing processes.
3. Rendering under the week table:
   - fresh cache (last success ≤ 5 min by monotonic age AND payload date ==
     current Berlin day), non-empty: heading `Abholungen — Geschirr steht
     noch beim Kunden`, one row per pickup: German-formatted date
     (`10.07.2026`), location, joined items (`Chafing-Dish ×2, Platten`),
     courier name or `–`;
   - fresh cache, empty list: no section — an empty reminder is noise;
   - fresh cache with `truncated: true` (round-2): a **prominent** warning
     line `Abholliste unvollständig — {total_count} offene Rückläufe
     insgesamt` above the rows, so truncation is impossible to miss;
   - stale or never-filled cache while the feature is on: one muted line
     `Abholungen: Kurier-App nicht erreichbar` (round-1 accepted) — the
     kitchen must know the signal is blind.
4. **HTML escaping is mandatory** for every courier-app-originating value:
   `location_text`, each item `name`, and `courier_name` (dates and
   quantities are re-rendered from parsed types, not echoed). Display
   truncation guards from §3 apply even if the serving side misbehaves.
5. The kiosk remains a GET-only server toward its own clients; no new kiosk
   routes.

## 6. Configuration and secrets

- The kiosk's systemd unit has **no `EnvironmentFile` today** (round-1
  blocker — the draft referenced one that does not exist). This pack adds
  `EnvironmentFile=/etc/catering/kiosk.env` to
  `infra/systemd/catering-kiosk.service` and to the live unit at deploy time.
  The file is root-owned, mode `600`, and holds `PICKUP_SIGNAL_URL` and
  `PICKUP_SIGNAL_TOKEN`; both stay empty until the courier app is live on the
  Lenovo.
- **Same-host deployment is the fixed plan (round-2):** both processes run on
  the Lenovo, so the production URL is pinned to loopback —
  `PICKUP_SIGNAL_URL=http://127.0.0.1:<port>/api/overdue-pickups` — and the
  signal never crosses a network interface. A non-loopback URL is a conscious
  future decision, not a default.
- The same token lands in the courier app's own root-readable env file as
  `KIOSK_SIGNAL_TOKEN`. Never in Git, never in unit files, never in chat —
  standard SECURITY.md rules.
- `.env.example` gains the two names (values empty).

## 7. Non-goals

- No writes in either direction; no acknowledgement/dismiss flow on the
  kiosk (collecting is recorded in the courier app by the courier).
- No pagination, no history — the current open list only.
- No change to the order feed, office panel, Core services, or repositories.
- No public exposure, no Cloudflare involvement.

## 8. Tests

Kiosk side (this repository):
- renderer: section with escaped location/items/courier and German dates;
  empty list → no section; stale/absent cache → muted note; `truncated:
  true` → prominent incompleteness warning with `total_count`; oversized
  strings truncated;
- wiring: URL and token both unset → page identical to today's and no client
  constructed (assert via a factory that fails the test if called); URL
  without token and token without URL → startup error;
- fetch-and-parse: 200 happy path incl. `quantity: null`, non-200, 401,
  malformed JSON, over-limit body, `date` ≠ current Berlin day, connection
  refused, timeout → cache not updated (live local HTTP fixture, same style
  as the order-feed tests); the bearer header is actually sent;
- refresher lifecycle (round-2): immediate first fetch; loop waits on
  `stop_event.wait(60)`; monotonic staleness boundary; stop + `join` on
  shutdown; **midnight rollover** — a fresh-by-age cache from yesterday's
  Berlin day renders as unavailable, not as data;
- observability (round-3): `pickup signal refresh succeeded` logged on first
  success and on recovery, exactly once per transition, never on
  steady-state repeats; the line contains no payload, token, or URL;
- security headers and read-only behavior of the kiosk unchanged.

Courier app side (counterpart, its own repository):
- route shape incl. `null` quantity, `null` courier name, `total_count`,
  `truncated`; oldest-first ordering; no lookback cutoff (an 8-day-old open
  return appears);
- check order: no/wrong token → constant `401` even with a garbage query;
  valid token + any query → `400`; `405` on POST;
- encoding limit: an oversized list yields `truncated: true` with the real
  `total_count` and a body under 256 KiB — never a silently shortened
  "complete" answer.

## 9. Operational notes

- Rollout order: freeze pack → implement kiosk side (dormant) → implement
  courier-app route → local end-to-end against both real servers, including
  the crossed-request scenario (chef board open while kiosk refreshes) →
  deploy kiosk via the production runbook (install `/etc/catering/kiosk.env`,
  `daemon-reload`, restart `catering-kiosk` only) → later, when the courier
  app lands on the Lenovo, fill both env files and restart both once.
- Production smoke test, status codes only, **and the token never enters a
  command line** (round-2: substituting it into `curl -H` exposes it in argv
  and the process list). The authenticated path is verified service-to-service
  through the kiosk itself, not by hand:

  ```bash
  # kiosk still healthy:
  curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8082/            # 200
  # unauthenticated probe is rejected (no secret involved):
  curl -s -o /dev/null -w '%{http_code}\n' \
    http://127.0.0.1:8090/api/overdue-pickups                                # 401
  # authenticated path: the kiosk's own refresher is the test client — its
  # fixed success line (§5.2) must appear after activation/restart:
  journalctl -u catering-kiosk --since '5 minutes ago' --no-pager \
    | grep -c 'pickup signal refresh succeeded'                              # >= 1
  ```

## 10. Review record

Round 1, 2026-07-13, verdict: not frozen, five blockers. All addressed:

1. **7-day lookback removed from the signal** — every open return appears;
   archiving only ever as a separate owner-confirmed rule (§3, §4.2).
2. **Contract/code gap made explicit** — items, ordering direction, and
   `courier_name` semantics documented as required counterpart changes, not
   as existing behavior (§4).
3. **Structured `items` replace `items_text`** (§3).
4. **Blocking cycle eliminated** — kiosk renders from a background-refreshed
   cache and never waits on the courier app; alternative listener process
   documented and left to round 2 (§5.2).
5. **Bearer token mandatory from v1**; kiosk unit gains the previously
   missing `EnvironmentFile`, secrets in root-readable `600` files (§3, §6).

Also adopted from round 1: visible muted failure line, dormant empty-URL
mode, hard size limits (§3).

Round 2, 2026-07-13, verdict: approve with changes, no freeze. All items
addressed:

1. **Courier-app token remarks were code, not docs** — shipped in the
   courier-app repository (commit `1e5509a`): expiry at the next Berlin
   midnight, half-open `created_at <= now < expires_at`, tokens store their
   `event_date` and `/my` uses it, SQLite migration 4 with backfill, tests
   for future-date distribution, exact midnight, and both DST transition
   days.
2. **Token configuration made consistent** — URL via CLI/env, token via env
   only (no CLI flag exists), both-or-neither with startup errors, dormant
   only when both are absent (§5.1).
3. **Limits reconciled with the completeness promise** — binding limit on
   encoded JSON, `total_count` + `truncated` fields, prominent kiosk warning
   on truncation, silent shortening forbidden (§3, §5.3).
4. **Refresher lifecycle made normative** — immediate first fetch,
   `stop_event.wait(60)`, monotonic age, stop+join on shutdown, instant
   staleness at Berlin-midnight rollover, payload-date validation (§5.2),
   all mirrored in §8 tests.
5. **Check order fixed** — bearer before query; constant `401` without a
   token regardless of query; `400` only for authenticated callers (§3).
6. **Token removed from smoke commands** — unauthenticated `401` probe plus
   service-to-service verification through the kiosk's own refresher; the
   secret never appears in argv or logs (§9).
7. **Same-host loopback URL pinned** for the Lenovo deployment (§6).

Explicit escaping list (`location_text`, item `name`, `courier_name`) added
to §5.4.

Round 3, 2026-07-13, verdict: architecture approved, freeze after mechanical
fixes; independent test run confirmed 124 passed. All items addressed:

1. **Migration-4 backfill defect fixed as migration 5** in the courier app
   (commit `8eb1627`, committed locally — that repository has no remote):
   `event_date` restored from `expires_at` (its calendar day under the old
   23:59:59 scheme, day-minus-one under the next-midnight scheme), because
   `date(created_at)` breaks on advance-minted tokens and SQLite's timezone
   normalization. Tests cover the advance-minted and past-midnight tokens
   and a post-migration-4 row that must survive unchanged.
2. **Fixed success log line** `pickup signal refresh succeeded` on first
   success/recovery; the smoke test greps for it — a muted display line or
   an error-free journal proves nothing about the authenticated path (§5.2,
   §8, §9).
3. **Contract completed**: `Cache-Control: no-store`,
   `X-Content-Type-Options: nosniff`, correct `Content-Length`; the
   200-character cap extended to `courier_name`; stable third sort key
   `assignment_id`, server-side only (§3).
4. **Document inaccuracies fixed**: the 256-KiB estimate now says tens of
   maximal entries, and `1e5509a` is described as committed locally, not
   shipped (§1, §3).
