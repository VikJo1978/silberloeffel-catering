# Current status

Operational truth last verified: **2026-07-27T11:32:00Z** (PR #42 merge and
post-merge repository/production alignment check).

This document separates **repository state** (what is on `origin/main`) from
**production state** (what is actually deployed and running on Lenovo
`debiancatering`, Tailscale `100.109.6.74`). A commit on `origin/main` is not
deployed until the relevant services have restarted while that commit (or a
descendant loaded at restart) is on disk, and post-deploy checks are
recorded. See `docs/runbooks/deployment-truth-checklist.md`.

## Repository state

| Item | Value |
|---|---|
| `origin/main` HEAD | `03a3780e699357c30e36049f1293f5a93a214f6f` (`03a3780`) |
| Latest merged PR | [#42 — Fix PDF startup preflight ordering and document configuration contract](https://github.com/VikJo1978/silberloeffel-catering/pull/42) (merge commit `03a3780e699357c30e36049f1293f5a93a214f6f`, parents `a67875d8` + `5f4df5e6`) |
| CI on the merged commit | `quality` — **pass** (both required checks green at merge time) |
| Full test suite at this commit (locally verified during review) | **2212 passed**, coverage **90.7%** (≥90% threshold), Ruff/mypy clean |

**Do not treat the SHA above as permanent:** query Git for the current value;
repository HEAD advances with every merge. Docs-only commits (including this
update) change repository HEAD but are **not** application deployments —
production state below remains authoritative until services restart.

## Production state

| Item | Value |
|---|---|
| Deployed commit | `a67875d800deff7a954e9c83d42174c41b647326` (`a67875d`) |
| Relationship to `origin/main` | **one merge behind** — production does not yet include PR #42 |
| Merged-but-not-yet-deployed changes | **PR #42 only** — [Fix PDF startup preflight ordering and document configuration contract](https://github.com/VikJo1978/silberloeffel-catering/pull/42) (closes issue #41). Not deployed; do not treat it as running in production. |
| Release discipline (proven) | deployment user can direct-push to `main`; prior pushes were not blocked by required green `quality`; branch protection may be absent or the user may have bypass — exact settings require authenticated owner/admin verification (see `docs/runbooks/release-discipline.md`) |

## Production services

Last verified observation: **2026-07-27**, immediately after the `a67875d`
deploy and its post-deploy observation pass. **These are a point-in-time
snapshot, not permanent expected values** — re-verify with `systemctl show`
before relying on them.

| Service | PID | Started (CEST) |
|---|---|---|
| `catering-office-api` | 427823 | 2026-07-26 22:52:29 |
| `catering-office-panel` | 435026 | 2026-07-27 08:49:50 |
| `catering-website-intake` | 362683 | 2026-07-22 22:50:09 |
| `catering-kiosk` | 332509 | 2026-07-21 00:36:38 |

Only `catering-office-panel` was restarted for the `a67875d` deploy (the only
service whose import graph is affected by that commit's change); the other
three retained their prior PID/start time, confirming they were not touched.

## Deployment verification (`a67875d`)

- HTTP checks: Office API `401`, Office Panel `401`, Kiosk `200`, Website
  Intake `405` — all matched the expected/documented contract.
- Database and backup integrity: `PRAGMA integrity_check` = `ok` on both the
  live database and the pre-deploy backup.
- Backup: `/home/viktor/catering-runtime/core.db.pre-a67875d-deploy.20260727-084522.bak`
  — 471040 bytes, SHA-256
  `82afe9dd5c758279446ce426c49adf3673adfd52f5a45dea6f3f42e99ce1642e`.
- Rollback: **not required.**

## Current known risk — systemd interpreter mismatch

The tracked unit files (`infra/systemd/catering-office-api.service`,
`infra/systemd/catering-office-panel.service`) still declare
`ExecStart=/usr/bin/python3 ...`. Production actually runs
`.venv/bin/python3 ...` through an **untracked** `systemd` drop-in override
(`/etc/systemd/system/catering-office-*.service.d/override.conf`) that exists
only on the host, not in this repository. Do not reinstall the tracked unit
files as-is before this is resolved — doing so would silently revert
production to the system interpreter, which lacks `reportlab` and has
already caused one real crash-loop incident. This is tracked as the next
slice below (`PDF_RUNTIME_VENV_AND_SYSTEMD_V1`), not fixed yet.

## Next action

1. Review and implement `PDF_RUNTIME_VENV_AND_SYSTEMD_V1` (tracked systemd
   interpreter alignment, production venv/runtime reproducibility,
   dependency lock strategy, non-mutating runtime verification tooling —
   not implemented yet).
2. Deploy PR #42 to production only through a controlled deploy, either
   together with or before Slice 2.
3. Then run the artificial end-to-end pre-launch validation.

### Deployed and closed

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

### Merged, not yet deployed

**PR #42 — PDF startup preflight ordering and configuration documentation —
MERGED, NOT DEPLOYED**

- Merged **2026-07-27** into `main` (merge commit `03a3780e699357c30e36049f1293f5a93a214f6f`); issue #41 closed.
- Fixes direct-mode Office Panel validating `OFFICE_PDF_*` configuration
  *after* opening `core.db` and applying migrations; hardens
  `OFFICE_PDF_LOGO_PATH` error handling; documents the full `OFFICE_PDF_*`
  contract in `.env.example` and the Lenovo runbook.
- **Production is still on `a67875d` and does not include this change.** Do
  not deploy without a controlled deploy per the runbook; see "Next action"
  above.

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

On `03a3780` (current `origin/main`) locally and in GitHub Actions: **2212
passed**, coverage **90.7%** (≥90% threshold), Ruff and mypy clean.
Documented pre-push gate in `docs/runbooks/release-discipline.md`.

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
