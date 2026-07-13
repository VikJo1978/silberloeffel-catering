# Silberlöffel Catering System

Operational software for receiving catering inquiries, preparing versioned
orders, controlling kitchen release gates, and showing the current week to the
kitchen. Python and SQLite are the production runtime; the public staging site
holds no production data and can exercise only the narrow Inquiry intake path.

> **Current state:** production services on the Lenovo are active. The public
> form-development and intake-test preview is available at
> [185.16.60.69:8080](http://185.16.60.69:8080/)
> and must be used with fake data only.

## Start here

| You want to… | Read… |
|---|---|
| understand the whole system | [Documentation index](docs/README.md) |
| see what is live and what is still open | [Current status](docs/current-status.md) |
| understand components and data flow | [Architecture](docs/architecture.md) |
| operate or deploy production | [Lenovo production runbook](docs/runbooks/lenovo-production.md) |
| operate the temporary website | [VPS staging runbook](docs/runbooks/vps-staging.md) |
| verify or restore SQLite backups | [Backup and restore](docs/runbooks/backup-restore.md) |
| integrate the website form | [Website intake API](docs/api/website-intake.md) |
| work in the office panel | [Office panel guide](docs/user/office-panel.md) |

## Local development

Python 3.12 or newer is required.

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/pip install --group dev
```

Copy `.env.example` only as a reference. Do not commit a populated environment
file or any production credential.

Run the office panel:

```bash
OFFICE_PANEL_PASSWORD=change-me \
  .venv/bin/python -m catering_system.ui.office_panel \
  --db core.db --host 127.0.0.1 --port 8081
```

Run the read-only kitchen kiosk:

```bash
.venv/bin/python -m catering_system.ui.kiosk_server \
  --db core.db --host 127.0.0.1 --port 8082
```

Run the isolated website preview:

```bash
.venv/bin/python -m catering_system.ui.staging_site \
  --db staging.db --host 127.0.0.1 --port 8080
```

## Quality gate

```bash
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy src/catering_system
.venv/bin/coverage run -m pytest -q
.venv/bin/coverage report
node --test infra/staging-form/app.test.cjs
node --test infra/cloudflare_worker/sanitize.test.mjs
```

GitHub Actions runs the same checks and enforces coverage above 90%. See
[Current status](docs/current-status.md) or the latest CI run for the current
test count instead of duplicating a number here.

## Non-negotiable boundaries

- The Lenovo SQLite database is the production operational truth.
- The office panel is a private LAN/Tailscale write surface and must never be
  public.
- The kitchen kiosk is read-only.
- The website receiver exposes one token-protected intake route only.
- The VPS staging database is separate. Optional Core forwarding can create
  only a namespaced test Inquiry through the token-protected intake receiver;
  it never reads Core or creates an Order.
- Contact data and secrets must not appear in logs, commits, screenshots, or
  documentation.

Historical planning and implementation packs are preserved in
[`docs/archive/packs/`](docs/archive/packs/). They explain past decisions but
are not the first place to look for current operating instructions.
