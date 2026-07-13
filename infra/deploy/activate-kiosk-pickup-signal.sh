#!/bin/sh
# Activate the production kiosk pickup signal with rollback on any failed gate.
# Run as root from the repository checkout. No secret is printed or passed in argv.

set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "run as root" >&2
    exit 1
fi

repo=/home/viktor/projects/silberloeffel-catering
courier_env=/home/viktor/courier-runtime/courier.env
unit_source="$repo/infra/systemd/catering-kiosk.service"
unit_target=/etc/systemd/system/catering-kiosk.service
env_target=/etc/catering/kiosk.env
backup_dir=/home/viktor/catering-runtime/predeploy-backups
stamp=$(date +%Y%m%d-%H%M%S)
unit_backup="$backup_dir/catering-kiosk.service-pre-pickup-$stamp"
env_backup="$backup_dir/kiosk.env-pre-pickup-$stamp"
had_env=0
tmp_env=

test -r "$courier_env"
test -r "$unit_source"
test -r "$unit_target"
test "$(grep -c '^KIOSK_SIGNAL_TOKEN=' "$courier_env")" -eq 1
token=$(sed -n 's/^KIOSK_SIGNAL_TOKEN=//p' "$courier_env")
test -n "$token"

mkdir -p "$backup_dir" /etc/catering
cp -p "$unit_target" "$unit_backup"
if [ -f "$env_target" ]; then
    cp -p "$env_target" "$env_backup"
    had_env=1
fi

rollback() {
    echo "activation failed; restoring previous kiosk configuration" >&2
    install -m 644 "$unit_backup" "$unit_target"
    if [ "$had_env" -eq 1 ]; then
        install -o root -g root -m 600 "$env_backup" "$env_target"
    else
        rm -f "$env_target"
    fi
    if [ -n "$tmp_env" ]; then
        rm -f "$tmp_env"
    fi
    systemctl daemon-reload
    systemctl restart catering-kiosk
}

on_exit() {
    status=$1
    trap - EXIT
    if [ "$status" -ne 0 ]; then
        rollback
    fi
    exit "$status"
}
trap 'on_exit $?' EXIT

tmp_env=$(mktemp /etc/catering/kiosk.env.XXXXXX)
chown root:root "$tmp_env"
chmod 600 "$tmp_env"
printf '%s\n%s\n' \
    'PICKUP_SIGNAL_URL=http://127.0.0.1:8090/api/overdue-pickups' \
    "PICKUP_SIGNAL_TOKEN=$token" > "$tmp_env"
mv -f "$tmp_env" "$env_target"
tmp_env=

install -m 644 "$unit_source" "$unit_target"
systemctl daemon-reload
since=$(date --iso-8601=seconds)
systemctl restart catering-kiosk

success=0
for _attempt in 1 2 3 4 5 6 7 8 9 10; do
    if systemctl is-active --quiet catering-kiosk && \
        journalctl -u catering-kiosk --since "$since" --no-pager \
            | grep -q 'pickup signal refresh succeeded'; then
        success=1
        break
    fi
    sleep 1
done
test "$success" -eq 1

kiosk_status=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8082/)
signal_status=$(curl -s -o /dev/null -w '%{http_code}' \
    http://127.0.0.1:8090/api/overdue-pickups)
test "$kiosk_status" = 200
test "$signal_status" = 401
test "$(stat -c %a "$env_target")" = 600
test "$(stat -c %U:%G "$env_target")" = root:root

trap - EXIT
printf 'ACTIVATION_OK kiosk=%s signal_unauth=%s\n' \
    "$kiosk_status" "$signal_status"
