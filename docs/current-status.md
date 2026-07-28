# Current status

Operational truth last verified: **2026-07-28T18:42:33Z** (PDF runtime
production migration — see "Deployed and closed" below — and independent
post-migration verification, including `infra/deploy/verify_pdf_runtime.py
--host-runtime`).

This document separates **repository state** (what is on `origin/main`) from
**production state** (what is actually deployed and running on Lenovo
`debiancatering`, Tailscale `100.109.6.74`). A commit on `origin/main` is not
deployed until the relevant services have restarted while that commit (or a
descendant loaded at restart) is on disk, and post-deploy checks are
recorded. See `docs/runbooks/deployment-truth-checklist.md`.

## Repository state

| Item | Value |
|---|---|
| `origin/main` HEAD | `ab0743f229b525b348ebdc6cfd71c2fac7ba153e` (`ab0743f`) |
| Latest merged functional PRs | [#45 — Add reproducible runtime dependency locking](https://github.com/VikJo1978/silberloeffel-catering/pull/45), [#46 — Align tracked office units with the running venv interpreter](https://github.com/VikJo1978/silberloeffel-catering/pull/46), [#48 — Add read-only PDF runtime verification](https://github.com/VikJo1978/silberloeffel-catering/pull/48) |
| Latest merged PR (docs-only) | this update (branch `docs/runtime-migration-status`, issue #49) — documentation-only; does not itself change production state |
| CI on the latest functional merges | `quality` — **pass** (required check green at merge time for #45, #46, #48) |

**Do not treat the SHA above as permanent:** query Git for the current value;
repository HEAD advances with every merge. Docs-only commits change
repository HEAD but are **not** application deployments — production state
below remains authoritative until services restart.

## Production state

| Item | Value |
|---|---|
| Deployed commit | `ab0743f229b525b348ebdc6cfd71c2fac7ba153e` (`ab0743f`) |
| Previous deployed commit | `a67875d800deff7a954e9c83d42174c41b647326` (`a67875d`) |
| Relationship to `origin/main` | **matches** — production is a clean fast-forward of `origin/main`, including PR #42, #45, #46, #48 |
| Merged-but-not-yet-deployed changes | none |
| Release discipline (proven) | deployment user can direct-push to `main`; prior pushes were not blocked by required green `quality`; branch protection may be absent or the user may have bypass — exact settings require authenticated owner/admin verification (see `docs/runbooks/release-discipline.md`) |

## Production services

Last verified observation: **2026-07-28**, immediately after the PDF runtime
production migration (see "Deployed and closed" below) and its independent
post-migration verification pass. **These are a point-in-time snapshot, not
permanent expected values** — re-verify with `systemctl show` before relying
on them.

| Service | PID | Started (CEST) |
|---|---|---|
| `catering-office-api` | 458270 | 2026-07-28 20:42:33 |
| `catering-office-panel` | 458277 | 2026-07-28 20:42:33 |
| `catering-website-intake` | 362683 | 2026-07-22 22:50:09 |
| `catering-kiosk` | 332509 | 2026-07-21 00:36:38 |

Only `catering-office-api` and `catering-office-panel` were restarted for the
PDF runtime migration; `catering-website-intake` and `catering-kiosk`
retained their prior PID/start time, confirming they were not touched.

## Deployment verification (`ab0743f`)

- HTTP checks: Office API `401`, Office Panel `401`, Kiosk `200`, Website
  Intake `GET /intake/website-form` `405`, unauthenticated
  `POST /intake/website-form` `401` — all matched the expected/documented
  contract (the GET/POST difference is expected; the two methods exercise
  different validation paths).
- Database integrity: `PRAGMA integrity_check` = `ok`.
- Runtime verifier: `infra/deploy/verify_pdf_runtime.py --host-runtime`
  (with `/home/viktor/.local/uv-bootstrap-venv/bin` on `PATH`) reported
  `OVERALL: OK`, `READY_WITHOUT_OVERRIDE` for both `catering-office-api` and
  `catering-office-panel`.
- Pre-migration database backup:
  `/home/viktor/catering-runtime/predeploy-backups/core-pre-runtime-migration-20260728-191432.db`
  — 471040 bytes, SHA-256
  `82afe9dd5c758279446ce426c49adf3673adfd52f5a45dea6f3f42e99ce1642e`,
  `integrity_check: ok`.
- Rollback: **not required.** Rollback assets (database backup above,
  previous venv at `.venv.pre-runtime-migration.20260728-191831`, and the
  removed systemd overrides archived at
  `/home/viktor/catering-runtime/backups/systemd-runtime-migration.20260728-191449/`)
  were retained, not deleted.

## Resolved — systemd interpreter mismatch

The previously-tracked risk here (tracked units declaring
`ExecStart=/usr/bin/python3 ...` while production ran `.venv/bin/python3`
through an untracked drop-in override) is **resolved** as of the PDF runtime
migration below. The tracked unit files now declare the venv interpreter
directly (PR #46), production runtime is reproduced from a committed
`uv.lock` (PR #45), and the untracked overrides have been removed —
`DropInPaths` is empty for both office services, confirmed by
`infra/deploy/verify_pdf_runtime.py --host-runtime` (PR #48). See "Deployed
and closed" below for full detail.

## Next action

1. Run the artificial end-to-end pre-launch validation.

### Deployed and closed

**PDF_RUNTIME_VENV_AND_SYSTEMD_MIGRATION_V1 — DEPLOYED, CLOSED**

- Production fast-forwarded **2026-07-28** from `a67875d800deff7a954e9c83d42174c41b647326`
  to `ab0743f229b525b348ebdc6cfd71c2fac7ba153e`, deploying PR #42 (PDF startup
  ordering and error handling), PR #45 (committed `uv.lock` and uv-based
  reproducibility), PR #46 (tracked office units use the project `.venv`),
  and PR #48 (read-only PDF runtime/systemd verifier).
- Runtime reproduced from the committed `uv.lock` via
  `uv sync --frozen --no-dev` (Python `3.13.5`, `reportlab==5.0.0`); dev
  dependencies are not required in the production runtime.
- `uv 0.11.32` is installed separately in
  `/home/viktor/.local/uv-bootstrap-venv` (an isolated bootstrap venv, not a
  system-wide install); the host-runtime verifier requires that path on
  `PATH`.
- Tracked systemd units for both office services now declare
  `/home/viktor/projects/silberloeffel-catering/.venv/bin/python3`; the
  previously-installed compatible overrides were removed from the active
  systemd configuration and archived (not deleted) — see "Deployment
  verification" above.
- Restart scope: `catering-office-api` and `catering-office-panel` only, at
  `2026-07-28 20:42:33 CEST`; `catering-kiosk` and `catering-website-intake`
  were **not** restarted.
- Production now has repository-specific, read-only GitHub access
  configured through repo-local `core.sshCommand`; the remote URL was not
  changed.

**PR #42 — PDF startup preflight ordering and configuration documentation —
DEPLOYED, CLOSED**

- Merged **2026-07-27** into `main` (merge commit `03a3780e699357c30e36049f1293f5a93a214f6f`); issue #41 closed.
- Fixes direct-mode Office Panel validating `OFFICE_PDF_*` configuration
  *after* opening `core.db` and applying migrations; hardens
  `OFFICE_PDF_LOGO_PATH` error handling; documents the full `OFFICE_PDF_*`
  contract in `.env.example` and the Lenovo runbook.
- Deployed to production as part of the `ab0743f` fast-forward above.

**PR #38 — catalog price-history response handling — DEPLOYED, CLOSED**

- Merged **2026-07-27**; issue #37 closed.
- Deployed to production as part of the `a67875d` fast-forward (same
  deployment as PR #40 below).
- Fixes `RemoteCoreClient.catalog_dish_detail` rejecting any dish that has
  price history.

**PR #40 — structured Offer/PDF error handling — DEPLOYED, CLOSED**

- Merged **2026-07-27**; issue #39 closed.
- Deployed to production as part of the `a67875d` fast-forward.
- Fixes `RemoteCoreClient` masking structured Offer/PDF business errors
  (`offer_document_blocked`, `confirmation_document_blocked`,
  `order_not_ready_to_send`) as a generic `502`.

**INQUIRY_CUSTOMER_REFERENCE_AND_SNAPSHOT_DEPLOY_V1 — CLOSED**

- Deployed **2026-07-20**: application commit `ad810b4`; inquiries migration **v4**
  `add_customer_reference` applied via canonical `SQLiteInquiryRepository` path.
- Restart scope: Office API + Office Panel only; kiosk **not restarted**.
- Additive columns on `inquiries`: `customer_id`, `snapshot_company_name`,
  `snapshot_contact_name`, `snapshot_email`, `snapshot_phone` (all nullable).
- `schema_migrations` **24 → 25**; all **33** existing Inquiry rows have NULL in
  new columns; no automatic matching or CustomerIdentity creation.
- CustomerIdentity tables remain **0/0**; Order/OrderVersion schema unchanged.
- Rollback backup:
  `/home/viktor/catering-runtime/backups/core.db.before-inquiry-customer-reference-20260720T081400Z`
  (mode 600, integrity ok).
- Post-deploy acceptance: API queue/inquiries/detail HTTP **200**;
  `customer_id`/`customer_snapshot` null on legacy Inquiry; contacts API **200**;
  Panel `/` and `/rueckruf` **200**; kiosk **200**; ContactProjection **17**
  contacts; journals since restart clean.

**DASHBOARD_CALENDAR_WEEK_FIX_V1 — CLOSED**

- Deployed **2026-07-20** via `catering-office-panel.service` restart only.
- Application commits loaded: `5000d6f` (Berlin operating date in direct
  Startseite), `cf2edb5` (test alignment; no additional runtime behavior).
- Source disk HEAD at restart: `5d47c8e` (includes docs-only lineage; no extra
  application behavior vs `cf2edb5`).
- Office API **not restarted** — unchanged code path; already used
  `office_api_views.berlin_today()`.
- Kiosk **not restarted** (PID unchanged).
- No DB migration; aggregate counts unchanged (33/24/33); CustomerIdentity
  tables remain empty (0/0); `schema_migrations` **24**.
- Production acceptance: dashboard `/` and `/rueckruf` HTTP **200**; dashboard
  KW matches `Europe/Berlin` operating date (verified KW **30/2026** on
  2026-07-20); direct/remote parity tests green; journal since restart clean.


**CORE_DB_PERMISSION_FIX_V1 — CLOSED**

- Applied **2026-07-20**: `chmod` on production DB only — mode **644 → 600**.
- Owner/group unchanged: **viktor:viktor**.
- DB SHA-256 unchanged:
  `dc501fae0259b6a791ad6ab3ebddea8a1db81a470db934820bc71b48032a5ba0`.
- Size unchanged (**700416**); `PRAGMA integrity_check` **ok**; no SQL writes.
- Services **not restarted** (Office API, Office Panel, kiosk PIDs unchanged).
- Post-change smoke: API read, dashboard `/`, `/rueckruf`, kiosk — HTTP **200**;
  journals without new database permission errors.

**CORE_CUSTOMER_IDENTITY_FOUNDATION_V1 — CLOSED**

- Office API and Office Panel restarted on `924f1c0` (2026-07-20 ~00:24 CEST).
- Production DB has additive schema: `customer_identities`, `phone_contact_points`.
- Migration markers present (one per component); tables **empty** (0/0).
- Inquiry/Order row counts unchanged from pre-migration baseline (33/24/33).
- Rollback backup:
  `/home/viktor/catering-runtime/backups/core.db.before-customer-identity-20260719T221452Z`
  (mode 600, integrity ok).

**AUERSWALD_SELF_FAX_CALLBACK_EXCLUSION_V1 — CLOSED**

- Container `auerswald-sync-auerswald-sync-1` running; active `main.py` SHA-256
  `f6ded6233cd815760a8b417699e868baf3097ea4ee7557d2bad2f30b1835d3b6`.
- Self-fax excluded from callback board (deployed 2026-07-19).

**Auerswald missed-board compatibility — CLOSED** (runtime stable; Office
Rückruf pull path operational).

## Production database (aggregate)

| Item | Value |
|---|---|
| Path | `/home/viktor/catering-runtime/core.db` |
| Owner / group | **viktor:viktor** |
| File mode | **600** (hardened 2026-07-20; was 644) |
| SHA-256 (verified unchanged) | `dc501fae0259b6a791ad6ab3ebddea8a1db81a470db934820bc71b48032a5ba0` |
| Integrity | ok |
| `customer_identities` | 0 rows |
| `phone_contact_points` | 0 rows |
| inquiries / orders / order_versions | **33 / 24 / 33** |
| `schema_migrations` | **25** (+ inquiries v4 customer reference; +2 CustomerIdentity markers vs pre-foundation 22) |

## Backups (Core)

| Control | State |
|---|---|
| Daily local cron | 03:15, 14-day retention |
| Encrypted offsite cron | 03:25 |
| Last verified offsite log | **2026-07-19** (`core-2026-07-19.db.gpg`) |
| Backup alerting / stale detection | **not implemented** — see `docs/proposals/BACKUP_HEALTH_AND_ALERTING_V1.md` |

Manual restore drill last verified: **2026-07-12**.

## Auerswald runtime

| Item | Value |
|---|---|
| Container | `auerswald-sync-auerswald-sync-1` (python:3.12-slim), up ~4h at audit |
| HubSpot | `HUBSPOT_ACCESS_TOKEN` **present** in container; manual HTTP endpoints in code; **no automated outbound** observed in logs |
| Auth/direct exposure | accepted operational debt |

Core HubSpot intake remains disabled.

## Courier and Fingerfood

| Project | Repo HEAD | Runtime |
|---|---|---|
| Courier (`courier-app`) | `f2c51a0` | `catering-courier-app.service` **inactive** |
| Fingerfood (`fingerfood-app`) | `74af846` | backup artifacts **2026-07-19**; `fingerfood-backup.timer` **inactive** |

## Quality baseline (repository)

On `03a3780` (historical — see "Repository state" above for the current
`origin/main` HEAD) locally and in GitHub Actions: **2212 passed**, coverage
**90.7%** (≥90% threshold), Ruff and mypy clean. Not re-run at `ab0743f` as
part of this documentation-only update. Documented pre-push gate in
`docs/runbooks/release-discipline.md`.

## Operational risks (open)

### Accepted — Office API process not restarted for calendar-week slice

Office API runtime remains `924f1c0`; functional calendar-week paths already
used `berlin_today()`. Restart was not required for this deploy.

### High — release discipline not server-enforced

Proven: deployment user can direct-push to `main`; prior pushes were not
blocked by required green `quality`. Branch protection may be absent or bypass
may apply — exact configuration requires authenticated owner/admin verification.
Required check target: **`quality`**. Force push must be prohibited. Preferred
flow: PR + required green `quality` (see release discipline runbook).

### High — no backup health alerting

Cron runs, but failure/stale backup does not notify anyone.

### Accepted — HubSpot credential retained in Auerswald

Token configured; automated outbound not observed. Revoke/remove is a separate slice.

### Accepted — Auerswald direct/auth exposure

Unchanged operational debt.

### Accepted — Courier inactive / Fingerfood timer inactive

Non-blocking for Core; noted for operational awareness.

### Accepted — kiosk and website intake stale runtime

Not restarted with recent Core changes; CustomerIdentity bootstrap not invoked there
(kiosk has no bootstrap helper).

## Verified recovery controls

Recovery-key protection verified on **2026-07-12** (unchanged):

- working private key on Mac only;
- password-protected AES-256 recovery archive restore-tested;
- no private key or archive password in Git, Lenovo, or VPS.

## Next milestones

1. **Branch protection verification** — owner/admin authenticated review; require green `quality`; block force push.
2. **BACKUP_HEALTH_AND_ALERTING_V1** — failure/stale notification.
