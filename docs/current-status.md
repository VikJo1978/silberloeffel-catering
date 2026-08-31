# Current status

Operational truth last updated: **2026-08-31**.

This file is a **current operational snapshot**, not a deployment diary. Historical
details remain available in Git history, merged pull requests, issue history and the
runbooks under `docs/runbooks/`.

Repository state and production state are deliberately kept separate. A commit on
`origin/main` is not production until the relevant service has loaded it and the
deployment has been checked.

## Current repository state

| Item | Value |
|---|---|
| `origin/main` HEAD before this docs update | `ed78e8211a4edf293e695aa770aa8a3752b20bd7` (`ed78e82`) |
| Commit | `Implement Courier cash handoff runtime V1 (#213)` |
| CI immediately before #213 merge | **green** — PR head `79d2316`, run `33395580432` |
| Open issues after backlog cleanup | **0** |
| Open pull requests after backlog cleanup | **0** |
| Working release flow | branch → PR → green CI → merge → production fast-forward |

The repository had accumulated old stacked and superseded pull requests from earlier
architecture slices. On 2026-08-27 they were reviewed against current `main` and all
remaining stale PRs were closed. Their branches and Git history remain available for
archaeology, but they are not active implementation work.

## Production state

Production host: `debiancatering`.

| Item | Value |
|---|---|
| Application repository | `/home/viktor/projects/silberloeffel-catering` |
| Core DB | `/home/viktor/catering-runtime/core.db` |
| Deployed application commit | `ed78e8211a4edf293e695aa770aa8a3752b20bd7` (`ed78e82`) |
| Relationship to application `main` before this docs-only update | **matches** |
| Latest functional deployment scope | Courier cash handoff rollout across Core Office API, Kiosk, Office Panel and Courier app |
| Latest functional verification | machine-route auth gates, shared bearer, Kiosk order-feed, Courier service and service health verified; no real BAR order exists yet for E2E |
| Office Panel unauthenticated health behavior | HTTP `303` redirect, expected |
| Office API after cash rollout | `active` on `100.109.6.74:8084`, restarted with the cash service bearer configured |

