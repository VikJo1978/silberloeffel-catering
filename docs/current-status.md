# Current status

Operational truth last updated: **2026-08-27**.

This file is a **current operational snapshot**, not a deployment diary. Historical
details remain available in Git history, merged pull requests, issue history and the
runbooks under `docs/runbooks/`.

Repository state and production state are deliberately kept separate. A commit on
`origin/main` is not production until the relevant service has loaded it and the
deployment has been checked.

## Current repository state

| Item | Value |
|---|---|
| `origin/main` HEAD before this docs update | `12cae6c8c3f1f8c7a59dfd42617f3f9d5b95854f` (`12cae6c`) |
| Commit | `Add readable manual task detail from Arbeitszentrale (#195)` |
| CI on that exact application SHA | **green** — run `33054612576` |
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
| Deployed application commit | `12cae6c8c3f1f8c7a59dfd42617f3f9d5b95854f` (`12cae6c`) |
| Relationship to application `main` before this docs-only update | **matches** |
| Latest functional deployment scope | Office Panel only |
| Latest functional verification | manual task detail opened successfully in production |
| Office Panel unauthenticated health behavior | HTTP `303` redirect, expected |
| Office API during the preceding panel deploy smoke | `active`; API was not restarted by the latest panel-only slices |

The latest application change (#195) was deployed after its post-merge CI passed.
The operator then verified the manual-task detail flow interactively in production.
No database migration was part of #188, #190, #192 or #194/#195.

This documentation commit must **not** be treated as a reason to restart production
services. It changes operational documentation only.

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

**Run the artificial end-to-end pre-launch validation.**

The next validation should exercise one coherent catering flow through the live
application boundaries, including at least:

1. inquiry creation and customer/contact handling;
2. offer preparation and the relevant document flow;
3. offer acceptance / conversion to order;
4. order operational state and READY_TO_SEND path;
5. kitchen/print projection and cash-payment warning where applicable;
6. kiosk/logistics projection for a suitable order;
7. manual task creation, priority, Bezug search, Arbeitszentrale display, task detail
   and completion;
8. permission boundaries for the actions used;
9. post-flow DB integrity and service/journal checks.

Any defects found by that E2E become concrete issues. Only after that validation should
the remaining infrastructure hardening be promoted to the front of the queue, especially
branch protection and backup-health alerting.
