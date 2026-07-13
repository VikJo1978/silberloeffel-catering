# Changelog

Significant user-visible, operational, and architectural changes are recorded
here. Historical fine-grained execution notes remain in `WORKLOG.md`.

## Unreleased

- Added and activated a fail-closed staging-to-Core Inquiry bridge: the VPS backend
  forwards namespaced fake submissions through an exact loopback URL over a
  restricted reverse-SSH tunnel, with a server-only bearer, redirect refusal,
  strict `202` acknowledgement, and idempotent retry keys. It never reads Core
  or creates Orders; real customer data still waits for HTTPS. The live E2E
  proof sent the same fake retry key twice and produced exactly one Inquiry and
  one staging audit row, with healthy databases and no public tunnel listener.
- Made the website-intake activation readiness check bounded and retry-aware so
  normal HTTP-listener startup latency cannot cause a false rollback; the
  receiver still rolls back automatically if it does not return fail-closed
  `401` within the readiness window.
- Implemented and activated the kiosk pickup-signal display (archived in
  `docs/archive/packs/KIOSK_PICKUP_SIGNAL_PACK_V1.md`): a background refresher
  reads the courier app's authenticated `/api/overdue-pickups` feed into a
  cache and the kiosk shows open equipment returns under the week table.
  The courier app runs as an enabled user service on port `8090`; the
  production kiosk uses a root-owned mode-`600` environment file and loopback
  URL. Activation on 2026-07-13 passed authenticated refresh, `200`/`401`
  route gates, process-secret, service-health, and both-database integrity
  checks. Without both variables the feature remains safely dormant and its
  HTML remains byte-identical, as pinned by a golden test.
- Published courier-app with its full history to the private
  `VikJo1978/courier-app` repository and added an independent GitHub Actions
  quality gate; registered and verified a dedicated read-only Lenovo deploy
  key and advanced the host to the same source revision.
- Added a read-only JSON order feed to the kitchen kiosk
  (`GET /api/order-feed?date=YYYY-MM-DD`) for the separate courier app, with
  a strict query contract and the same release gates as the Wochenübersicht
  (frozen in `docs/archive/packs/KIOSK_ORDER_FEED_PACK_V1.md`).
- Corrected kiosk exposure wording in the architecture guide, security
  policy, and production runbook: the kiosk is reachable on the LAN and over
  Tailscale, not "LAN only".
- Deployed the kiosk order feed to the Lenovo after a verified pre-deploy
  backup and successful CI; smoke checks confirmed the feed, validation, HTML
  kiosk, service health, and database integrity.
- Reorganized project documentation into maintained architecture, API,
  operations, user, security, and decision guides.
- Repaired the production backup schedule by moving it to the private,
  user-owned runtime directory and enforcing owner-only files with `umask 077`.
- Created and verified a cron-equivalent backup against production row counts
  while all three services remained active.
- Added GPG-encrypted off-host backups from Lenovo to a restricted VPS account,
  SHA-256 verification, local/remote retention, and a daily `03:25` schedule.
- Completed a restore drill by downloading the VPS ciphertext to the Mac,
  decrypting with a Mac-only recovery key, and verifying SQLite integrity and
  production row counts.
- Created and restore-tested an independently password-protected AES-256
  recovery-key archive; the owner confirmed an off-device copy with its
  password stored separately.
- Stopped hardcoding the test count in README and ignored the operator-owned
  `.claude/` directory to prevent accidental commits.
- Added CLI-bootstrap coverage for the website intake receiver and aligned the
  kiosk/office systemd templates with the verified live Lenovo paths.
- Raised website intake receiver coverage to 99.2% with raw malformed-length,
  oversized-body, invalid-date, and unresolved-idempotency-race tests.
- Added a read-only, HTML-escaped staging inquiry viewer that returns `404`
  publicly and is accessible only through a VPS SSH tunnel.
- Fast-forwarded the Lenovo production checkout through final audit commit
  `08034ba` after successful CI; no service restart was needed because the
  running production modules were unchanged.

## 2026-07-12

### Staging website

- Added a full temporary Silberlöffel website preview on VPS
  `185.16.60.69:8080`.
- Added isolated SQLite storage, security headers, request limits, honeypot, and
  per-IP submission limiting.
- Changed the HTTP runtime to a threaded server so a stalled browser connection
  cannot block other visitors.
- Verified desktop/mobile rendering, form persistence, and a 10-user asset
  smoke test.

### Production hardening

- Added database-safe website inquiry idempotency.
- Added CSRF protection and request limits to office writes.
- Strengthened SQLite migrations, ownership constraints, and version-number
  uniqueness.
- Split office HTTP routing and shared views into focused modules.
- Added security headers and quality gates.
- Deployed the resulting production revision to Lenovo and verified all three
  services, database integrity, office authentication, kiosk rendering, and
  website intake.

### Delivery quality

- Added GitHub Actions for Ruff, format, Mypy, Python tests with coverage, and
  Cloudflare Worker tests.
- Established a 90% coverage threshold.

## 2026-07-08 to 2026-07-10

- Built the action-oriented office dashboard, searchable Inquiry and Order
  pages, callback integration, proposal preview, website form mapping, intake
  receiver, and retry idempotency.
- Added systemd service definitions and brought the Lenovo services under
  automatic restart/startup management.

## Earlier MVP slices

- Implemented Inquiry intake channels and verification gates.
- Implemented versioned Order conversion and immutable OrderVersion history.
- Implemented kitchen print confirmation, effective-version selection,
  cancellation, derived `READY_TO_SEND`, and weekly kitchen overview.

See [`docs/archive/packs/`](docs/archive/packs/) and `WORKLOG.md` for the original
slice-by-slice record.
