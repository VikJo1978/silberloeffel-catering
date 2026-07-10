LENOVO_WEBSITE_INTAKE_SYSTEMD_IMPLEMENTATION_PACK_V1

0. Purpose

Narrow, executable implementation plan for exactly one step of
WEBSITE_INTAKE_RECEIVER_DEPLOYMENT_PACK_V1's §10 checklist: installing
website_intake_endpoint.py (0f6e034, idempotency 2ed5510) as a systemd
service on the kitchen Lenovo, bound to 127.0.0.1:8083 only. This pack does
not set up Cloudflare Tunnel and does not deploy or touch the Worker in any
way — those stay exactly as WEBSITE_INTAKE_RECEIVER_DEPLOYMENT_PACK_V1 §5
already described them: future, separate, owner-performed steps. Until
Tunnel is configured, the service being installed here has no reachable
caller at all (loopback-only, no LAN listener, no public listener) — it is
inert but running, ready for Tunnel to be pointed at it later.

Every claim below was checked against current repo state on 2026-07-10:
website_intake_endpoint.py's actual CLI flags/defaults, the two existing
systemd units (infra/systemd/catering-kiosk.service,
catering-office-panel.service), DEPLOYMENT.md §1b/§1c, and the Lenovo
bring-up facts recorded after the 2026-07-05 live bring-up (WORKLOG Entry
050): kiosk actually runs on port 8082 on the live host, not the 8080 shown
in DEPLOYMENT.md §1's example command — that discrepancy predates this pack
and is not introduced or fixed by it; it only matters here because it
confirms the live host's real port map is 8081 (office panel) / 8082
(kiosk) / 8083 (this receiver, unused so far) — no collision.

Revision note (v2): incorporated 12 corrections from the second review
round — real-values-only unit (no placeholders committed), confirmed
runtime path instead of a guessed /usr/bin/python3, a shell-history-safe
secret write, a timestamped+integrity-checked backup, an explicit
service-user filesystem access check, unique per-run submission_id values,
no assumed Office Panel delete flow, SQL baseline/post-check around the
idempotency retry, strict response-body leak checks, an evidence-based
(not assumed) journal check, a rollback split into host-level vs git-level,
and a systemd restart-storm guard.

