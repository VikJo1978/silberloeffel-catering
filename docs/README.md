# Project documentation

This directory is the maintained source of truth for understanding and operating
the Silberlöffel Catering System. Start with the current documents; use the
archive only when the reasoning behind an older implementation is needed.

## Current documentation

| Area | Document | Purpose |
|---|---|---|
| Status | [Current status](current-status.md) | Verified production snapshot and open risks |
| Operations | [Operations hub](operations/README.md) | Service inventory, secrets registry, deployment evidence, recovery |
| Operations | [Service inventory](operations/service-inventory.md) | Live services, ports, paths, env-file locations and drift |
| Operations | [Secrets registry](operations/secrets-registry.md) | Credential names, runtime locations and rotation rules, never values |
| Operations | [Deployment log](operations/deployment-log.md) | What actually reached production and how it was verified |
| Recovery | [Disaster recovery](operations/disaster-recovery.md) | Rebuild order for a lost production host |
| Design | [Architecture](architecture.md) | Components, data flow, invariants |
| Production | [Lenovo runbook](runbooks/lenovo-production.md) | Deploy, verify, troubleshoot, roll back |
| Data safety | [Backup and restore](runbooks/backup-restore.md) | SQLite backup, verification, recovery |
| Staging | [VPS runbook](runbooks/vps-staging.md) | Temporary/staging site operations |
| Staging | [6D-3a smoke test](runbooks/STAGING_SMOKE_6D3A.md) | Catalog → Configurator → Offer → Print manual checklist |
| Integration | [Website intake API](api/website-intake.md) | Payloads, responses, authentication |
| Integration | [Kiosk order feed API](api/kiosk-order-feed.md) | Per-date courier feed contract |
| Integration | [Core Office API](api/core-office-api.md) | Office panel commands and reads |
| Integration | [Kiosk pickup signal API](api/kiosk-pickup-signal.md) | Open equipment-return feed and kiosk cache |
| Design | [Offer contract V1](proposals/offer_contract_v1.md) | Draft commercial snapshot and acceptance boundary |
| Design | [Office Panel UI v2 implementation pack](proposals/OFFICE_PANEL_UI_V2_IMPLEMENTATION_PACK_V1.md) | Presentation-only migration plan and invariants |
| Users | [Office panel guide](user/office-panel.md) | Daily office workflow and gates |
| Decisions | [Decision register](decisions/README.md) | Durable architectural decisions |
| Releases | [Changelog](../CHANGELOG.md) | User-visible and architectural changes |
| Security | [Security policy](../SECURITY.md) | Exposure rules and credential handling |

## Documentation rules

1. **Facts beat plans.** `current-status.md` and runbooks describe verified reality,
   not an intended future state.
2. **No secrets.** Git stores variable names, paths and procedures, never real
   passwords, tokens, recovery codes or private keys.
3. **One owner per fact.** Architecture explains why; runbooks explain how;
   service inventory explains where; deployment log proves what reached production;
   changelog explains product/release changes.
4. **Every production deployment leaves evidence.** Update current status and the
   deployment log; update the affected runbook/inventory when runtime structure
   changes; update the changelog when the product or architecture changes.
5. **Current status stays short.** Move superseded operational facts to the
   deployment log, changelog, worklog or archive instead of accumulating years of
   archaeology on the status page.
6. **Configuration drift is documented, not hidden.** If live systemd/config differs
   from tracked source, record the drift and do not claim `main` can reproduce the
   host until it is reconciled.
7. **Historical packs stay immutable.** Superseded plans move to the archive and
   are not silently rewritten as current truth.

## Secret-storage rule

The target master recovery vault is `Bitwarden / Silberloeffel Catering`.
Production services consume root-readable env files or provider secret stores.
See `operations/secrets-registry.md` for the inventory and naming convention.

## Historical material

- [Implementation and execution packs](archive/packs/README.md)
- [Chronological legacy worklog](../WORKLOG.md)

`WORKLOG.md` remains useful for archaeology, but it is not an operational status
page. Start with `current-status.md` and `operations/README.md` during incidents.
