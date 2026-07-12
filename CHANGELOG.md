# Changelog

Significant user-visible, operational, and architectural changes are recorded
here. Historical fine-grained execution notes remain in `WORKLOG.md`.

## Unreleased

- Reorganized project documentation into maintained architecture, API,
  operations, user, security, and decision guides.
- Marked the unverified automatic-backup permission as an active operational
  risk.

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
