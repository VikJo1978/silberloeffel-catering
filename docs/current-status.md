# Current status

Operational truth last verified: **2026-07-19T22:58:14Z** (read-only audit on
Lenovo `debiancatering`, Tailscale `100.109.6.74`).

This document separates **repository truth** from **production runtime truth**.
A commit on `origin/main` is not deployed until the relevant services have
restarted while that commit (or a descendant loaded at restart) is on disk,
and post-deploy checks are recorded. See
`docs/runbooks/deployment-truth-checklist.md`.

## Repository truth

At audit time (**2026-07-19T22:58:14Z**), `git rev-parse origin/main` reported
`cf2edb568d2577f3d0cc06c534a295b861138e76`. **Do not treat a SHA printed here
as permanent:** after this document is committed and pushed, repository HEAD
advances — query Git for the current value.

| Item | Value (at audit) |
|---|---|
| Last verified **application-code** commit on `main` | `cf2edb568d2577f3d0cc06c534a295b861138e76` (`cf2edb5`) |
| Preceding application commit on same line | `5000d6f` (calendar-week runtime fix) |
| GitHub Actions `quality` on `cf2edb5` | **success** — run [29706686826](https://github.com/VikJo1978/silberloeffel-catering/actions/runs/29706686826) |
| Canonical checkout (`/home/viktor/projects/silberloeffel-catering`) | `924f1c0ddba34fa7cbe93920ee81e0fc45184646` (behind last verified application commit; not yet fast-forwarded) |
| Release discipline (proven) | deployment user can direct-push to `main`; prior pushes were not blocked by required green `quality`; branch protection may be absent or the user may have bypass — exact settings require authenticated owner/admin verification (see `docs/runbooks/release-discipline.md`) |

**Docs-only commits** (including this operational-truth update) change repository
HEAD but are **not** application deployments. Production runtime truth below
remains authoritative until services restart.

## Production runtime truth

Services load Python from `PYTHONPATH=.../src` at **process start**. Disk
HEAD and in-memory runtime code diverge until each service restarts.

| Service | Unit | Runtime commit | Last restart (CEST) | MainPID | Drift vs last verified app code (`cf2edb5`) |
|---|---|---|---|---|---|
| Office API | `catering-office-api.service` | `924f1c0ddba34fa7cbe93920ee81e0fc45184646` | 2026-07-20 00:24:32 | 305792 | **2 commits behind** (`5000d6f`, `cf2edb5`) |
| Office Panel | `catering-office-panel.service` | `924f1c0ddba34fa7cbe93920ee81e0fc45184646` | 2026-07-20 00:24:49 | 305803 | **2 commits behind** |
| Kitchen kiosk | `catering-kiosk.service` | `02b105246f4801e5732c7d13cfc07ac36a7976b6` | 2026-07-19 06:29:42 | 147681 | **many commits behind** |
| Website intake | `catering-website-intake.service` | `68a1cb0d79b538f10326aef17653a3590f4e2c04` | 2026-07-13 16:51:09 | 75898 | **many commits behind** |

All four units were **active** at verification. Shared DB:
`/home/viktor/catering-runtime/core.db`.

### Undeployed application code (on `main` at audit, not in API/Panel runtime)

Calendar-week **application** fix is **not deployed**. Office API/Panel runtime
remains on `924f1c0`.

| Commit | Subject | Notes |
|---|---|---|
| `5000d6f` | Make dashboard calendar-week parity deterministic | **not deployed** — no restart after push |
| `cf2edb5` | Align diese-woche panel test with Berlin operating date | **not deployed** — test alignment only; same runtime drift |

### Deployed and closed

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
| File mode | **644** (open risk — target 600) |
| Integrity | ok |
| `customer_identities` | 0 rows |
| `phone_contact_points` | 0 rows |
| inquiries / orders / order_versions | **33 / 24 / 33** |
| `schema_migrations` | **24** (+2 CustomerIdentity markers vs pre-foundation 22) |

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

### High — application-code / runtime drift

Last verified application-code commit at audit was `cf2edb5`; Office API/Panel
runtime is `924f1c0`. Calendar-week application fix is **not deployed**.
Canonical checkout is also behind that application baseline. A subsequent
docs-only commit on `main` does not close this drift.

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

### Accepted — production `core.db` mode 644

Should be tightened to 600 in a separate controlled slice.

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

1. **Operational truth docs commit** — this document + runbooks (docs-only; not an application deploy).
2. **Optional controlled deploy** — restart Office API/Panel to pick up
   `5000d6f`/`cf2edb5` application code (calendar-week fix only; no schema change).
3. **Branch protection verification** — owner/admin authenticated review; require green `quality`; block force push.
4. **BACKUP_HEALTH_AND_ALERTING_V1** — failure/stale notification.
5. **INQUIRY_CUSTOMER_REFERENCE_AND_SNAPSHOT_V1** — next Core slice after truth docs.
