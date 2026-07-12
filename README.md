# Catering System

Operational catering MVP with a Python standard-library runtime and SQLite as
the Core source of truth. It receives inquiries, turns eligible inquiries into
versioned orders, enforces print/effective-order gates, and exposes separate
office and kitchen HTTP surfaces.

## Architecture

- `domain/` contains the business records and pure derived progression views.
- `services/` owns use cases and business transitions.
- `repositories/` contains in-memory test adapters and SQLite persistence.
- `intake/` validates channel-specific inquiry payloads.
- `ui/office_panel.py` composes office workflows; HTTP routing, shared views,
  and proposal preview live in separate modules.
- `ui/kiosk_server.py` is read-only; `ui/website_intake_endpoint.py` exposes one
  token-protected write route for the Cloudflare Worker.
- `ui/staging_site.py` serves the portable public-site prototype and stores test
  submissions in a separate SQLite database; it never writes to production Core.

The many `order_progression_*` records are deliberate, pure projections from
the frozen Slice B contracts. They do not add independent state or extra write
paths. Consolidating them would change accepted external/debug contracts, so
their separation is an architectural constraint rather than removable debt.

## Local setup

Python 3.12 or newer is required.

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/pip install --group dev
```

Run the office panel against a local database:

```bash
OFFICE_PANEL_PASSWORD=change-me \
  .venv/bin/python -m catering_system.ui.office_panel --db core.db --port 8081
```

Run the read-only kiosk separately:

```bash
.venv/bin/python -m catering_system.ui.kiosk_server --db core.db --port 8082
```

Run the isolated website preview locally:

```bash
.venv/bin/python -m catering_system.ui.staging_site \
  --db staging.db --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080/`. Use fake data only: the staging form is intended
for design and integration tests and does not forward submissions to Core.

SQLite migrations run automatically when a repository opens the database. Back
up a production database before deploying a new version; migration validation
fails startup rather than silently accepting an unknown or inconsistent schema.

See [DEPLOYMENT.md](DEPLOYMENT.md) for the Lenovo/systemd, VPS staging, backup,
website receiver, and Cloudflare Tunnel procedure.

## Quality checks

```bash
.venv/bin/ruff check src tests
.venv/bin/mypy src/catering_system
.venv/bin/coverage run -m pytest -q
.venv/bin/coverage report
node --test infra/cloudflare_worker/sanitize.test.mjs
```

CI runs the same checks and rejects Python coverage below 90%.
