#!/bin/sh
# Rotate the Lenovo website-intake bearer to the prepared staging token.
# The token is consumed from a mode-600 handoff file and never printed.

set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "run as root" >&2
    exit 1
fi

token_handoff=/home/viktor/catering-runtime/staging-core-intake.token
env_target=/etc/catering/website-intake.env
backup_dir=/home/viktor/catering-runtime/predeploy-backups
stamp=$(date +%Y%m%d-%H%M%S)
env_backup="$backup_dir/website-intake.env-pre-staging-$stamp"
tmp_env=

test -f "$token_handoff"
test "$(stat -c %a "$token_handoff")" = 600
test "$(stat -c %U "$token_handoff")" = viktor
test "$(wc -l < "$token_handoff")" -eq 1
token=$(cat "$token_handoff")
case "$token" in
    *[!A-Za-z0-9_-]*|'')
        echo "invalid token handoff" >&2
        exit 1
        ;;
esac
test "${#token}" -ge 32

mkdir -p "$backup_dir" /etc/catering
cp -p "$env_target" "$env_backup"

rollback() {
    echo "activation failed; restoring previous website-intake token" >&2
    install -o root -g root -m 600 "$env_backup" "$env_target"
    if [ -n "$tmp_env" ]; then
        rm -f "$tmp_env"
    fi
    systemctl restart catering-website-intake
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

tmp_env=$(mktemp /etc/catering/website-intake.env.XXXXXX)
chown root:root "$tmp_env"
chmod 600 "$tmp_env"
printf 'WEBSITE_INTAKE_TOKEN=%s\n' "$token" > "$tmp_env"
mv -f "$tmp_env" "$env_target"
tmp_env=

systemctl restart catering-website-intake

# systemd reports the process as active before the HTTP listener is necessarily
# ready. Give the receiver a short, bounded readiness window so a normal startup
# does not trigger rollback. The probe deliberately carries no bearer token.
status=000
attempt=1
while [ "$attempt" -le 15 ]; do
    if systemctl is-active --quiet catering-website-intake; then
        status=$(curl -sS -o /dev/null -w '%{http_code}' \
            --connect-timeout 1 --max-time 2 \
            -X POST -H 'Content-Type: application/json' \
            --data '{}' http://127.0.0.1:8083/intake/website-form 2>/dev/null \
            || true)
        if [ -z "$status" ]; then
            status=000
        fi
        if [ "$status" = 401 ]; then
            break
        fi
    fi
    sleep 1
    attempt=$((attempt + 1))
done
if [ "$status" != 401 ]; then
    printf 'website-intake readiness check failed (status=%s)\n' "$status" >&2
    exit 1
fi
test "$(stat -c %a "$env_target")" = 600
test "$(stat -c %U:%G "$env_target")" = root:root

rm -f "$token_handoff"
trap - EXIT
printf 'ACTIVATION_OK receiver_unauth=%s\n' "$status"
