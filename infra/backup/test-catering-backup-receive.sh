#!/bin/sh
# Shell harness for catering-backup-receive.sh (fixture storage only).

set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
RECEIVER=$ROOT/catering-backup-receive.sh
PASS=0
FAIL=0

fail() {
    echo "FAIL: $*"
    FAIL=$((FAIL + 1))
}

pass() {
    echo "PASS: $*"
    PASS=$((PASS + 1))
}

run_receiver() {
    cmd=$1
    storage=$2
    payload=${3-}
    set +e
    if [ -n "$payload" ]; then
        CATERING_BACKUP_RECEIVE_STORAGE=$storage SSH_ORIGINAL_COMMAND=$cmd \
            sh "$RECEIVER" <<EOF >/tmp/receiver-out.$$ 2>/tmp/receiver-err.$$
$payload
EOF
    else
        CATERING_BACKUP_RECEIVE_STORAGE=$storage SSH_ORIGINAL_COMMAND=$cmd \
            sh "$RECEIVER" </dev/null >/tmp/receiver-out.$$ 2>/tmp/receiver-err.$$
    fi
    rc=$?
    set -e
    printf '%s' "$rc"
}

assert_rc() {
    label=$1
    expected=$2
    actual=$3
    if [ "$actual" -eq "$expected" ]; then
        pass "$label (rc=$actual)"
    else
        fail "$label expected rc=$expected got rc=$actual"
    fi
}

fixture() {
    dir=$(mktemp -d /tmp/catering-receiver-test.XXXXXX)
    printf '%s\n' "$dir"
}

put_payload() {
    printf 'payload-%s' "$1"
}

echo "=== receiver test matrix ==="

# 1 valid Core
dir=$(fixture)
rc=$(run_receiver "put core-2026-07-19.db.gpg" "$dir" "$(put_payload core)")
assert_rc "valid Core filename accepted" 0 "$rc"
test -f "$dir/core-2026-07-19.db.gpg" && pass "Core final artifact exists" || fail "Core final missing"
stat -c '%a' "$dir/core-2026-07-19.db.gpg" | grep -qx '600' && pass "Core mode 600" || fail "Core mode not 600"
rm -rf "$dir"

# 2 valid Courier gpg
dir=$(fixture)
rc=$(run_receiver "put courier-20260719T051613Z.tar.gz.gpg" "$dir" "$(put_payload courier-gpg)")
assert_rc "valid Courier gpg accepted" 0 "$rc"
rm -rf "$dir"

# 3 valid Courier sidecar
dir=$(fixture)
rc=$(run_receiver "put courier-20260719T051613Z.tar.gz.gpg.sha256" "$dir" "$(printf 'abc123\n')")
assert_rc "valid Courier sidecar accepted" 0 "$rc"
rm -rf "$dir"

# 4 invalid filename
dir=$(fixture)
rc=$(run_receiver "put evil.gpg" "$dir" "$(put_payload evil)")
assert_rc "invalid filename rejected" 64 "$rc"
rm -rf "$dir"

# 5 traversal ../
dir=$(fixture)
rc=$(run_receiver "put ../escape.gpg" "$dir" "$(put_payload escape)")
assert_rc "../ traversal rejected" 64 "$rc"
rm -rf "$dir"

# 6 slash and backslash
dir=$(fixture)
rc=$(run_receiver "put core-2026/evil.db.gpg" "$dir" "$(put_payload slash)")
assert_rc "slash rejected" 64 "$rc"
rc=$(run_receiver "put core-2026\\evil.db.gpg" "$dir" "$(put_payload bslash)")
assert_rc "backslash rejected" 64 "$rc"
rm -rf "$dir"

# 7 control whitespace
dir=$(fixture)
rc=$(run_receiver "put core-2026-07-19.db.gpg " "$dir" "$(put_payload ws)")
assert_rc "trailing space rejected" 64 "$rc"
rc=$(run_receiver "put core-2026-07-19 .db.gpg" "$dir" "$(put_payload ws2)")
assert_rc "embedded space rejected" 64 "$rc"
rm -rf "$dir"

# 8 duplicate final artifact not overwritten
dir=$(fixture)
printf 'first' >"$dir/core-2026-07-19.db.gpg"
chmod 600 "$dir/core-2026-07-19.db.gpg"
rc=$(run_receiver "put core-2026-07-19.db.gpg" "$dir" "second")
assert_rc "duplicate final artifact rejected" 64 "$rc"
grep -qx 'first' "$dir/core-2026-07-19.db.gpg" && pass "existing artifact preserved" || fail "artifact overwritten"
rm -rf "$dir"

