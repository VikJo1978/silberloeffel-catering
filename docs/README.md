# Project documentation

This directory is the maintained source of truth for understanding and
operating the Silberlöffel Catering System. Start with the current documents;
use the archive only when the reasoning behind an older implementation is
needed.

## Current documentation

| Area | Document | Purpose |
|---|---|---|
| Status | [Current status](current-status.md) | Live services, verified facts, open risks |
| Design | [Architecture](architecture.md) | Components, data flow, invariants |
| Production | [Lenovo runbook](runbooks/lenovo-production.md) | Deploy, verify, troubleshoot, roll back |
| Staging | [VPS runbook](runbooks/vps-staging.md) | Temporary site at the public IP |
| Data safety | [Backup and restore](runbooks/backup-restore.md) | SQLite backup, verification, recovery |
| Integration | [Website intake API](api/website-intake.md) | Payloads, responses, authentication |
| Integration | [Kiosk order feed API](api/kiosk-order-feed.md) | Per-date courier feed contract |
| Users | [Office panel guide](user/office-panel.md) | Daily office workflow and gates |
| Decisions | [Decision register](decisions/README.md) | Durable architectural decisions |
| Releases | [Changelog](../CHANGELOG.md) | User-visible and operational changes |
| Security | [Security policy](../SECURITY.md) | Exposure rules and credential handling |

## Documentation rules

1. **Facts beat plans.** Runbooks describe the configuration actually running.
2. **No secrets.** Use variable names and paths, never values.
3. **One owner per fact.** Architecture explains why; runbooks explain how;
   changelog records when.
4. **Every production change updates docs.** At minimum update current status,
   the affected runbook, and the changelog.
5. **Historical packs stay immutable.** Superseded plans move to the archive and
   are not silently rewritten as current truth.

## Historical material

- [Implementation and execution packs](archive/packs/README.md)
- [Chronological legacy worklog](../WORKLOG.md)

The legacy worklog is useful for archaeology but is no longer the primary
status page. New current-state information belongs in `current-status.md` and
release information belongs in `CHANGELOG.md`.
