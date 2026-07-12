WEBSITE_INTAKE_RECEIVER_DEPLOYMENT_PACK_V1

0. Purpose

Deployment/ops-only pack. Specifies how website_intake_endpoint.py (0f6e034)
actually gets run and safely reached by the already-deployed Cloudflare
Worker (WORKER_TO_CORE_WEBSITE_INTAKE_PACK_V1, frozen 1dd6a75), without
deploying anything, without touching Worker secrets, and without creating
any systemd/tunnel config file yet. No code changes, no ops actions in this
pack. Every claim below was checked against current code and deployment
artifacts on 2026-07-10 (src/catering_system/ui/website_intake_endpoint.py,
infra/cloudflare_worker/worker.js, DEPLOYMENT.md, infra/systemd/*.service,
PUBLIC_SITE_EXECUTION_PACK_V1.md).

⸻

1. Current state — evidence base

1.1 website_intake_endpoint.py (0f6e034) exists, is tested (14 pytest +
implicitly exercised via the shared adapter's own 21 tests), and is
runnable via `python3 -m catering_system.ui.website_intake_endpoint --db
<path> --token <token>` — but has never been started outside pytest's
in-process live-socket fixtures. Its CLI defaults: `--host 0.0.0.0`, `--port
8083`, `--token` from `--token` or `WEBSITE_INTAKE_TOKEN`; refuses to start
without a token (mirrors office_panel.py's own password-required pattern).

1.2 infra/cloudflare_worker/worker.js (0f6e034) is deployed today
(DEPLOYMENT.md §3's `wrangler deploy` command is real) and already performs
`fetch(env.UPSTREAM_URL, {headers: {Authorization: `Bearer
${env.UPSTREAM_TOKEN}`}})` after sanitizing. Its `ALLOWED_FIELDS` now
includes website_form's full field set (1dd6a75/0f6e034). What `UPSTREAM_URL`
currently points to in the live deployment is unknown from repo evidence
alone (it is set via `wrangler secret put` / dashboard config, not
committed) — per WORKER_TO_CORE_WEBSITE_INTAKE_PACK_V1 §1.4, nothing in this
repo has ever consumed it, so it plausibly points nowhere real yet.

1.3 The Lenovo already runs two always-on Python HTTP services via systemd
(DEPLOYMENT.md §1b, infra/systemd/catering-kiosk.service,
catering-office-panel.service), against the same SQLite file
(/var/lib/catering/core.db), plus a daily backup cron (§1c). This is the
proven, existing operational pattern this pack's receiver follows —
no new pattern invented.

1.4 DEPLOYMENT.md §3 gives the Worker's actual deploy shape: `npx wrangler
deploy worker.js --name catering-intake`, `npx wrangler secret put
UPSTREAM_TOKEN`, `UPSTREAM_URL` as a plain var (dashboard or wrangler.toml).
No Cloudflare Tunnel is mentioned or configured anywhere in this repo today
— WORKER_TO_CORE_WEBSITE_INTAKE_PACK_V1 §3/§12 recommended one but left it
as an explicit open gap. This pack treats Tunnel setup the same way:
recommended, not configured.

⸻

2. Deployment boundary

	•	Office Panel stays LAN-only, unchanged — nothing in this pack touches
		port 8081 or its deployment
	•	the receiver is never bound to a LAN-reachable interface — its only
		real client is a local process (cloudflared) on the same host, so it
		binds 127.0.0.1 only, not the codebase's own CLI default of 0.0.0.0
		(§4 explains why this is a deployment-time flag choice, not a code
		change)
	•	no broad Core exposure — the receiver's one route, already built and
		tested, is the entire reachable surface
	•	no direct browser-to-Core path is created by this pack — only
		Worker → Tunnel → receiver, exactly as WORKER_TO_CORE_WEBSITE_
		INTAKE_PACK_V1 §3 already fixed
	•	this pack documents deployment; it performs none of it

⸻

3. Recommended V1 deployment topology

Same host as Core DB and Office Panel — the kitchen Lenovo — as a third
systemd service, for the exact reason WORKER_TO_CORE_WEBSITE_INTAKE_PACK_V1
already gave and this pack confirms against DEPLOYMENT.md's frozen rule
("Core-on-Lenovo is a frozen rule," §1): the receiver writes into the same
SQLite file the kiosk and office panel already use; a separate host would
mean either a network-shared SQLite file (fragile, unsupported by this
codebase's sqlite3.connect() usage) or a second database (a second source of
truth — forbidden by every pack in this chain). Docker/container is not
adopted for V1: nothing else in this deployment uses containers
(DEPLOYMENT.md's entire bring-up is bare systemd + venv/PYTHONPATH), and
introducing one component's worth of container tooling for a single Python
stdlib script would be new operational surface for no functional gain.

⸻

4. Runtime / service design

Process: `PYTHONPATH=/opt/catering/src python3 -m
catering_system.ui.website_intake_endpoint --db
/var/lib/catering/core.db --host 127.0.0.1 --port 8083` — same DB path the
kiosk/office panel already use (§1.3), same PYTHONPATH convention
(DEPLOYMENT.md §1/§1a).

Bind address: 127.0.0.1, explicitly overriding the code's own `--host
0.0.0.0` default. This is a deployment-time flag, not a code change — the
default stays 0.0.0.0 in the CLI (useful for local dev/testing exactly as
this pack's own §8 smoke tests use it) but production systemd ExecStart
pins it to loopback-only, since the only intended caller is cloudflared
running on the same machine (§5). This mirrors how office_panel.py's own
0.0.0.0 default is intentional there (real LAN clients exist) while being
wrong here (no real LAN client should ever exist for this route).

Port: 8083 — already the code's own default, already reserved for this
purpose by WORKER_TO_CORE_WEBSITE_INTAKE_PACK_V1 §3 (8081 office panel,
8082 kiosk are taken).

Future systemd unit (not created by this pack) —
infra/systemd/catering-website-intake.service, identical shape to the
existing two:

	[Unit]
	Description=Catering website intake receiver (Worker-facing, loopback-only)
	After=network.target

	[Service]
	Type=simple
	User=catering
	WorkingDirectory=/opt/catering
	Environment=PYTHONPATH=/opt/catering/src
	EnvironmentFile=/etc/catering/website-intake.env
	ExecStart=/usr/bin/python3 -m catering_system.ui.website_intake_endpoint --db /var/lib/catering/core.db --host 127.0.0.1 --port 8083
	Restart=on-failure
	RestartSec=3

	[Install]
	WantedBy=multi-user.target

Future env file (not created by this pack) — /etc/catering/website-intake.env,
chmod 600, same convention as office-panel.env:

	WEBSITE_INTAKE_TOKEN=<strong-random-token>

⸻

5. Tunnel / Worker configuration design

Recommended mechanism: Cloudflare Tunnel (cloudflared), not a firewalled
public port. Rationale, concrete rather than generic: a Tunnel makes an
outbound-only connection from the Lenovo to Cloudflare's edge — no inbound
port is ever opened on the Lenovo's router/firewall, which is a strictly
smaller exposure than even a token-gated public port (§1.4's "Worker must
reach it via public internet" constraint is satisfied without any inbound
listener at all). It also pairs naturally: the Worker already lives on the
same vendor's edge network.

Future cloudflared config shape (not created by this pack), roughly:

	tunnel: <tunnel-id>
	credentials-file: /etc/cloudflared/<tunnel-id>.json
	ingress:
	  - hostname: intake-internal.<owner-chosen-domain>
	    service: http://127.0.0.1:8083
	  - service: http_status:404

The exact hostname is an owner decision (§12) — a subdomain that is never
linked from the public site, never indexed, and ideally not guessable;
security here rests on WEBSITE_INTAKE_TOKEN, not on the hostname being
secret, but there is no reason to make it easy to find either.

Future wrangler commands (not run by this pack):

	npx wrangler secret put UPSTREAM_TOKEN
	# paste the same value as WEBSITE_INTAKE_TOKEN

	# UPSTREAM_URL set as a plain var (wrangler.toml or dashboard):
	# https://intake-internal.<owner-chosen-domain>/intake/website-form

Future worker redeploy (only needed if UPSTREAM_URL/UPSTREAM_TOKEN change or
worker.js itself is redeployed — this pack's own worker.js change, 0f6e034,
is not yet deployed):

	cd infra/cloudflare_worker
	npx wrangler deploy worker.js --name catering-intake

⸻

6. Secrets / token handling

	•	WEBSITE_INTAKE_TOKEN (receiver-side) and UPSTREAM_TOKEN (Worker-side)
		must hold the identical value — two env var names for the same
		shared secret, one on each side of the Tunnel, matching the existing
		UPSTREAM_TOKEN/office-panel-password pattern of "the secret lives
		only in its own chmod-600 file, never in code, never committed"
	•	generation: a long random token (e.g. `openssl rand -hex 32`),
		generated once, stored in both places, never derived from anything
		guessable
	•	no secret is committed to git under this pack — the future env file
		and the future wrangler secret command are both outside the repo's
		tracked content, exactly like OFFICE_PANEL_PASSWORD and the existing
		UPSTREAM_TOKEN already are
	•	rotation procedure: generate a new token; update
		/etc/catering/website-intake.env and `systemctl restart
		catering-website-intake` first, then `wrangler secret put
		UPSTREAM_TOKEN` with the same new value. Honest limitation, not
		hidden: the code supports exactly one valid token at a time (no
		grace-period dual-token acceptance), so there is an unavoidable
		short window between the two steps where a real Worker request
		would 401 — acceptable for a low-traffic V1 channel, worth noting
		for whoever performs the rotation so it isn't mistaken for a bug
	•	logs must never contain the token itself — website_intake_endpoint.py
		already only logs "auth rejected" on failure (0f6e034), never the
		header value; this pack does not change that

⸻

7. DB safety

	•	the receiver writes into the exact same SQLite file the kiosk and
		office panel already use (§1.3) — no new database, no new
		connection pattern
	•	HTTPServer (not ThreadingHTTPServer) is deliberate, already in the
		code (0f6e034's own comment references WORKLOG Entry 048) — the
		same single-thread constraint every SQLite-backed server in this
		repo already respects; this pack does not revisit that decision,
		only confirms the deployment doesn't fight it (no reverse proxy or
		process manager should ever run multiple instances of this service
		against the same DB file concurrently)
	•	before first deployment: take a manual backup in addition to the
		existing daily cron (DEPLOYMENT.md §1c) —
		`sqlite3 /var/lib/catering/core.db ".backup
		/var/backups/catering/core-pre-website-intake.db"` — a named,
		one-off safety copy, separate from the rotating daily backups, kept
		until the receiver has been live for a few days without incident
	•	test against a copied DB first — the same isolated-copy discipline
		already used repeatedly this session for every prior live-test
		(copy core.db, run the receiver against the copy on a scratch port,
		never the production file, verify, then discard the copy) — §8
		gives the exact commands
	•	verify Inquiry count changes only after the smoke test, by exactly
		one per successful POST — no bulk change, no unexpected rows
	•	verify Orders/OrderVersions counts are unchanged before and after —
		structurally guaranteed by the code (the receiver never imports
		order_service.py or operational_core_service.py), but verified
		empirically anyway, matching this project's "trust but verify"
		practice from every prior live-test in this chain

⸻

8. Smoke test plan

All commands run against a copied DB on a non-production port first (§7);
only after these pass on a copy should the same sequence ever be considered
against the real Lenovo deployment, and even then only manually, by the
owner, outside this pack's scope.

	1.	cp core.db /tmp/core-smoke-test.db
	2.	start the receiver against the copy:
		WEBSITE_INTAKE_TOKEN=smoke-test-token python3 -m
		catering_system.ui.website_intake_endpoint --db
		/tmp/core-smoke-test.db --host 127.0.0.1 --port 8093
	3.	curl without a token → expect 401:
		curl -i -X POST http://127.0.0.1:8093/intake/website-form
		-H "Content-Type: application/json" -d '{"event_date":"2026-09-20"}'
	4.	curl with the correct token and a valid payload → expect 202 with
		{"accepted": true, "inquiry_id": "..."}:
		curl -i -X POST http://127.0.0.1:8093/intake/website-form
		-H "Authorization: Bearer smoke-test-token"
		-H "Content-Type: application/json"
		-d '{"event_date":"2026-09-20","guest_count_estimate":10,"message":"Testanfrage"}'
	5.	inspect the copied DB directly: exactly one new row in inquiries,
		inquiry_source = 'website_form', intake_message contains the test
		message — sqlite3 /tmp/core-smoke-test.db "SELECT inquiry_source,
		intake_message FROM inquiries ORDER BY created_at DESC LIMIT 1;"
	6.	verify orders/order_versions row counts are identical to before step
		2 — sqlite3 /tmp/core-smoke-test.db "SELECT COUNT(*) FROM orders;"
		and the same for order_versions
	7.	confirm the response body from step 4 contains no more than
		accepted/inquiry_id — no echoed message/contact text (already
		covered by 0f6e034's own tests; this is the manual equivalent)
	8.	stop the receiver, delete /tmp/core-smoke-test.db
	9.	only once a real Tunnel + Worker deployment exists (future, separate
		step): send one real test submission through the actual public
		site/Worker path and confirm it arrives as an Inquiry — the same
		checks as steps 5-7, this time end-to-end; confirm the site's own
		success message stays the generic "wir rufen Sie zurück"-style copy
		(PUBLIC_SITE §4) regardless of the receiver's actual response body,
		since the Worker already never relays upstream content to the
		public caller (worker.js's existing code, unchanged)
	10.	confirm the Worker still strips an unrecognized field — one curl
		directly at the Worker's own public URL with an extra field (e.g.
		"admin": true) and confirm it never appears in what the receiver
		logs or in the resulting Inquiry

⸻

9. Rollback plan

	•	stop the service: `systemctl stop catering-website-intake` (or, if
		not yet running as a service, kill the manually-started process) —
		the SQLite file is untouched by stopping the process, exactly like
		stopping the kiosk or office panel today
	•	disable the Tunnel ingress rule (or the whole cloudflared service) so
		the Worker's fetch to UPSTREAM_URL starts failing closed —
		worker.js's existing code already returns "upstream error"/502 to
		the public caller on any non-2xx or connection failure, so a
		disabled receiver degrades to "the form doesn't work" rather than
		any Core exposure risk
	•	alternatively, unset or repoint UPSTREAM_URL (wrangler secret/var
		update) if a full Worker rollback is preferred over a Tunnel-level
		disable — either achieves the same effect
	•	no data rollback is needed for Inquiries already created during
		testing or a brief live period — they remain ordinary,
		office-reviewable Inquiry records (source = website_form), exactly
		as disposable and low-stakes as every other channel's Inquiries;
		the office can simply review and either convert or ignore them
		through the existing, unchanged Office Panel flow
	•	no Order rollback is ever needed, structurally — nothing in this
		chain, at any point, creates an Order

⸻

10. Future implementation checklist (not performed by this pack)

	•	generate WEBSITE_INTAKE_TOKEN, create /etc/catering/website-intake.env
		(chmod 600)
	•	create infra/systemd/catering-website-intake.service (§4's shape)
	•	sudo cp ... /etc/systemd/system/, daemon-reload, enable --now
	•	set up cloudflared (tunnel create, DNS route, ingress config, §5)
	•	confirm UPSTREAM_TOKEN (Worker secret) equals WEBSITE_INTAKE_TOKEN
	•	set UPSTREAM_URL to the Tunnel-exposed HTTPS address
	•	deploy the already-committed worker.js (0f6e034) via wrangler
	•	run §8's smoke test sequence against the real host (on a DB copy
		first, per §7)
	•	only then point the actual public site form (once it exists,
		PUBLIC_SITE §7's own phasing) at the Worker URL
	•	add journalctl -u catering-website-intake -f to the office/ops
		runbook alongside the existing two services' log commands

⸻

11. Non-goals

	•	no real production deployment performed by this pack
	•	no systemd unit file created now (§4 shows its future shape only)
	•	no Tunnel config created now (§5 shows its future shape only)
	•	no Worker secret changed now (WEBSITE_INTAKE_TOKEN/UPSTREAM_TOKEN
		rotation described, not executed)
	•	no Worker redeployed now (0f6e034's worker.js stays undeployed)
	•	no Office Panel exposure of any kind
	•	no file upload support (unchanged from every prior pack in this
		chain)
	•	no duplicate/idempotency implementation — still the open gap
		WORKER_TO_CORE_WEBSITE_INTAKE_PACK_V1 §7 already named, not solved
		by adding deployment
	•	no CRM integration touched by this pack
	•	no AI Telefonist touched by this pack
	•	no automatic Order conversion — the existing, unchanged, manual
		"In Auftrag umwandeln" office action remains the only path

⸻

12. Open gaps — not decided here, flagged for the owner

	•	the Tunnel hostname (intake-internal.<domain> in §5 is a placeholder)
		— an owner naming decision
	•	whether cloudflared is already installed/available on the Lenovo, or
		needs its own separate bring-up step first — unknown from repo
		evidence, an ops question
	•	token rotation cadence/policy — none exists for OFFICE_PANEL_PASSWORD
		or UPSTREAM_TOKEN either today; this pack does not introduce a new
		gap, only inherits the existing one (same note as WORKER_TO_CORE_
		WEBSITE_INTAKE_PACK_V1 §12)
	•	whether the manual pre-deployment backup (§7) should be automated
		into a one-line runbook step or stays a manual owner action —
		deferred
	•	monitoring/alerting if the receiver process dies (systemd's
		Restart=on-failure covers process crashes; nothing here alerts a
		human) — same gap level as the existing two services today, not
		newly introduced

⸻

13. Exit

Complete when this document is reviewed and frozen as accepted deployment
design, with zero ops actions taken and zero code changes. Actual
deployment (§10's checklist) is a separate future step, performed by the
owner outside this pack's authorization, each item its own explicit action
— this pack documents the shape, it does not perform any of it.