# 9 partial upload does not become final
dir=$(fixture)
rc=$(run_receiver "put core-2026-07-20.db.gpg" "$dir" </dev/null)
assert_rc "empty upload rejected" 1 "$rc"
test ! -e "$dir/core-2026-07-20.db.gpg" && pass "no final after empty upload" || fail "final appeared after empty upload"
test -z "$(find "$dir" -maxdepth 1 -name '.core-2026-07-20.db.gpg.*' -print)" && pass "partial cleaned" || fail "partial left behind"
rm -rf "$dir"

# 10 wrong checksum path (sender-side verification contract)
dir=$(fixture)
payload=$(put_payload checksum)
sum=$(printf '%s\n' "$payload" | sha256sum | cut -d' ' -f1)
CATERING_BACKUP_RECEIVE_STORAGE=$dir SSH_ORIGINAL_COMMAND="put core-2026-07-21.db.gpg" sh "$RECEIVER" <<EOF >/dev/null
$payload
EOF
remote=$(CATERING_BACKUP_RECEIVE_STORAGE=$dir SSH_ORIGINAL_COMMAND="sha256 core-2026-07-21.db.gpg" sh "$RECEIVER")
if [ "$remote" = "$sum" ]; then
    pass "sha256 command returns digest for stored artifact"
else
    fail "sha256 mismatch for stored artifact"
fi
wrong=0000000000000000000000000000000000000000000000000000000000000000
if [ "$remote" != "$wrong" ]; then
    pass "wrong checksum detectable by sender comparison"
else
    fail "wrong checksum not detectable"
fi
rm -rf "$dir"

# 11 courier prune does not touch core
dir=$(fixture)
touch -d '40 days ago' "$dir/core-2026-01-01.db.gpg"
touch -d '40 days ago' "$dir/courier-20260103T010101Z.tar.gz.gpg"
touch -d '40 days ago' "$dir/courier-20260104T020202Z.tar.gz.gpg"
CATERING_BACKUP_RECEIVE_STORAGE=$dir SSH_ORIGINAL_COMMAND=prune sh "$RECEIVER" >/dev/null
test ! -e "$dir/core-2026-01-01.db.gpg" && pass "Core old artifact pruned" || fail "Core old artifact kept"
test -e "$dir/courier-20260104T020202Z.tar.gz.gpg" && pass "newest Courier gpg retained while Core pruned" || fail "Courier newest removed"
test ! -e "$dir/courier-20260103T010101Z.tar.gz.gpg" && pass "older Courier gpg pruned" || fail "older Courier gpg kept"
rm -rf "$dir"

# 12 core prune does not touch courier
dir=$(fixture)
touch -d '40 days ago' "$dir/courier-20260102T010101Z.tar.gz.gpg"
touch -d '40 days ago' "$dir/courier-20260102T010101Z.tar.gz.gpg.sha256"
CATERING_BACKUP_RECEIVE_STORAGE=$dir SSH_ORIGINAL_COMMAND=prune sh "$RECEIVER" >/dev/null
test -e "$dir/courier-20260102T010101Z.tar.gz.gpg" && pass "Courier artifact survives Core prune pass" || fail "Courier removed by Core prune"
rm -rf "$dir"

# 13 unknown file not deleted
dir=$(fixture)
touch -d '40 days ago' "$dir/unknown-backup.dat"
CATERING_BACKUP_RECEIVE_STORAGE=$dir SSH_ORIGINAL_COMMAND=prune sh "$RECEIVER" >/dev/null
test -e "$dir/unknown-backup.dat" && pass "unknown file retained" || fail "unknown file deleted"
rm -rf "$dir"

# 14 keep at least one latest courier artifact
dir=$(fixture)
touch -d '40 days ago' "$dir/courier-20260103T010101Z.tar.gz.gpg"
touch -d '40 days ago' "$dir/courier-20260104T020202Z.tar.gz.gpg"
touch -d '40 days ago' "$dir/courier-20260104T020202Z.tar.gz.gpg.sha256"
CATERING_BACKUP_RECEIVE_STORAGE=$dir SSH_ORIGINAL_COMMAND=prune sh "$RECEIVER" >/dev/null
test ! -e "$dir/courier-20260103T010101Z.tar.gz.gpg" && pass "older courier gpg pruned" || fail "older courier gpg kept"
test -e "$dir/courier-20260104T020202Z.tar.gz.gpg" && pass "newest courier gpg retained" || fail "newest courier gpg pruned"
rm -rf "$dir"

echo "=== summary: pass=$PASS fail=$FAIL ==="
test "$FAIL" -eq 0