Revision note (v3, this version): incorporated 4 further corrections from
the third review round — the receiver token is now read back out of the
already-written env file instead of ever appearing literally in a curl
command (shell-history-safe end to end, not just at write time); all
response bodies from §4 are written to a private mktemp temp directory,
never into the repo's WorkingDirectory, and removed via trap on exit
including on failure; every check in §4 that was previously prose ("Expect
202") is now a literal `test`/assert statement that fails the script if
wrong, matching this session's own local-copy smoke test discipline; and
§3.0's fact-gathering now also captures each existing unit's Environment=
line and stops if the two existing units disagree on runtime/environment,
rather than §3.6 computing PYTHONPATH or Group= itself.

Revision note (v4, this version): incorporated 2 further corrections from
the fourth review round — the token is no longer passed to curl via an
interpolated `-H` argument at all (that still leaked into the curl
process's own argv, visible to `ps` during the request, even though it
never touched shell history); §4.3 now writes it once into a chmod-600
`curl --config` file inside $VERIFY_DIR instead, and every authenticated
request in §4.6/§4.7 uses `--config` rather than a header string. The
leak-check-then-unset ordering in §4.8 was also fixed: the grep-based leak
check against $WEBSITE_INTAKE_TOKEN now runs strictly before `unset
WEBSITE_INTAKE_TOKEN`, since running it after would grep for an empty
string and pass vacuously rather than proving anything.

Revision note (v5, this version): §3.0 has now actually been run on the
live Lenovo (2026-07-10), not just planned — see §3.0's confirmation block
below for the full result. Two consequences of that real output: (1) User=,
Group=, WorkingDirectory=, Environment=, and the interpreter path agree
between catering-kiosk and catering-office-panel, so §3.0's stop-and-flag
condition did not trigger, and §3.6's unit template below is now filled in
with those confirmed real values rather than <from §3.0> placeholders; (2)
the same live ExecStart= output also revealed that the actual Core DB path
is /home/viktor/catering-runtime/core.db, not /var/lib/catering/core.db —
every occurrence of the old, wrongly-assumed path (inherited from
DEPLOYMENT.md's documented default, which this pack had not itself
verified against the live host until now) has been corrected throughout
§2–§5 and §9 in this pass. DEPLOYMENT.md itself is not touched by this
correction — it documents a general/default bring-up procedure, and this
pack's own wrong assumption about this one Lenovo's actual runtime path is
this pack's error to fix, not DEPLOYMENT.md's. The systemd unit file itself
is still not created on disk by this pack — §3.6 below is filled in as the
exact content it will have once a separate explicit GO authorizes actually
writing infra/systemd/catering-website-intake.service.

⸻

1. Scope boundary

	•	in scope: one new systemd unit
		(infra/systemd/catering-website-intake.service), one new env file on
		the Lenovo (/etc/catering/website-intake.env), the install/enable
		commands, and the verification that the process runs and is
		loopback-only
	•	out of scope, explicitly: Cloudflare Tunnel (cloudflared install,
		tunnel create, DNS route, ingress config), Worker deployment or
		Worker secret changes (UPSTREAM_TOKEN, UPSTREAM_URL), the public
		Wix site pointing at anything, any code change to
		website_intake_endpoint.py or worker.js, any change to Office Panel
		or kiosk services, any Order/OrderVersion/READY_TO_SEND/wirksam
		logic, any CRM or AI Telefonist work
	•	after this pack's steps are performed, the receiver is running but
		has zero real callers — nothing outside the Lenovo itself can reach
		127.0.0.1:8083; this is intentional and is the entire point of
		doing systemd install and Tunnel setup as two separate, independently
		reversible steps

⸻

2. Preconditions (owner should confirm on the Lenovo before starting)

	•	the repo is checked out at the real Lenovo path with the current
		main branch (0f6e034 or later — must include
		website_intake_endpoint.py and the idempotency commit 2ed5510)
	•	catering-kiosk and catering-office-panel services are already
		installed and healthy (systemctl status catering-kiosk
		catering-office-panel both active) — this pack adds a third unit
		alongside them, and §3.0 below reads their real config so the new
		unit matches fact, not assumption
	•	port 8083 is free (ss -ltnp | grep 8083 or lsof -nP -iTCP:8083 shows
		nothing) — confirms no collision with the future Tunnel-facing
		process or anything else

⸻

3. Steps

3.0 Read the real config of the two existing services — required before
writing anything into the new unit; nothing in §3.6 may be filled in from
assumption or from this pack's own placeholder text:

	systemctl cat catering-kiosk
	systemctl cat catering-office-panel
	systemctl show catering-kiosk \
	  -p User -p Group -p WorkingDirectory -p ExecStart \
	  -p Environment -p EnvironmentFiles
	systemctl show catering-office-panel \
	  -p User -p Group -p WorkingDirectory -p ExecStart \
	  -p Environment -p EnvironmentFiles

Record the real User=, Group=, WorkingDirectory=, Environment= (in
particular the exact PYTHONPATH= value the existing services actually use),
and the real interpreter path used in ExecStart= (this tells us
definitively whether the Lenovo runs the two existing services from a
system Python, a venv, or an editable install — the local Mac smoke test
used .venv/bin/python3, but that has no bearing on what the Lenovo actually
runs; §3.6's ExecStart must use whichever interpreter path this command
shows for the existing services, not a guess).

§3.6's unit must copy the confirmed Environment= value verbatim from
whichever of these two commands' output it matches — never recompute
PYTHONPATH from WorkingDirectory + "/src" by pattern-matching
DEPLOYMENT.md's example; the example may not match what is actually
installed. If Group= is absent or empty in both existing units' output,
§3.6's unit omits the Group= line entirely rather than writing an empty
value.

If the two existing units disagree with each other on User=, Group=,
WorkingDirectory=, Environment=, or the interpreter path in ExecStart=,
stop and flag it back for a decision before continuing — this pack assumes
they agree, matching DEPLOYMENT.md §1b's shared-pattern description, but
does not yet have hard proof of that for the current installed state, and
picking one of two disagreeing patterns without a decision would be a
guess, not a confirmed fact.

Confirmed on the live Lenovo (2026-07-10) — §3.0 has actually been run;
this is real output, not a plan:

	catering-kiosk: User=viktor, Group=(absent), WorkingDirectory=
	/home/viktor/projects/silberloeffel-catering, Environment=PYTHONPATH=
	/home/viktor/projects/silberloeffel-catering/src, ExecStart uses
	/usr/bin/python3 (confirmed via readlink -f on the running process's
	/proc/<pid>/exe: resolves to /usr/bin/python3.13), --db
	/home/viktor/catering-runtime/core.db, no EnvironmentFile.

	catering-office-panel: identical User=/Group=/WorkingDirectory=/
	Environment=/interpreter to catering-kiosk; additionally has
	EnvironmentFile=/etc/catering/office-panel.env; same --db
	/home/viktor/catering-runtime/core.db.

The two units agree on every value this pack cares about — the
stop-and-flag condition above did not trigger. §3.6 below is filled in
with these confirmed values.

This same output also corrected a standing wrong assumption in every prior
version of this pack: the real Core DB path is
/home/viktor/catering-runtime/core.db, not /var/lib/catering/core.db as
DEPLOYMENT.md's general example and this pack's own earlier drafts assumed.
Every reference to the old path elsewhere in this document (§3.4's backup
source, §3.5's access checks, §3.6's ExecStart, §4.4/§4.9's SQL commands,
§4.10's rollback note) has been corrected in this revision to
/home/viktor/catering-runtime/core.db, and the directory check in §3.5 now
targets /home/viktor/catering-runtime instead of /var/lib/catering.

3.1 Generate the token (once, on the Lenovo or any trusted machine):

	openssl rand -hex 32

Save the output; it becomes WEBSITE_INTAKE_TOKEN below. This same value
will later (separate future step, not this pack) become the Worker's
UPSTREAM_TOKEN — but that pairing happens only when Tunnel/Worker are
configured, not now. Until then this token authenticates a receiver nothing
can reach anyway.

3.2 Create the env file without ever putting the token on a command line or
in shell history:

	sudo install -d -m 0750 -o root -g root /etc/catering
	sudo install -m 0600 -o root -g root /dev/null /etc/catering/website-intake.env
	sudoedit /etc/catering/website-intake.env

In the editor opened by sudoedit, write exactly one line:

	WEBSITE_INTAKE_TOKEN=<generated-token>

Save and exit. sudoedit never passes the secret as a process argument and
never places it in shell history, unlike `sh -c 'echo ... > file'` or
`echo ... | sudo tee`.

3.3 Verify the env file's ownership and permissions:

	sudo stat -c '%U %G %a %n' /etc/catering/website-intake.env

Expected output: root root 600 /etc/catering/website-intake.env. If it
differs, fix before proceeding (`sudo chown root:root` /
`sudo chmod 600`).

3.4 Take a timestamped, integrity-checked backup of the Core DB before
touching anything else on the host:

	BACKUP="/var/backups/catering/core-pre-website-intake-$(date +%Y%m%d-%H%M%S).db"
	sudo install -d -m 0750 /var/backups/catering
	sudo sqlite3 /home/viktor/catering-runtime/core.db ".backup '$BACKUP'"
	sudo sqlite3 "$BACKUP" "PRAGMA integrity_check;"

Expected: ok. Record the actual $BACKUP path used — it must be written into
the execution report (§9 below), not left implicit, since the filename is
no longer fixed/predictable.

3.5 Verify the service user can actually read and write where the receiver
needs to, before the unit ever starts it — read access to the DB file alone
is not sufficient, since SQLite (in the default rollback-journal mode this
repo's core.db already uses) needs to create a `-journal` sibling file next
to the database during writes, which requires write access to the
containing directory as well as the file:

	namei -l /home/viktor/catering-runtime/core.db
	sudo -u viktor test -r /home/viktor/catering-runtime/core.db
	sudo -u viktor test -w /home/viktor/catering-runtime/core.db
	sudo -u viktor test -w /home/viktor/catering-runtime

The confirmed service user is viktor. All three test commands must exit 0.

3.6 Create the systemd unit at infra/systemd/catering-website-intake.service
in the repo. This is the one file this pack proposes creating in the repo
(tracked); everything else in this section runs only on the Lenovo, outside
git. The values below are §3.0's confirmed real values (see the
confirmation block in §3.0 above) — no placeholders remain, and this is the
exact content the file will have once a separate explicit GO authorizes
actually writing it:

	# Website intake receiver (Worker-facing, loopback-only) — installed per
	# LENOVO_WEBSITE_INTAKE_SYSTEMD_IMPLEMENTATION_PACK_V1.
	# The token lives ONLY in /etc/catering/website-intake.env (root:root, 600), never here.

	[Unit]
	Description=Catering website intake receiver (Worker-facing, loopback-only)
	After=network.target
	StartLimitIntervalSec=60
	StartLimitBurst=5

	[Service]
	Type=simple
	User=viktor
	WorkingDirectory=/home/viktor/projects/silberloeffel-catering
	Environment=PYTHONPATH=/home/viktor/projects/silberloeffel-catering/src
	EnvironmentFile=/etc/catering/website-intake.env
	ExecStart=/usr/bin/python3 -m catering_system.ui.website_intake_endpoint --db /home/viktor/catering-runtime/core.db --host 127.0.0.1 --port 8083
	Restart=on-failure
	RestartSec=3

	[Install]
	WantedBy=multi-user.target

No Group= line — both catering-kiosk and catering-office-panel run with
Group= absent/empty, so per §3.0's rule this unit omits it too rather than
writing an empty value.

StartLimitIntervalSec=60 / StartLimitBurst=5 caps restart attempts to 5
within any 60-second window — without this, a bad token/env/DB path would
let Restart=on-failure + RestartSec=3 retry indefinitely, generating
continuous journal/process churn instead of surfacing as a clearly failed,
inspectable unit (systemctl status would show "failed" with
`systemctl reset-failed` needed to re-arm, which is the intended signal
that something needs human attention rather than infinite silent retries).

--host 127.0.0.1 remains explicit, overriding the code's own CLI default of
0.0.0.0 (website_intake_endpoint.py's argparse default) — same reasoning as
WEBSITE_INTAKE_RECEIVER_DEPLOYMENT_PACK_V1 §4: this process must never be
LAN-reachable, only reachable from another process on the same host (later:
cloudflared; today: nothing).

3.7 Install and enable on the Lenovo:

	sudo cp infra/systemd/catering-website-intake.service /etc/systemd/system/
	sudo systemctl daemon-reload
	sudo systemctl enable --now catering-website-intake

⸻

4. Verification (performed on the Lenovo, immediately after 3.7)

Record the install timestamp before starting this section — it is needed
for the journal check in §4.12, so the check is scoped to this install's
own activity rather than assumed log content:

	INSTALL_TS="$(date -Iseconds)"

4.1 systemctl status catering-website-intake → active (running)

4.2 ss -ltnp | grep 8083 or lsof -nP -iTCP:8083 -sTCP:LISTEN → must show
127.0.0.1:8083 only, never 0.0.0.0:8083 or *:8083 — if it shows a wildcard
bind, stop and fix the unit's --host flag before proceeding to anything
else.

4.3 Set up a private scratch directory for response bodies — never the
repo's WorkingDirectory, which must stay clean — and register cleanup
before anything is written to it, so it is removed even if a later step
fails:

	VERIFY_DIR="$(mktemp -d /tmp/catering-website-intake-verify.XXXXXX)"
	chmod 700 "$VERIFY_DIR"
	cleanup_verify() { rm -rf "$VERIFY_DIR"; unset WEBSITE_INTAKE_TOKEN; }
	trap cleanup_verify EXIT INT TERM

Read the token back out of the env file written in §3.2, then immediately
write it into a private curl config file inside $VERIFY_DIR rather than
ever interpolating it into a `-H` argument: an interpolated `-H
"Authorization: Bearer $TOKEN"` is expanded by the shell before curl even
starts, so the literal token sits in that curl process's argv and is
briefly visible to anyone who can run `ps` on the host during the request —
`--config` avoids that, since the header value then lives only in a
chmod-600 file curl reads internally, never in its own argv:

	WEBSITE_INTAKE_TOKEN="$(sudo sed -n 's/^WEBSITE_INTAKE_TOKEN=//p' /etc/catering/website-intake.env)"
	test -n "$WEBSITE_INTAKE_TOKEN"

	AUTH_CONFIG="$VERIFY_DIR/curl-auth.conf"
	printf 'header = "Authorization: Bearer %s"\n' "$WEBSITE_INTAKE_TOKEN" > "$AUTH_CONFIG"
	chmod 600 "$AUTH_CONFIG"

$AUTH_CONFIG is removed along with the rest of $VERIFY_DIR by
cleanup_verify; it is never referenced in the execution report (§9). The
$WEBSITE_INTAKE_TOKEN shell variable itself is still needed a little
longer — for the leak check in §4.8, which must run before it is unset
(see §4.8's ordering note) — so it is not unset here yet.

4.4 SQL baseline, taken before any HTTP request is sent:

	BASE_INQUIRIES="$(sudo sqlite3 /home/viktor/catering-runtime/core.db 'SELECT COUNT(*) FROM inquiries;')"
	BASE_ORDERS="$(sudo sqlite3 /home/viktor/catering-runtime/core.db 'SELECT COUNT(*) FROM orders;')"
	BASE_ORDER_VERSIONS="$(sudo sqlite3 /home/viktor/catering-runtime/core.db 'SELECT COUNT(*) FROM order_versions;')"

4.5 From the Lenovo itself (not remotely), request without a token:

	HTTP_1="$(curl -sS -o "$VERIFY_DIR/resp_1.json" -w '%{http_code}' -X POST \
	  http://127.0.0.1:8083/intake/website-form \
	  -H "Content-Type: application/json" \
	  -d '{"event_date":"2026-09-20"}')"
	test "$HTTP_1" = "401"

Proves the process answers and still enforces the token.

4.6 Generate a unique submission id for this install run — a fixed value
like "lenovo-install-smoke-1" must not be reused across installs/retries of
this pack, since a stale earlier row with the same id would make the
idempotency check in §4.8/§4.9 meaningless:

	SUBMISSION_ID="lenovo-install-smoke-$(date +%Y%m%d-%H%M%S)"

From the Lenovo itself, authenticated via the $AUTH_CONFIG file from §4.3
(not an interpolated header), first valid request:

	HTTP_2="$(curl -sS --config "$AUTH_CONFIG" -o "$VERIFY_DIR/resp_2.json" -w '%{http_code}' -X POST \
	  http://127.0.0.1:8083/intake/website-form \
	  -H "Content-Type: application/json" \
	  -d "{\"event_date\":\"2026-09-20\",\"submission_id\":\"$SUBMISSION_ID\"}")"
	test "$HTTP_2" = "202"

Record $SUBMISSION_ID (not the token) in the execution report (§9) — it is
the only handle for finding this test row later.

4.7 Immediately retry the identical request (same $SUBMISSION_ID) to prove
idempotency on the real host, not just in the earlier local-copy smoke
test:

	HTTP_3="$(curl -sS --config "$AUTH_CONFIG" -o "$VERIFY_DIR/resp_3.json" -w '%{http_code}' -X POST \
	  http://127.0.0.1:8083/intake/website-form \
	  -H "Content-Type: application/json" \
	  -d "{\"event_date\":\"2026-09-20\",\"submission_id\":\"$SUBMISSION_ID\"}")"
	test "$HTTP_3" = "202"

4.8 Leak check, then token cleanup — order is fixed and matters: the leak
check must run while $WEBSITE_INTAKE_TOKEN still holds its real value, and
only afterward is the variable unset, since `grep -F ""` against an
already-unset (empty) variable would trivially match almost any line and
silently defeat the check instead of proving anything:

	! grep -F "$WEBSITE_INTAKE_TOKEN" "$VERIFY_DIR"/resp_*.json
	unset WEBSITE_INTAKE_TOKEN

(grep exit 1 = no match = pass, evaluated before the unset above — never
after). No further reads of the token, from the env file or otherwise, are
needed for the remaining checks in this section.

Then, separately, strict response-body contract check on resp_2.json and
resp_3.json — executable, not descriptive:

	python3 - "$VERIFY_DIR/resp_2.json" "$VERIFY_DIR/resp_3.json" <<'PY'
	import json
	import sys

	first = json.load(open(sys.argv[1], encoding="utf-8"))
	second = json.load(open(sys.argv[2], encoding="utf-8"))

	for body in (first, second):
	    assert set(body) == {"accepted", "inquiry_id"}, body
	    assert body["accepted"] is True
	    assert isinstance(body["inquiry_id"], str) and body["inquiry_id"]

	assert first["inquiry_id"] == second["inquiry_id"]
	print(first["inquiry_id"])
	PY

A non-zero exit (an AssertionError) means the contract was violated — stop
and investigate rather than continuing to §4.9.

4.9 SQL post-check against the §4.4 baseline — executable assertions:

	POST_INQUIRIES="$(sudo sqlite3 /home/viktor/catering-runtime/core.db 'SELECT COUNT(*) FROM inquiries;')"
	POST_ORDERS="$(sudo sqlite3 /home/viktor/catering-runtime/core.db 'SELECT COUNT(*) FROM orders;')"
	POST_ORDER_VERSIONS="$(sudo sqlite3 /home/viktor/catering-runtime/core.db 'SELECT COUNT(*) FROM order_versions;')"
	MATCHING_ROWS="$(sudo sqlite3 /home/viktor/catering-runtime/core.db \
	  "SELECT COUNT(*) FROM inquiries WHERE inquiry_source='website_form' AND intake_external_ref='$SUBMISSION_ID';")"

	test "$POST_INQUIRIES" -eq $((BASE_INQUIRIES + 1))
	test "$POST_ORDERS" -eq "$BASE_ORDERS"
	test "$POST_ORDER_VERSIONS" -eq "$BASE_ORDER_VERSIONS"
	test "$MATCHING_ROWS" -eq 1

All four `test` commands must exit 0: exactly one new Inquiry (the retry in
§4.7 did not add a second row), Orders and OrderVersions structurally
untouched, exactly one row for (website_form, $SUBMISSION_ID).

4.10 Confirm in Office Panel (existing, unchanged UI) that exactly one
Inquiry appears with source website_form and intake_external_ref equal to
$SUBMISSION_ID. This record is kept, not deleted — it becomes a documented
production install-smoke record, identified by its $SUBMISSION_ID (recorded
in §9's execution report). No SQL DELETE is performed against
/home/viktor/catering-runtime/core.db by this pack, and no UI delete action is assumed
or invoked, since no confirmed, owner-approved "delete an Inquiry" flow has
been established anywhere in this project to date. If the owner later
wants this test record gone, that is its own separate, explicitly
authorized task using whatever Inquiry-removal mechanism is confirmed to
exist at that time — not decided or performed here.

4.11 From a second machine on the LAN (not the Lenovo), confirm
http://<lenovo-lan-ip>:8083/intake/website-form is NOT reachable (connection
refused/timeout) — this is the check that actually matters for the "no LAN
exposure" claim: it proves loopback-only binding holds under systemd, not
just under a manual foreground run.

4.12 Journal check, scoped to this install's own activity (using $INSTALL_TS
from the top of §4) and checked against actual output rather than an
assumed set of log lines:

	sudo journalctl -u catering-website-intake --since "$INSTALL_TS" --no-pager

Read the actual output and confirm the absence of: the token value, any
email address, any phone number, any message/subject text, and the full
request payload. Do not assume in advance which specific line format the
service logs at — verify against what is actually printed.

4.13 Explicit cleanup, in case the trap somehow did not fire (belt and
braces — §4.3 already registered it on EXIT/INT/TERM):

	cleanup_verify
	trap - EXIT INT TERM
	test ! -d "$VERIFY_DIR"

⸻

5. Rollback

Host rollback (undoes the running service on the Lenovo; does not touch
git):

	sudo systemctl disable --now catering-website-intake
	sudo rm -f /etc/systemd/system/catering-website-intake.service
	sudo systemctl daemon-reload
	sudo systemctl reset-failed catering-website-intake
	sudo rm -f /etc/catering/website-intake.env

SQLite file is untouched by any of the above, exactly like stopping kiosk
or office panel; the one test Inquiry from §4.10 remains as a harmless,
documented Office Panel record (its removal, if ever wanted, is the
separate future task §4.10 already describes). No Tunnel/Worker rollback is
needed by this pack — none was touched.

Git rollback (separate concern; only relevant if the tracked unit file
itself needs to be removed from the repo, independent of whether the host
install above has been undone): `git revert` or a follow-up commit removing
infra/systemd/catering-website-intake.service — its own explicit,
separately authorized step, not implied by or bundled with the host
rollback above. Doing the host rollback does not, by itself, remove the
tracked file from the repository, and vice versa.

⸻

6. Non-goals (explicit, matching the reviewer's stated next-step framing)

	•	no Cloudflare Tunnel installed or configured
	•	no cloudflared process, no tunnel credentials, no DNS/ingress config
	•	no Worker redeployed, no UPSTREAM_TOKEN or UPSTREAM_URL set or changed
	•	no public/Wix-facing change of any kind — the receiver remains
		unreachable from outside the Lenovo after this pack, by design
	•	no change to website_intake_endpoint.py, worker.js, or any other
		source file
	•	no change to Office Panel, kiosk, Order/OrderVersion,
		READY_TO_SEND, wirksam/effective, or CRM/AI Telefonist logic
	•	no idempotency behavior change — 2ed5510's find_by_source_and_
		external_ref logic is used as-is
	•	no Inquiry deletion mechanism introduced or invoked

⸻

7. Open gaps — not decided here, flagged for the owner

	•	resolved (2026-07-10): §3.0 has been run on the live Lenovo; User=,
		Group=, WorkingDirectory=, Environment=, and interpreter path all
		agree between catering-kiosk and catering-office-panel, and §3.6
		now carries those confirmed real values — no longer an open gap
	•	resolved (2026-07-10): the real Core DB path is
		/home/viktor/catering-runtime/core.db, not /var/lib/catering/
		core.db as every earlier version of this pack assumed — corrected
		throughout §2–§5 and §9 in this revision
	•	timing of the future Tunnel/Worker pack relative to this one — this
		pack can be performed and left running indefinitely with zero
		external exposure before Tunnel work ever starts
	•	whether/when the §4.10 test Inquiry should ever be removed, and by
		what confirmed mechanism — explicitly deferred, not decided here

⸻

8. Exit

Complete when: the unit file is reviewed and frozen as accepted, then (only
after a separate explicit GO) actually created in the repo — with §3.0's
real values, not placeholders — and committed, then (only after that, on
the physical Lenovo, by the owner) installed and verified per §4. This pack
authorizes none of the Lenovo-side ops actions itself — those remain the
owner's own actions, outside this pack's or Claude's execution, exactly as
WEBSITE_INTAKE_RECEIVER_DEPLOYMENT_PACK_V1 §13 already established for the
larger deployment design.

⸻

9. Execution report (§3.0 has actually been run and is filled in below;
§3.1 onward remain unperformed as of this revision)

	•	§3.0 confirmed values (live Lenovo, 2026-07-10): User=viktor,
		Group=(absent), WorkingDirectory=/home/viktor/projects/
		silberloeffel-catering, Environment=PYTHONPATH=/home/viktor/
		projects/silberloeffel-catering/src, interpreter=/usr/bin/python3
		(resolves to /usr/bin/python3.13); both existing units agree, stop
		condition not triggered; real Core DB path confirmed as
		/home/viktor/catering-runtime/core.db (corrected throughout this
		pack in this revision)
	•	§3.4 actual $BACKUP path and integrity_check result
	•	§3.5 access-check results (pass/fail for each of the three test
		commands)
	•	§4.6 actual $SUBMISSION_ID used
	•	§4.1–§4.13 actual results (statuses, counts, bind address, journal
		excerpt confirmation, VERIFY_DIR removal confirmed)

The WEBSITE_INTAKE_TOKEN value itself is never written into this report —
only a pass/fail confirmation that §4.3's `test -n "$WEBSITE_INTAKE_TOKEN"`
succeeded (i.e. it was read back from the env file correctly), exactly as
the secret handling in §3.2/§3.3 already established: the token lives only
in /etc/catering/website-intake.env, never in any document, log, or report.