The latest application change (#195) was deployed after its post-merge CI passed.
The operator then verified the manual-task detail flow interactively in production.
No database migration was part of #188, #190, #192 or #194/#195.

This documentation commit must **not** be treated as a reason to restart production
services. It changes operational documentation only.


## Courier cash handoff production rollout

The frozen Courier cash-handoff contract is now activated on the Lenovo production
host.

- Core is deployed at `ed78e8211a4edf293e695aa770aa8a3752b20bd7`
  (`ed78e82`, PR #213).
- Courier is deployed at `f3419a40cabd53bd9badc900ddf40a9426e0a863`
  (`f3419a4`, courier-app PR #16).
- `catering-office-api` is active on `100.109.6.74:8084`.
- `catering-courier-app` is active on `0.0.0.0:8090`.
- `catering-kiosk` is active on `0.0.0.0:8082` and loaded the new
  `cash_handoff` projection code.
- Core and Courier use the same dedicated `COURIER_CASH_SERVICE_TOKEN`; its
  value remains only in the production environment files.
- An unauthenticated POST to the cash machine route returns `401`.
- The same route with the configured bearer and an intentionally empty payload
  reaches request validation and returns `400`, proving authentication and
  connectivity without creating a cash event.
- Kiosk root and order-feed checks return `200`; the kiosk journal records
  `pickup signal refresh succeeded`.
- Production currently contains zero `BAR_VOR_ORT` payment reminders, so a
  truthful end-to-end cash handoff cannot yet be exercised.

No synthetic BAR order was created in production merely to force the last E2E
step. The first real BAR order is the production E2E candidate.

## Current Office task workflow

Manual office tasks are now a first-class Office workflow:

- persisted manual tasks are exposed in `/aufgaben`;
- open manual tasks are included in the Arbeitszentrale together with system tasks;
- priority is explicit (`HIGH`, `NORMAL`, `LOW`) and ranks before due date;
- a task may reference Kontakt, Anfrage, Angebot, Auftrag or no subject;
- the Bezug picker is searchable and category-filterable;
- its inline JavaScript is permitted by CSP only through an exact SHA-256 hash;
- Safari hidden-state behavior is explicitly covered;
- a manual task opens its own `/aufgaben/{task_id}` detail page;
- title, description, priority, due date, assignee, status and Bezug are readable
  before navigating to the referenced business object;
- `Bezug öffnen` remains a separate action;
- completion remains permission-controlled.

Relevant completed work:

| Issue / PR | Result |
|---|---|
| #182 / #185 | manual tasks exposed in Aufgaben UI |
| #186 / #187 | manual tasks integrated into Arbeitszentrale with priority and subject links |
| #188 / #189 | searchable, category-first Bezug picker |
| #190 / #191 | reliable hidden-state handling in Safari |
| #192 / #193 | strict CSP hash authorization for the picker script |
| #194 / #195 | readable manual-task detail page before Bezug navigation |

## Customer recommendation / repeat-customer foundation

Issue #152 is completed in current `main`.

The current model keeps **factual order history separate from explicit customer
preferences**. Recommendation hints are derived and explainable rather than silently
rewriting customer facts. This remains the intended boundary for future recommendation
work.

## Logistics / kiosk work

The current repository includes the completed logistics timing and return-logistics
work from #171 and #175. Older stacked Kitchen Execution / Delivery Execution PRs from
the earlier August branch series were reviewed during backlog cleanup and closed as
obsolete rather than merged into the much newer architecture.

Closing those PRs did not delete their branches or history.

## Runtime / release controls

The established production deployment discipline remains:

1. exact target commit has green CI;
2. production worktree must be clean;
3. DB-affecting deploys require backup and integrity verification;
4. production updates use `git merge --ff-only origin/main`, never a hard reset;
5. restart only services affected by the change;
6. verify service state, HTTP behavior and journals after restart;
7. documentation changes go through Git/PR and do not dirty the production worktree.

Runtime continues to use the project virtual environment and committed dependency lock
established by the earlier PDF runtime migration.

## Known operational risks

### High — branch protection is not independently verified

The GitHub integration used for this update cannot read the branch-protection endpoint
(it returns HTTP 403 to the integration), so server-side enforcement has **not** been
re-verified here.

The desired state remains:

- PR required for `main`;
- green CI required before merge;
- force push disabled;
- direct push prevented or tightly controlled.

Until owner/admin verification proves that state, release discipline remains partly a
process control rather than a guaranteed server-side control.

### High — no backup health / stale-backup alerting

The repository still contains
`docs/proposals/BACKUP_HEALTH_AND_ALERTING_V1.md`; automated failure/staleness
notification is not recorded as implemented.

Backups should not be considered operationally healthy merely because cron jobs exist.
A silent failed backup is just a scheduled confidence trick.

### Accepted / reverify before relying on old runtime notes

Older status snapshots contained point-in-time facts about Auerswald, Courier,
Fingerfood, kiosk and website-intake runtime state. Those July snapshots are no longer
promoted here as current truth. Re-check the actual services when work on those
components resumes.

## Recovery controls

Production DB changes continue to require a pre-deploy backup when migrations or other
DB-affecting work are involved.

Existing recovery and deployment runbooks remain under `docs/runbooks/`. Historical
backup hashes, PIDs and old deployment timestamps belong in deployment evidence and Git
history, not in this living status page.

## Next action

**Exercise the Courier cash handoff on the first real `BAR_VOR_ORT` order.**

Do not create synthetic production customer/order data solely for this check.
When the first real BAR order exists, verify the coherent path:

1. current Quittung is printed;
2. driver records receipt from the customer and Quittung handoff;
3. driver records handoff to the chef;
4. chef confirms receipt from the driver;
5. Core reaches `FINAL_PAID`;
6. journals, idempotency state and both SQLite databases remain healthy.

Until such an order exists, the cash rollout is operationally complete at the
infrastructure/contract level. General application E2E validation may continue
independently.
