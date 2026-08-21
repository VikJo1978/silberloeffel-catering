# Production service inventory

Last read-only audit: **2026-08-21 08:11 CEST** on `debiancatering`.
Tailscale IPv4 observed: `100.109.6.74`.
Application checkout revision observed: `4eadf014654992619be317c8b3b079c5d8dcd26b`.

This file contains no credentials. Environment-file paths are safe to document;
their contents are not.

## Core host

| Service / component | State at audit | Listen / exposure | Runtime / data | Environment |
|---|---|---|---|---|
| `catering-office-panel.service` | enabled, active | `0.0.0.0:8081` | repo `/home/viktor/projects/silberloeffel-catering`; `core.db` | `/etc/catering/office-panel.env` |
| `catering-office-api.service` | enabled, active | `100.109.6.74:8084` | project `.venv`; `core.db` | `/etc/catering/office-api.env` |
| `catering-kiosk.service` | enabled, active | `0.0.0.0:8082` | system Python; read-only Core use | `/etc/catering/kiosk.env` optional |
| `catering-website-intake.service` | enabled, active | `127.0.0.1:8083` | system Python; Inquiry writes | `/etc/catering/website-intake.env` |
| `kitchen-print-agent.service` | enabled, active | no HTTP listener of its own | project `.venv`; module `kitchen_print_agent` | `/etc/kitchen-print-agent.env` |
| `catering-kitchen-api.service` | enabled, active | `127.0.0.1:8086` | project `.venv`; `core.db` | `/etc/catering/kitchen-api.env` |
| GitHub Actions self-hosted runner | active | outbound GitHub connection | `/home/chatops/actions-runner` | runner registration managed by GitHub |
| courier listener | listener observed | `0.0.0.0:8090` | separate courier runtime | ownership/unit not re-audited in this pass |
| `catering-intake-vps-tunnel.service` | unit not found, inactive | none observed at `18083` | tracked template exists, live unit absent | n/a |

## Exact live commands verified on 2026-08-21

### Office API

```text
/home/viktor/projects/silberloeffel-catering/.venv/bin/python3
  -m catering_system.ui.office_api
  --db /home/viktor/catering-runtime/core.db
  --host 100.109.6.74
  --port 8084
```

### Office Panel

```text
/home/viktor/projects/silberloeffel-catering/.venv/bin/python3
  -m catering_system.ui.office_panel
  --db /home/viktor/catering-runtime/core.db
  --port 8081
```

### Kiosk

```text
/usr/bin/python3
  -m catering_system.ui.kiosk_server
  --db /home/viktor/catering-runtime/core.db
  --port 8082
```

### Website intake

```text
/usr/bin/python3
  -m catering_system.ui.website_intake_endpoint
  --db /home/viktor/catering-runtime/core.db
  --host 127.0.0.1
  --port 8083
```

### Kitchen Print Agent

```text
/home/viktor/projects/silberloeffel-catering/.venv/bin/python3
  -m kitchen_print_agent
```

### Kitchen API

```text
/home/viktor/projects/silberloeffel-catering/.venv/bin/python3
  -m catering_system.ui.kitchen_api
  --db /home/viktor/catering-runtime/core.db
  --host 127.0.0.1
  --port 8086
```

## Shared production paths

| Purpose | Path |
|---|---|
| Application checkout | `/home/viktor/projects/silberloeffel-catering` |
| Python runtime | `/home/viktor/projects/silberloeffel-catering/.venv` |
| Core SQLite DB | `/home/viktor/catering-runtime/core.db` |
| Production env directory | `/etc/catering/` |
| Restricted ops wrapper | `/usr/local/sbin/catering-ops` |
| ChatOps sudo policy | `/etc/sudoers.d/chatops-catering` |
| Actions runner home | `/home/chatops/actions-runner` |

## Known configuration drift

As of this audit, both Kitchen Print Agent and Kitchen API are active from live
systemd units under `/etc/systemd/system`, while the exact Lenovo Phase 3B source
changes that produced those units are preserved on GitHub branch
`wip/kitchen-print-lenovo-phase3b` and are not yet merged into `main`.

In particular, tracked `main` still has the older `kitchen-print-agent.service`
using `/opt/kitchen-print-agent`, while the live service uses the main project
checkout and `.venv`. `catering-kitchen-api.service` is not present on `main` at
this snapshot. Do not reinstall Kitchen units from `main` until this drift is
resolved through a reviewed merge.

## Verification commands

Safe read-only checks:

```bash
systemctl is-active catering-office-api catering-office-panel \
  catering-kiosk catering-website-intake kitchen-print-agent catering-kitchen-api
ss -ltn
sudo -n /usr/local/sbin/catering-ops revision
```

Never use a service inventory command that prints environment variable values.
