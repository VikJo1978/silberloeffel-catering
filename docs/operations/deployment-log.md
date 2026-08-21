# Production deployment log

This is the concise operational history for production changes. It supplements
`CHANGELOG.md`: the changelog explains what changed in the product; this file
records what actually reached production, what was backed up and how it was
verified.

Never record credentials, customer payloads, bearer tokens or private keys here.

## 2026-08-21 — Order hard-delete FK fix

| Item | Evidence |
|---|---|
| Host | `debiancatering` |
| Previous production commit | `60f50c8ddd0bb5532bd673290d7d0b248819d4da` |
| Deployed commit | `4eadf014654992619be317c8b3b079c5d8dcd26b` |
| Main change | PR #145, transitive FK purge + rollback after COMMIT failure |
| Pre-restart DB backup | `/home/viktor/catering-runtime/core.db.backup-20260821-080351` |
| Restarted service | `catering-office-api.service` |
| Service result | `active` |
| Production functional proof | `POST /office/v1/orders/{id}/delete` committed with HTTP/status `200` at `2026-08-21 08:05:28 CEST` |
| Regression symptom after deploy | no new `FOREIGN KEY constraint failed`; no new `cannot start a transaction within a transaction` |
| Deployment path | private `VikJo1978/silberloeffel-ops` self-hosted runner → restricted `/usr/local/sbin/catering-ops` wrapper |
| Result | **SUCCESS** |

Before deployment, four unrelated local Kitchen Phase 3B changes were discovered
on the production checkout. They were preserved on branch
`wip/kitchen-print-lenovo-phase3b` before the checkout was cleaned and
fast-forwarded. Live Kitchen units remain active and are tracked as configuration
drift until that branch is reviewed and reconciled with `main`.

## Record template

Copy this block for future deployments:

```text
## YYYY-MM-DD — <short purpose>

Host:
Previous production commit:
Target/deployed commit:
Pull request(s):
Database backup path:
Services restarted:
Migration(s):
Smoke/functional checks:
Journal result:
Rollback required: yes/no
Result: SUCCESS / ROLLED BACK / PARTIAL
Operator notes:
```

## Minimum evidence rule

A deployment is not considered documented until these four facts exist:

1. exact deployed commit;
2. exact database backup path for Core-writing changes;
3. exact services restarted;
4. at least one post-restart health or functional verification result.

GitHub merge time alone is not deployment evidence.
