# VPS staging runbook

The VPS hosts a temporary public preview while access to the real Silberlöffel
website is unavailable. It is a design and integration test environment, not a
production customer channel.

## Inventory

| Fact | Value |
|---|---|
| Public URL | [http://185.16.60.69:8080/](http://185.16.60.69:8080/) |
| SSH | `root@185.16.60.69` |
| Service | `catering-staging-site` |
| Runtime user | `catering-staging` |
| Application | `/opt/catering-staging-site` |
| Database | `/var/lib/catering-staging/staging.db` |
| systemd unit | `/etc/systemd/system/catering-staging-site.service` |

## Safety boundary

- No domain and no HTTPS are configured.
- Use invented names, emails, phone numbers, and event details only.
- The staging process has no production token and no Lenovo connection.
- The public API does not expose a list of saved submissions.
- The database is disposable test data.

## Status and health

```bash
ssh -i ~/.ssh/id_ed25519 root@185.16.60.69
systemctl is-active catering-staging-site
curl -fsS http://127.0.0.1:8080/healthz
ss -ltnp 'sport = :8080'
journalctl -u catering-staging-site -n 100 --no-pager
```

Expected health response:

```json
{"status": "ok", "environment": "staging"}
```

## Deploy an update

From the repository on the Mac:

```bash
scp -i ~/.ssh/id_ed25519 \
  src/catering_system/ui/staging_site.py \
  root@185.16.60.69:/opt/catering-staging-site/staging_site.py

scp -i ~/.ssh/id_ed25519 -r \
  src/catering_system/ui/staging_site_assets \
  root@185.16.60.69:/opt/catering-staging-site/

scp -i ~/.ssh/id_ed25519 \
  infra/systemd/catering-staging-site.service \
  root@185.16.60.69:/etc/systemd/system/catering-staging-site.service
```

On the VPS:

```bash
chown -R root:root /opt/catering-staging-site
find /opt/catering-staging-site -type d -exec chmod 755 {} +
find /opt/catering-staging-site -type f -exec chmod 644 {} +
python3 -m py_compile /opt/catering-staging-site/staging_site.py
systemctl daemon-reload
systemctl restart catering-staging-site
systemctl is-active catering-staging-site
curl -fsS http://127.0.0.1:8080/healthz
```

Verify the public URL from a different machine after local health succeeds.

## Browser smoke test

1. Open the public URL with explicit `http://`.
2. Check desktop and mobile layouts.
3. Submit one clearly labelled fake request.
4. Confirm a green `Gespeichert` message and a test ID.
5. Verify service health again.

## Concurrency regression

The server uses `ThreadingHTTPServer`. A stalled browser connection must not
block other visitors; this is covered by an automated regression test.

A lightweight ten-visitor asset check from a trusted machine:

```bash
seq 1 10 | xargs -P10 -I{} sh -c \
  'for path in / /styles.css /app.js /healthz; do
     curl -fsS --connect-timeout 3 --max-time 10 \
       -o /dev/null "http://185.16.60.69:8080$path"
   done'
```

Do not run sustained load tests without first setting traffic and resource
limits. This small smoke test is not a capacity benchmark.

## Inspect test data

```bash
python3 -c '
import sqlite3
c = sqlite3.connect("/var/lib/catering-staging/staging.db")
print(c.execute("PRAGMA quick_check").fetchone())
print(c.execute("SELECT COUNT(*) FROM staging_inquiries").fetchone())
'
```

Do not print full rows if anyone may have entered real contact data by mistake.

## Troubleshooting

| Symptom | Action |
|---|---|
| blank page that never completes | check service; confirm the threading fix is deployed |
| connection refused | inspect service and provider firewall |
| CSS missing | verify `staging_site_assets/` beside `staging_site.py` |
| form returns 429 | wait for the one-minute per-IP rate window |
| form returns 400 | validate date, name, contact method, and guest count |
| service cannot write DB | verify owner `catering-staging` on `/var/lib/catering-staging` |

## Retirement

After the real website integration is live:

1. export or discard test data according to the owner's decision;
2. stop and disable `catering-staging-site`;
3. close public port `8080`;
4. remove the public preview link from current-status documentation.

Do not delete anything until the real site has passed an end-to-end test.
