# BACKUP_HEALTH_AND_ALERTING_V1 (proposal)

Status: **not implemented** — audit recorded **2026-07-19T22:58:14Z**.

## Current backup truth (Lenovo Core)

| Signal | How determined today |
|---|---|
| Last successful local backup | Newest `core-YYYY-MM-DD.db` in `/home/viktor/catering-runtime/backups/` (cron **03:15**) |
| Last successful offsite transfer | Last `off-site backup verified:` line in `offsite-backup.log` (cron **03:25**) |
| Verified offsite as of audit | **2026-07-19** (`core-2026-07-19.db.gpg`) |
| CustomerIdentity rollback backup | `core.db.before-customer-identity-20260719T221452Z` (mode 600, integrity ok) |
| Failure notification | **none** |
| Stale-backup detection | **none** |
| Heartbeat / external monitor | **none** |

Auerswald and Fingerfood have separate backup scripts/artifacts; no unified alerting.

## Gaps

1. Cron failure is silent unless someone reads logs.
2. Offsite success is log-only; no alert on missing daily `.gpg`.
3. No maximum-age alarm (e.g. backup older than 26 hours).
4. No automated cross-check that backup aggregate row counts match production.

## Next slice scope (minimal)

1. Post-backup verification script (integrity + aggregate counts) exiting non-zero on failure.
2. Wrapper or timer that alerts on failure (mail/Tailscale webhook — owner choice).
3. Stale-backup detector for local and offsite artifacts.
4. Runbook section for expected paths and retention.
5. Optional: extend existing `validate-*-backup.py` patterns.

Out of scope for V1 proposal: full observability platform, PagerDuty, production schema changes.
