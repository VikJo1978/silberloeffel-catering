# Changelog

Significant user-visible, operational, and architectural changes are recorded
here. Historical fine-grained execution notes remain in `WORKLOG.md`.

## Unreleased

- Implemented Phase 1 of the frozen Proxmox office pack
  (`docs/proposals/PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1.md`): a dormant
  Core Office API on the Lenovo Tailscale address (`8084`) serving the full
  frozen read/command contract against the existing services, with atomic
  idempotency (in-`core.db` ledger, one transaction per command), post-commit
  event dispatch, a 2-second busy timeout mapping to `503 core_busy`, and a
  partial UNIQUE index closing the double-convert gap while keeping
  re-conversion after Storno. Not deployed; the office panel keeps its direct
  database access until Phase 2.
- Tightened Core Office API validation after review (still Phase 1, dormant):
  enforce the 512 KiB response cap as `500 internal`, require uuid4 for
  `command_id` and id/version references, require UTC-with-offset `expect`
  timestamps, and merge intake fields on update (omitted keeps, `""` clears,
  `null` is `400`) instead of silently wiping omitted fields.
- Recorded ADR-011: the Core Office API supersedes the office panel's in-process
  Core access; after cutover exactly three Lenovo processes touch `core.db` —
  the Core Office API (read+command), the kiosk (read), and the website-intake
  receiver (Inquiry create). Archived kiosk packs stay untouched.
- Implemented Phase 2 of the frozen Proxmox office pack: `RemoteCoreClient`
  (bearer-only auth, 3 s/5 s timeouts, redirect refusal, 512 KiB response cap,
  no business rules reproduced on Proxmox) and dual-mode wiring for the office
  panel — `CORE_OFFICE_API_URL`/`CORE_OFFICE_API_TOKEN` unset keeps the
  existing direct-`core.db` mode byte-identical; both set switches to remote
  mode without ever opening `core.db`; either alone refuses to start. Every
  mutating form now carries a hidden `_command_id` plus the frozen contract's
  preconditions, so a retry after an indeterminate failure resends the
  identical envelope. An unreachable/malformed API renders the fixed
  degradation page instead of an empty dashboard. Still not deployed — the
  panel keeps running in direct mode until a separate Phase 3+ rollout.
- Closed the Phase 2 contract-review gaps before rollout: the remote dashboard
  now consumes Core's single authoritative Berlin `QueueView`; exact response
  shapes, status/error pairs and echoed `command_id` values are enforced;
  truncation metadata is preserved with visible warnings and the true version
  count is used for optimistic writes; successful commands no longer perform
  a failure-prone post-commit reread; and unavailable Auerswald data on
  Proxmox is labelled “Rückruf-Liste: nur vor Ort verfügbar”. Phase 2 remains
  local and undeployed.
- Added the Phase 3 print-ACK attention design and Core Slice 3A kitchen print
  job facts: an append-only attempt history with additive immutable facts,
  persisted acceptance/ACK deadlines, tracked reprints, pure state derivation,
  and atomic ACK with the existing OrderVersion kitchen-print confirmation.
  This local slice adds no Office UI, HTTP API, kitchen print agent or printer
  integration and has not been deployed.

- Corrected the operational status after the office-workflow proof: the
  staging form now exercises an already-connected office queue, the Lenovo
  courier checkout is recorded at `18b3633`, and replacement-site work is
  explicitly deferred by the owner.
- Updated the CI bootstrap actions to their current Node.js 24-compatible
  major versions, removing GitHub's Node.js 20 deprecation warning.
- Recorded ADR-010: keep the synchronous, truthful-`502` intake path during
  fake-data testing, but require a restart-safe SQLite delivery buffer and an
  outage-recovery E2E proof before accepting real customer submissions.
- Hardened the temporary inquiry form without changing the surrounding site:
  browser-side contact-pair validation, a bounded request timeout, preserved
  retry state and entered values on failure, and stable German error messages
  now have their own JavaScript CI tests.
- Added a dormant, read-only Inquiry-to-offer prefill handoff: the office panel
  can open the separate configurator with known contact and event values in an
  editable draft, without creating an Order or writing proposal data into Core.
- Preserved both company and contact name in future website Inquiry context;
  previously the short subject kept the company while the name was lost.
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
- Verified the staging-to-office workflow against the live E2E Inquiry without
  mutating production: the authenticated office service reads the same Core
  database, shows the website Inquiry as pending verification, and has no
  linked Order. A database backup copy completed the guarded
  `pending → verified → OrderVersion 1` path, now covered by a regression test.
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
