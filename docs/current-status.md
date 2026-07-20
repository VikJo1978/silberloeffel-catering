# Current status

Operational truth last verified: **2026-07-20T08:30:00Z** (inquiry customer
reference deploy acceptance on Lenovo `debiancatering`, Tailscale `100.109.6.74`).

This document separates **repository truth** from **production runtime truth**.
A commit on `origin/main` is not deployed until the relevant services have
restarted while that commit (or a descendant loaded at restart) is on disk,
and post-deploy checks are recorded. See
`docs/runbooks/deployment-truth-checklist.md`.

## Repository truth

At deploy verification (**2026-07-20T08:30:00Z**), `git rev-parse origin/main` reported
`ad810b40722330152133df53452f8ba190ed2cd6`. **Do not treat a SHA printed here
as permanent:** after this document is committed and pushed, repository HEAD
advances — query Git for the current value.

| Item | Value (at audit) |
|---|---|
| Last verified **application-code** commit deployed (API/Panel) | `ad810b40722330152133df53452f8ba190ed2cd6` (`ad810b4`) |
| Repository HEAD at verification | `ad810b40722330152133df53452f8ba190ed2cd6` |
| GitHub Actions `quality` on `ad810b4` | **success** — run [29726086008](https://github.com/VikJo1978/silberloeffel-catering/actions/runs/29726086008) |
| Canonical checkout (`/home/viktor/projects/silberloeffel-catering`) | `ad810b40722330152133df53452f8ba190ed2cd6` (matches `origin/main` at verification) |
| Release discipline (proven) | deployment user can direct-push to `main`; prior pushes were not blocked by required green `quality`; branch protection may be absent or the user may have bypass — exact settings require authenticated owner/admin verification (see `docs/runbooks/release-discipline.md`) |

**Docs-only commits** (including this operational-truth update) change repository
HEAD but are **not** application deployments. Production runtime truth below
remains authoritative until services restart.

## Production runtime truth

Services load Python from `PYTHONPATH=.../src` at **process start**. Disk
HEAD and in-memory runtime code diverge until each service restarts.

| Service | Unit | Runtime commit | Last restart (CEST) | MainPID | Notes |
|---|---|---|---|---|---|
| Office API | `catering-office-api.service` | `ad810b40722330152133df53452f8ba190ed2cd6` | 2026-07-20 10:22:11 | 322811 | inquiry customer reference **deployed** |
| Office Panel | `catering-office-panel.service` | `ad810b40722330152133df53452f8ba190ed2cd6` | 2026-07-20 10:22:15 | 322821 | inquiry customer reference **deployed** |
| Kitchen kiosk | `catering-kiosk.service` | `02b105246f4801e5732c7d13cfc07ac36a7976b6` | 2026-07-19 06:29:42 | 147681 | **unchanged** (not restarted) |
| Website intake | `catering-website-intake.service` | `68a1cb0d79b538f10326aef17653a3590f4e2c04` | 2026-07-13 16:51:09 | 75898 | **many commits behind** |

All four units were **active** at verification. Shared DB:
`/home/viktor/catering-runtime/core.db`.

### Deployed and closed

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

On `cf2edb5` locally and in GitHub Actions: **1376 passed**, coverage **≥90%**,
Ruff and mypy clean. Documented pre-push gate in
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
