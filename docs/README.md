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
| Production | [Kitchen print agent](runbooks/KITCHEN_PRINT_AGENT_OPERATIONS.md) | CUPS, agent systemd, fault injection, first live print |
| Staging | [VPS runbook](runbooks/vps-staging.md) | Temporary site at the public IP |
| Staging | [6D-3a smoke test](runbooks/STAGING_SMOKE_6D3A.md) | Catalog → Configurator → Offer → Print manual checklist |
| Data safety | [Backup and restore](runbooks/backup-restore.md) | SQLite backup, verification, recovery |
| Integration | [Website intake API](api/website-intake.md) | Payloads, responses, authentication |
| Integration | [Kiosk order feed API](api/kiosk-order-feed.md) | Per-date courier feed contract |
| Integration | [Core Office API](api/core-office-api.md) | Office panel commands and reads (Phase 1, dormant) |
| Integration | [Kiosk pickup signal API](api/kiosk-pickup-signal.md) | Open equipment-return feed and kiosk cache |
| Design | [Offer contract V1](proposals/offer_contract_v1.md) | Draft commercial snapshot and acceptance boundary |
| Design | [Office Panel UI v2 implementation pack](proposals/OFFICE_PANEL_UI_V2_IMPLEMENTATION_PACK_V1.md) | Presentation-only migration plan and invariants |
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
