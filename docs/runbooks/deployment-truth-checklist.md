# Deployment truth checklist

Mandatory after **every** production deploy. A deploy is **not CLOSED** until
this checklist is complete, `docs/current-status.md` is updated, and the docs
update is committed and pushed to `main`.

## Core rule

**Presence of a commit in a checkout or on `origin/main` does not prove that a
process loaded that commit.** Runtime truth requires restart evidence and
post-deploy verification. A **docs-only commit** on `main` is not an application
deployment and does not change production runtime truth.

## Before deploy

- [ ] Confirm intended **source commit** (usually `origin/main`) and **parent/rollback** SHA.
- [ ] Confirm canonical checkout is clean (or document intentional divergence).
- [ ] Run local pre-push / official gates when changing code (see release discipline).
- [ ] Capture production baseline per service: MainPID, ActiveEnterTimestamp, runtime commit estimate, DB file hash/mode, aggregate row counts, `PRAGMA integrity_check`.
- [ ] Create consistent DB backup (SQLite `.backup` API) when schema or data risk exists.
- [ ] Run migration dry-run on a disposable copy when schema changes are involved.

## Deploy

- [ ] Fast-forward or merge only — no force push.
- [ ] Restart **only** services that must load changed code (record exact units and order).
- [ ] Apply schema changes only via official startup bootstrap — no ad-hoc SQL on production.
- [ ] For shared-schema services: typically Office API first, then Office Panel.

## Record for each deploy (minimum)

| Field | Required |
|---|---|
| Source commit SHA (intended) | yes |
| **Deployed runtime commit** per restarted service | yes |
| Parent / rollback commit SHA | yes |
| Service restart timestamps (per unit) | yes |
| DB migration status (none / additive / …) | yes |
| Smoke results (HTTP/journal; auth as applicable) | yes |
| Aggregate Inquiry/Order counts unchanged (if no data migration) | yes |
| Pre-deploy backup path + hash | yes |
| Rollback readiness confirmed | yes |
| GitHub `quality` check green on source commit | yes (before or after push, as applicable) |

## Smoke minimum (Core)

- Office API: active, journal without traceback/IntegrityError/database locked.
- Office Panel: dashboard and `/rueckruf` HTTP 200 with correct auth.
- Kiosk: verify only if deliberately restarted.
- `PRAGMA integrity_check` on production DB: ok.

## Close deploy

- [ ] Update `docs/current-status.md` with verified **production runtime truth** (not just git HEAD).
- [ ] Commit and push the operational-truth update to `main`.
- [ ] Do **not** mark a slice CLOSED in prose until runtime commit and checks match.

Deploy is **not CLOSED** without the operational-truth doc update on `main`.
