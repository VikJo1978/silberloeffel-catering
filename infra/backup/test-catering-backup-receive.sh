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

# 4 valid Fingerfood gpg
dir=$(fixture)
rc=$(run_receiver "put fingerfood-20260719T062608Z.tar.gz.gpg" "$dir" "$(put_payload fingerfood-gpg)")
assert_rc "valid Fingerfood gpg accepted" 0 "$rc"
test -f "$dir/fingerfood-20260719T062608Z.tar.gz.gpg" && pass "Fingerfood final artifact exists" || fail "Fingerfood final missing"
stat -c '%a' "$dir/fingerfood-20260719T062608Z.tar.gz.gpg" | grep -qx '600' && pass "Fingerfood mode 600" || fail "Fingerfood mode not 600"
rm -rf "$dir"

# 5 valid Fingerfood sidecar
dir=$(fixture)
rc=$(run_receiver "put fingerfood-20260719T062608Z.tar.gz.gpg.sha256" "$dir" "$(printf 'abc123\n')")
assert_rc "valid Fingerfood sidecar accepted" 0 "$rc"
rm -rf "$dir"

# 6 malformed Fingerfood timestamp
dir=$(fixture)
rc=$(run_receiver "put fingerfood-2026071T062608Z.tar.gz.gpg" "$dir" "$(put_payload bad-ts)")
assert_rc "malformed Fingerfood timestamp rejected" 64 "$rc"
rm -rf "$dir"

# 7 invalid extension
dir=$(fixture)
rc=$(run_receiver "put evil.gpg" "$dir" "$(put_payload evil)")
assert_rc "invalid extension rejected" 64 "$rc"
rc=$(run_receiver "put fingerfood-20260719T062608Z.tar.gz" "$dir" "$(put_payload no-gpg)")
assert_rc "Fingerfood missing .gpg rejected" 64 "$rc"
rm -rf "$dir"

# 8 traversal ../
dir=$(fixture)
rc=$(run_receiver "put ../escape.gpg" "$dir" "$(put_payload escape)")
assert_rc "../ traversal rejected" 64 "$rc"
rm -rf "$dir"

# 9 slash and backslash
dir=$(fixture)
rc=$(run_receiver "put core-2026/evil.db.gpg" "$dir" "$(put_payload slash)")
assert_rc "slash rejected" 64 "$rc"
rc=$(run_receiver "put core-2026\\evil.db.gpg" "$dir" "$(put_payload bslash)")
assert_rc "backslash rejected" 64 "$rc"
rc=$(run_receiver "put fingerfood-2026/evil.tar.gz.gpg" "$dir" "$(put_payload ff-slash)")
assert_rc "Fingerfood slash rejected" 64 "$rc"
rm -rf "$dir"

# 10 control whitespace
dir=$(fixture)
rc=$(run_receiver "put core-2026-07-19.db.gpg " "$dir" "$(put_payload ws)")
assert_rc "trailing space rejected" 64 "$rc"
rc=$(run_receiver "put core-2026-07-19 .db.gpg" "$dir" "$(put_payload ws2)")
assert_rc "embedded space rejected" 64 "$rc"
rc=$(run_receiver "put fingerfood-20260719T062608Z.tar.gz.gpg$(printf '\t')" "$dir" "$(put_payload tab)")
assert_rc "control whitespace rejected" 64 "$rc"
rm -rf "$dir"

# 11 duplicate Fingerfood artifact not overwritten
dir=$(fixture)
printf 'first' >"$dir/fingerfood-20260719T062608Z.tar.gz.gpg"
chmod 600 "$dir/fingerfood-20260719T062608Z.tar.gz.gpg"
rc=$(run_receiver "put fingerfood-20260719T062608Z.tar.gz.gpg" "$dir" "second")
assert_rc "duplicate Fingerfood artifact rejected" 64 "$rc"
grep -qx 'first' "$dir/fingerfood-20260719T062608Z.tar.gz.gpg" && pass "existing Fingerfood artifact preserved" || fail "Fingerfood artifact overwritten"
rm -rf "$dir"

# 12 interrupted put does not become final
dir=$(fixture)
rc=$(run_receiver "put fingerfood-20260719T062609Z.tar.gz.gpg" "$dir" </dev/null)
assert_rc "empty Fingerfood upload rejected" 1 "$rc"
test ! -e "$dir/fingerfood-20260719T062609Z.tar.gz.gpg" && pass "no final after empty Fingerfood upload" || fail "final appeared after empty upload"
test -z "$(find "$dir" -maxdepth 1 -name '.fingerfood-20260719T062609Z.tar.gz.gpg.*' -print)" && pass "Fingerfood partial cleaned" || fail "Fingerfood partial left behind"
rm -rf "$dir"

