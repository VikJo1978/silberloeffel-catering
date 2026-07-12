# Deployment

This file is the stable entry point for deployment documentation. Environment-
specific procedures live in maintained runbooks:

- [Lenovo production deployment](docs/runbooks/lenovo-production.md)
- [VPS staging deployment](docs/runbooks/vps-staging.md)
- [Backup and restore](docs/runbooks/backup-restore.md)
- [Website intake API and secret rotation](docs/api/website-intake.md)
- [Current live status](docs/current-status.md)

## Before every production deployment

1. Confirm CI passed for the exact commit.
2. Check the production worktree for local changes.
3. Create and verify a pre-deploy SQLite backup.
4. Update by fast-forward only.
5. Restart only the intended services.
6. Verify service state, database integrity, UI smoke tests, and journals.
7. Record the release in `CHANGELOG.md` and update `docs/current-status.md`.

## Boundaries

- Production Core stays on Lenovo.
- Office and kiosk ports are never public.
- Website intake remains loopback-only behind Cloudflare.
- VPS staging contains fake data only and never connects to production.
- No secret value belongs in Git, documentation, or chat logs.

Historical deployment plans are preserved under
[`docs/archive/packs/`](docs/archive/packs/).
