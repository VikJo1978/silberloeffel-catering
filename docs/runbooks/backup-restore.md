# Backup and restore

The production SQLite database is the operational truth. A backup is valid only
when it exists, is non-empty, and passes `PRAGMA quick_check`.

## Current schedule

The `viktor` crontab on Lenovo contains:

```cron
15 3 * * * sqlite3 /home/viktor/catering-runtime/core.db ".backup /var/backups/catering/core-$(date +\%F).db"
30 3 * * * find /var/backups/catering -name 'core-*.db' -mtime +14 -delete
```

This intends to create a daily online SQLite backup and retain 14 days.

## Repair the current backup permission

As observed on 2026-07-12, `/var/backups/catering` is `root:root` with mode
`750`, while the jobs run as `viktor`. Treat scheduled backups as broken until
the following is performed and verified.

On Lenovo:

```bash
sudo chown root:viktor /var/backups/catering
sudo chmod 770 /var/backups/catering
```

Then create a manual proof backup as `viktor`:

```bash
stamp=$(date +%F-%H%M%S)
target="/var/backups/catering/core-manual-$stamp.db"
sqlite3 /home/viktor/catering-runtime/core.db ".backup $target"
test -s "$target"
sqlite3 "$target" 'PRAGMA quick_check;'
ls -lh "$target"
```

Expected: a non-zero file and exactly `ok` from `quick_check`.

After the next scheduled run:

```bash
ls -lh /var/backups/catering/core-$(date +%F).db
sqlite3 /var/backups/catering/core-$(date +%F).db 'PRAGMA quick_check;'
```

## Pre-deploy backup

Scheduled backups do not replace a pre-deploy backup:

```bash
mkdir -p /home/viktor/catering-runtime/predeploy-backups
stamp=$(date +%Y%m%d-%H%M%S)
target="/home/viktor/catering-runtime/predeploy-backups/core-predeploy-$stamp.db"
sqlite3 /home/viktor/catering-runtime/core.db ".backup $target"
test -s "$target"
sqlite3 "$target" 'PRAGMA quick_check;'
```

Record the backup filename and deployed Git commit together.

## Off-host copy

A backup on the same Lenovo does not protect against disk loss. At least one
verified copy must live on a different machine or encrypted storage. Do not put
the production database in GitHub or on the public staging VPS.

Minimum weekly check:

- newest local backup age;
- newest off-host backup age;
- non-zero size;
- `PRAGMA quick_check = ok` on a copied file;
- restore procedure still understood by two people or documented access.

## Restore production

> **Destructive operation:** restoring discards writes made after the selected
> backup. Confirm the accepted data-loss window before starting.

### 1. Select and verify the backup

```bash
backup=/absolute/path/to/selected-backup.db
test -s "$backup"
sqlite3 "$backup" 'PRAGMA quick_check;'
```

### 2. Stop all database users

```bash
sudo systemctl stop \
  catering-office-panel \
  catering-kiosk \
  catering-website-intake
```

### 3. Preserve the failed database and restore

```bash
db=/home/viktor/catering-runtime/core.db
sudo cp "$db" "$db.before-restore-$(date +%Y%m%d-%H%M%S)"
sudo cp "$backup" "$db"
sudo chown viktor:viktor "$db"
sqlite3 "$db" 'PRAGMA quick_check;'
```

### 4. Start and smoke test

```bash
sudo systemctl start \
  catering-office-panel \
  catering-kiosk \
  catering-website-intake
systemctl is-active \
  catering-office-panel \
  catering-kiosk \
  catering-website-intake
journalctl -u catering-office-panel -u catering-kiosk \
  -u catering-website-intake --since '5 minutes ago' --no-pager
```

Verify office and kiosk data before resuming normal work.

## Incident record

For every restore, record:

- reason and decision owner;
- failed database copy;
- restored backup filename and timestamp;
- expected data-loss interval;
- Git commit running after restore;
- `quick_check` result;
- office/kiosk smoke-test result.