# 13 duplicate final artifact not overwritten (Core regression)
dir=$(fixture)
printf 'first' >"$dir/core-2026-07-19.db.gpg"
chmod 600 "$dir/core-2026-07-19.db.gpg"
rc=$(run_receiver "put core-2026-07-19.db.gpg" "$dir" "second")
assert_rc "duplicate Core artifact rejected" 64 "$rc"
grep -qx 'first' "$dir/core-2026-07-19.db.gpg" && pass "existing Core artifact preserved" || fail "Core artifact overwritten"
rm -rf "$dir"

# 14 sha256 contract
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
rm -rf "$dir"

# 15 courier prune does not touch core
dir=$(fixture)
touch -d '40 days ago' "$dir/core-2026-01-01.db.gpg"
touch -d '40 days ago' "$dir/courier-20260103T010101Z.tar.gz.gpg"
touch -d '40 days ago' "$dir/courier-20260104T020202Z.tar.gz.gpg"
CATERING_BACKUP_RECEIVE_STORAGE=$dir SSH_ORIGINAL_COMMAND=prune sh "$RECEIVER" >/dev/null
test ! -e "$dir/core-2026-01-01.db.gpg" && pass "Core old artifact pruned" || fail "Core old artifact kept"
test -e "$dir/courier-20260104T020202Z.tar.gz.gpg" && pass "newest Courier gpg retained while Core pruned" || fail "Courier newest removed"
test ! -e "$dir/courier-20260103T010101Z.tar.gz.gpg" && pass "older Courier gpg pruned" || fail "older Courier gpg kept"
rm -rf "$dir"

# 16 core prune does not touch courier
dir=$(fixture)
touch -d '40 days ago' "$dir/courier-20260102T010101Z.tar.gz.gpg"
touch -d '40 days ago' "$dir/courier-20260102T010101Z.tar.gz.gpg.sha256"
CATERING_BACKUP_RECEIVE_STORAGE=$dir SSH_ORIGINAL_COMMAND=prune sh "$RECEIVER" >/dev/null
test -e "$dir/courier-20260102T010101Z.tar.gz.gpg" && pass "Courier artifact survives Core prune pass" || fail "Courier removed by Core prune"
rm -rf "$dir"

# 17 Fingerfood prune removes only old Fingerfood artifacts
dir=$(fixture)
touch -d '40 days ago' "$dir/fingerfood-20260103T010101Z.tar.gz.gpg"
touch -d '40 days ago' "$dir/fingerfood-20260104T020202Z.tar.gz.gpg"
touch -d '40 days ago' "$dir/fingerfood-20260104T020202Z.tar.gz.gpg.sha256"
CATERING_BACKUP_RECEIVE_STORAGE=$dir SSH_ORIGINAL_COMMAND=prune sh "$RECEIVER" >/dev/null
test ! -e "$dir/fingerfood-20260103T010101Z.tar.gz.gpg" && pass "older Fingerfood gpg pruned" || fail "older Fingerfood gpg kept"
test -e "$dir/fingerfood-20260104T020202Z.tar.gz.gpg" && pass "newest Fingerfood gpg retained" || fail "newest Fingerfood gpg pruned"
rm -rf "$dir"

# 18 Fingerfood prune does not touch Core or Courier
dir=$(fixture)
touch -d '10 days ago' "$dir/core-2026-06-01.db.gpg"
touch -d '10 days ago' "$dir/courier-20260602T010101Z.tar.gz.gpg"
touch -d '40 days ago' "$dir/fingerfood-20260103T010101Z.tar.gz.gpg"
touch -d '40 days ago' "$dir/fingerfood-20260104T020202Z.tar.gz.gpg"
CATERING_BACKUP_RECEIVE_STORAGE=$dir SSH_ORIGINAL_COMMAND=prune sh "$RECEIVER" >/dev/null
test -e "$dir/core-2026-06-01.db.gpg" && pass "Core artifact survives Fingerfood prune pass" || fail "Core removed by Fingerfood prune"
test -e "$dir/courier-20260602T010101Z.tar.gz.gpg" && pass "Courier artifact survives Fingerfood prune pass" || fail "Courier removed by Fingerfood prune"
test -e "$dir/fingerfood-20260104T020202Z.tar.gz.gpg" && pass "newest Fingerfood gpg retained in mixed prune" || fail "newest Fingerfood gpg pruned in mixed prune"
test ! -e "$dir/fingerfood-20260103T010101Z.tar.gz.gpg" && pass "older Fingerfood gpg pruned in mixed prune" || fail "older Fingerfood gpg kept in mixed prune"
rm -rf "$dir"

# 19 unknown file not deleted
dir=$(fixture)
touch -d '40 days ago' "$dir/unknown-backup.dat"
CATERING_BACKUP_RECEIVE_STORAGE=$dir SSH_ORIGINAL_COMMAND=prune sh "$RECEIVER" >/dev/null
test -e "$dir/unknown-backup.dat" && pass "unknown file retained" || fail "unknown file deleted"
rm -rf "$dir"

# 20 keep at least one latest courier artifact (Courier regression)
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
