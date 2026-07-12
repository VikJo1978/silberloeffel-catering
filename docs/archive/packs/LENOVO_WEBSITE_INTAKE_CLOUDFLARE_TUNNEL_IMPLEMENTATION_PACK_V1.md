LENOVO_WEBSITE_INTAKE_CLOUDFLARE_TUNNEL_IMPLEMENTATION_PACK_V1

0. Purpose

Planning/documentation-only pack. Covers exactly one narrow step: how
cloudflared, running on the same kitchen Lenovo as the already-installed
catering-website-intake.service (infra/systemd/catering-website-intake.
service, 61a4296), would reach that receiver's existing loopback listener
at http://127.0.0.1:8083 — nothing beyond that. No cloudflared install, no
tunnel creation, no Cloudflare authentication, no DNS change, no
credentials file, no Worker secret change, no Worker deploy, no Core code
change, no receiver code change, and no systemd unit created or modified
in this pack. Every claim below was checked against current repo state on
2026-07-11: infra/cloudflare_worker/worker.js, DEPLOYMENT.md,
infra/systemd/catering-website-intake.service (accepted 61a4296),
WEBSITE_INTAKE_RECEIVER_DEPLOYMENT_PACK_V1.md,
WORKER_TO_CORE_WEBSITE_INTAKE_PACK_V1.md,
LENOVO_WEBSITE_INTAKE_SYSTEMD_IMPLEMENTATION_PACK_V1.md, and a repo-wide
search for cloudflared/tunnel/UPSTREAM_URL/UPSTREAM_TOKEN/account/zone/
hostname references (§3 records what that search did and did not find).

Revision note (v2, this version): incorporated 5 corrections from the
first review round. (1) Cloudflare Tunnels come in two distinct management
models — locally-managed (config.yml + credentials JSON on the host) and
remotely-managed (ingress configured in the Cloudflare dashboard, connector
run via a single tunnel token) — and this pack previously described only
the locally-managed shape while leaving the choice open elsewhere; §2, §4,
§6, §7, §8, §9, and §12 now treat the model choice as its own explicit gate
and never mix the two models' artifacts. (2) The claim that the Tunnel's
ingress rule alone restricts traffic to the receiver's one route was
imprecise — an ingress rule without a path matcher forwards every path
under a hostname to the target service; §5 and §7 now require an explicit
path matcher for /intake/website-form, and §10 gained checks proving
unmatched paths get a Tunnel-level 404 rather than reaching the receiver.
(3) §12 gained an explicit security-model gate (public hostname + Bearer
token only, vs. adding Cloudflare Access Service Auth as a second
independent layer) that must be decided before any DNS/public hostname
step — not decided in this pack, and if Access is chosen it becomes its
own separate pack with its own Worker secrets, not folded into this one.
(4) The "local Tunnel verification before DNS" gate was underspecified;
§12's gate is now a precise, local-only checklist (config validation,
connector startup, Tunnel connection status, receiver still reachable
directly, ingress rule matching via a locally-run command if the installed
cloudflared version supports one) and explicitly does not claim a public
hostname is reachable before a DNS/public-hostname route exists — Cloudflare
requires that mapping to exist first, and creating it is its own later
gate. (5) §4's discovery no longer conflates "Cloudflare account login on
the Lenovo" with tunnel existence — remotely-managed connectors need only a
tunnel token, not a local cert.pem/login — and now separately asks whether
any found artifact is locally- or remotely-managed evidence, whether a
Tunnel already exists in the Dashboard (an account-side check, not a
Lenovo shell command), and explicitly forbids printing any token,
credentials JSON, or cert.pem content during discovery.

Revision note (v3, this version): incorporated 3 further corrections from
the second review round. (1) §6.2 now states an explicit architectural
default for a new production tunnel — dedicated, remotely-managed — rather
than presenting locally-managed and remotely-managed as equally likely
choices; locally-managed remains available only as a discovery-based
exception when an existing locally-managed tunnel is found and a separate
review decides to reuse it (§6.3). This is a default, not an
authorization — it creates nothing by itself. (2) §8.2/§9 now prefer
cloudflared's `--token-file`/`TUNNEL_TOKEN_FILE` mechanism (available from
cloudflared 2025.4.0) for the remotely-managed model's one local secret,
keeping the token out of both argv and any environment variable's own
value; the previous chmod-600-env-file approach is now an explicit,
version-gated fallback only, used if the installed cloudflared predates
that flag. The imprecise phrase "no local config.yml or credentials JSON
at all" was also corrected to "no local ingress config.yml or tunnel
credentials JSON; the connector still requires a protected local token or
token-file." (3) §10.4a no longer asserts a literal Tunnel-level 404 for
unmatched paths under both management models — that expectation is
Cloudflare-documented and correct for locally-managed's config.yml
catch-all rule, but for a remotely-managed Dashboard-configured hostname
this pack now requires checking, not assuming, that the request never
reaches the receiver (via the receiver's own journal) and recording
whatever actual Cloudflare-side response status is observed.

Boundary — this pack covers only:

	cloudflared on Lenovo → http://127.0.0.1:8083

It explicitly excludes:

	•	Worker deployment (worker.js stays exactly as committed, undeployed
		changes included — this pack does not run `wrangler deploy`)
	•	Worker secret changes (UPSTREAM_TOKEN, UPSTREAM_URL — both stay
		whatever they currently are in the live Cloudflare dashboard, which
		this pack has no visibility into and does not touch)
	•	Wix/browser changes — the public site/form is untouched
	•	public Office Panel — port 8081 stays LAN-only, never routed through
		anything this pack describes
	•	public kiosk — port 8082 stays LAN-only, same reasoning
	•	any broad Core endpoint — the Tunnel's only destination, in every
		version of this pack's proposed config, is 127.0.0.1:8083, and
		(per this revision's §5/§7 correction) the ingress rule itself
		must be path-matched to exactly /intake/website-form, not left as
		a bare hostname rule that would forward every path underneath it
	•	Core schema or business-logic changes — none proposed, none needed

⸻

1. Confirmed live facts

	•	receiver address: 127.0.0.1:8083 (loopback-only; confirmed bound
		there, not 0.0.0.0, per the live verification already performed
		when catering-website-intake.service was installed and accepted)
	•	receiver service name: catering-website-intake.service, enabled and
		active on the Lenovo (infra/systemd/catering-website-intake.
		service, committed 61a4296)
	•	live repo path on the Lenovo: /home/viktor/projects/
		silberloeffel-catering
	•	live Core DB path: /home/viktor/catering-runtime/core.db
	•	the receiver is already production-smoke-tested: a valid request
		returns 202, a duplicate submission_id returns the same
		inquiry_id, exactly one Inquiry is created, orders and
		order_versions counts are unchanged, and the journal shows no
		token/payload content — all already proven live, not re-litigated
		by this pack
	•	/etc/catering/website-intake.env exists on the Lenovo, root:root,
		600, holding WEBSITE_INTAKE_TOKEN — this pack does not read, copy,
		or reference its value anywhere
	•	ports 8081 (catering-office-panel) and 8082 (catering-kiosk) are
		unrelated, pre-existing LAN-only services on the same host — no
		relationship to this pack's scope other than "must not be exposed
		by whatever this pack eventually proposes"
	•	whatever Tunnel/ingress configuration is eventually implemented
		must expose only the receiver's route — never Office Panel, never
		kiosk, never a generic catch-all forward to the Lenovo's LAN

⸻

2. Facts still unknown — explicit stop conditions, not guesses

None of the following were found anywhere in this repository (§3 records
the exact searches run) and none are invented here. Each remains an open
question the owner must answer before any Cloudflare-side action is taken
— none of these are filled in with a placeholder that could accidentally
be executed as if it were real:

	•	whether cloudflared is already installed on the Lenovo, and if so
		which version — unknown; §4's discovery commands answer this
	•	whether a Cloudflare account login/credential already exists on the
		Lenovo (e.g. from a prior, unrelated cloudflared use) — unknown
	•	which Cloudflare account this Tunnel should belong to — not
		determinable from repo evidence; the repo contains no account ID,
		email, or dashboard reference anywhere
	•	which zone/domain this Tunnel should be associated with — unknown;
		no domain name is committed anywhere in this repo (checked: no
		wrangler.toml exists at all, and no .md file names a real domain —
		WEBSITE_INTAKE_RECEIVER_DEPLOYMENT_PACK_V1.md §5 uses the literal
		placeholder text "intake-internal.<owner-chosen-domain>", never a
		real value)
	•	the intended private/public hostname for the intake route — same
		placeholder-only status; an owner naming decision, not decided here
	•	tunnel name — no tunnel has ever been created per any prior pack's
		own explicit non-goals; there is no existing name to reuse
	•	whether an existing Cloudflare Tunnel (created for some unrelated
		purpose) should be reused, or a dedicated tunnel created for this
		route specifically — unknown until §4.1's host-side and §4.2's
		account-side discovery are both run
	•	confirmation that §6.2's default (a new dedicated tunnel is
		remotely-managed) is actually what gets built, or a reasoned,
		discovery-based departure from it (locally-managed, only if an
		existing locally-managed tunnel is found and a separate review
		decides to reuse it, §6.2/§6.3) — a distinct, explicit decision
		gate (§12), not skipped just because a default now exists
	•	if an existing Tunnel is found and reused (previous bullet), which
		management model that specific Tunnel already uses — a tunnel's
		management model is fixed at creation and cannot be silently
		switched; reusing it means accepting whatever model it already has
	•	credentials-file and config.yml ownership and filesystem paths on
		the Lenovo (locally-managed only) — cloudflared's own install
		method determines its defaults (§6); nothing here assumes a
		specific path in advance
	•	whether Cloudflare Access (Service Auth / service tokens) should
		sit in front of the public hostname as a second independent layer
		beyond the receiver's own Bearer token — an explicit security
		decision gate (§12), not decided here; if adopted, it needs its
		own separate pack and its own Worker secrets, not folded into this
		implementation
	•	the exact UPSTREAM_URL format the Worker will eventually need
		(depends on the confirmed hostname above, which does not exist
		yet) — cannot be stated as a real value; §7's config shape marks
		this explicitly as a placeholder

Any of the above appearing as a concrete value anywhere in a future
execution step must trace back to owner confirmation or §4's discovery
output — never to an assumption carried over from this pack.

⸻

3. Repository search performed for this pack (evidence, not assumption)

Searched the full repository (2026-07-11) for: cloudflared, tunnel,
UPSTREAM_URL, UPSTREAM_TOKEN, account_id, zone_id, hostname, DNS route.
Findings:

	•	infra/cloudflare_worker/ contains only worker.js and
		sanitize.test.mjs — no wrangler.toml, no account/zone
		configuration file of any kind exists in this repo
	•	every reference to "cloudflared" or "tunnel" in the repo is
		documentation-only, inside packs already reviewed for this chain
		(WEBSITE_INTAKE_RECEIVER_DEPLOYMENT_PACK_V1.md,
		WORKER_TO_CORE_WEBSITE_INTAKE_PACK_V1.md,
		LENOVO_WEBSITE_INTAKE_SYSTEMD_IMPLEMENTATION_PACK_V1.md,
		WEBSITE_FORM_INQUIRY_OFFICE_UX_PACK_V1.md,
		WEBSITE_FORM_INTAKE_IDEMPOTENCY_PACK_V1.md) — all describing the
		mechanism as recommended-but-not-configured, none containing a
		real hostname, tunnel ID, or credentials path
	•	UPSTREAM_URL and UPSTREAM_TOKEN appear only as env-binding names
		read by worker.js (`env.UPSTREAM_URL`, `env.UPSTREAM_TOKEN`) and in
		DEPLOYMENT.md §3's deploy commands (`npx wrangler secret put
		UPSTREAM_TOKEN`, "# set UPSTREAM_URL as a plain var in
		wrangler.toml or the dashboard") — their live values are set via
		wrangler/dashboard, outside this repo, and were not and are not
		inspected by this pack
	•	the only Worker name recorded anywhere in this repo is
		catering-intake, from DEPLOYMENT.md §3's own `npx wrangler deploy
		worker.js --name catering-intake` — an existing, already-documented
		fact, not invented by this pack; whether that deployed Worker is
		still live, and what its current UPSTREAM_URL/UPSTREAM_TOKEN are,
		is unknown from repo evidence alone (same open gap
		WEBSITE_INTAKE_RECEIVER_DEPLOYMENT_PACK_V1.md §1.2 already named)
	•	no account ID, zone ID, or real domain name was found anywhere in
		tracked repository content

⸻

4. Discovery — split into host-side (Lenovo shell) and account-side
(Cloudflare Dashboard); neither prints any secret

4.1 Local host discovery (read-only; owner runs on the Lenovo). None of
these commands install, configure, authenticate, or change anything —
every one is read-only inspection, run before any decision is made. None
of them require a Cloudflare login and none of them reveal whether a
Tunnel exists in the account — that is §4.2's job:

	command -v cloudflared || true
	cloudflared --version 2>/dev/null || true
	systemctl list-unit-files | grep -i cloudflared || true
	systemctl list-units --all | grep -i cloudflared || true
	sudo find /etc /home/viktor -maxdepth 4 \
	  \( -iname '*cloudflared*' -o -iname 'config.yml' -o -iname 'config.yaml' \
	     -o -iname 'cert.pem' -o -iname '*.json' \) \
	  2>/dev/null
	ss -ltnp

If any cloudflared-named systemd unit is found, additionally inspect (but
do not print the value of any secret argument it references):

	systemctl cat <found-unit-name>

Interpreting the output — explicitly distinguishing which management
model (§6.2) each signal points to, since the two are not interchangeable:

	•	command -v cloudflared / --version: empty output = not installed;
		a version string = already installed, and §6.1's "install vs.
		reuse" choice is answered — reuse what's there rather than
		reinstalling. This says nothing about which management model any
		existing tunnel uses.
	•	systemctl list-unit-files / list-units: any cloudflared-named unit
		found means a prior setup may already exist and must be inspected
		before assuming this pack's §5/§7 apply cleanly
	•	the found unit's ExecStart=, once inspected: a `--config <path>`
		flag pointing at a config.yml is locally-managed evidence; a
		`--token <value>` flag (or a `TUNNEL_TOKEN`-style environment
		reference) is remotely-managed evidence — these are mutually
		exclusive signals, not two options to combine
	•	the find command: locates any existing cloudflared config.yml
		and/or credentials JSON / cert.pem under /etc or the Lenovo home
		directory — their mere presence is locally-managed evidence; their
		absence, combined with a running cloudflared process, is
		remotely-managed evidence. Do not open, cat, or otherwise print
		the contents of any credentials JSON, cert.pem, or token value
		found this way — file existence and path only matter for this
		discovery step, never the secret material itself
	•	ss -ltnp: confirms the current full port-listen picture on the
		Lenovo (8081, 8082, 8083 already known; anything else present is
		relevant context, not touched by this pack)

4.2 Cloudflare account-side discovery (Dashboard; not a Lenovo shell
command, and not necessarily requiring any credential to already exist on
the Lenovo — remotely-managed connectors need only a tunnel token issued
at connector-start time, not a persistent local login). The owner checks,
in Zero Trust → Networks → Tunnels:

	•	whether any Tunnel already exists on the target account at all
	•	for each Tunnel found: its displayed connector/management type
		(the Dashboard distinguishes locally-managed "cloudflared"
		connectors from remotely-managed ones configured entirely in the
		Dashboard)
	•	for each Tunnel found: who currently manages its ingress/public
		hostname routes — a local config.yml (locally-managed) or the
		Dashboard's own "Public Hostname" tab (remotely-managed) — these
		are mutually exclusive per tunnel, never both at once
	•	whether any existing Tunnel is already idle/unused and could be
		reused, versus all existing Tunnels being in active use for
		unrelated purposes (in which case a dedicated new Tunnel, per
		§6.3, is the only safe option)

Repository-side discovery has already been performed for this pack (§3) —
no further repo search is needed before proceeding to review; only the
live-host (§4.1) and Cloudflare-account (§4.2) facts above remain open.

⸻

5. Recommended architecture

	•	cloudflared runs on the same Lenovo as the receiver — not a
		separate host, for the same "outbound-only connection, no inbound
		port ever opened" reasoning WEBSITE_INTAKE_RECEIVER_DEPLOYMENT_
		PACK_V1 §5 already gave, restated here because it is the load-
		bearing reason for the whole architecture: a Cloudflare Tunnel
		makes only an outbound connection from the Lenovo to Cloudflare's
		edge, so no port is ever opened on the Lenovo's router/firewall
	•	ingress forwards to http://127.0.0.1:8083, restricted by an
		explicit path matcher (§7) to exactly /intake/website-form — an
		ingress rule without a path matcher forwards every path under its
		hostname to the target service, so the path matcher, not the bare
		hostname rule, is what actually keeps this narrow; the receiver's
		own routing (only POST /intake/website-form accepted, everything
		else already 404/405 today) is a second, independent layer, not a
		substitute for the Tunnel-level restriction
	•	the receiver itself is unchanged and stays loopback-only; cloudflared
		becomes its only real client, exactly as
		LENOVO_WEBSITE_INTAKE_SYSTEMD_IMPLEMENTATION_PACK_V1.md's own
		Purpose section already anticipated ("inert but running, ready for
		Tunnel to be pointed at it later")
	•	no firewall rule opens port 8083 — the Tunnel's outbound-only model
		makes this unnecessary, and opening it would defeat the point
	•	no direct LAN or public access to the receiver is created by this
		pack or its eventual implementation — the only path in is
		Cloudflare edge → Tunnel → 127.0.0.1:8083 on the same host
	•	ports 8081 and 8082 are never referenced by any ingress rule this
		pack proposes — §7's schematic config shows exactly one hostname
		rule plus a catch-all, nothing else
	•	a catch-all ingress rule returns an error (e.g. `service:
		http_status:404`) for any request that doesn't match the intake
		hostname — so a cloudflared misconfiguration fails closed, not open
	•	cloudflared's credentials and config file are not committed to
		this Git repository under any circumstance — same "secret lives
		outside the repo" rule already applied to office-panel.env and
		website-intake.env

No final hostname is assumed anywhere in this pack — §7's schematic uses
an explicit placeholder, not a guessed real value, matching §2's stop
conditions.

⸻

6. Installation alternatives — not selected without discovery facts

Three separate either/or decisions, all genuinely open until §4 is run.
They are ordered: 6.1 and 6.2 must both be answered before 6.3 can be
meaningfully decided, since reusing an existing tunnel (6.3) also means
inheriting whatever management model (6.2) that tunnel already has.

6.1 Installing cloudflared vs. using an already-installed one

	•	if §4.1's `command -v cloudflared` / `--version` shows nothing:
		cloudflared would need to be installed via Cloudflare's official
		package (their apt repository) or a downloaded static binary —
		which method is an owner preference (system package manager
		integration vs. a single binary with no package-manager
		dependency), not decided here
	•	if §4.1 shows an existing installation: reuse it as-is; do not
		reinstall or upgrade without a separate reason, since an unplanned
		version change to an already-working binary is its own risk this
		pack does not need to introduce

6.2 Management model — locally-managed vs. remotely-managed. These are two
structurally different ways Cloudflare Tunnels work, and this pack must
not mix their artifacts in one executable path:

	•	locally-managed: the tunnel is created via `cloudflared tunnel
		create <name>` (which itself needs a one-time `cloudflared tunnel
		login`, producing a cert.pem, before it can create or manage
		tunnels on the account from this host), producing a credentials
		JSON file and a tunnel ID; ingress rules live entirely in a local
		config.yml (§7.1's schematic) that cloudflared reads at connector
		startup; §7.1's config.yml/credentials-file shape applies only to
		this model
	•	remotely-managed: the tunnel and its public-hostname ingress rules
		are created and configured entirely in the Cloudflare dashboard
		(Zero Trust → Networks → Tunnels); the connector on the Lenovo is
		started with a single tunnel token — there is no local ingress
		config.yml and no tunnel credentials JSON, but the connector still
		requires a protected local token or token-file (§8.2/§9 cover
		exactly how that one remaining local secret must be handled)
	•	explicit rule: never combine the two — a locally-managed tunnel's
		ingress is defined only in its config.yml, never edited via the
		Dashboard; a remotely-managed tunnel's ingress is defined only in
		the Dashboard, and it has no config.yml to edit at all.  §4.2's
		account-side discovery determines which model any existing tunnel
		already uses

Default decision for a new production deployment: dedicated
remotely-managed tunnel. Cloudflare's own current guidance positions
locally-managed tunnels primarily for legacy setups, local testing, and
special cases where account-side management genuinely doesn't fit —
Dashboard-created, remotely-managed tunnels are the documented default
path for a normal production setup like this one. This pack adopts that as
its own default rather than treating the two models as equally likely
choices.

Locally-managed is not the default and is used only as an exception, and
only when both of the following hold: (a) §4's discovery (§4.1 host-side,
§4.2 account-side) finds an existing locally-managed tunnel already
installed, and (b) a separate, explicit review decides to reuse that
existing tunnel rather than create a new dedicated one. A brand-new
dedicated tunnel created for this route is remotely-managed by default —
choosing locally-managed for a brand-new tunnel would need its own
explicit justification this pack does not anticipate needing.

This is an architectural default, not an authorization — it does not
create any tunnel. §12's gate 3 still requires an explicit GO confirming
this default (or a reasoned departure from it, if discovery turns up a
locally-managed tunnel worth reusing) before anything is installed.

6.3 Reusing an existing tunnel vs. creating a dedicated one

	•	if §4's discovery (host-side §4.1 and account-side §4.2) reveals a
		pre-existing Cloudflare Tunnel already configured (for any
		purpose, related or not), its management model (6.2), ingress
		rules, and credentials must be inspected before deciding whether
		to add an ingress rule to it or to create a separate, dedicated
		tunnel just for this route — and reusing it means accepting its
		already-fixed management model (§6.2's locally-managed exception
		applies exactly here, and only here)
	•	if no existing tunnel is found: per §6.2's default, create a
		dedicated remotely-managed tunnel specifically for this receiver
		— smaller blast radius than reusing any existing tunnel, since
		nothing else would share its token, and it follows Cloudflare's
		own recommended production shape rather than introducing a local
		config.yml/credentials JSON this deployment doesn't otherwise need

None of 6.1/6.2/6.3 is executed here — §6.2 fixes the architectural
default; §12's gate 3 still requires its own explicit GO before anything
is installed.

⸻

7. Proposed config shape — schematic only, not executable, requires
confirmed values before it could ever be used

7.1 Locally-managed model only (§6.2) — this config.yml shape does not
apply if remotely-managed is chosen (§7.2 covers that case instead):

	tunnel: <confirmed-tunnel-id>
	credentials-file: <confirmed-root-owned-credentials-path>

	ingress:
	  - hostname: <confirmed-intake-hostname>
	    path: ^/intake/website-form$
	    service: http://127.0.0.1:8083
	  - service: http_status:404

Every angle-bracketed value above is unknown per §2 and must come from
either §4's discovery output or an explicit owner decision — none may be
filled in by guessing a plausible-looking value. The `path:` matcher shown
is illustrative only — its exact accepted syntax (regular expression vs.
glob, anchoring behavior) must be verified against cloudflared's own
documentation for the actually-installed version (§4.1) before being
treated as final; a version mismatch between what this pack shows and
what the installed binary actually accepts is exactly the kind of thing
§10's future verification step must catch before relying on it.
Explicitly, this shape contains:

	•	no Office Panel route (no rule references port 8081, anywhere)
	•	no kiosk route (no rule references port 8082, anywhere)
	•	no generic localhost forwarding — the single hostname+path rule
		targets exactly http://127.0.0.1:8083 for the one path shown, not
		the whole hostname (without the path matcher, the same hostname
		rule would forward every path underneath it, per this revision's
		§5 correction)
	•	no broad wildcard hostname (e.g. no `*.confirmed-domain` catch-all)
		unless that is itself a separate, explicitly approved decision —
		the default shape above uses one specific hostname, not a wildcard

7.2 Remotely-managed model only (§6.2) — no config.yml exists in this
model; the equivalent restriction is entered as Dashboard fields when
adding a "Public Hostname" to the tunnel: a Hostname field (same unknown
value as §7.1's <confirmed-intake-hostname>), a Path field set to
/intake/website-form (the Dashboard's own path-matching field, not
necessarily the same regex syntax as config.yml's — to be confirmed
against the Dashboard's own current UI at decision time, not assumed
identical to §7.1), and a Service field set to http://127.0.0.1:8083. The
same three restrictions listed in §7.1 (no 8081/8082 route, no generic
forwarding, no wildcard hostname) apply equally here — they are properties
of what gets configured, not of which model configures it.

⸻

8. Secret and permission model

Split by management model (§6.2) — the two have different secret
artifacts entirely:

8.1 Locally-managed model

	•	cloudflared's credentials file lives outside this Git repository,
		on the Lenovo's filesystem only — never committed, matching every
		other secret in this deployment chain (office-panel.env,
		website-intake.env)
	•	cloudflared's config file (config.yml/config.yaml) also lives
		outside this repository — §7.1's schematic is documentation, not a
		file this pack creates
	•	both files should be root-owned with the least-readable permissions
		that still let the cloudflared process itself read them — the
		exact ownership/mode depends on which install method (§6.1) is
		chosen and how the cloudflared service itself is later configured
		to run (§9); not finalized here

8.2 Remotely-managed model

	•	there is no credentials JSON and no ingress config.yml on the
		Lenovo at all — the connector still requires a protected local
		token or token-file, and that is the only local secret this model
		introduces
	•	the token must never be placed as a literal command-line argument
		(e.g. `cloudflared service install <literal-token>` or
		`ExecStart=... --token <literal-token>`) and must never live as a
		plain environment variable value directly in a unit file — the
		same secret-in-argv exposure already corrected for
		WEBSITE_INTAKE_TOKEN in this project's own history (visible via
		`ps` during process start, and potentially in shell history if
		typed manually)
	•	preferred mechanism, if the installed cloudflared version supports
		it (§4.1's `cloudflared --version` check, cross-referenced against
		Cloudflare's own documentation at decision time — this pack does
		not assume a specific version is installed): a root-owned,
		chmod-600 token file, referenced via cloudflared's own
		`--token-file <path>` flag (or the equivalent `TUNNEL_TOKEN_FILE`
		environment variable pointing at that same file) — the token
		never appears in argv and never appears as an environment
		variable's own value, only as the contents of a file cloudflared
		reads directly; this also makes rotating the token a matter of
		rewriting that one file, independent of the unit definition
	•	fallback, only if the installed cloudflared version does not
		support `--token-file`/`TUNNEL_TOKEN_FILE`, and only after that
		gap is confirmed (not assumed) and a separate review accepts the
		fallback: the token goes into its own chmod-600 env file, read by
		the unit via EnvironmentFile=, matching the pattern already
		established for every other secret in this deployment
		(WEBSITE_INTAKE_TOKEN, OFFICE_PANEL_PASSWORD) — still never a
		literal ExecStart= argument
	•	whatever official install command Cloudflare provides for token-
		based connector setup must be checked, at decision time, for
		whether it already writes the token into a `--token-file`-style
		location safely on its own before assuming a manual wrapper
		(token-file or, as fallback, env-file) is even necessary — not
		assumed either way here

8.3 Applies to both models

	•	the Worker's Bearer token (the shared secret already named
		WEBSITE_INTAKE_TOKEN on the receiver side, UPSTREAM_TOKEN on the
		Worker side — WEBSITE_INTAKE_RECEIVER_DEPLOYMENT_PACK_V1 §6)
		remains stored only in /etc/catering/website-intake.env on the
		Lenovo (already true today) and, later, in Cloudflare's own Worker
		secret storage (via `wrangler secret put UPSTREAM_TOKEN`) — this
		pack introduces no new location for that token
	•	the token must never be placed in cloudflared's ingress config —
		cloudflared's only job in this architecture is transporting HTTP
		bytes from Cloudflare's edge to 127.0.0.1:8083; it performs no
		application-level authentication of its own
	•	Bearer authentication continues to happen exactly where it already
		does today: inside website_intake_endpoint.py, checking the
		Authorization header on every request — unchanged by this pack,
		unchanged by cloudflared's presence

⸻

9. Proposed systemd integration — described, not created

A future cloudflared service (either the official `cloudflared service
install` command's own generated unit, or a hand-written one matching this
repo's existing three-unit shape) would need the following confirmed
before it is written — none created by this pack. Which of the two
sub-lists below applies depends entirely on §6.2's management-model
decision; a unit must not reference both a config file and a bare tunnel
token:

	•	locally-managed (§7.1): confirmed config file path and confirmed
		credentials file path (from §4's discovery, or wherever the chosen
		install method places them by default) — both are file paths
		referenced by the unit, not secrets themselves
	•	remotely-managed (§7.2): no config file path, no credentials file
		path — instead (§8.2), preferably a confirmed root-owned
		token-file path referenced via `--token-file`/TUNNEL_TOKEN_FILE,
		or (only as a version-gated fallback) a confirmed env-file path
		referenced via EnvironmentFile=; never a literal ExecStart=
		argument either way

Common to both models:

	•	actual service user cloudflared would run as (may differ from
		viktor, depending on install method — official packages often
		create their own dedicated system user; this must be checked, not
		assumed to match the receiver's own User=viktor)
	•	restart policy (Restart=on-failure, matching every other unit in
		this repo, is the expected default — to be confirmed against
		whatever the official installer generates, not silently
		overridden)
	•	restart-rate limiting (StartLimitIntervalSec/StartLimitBurst,
		matching the guard already added to catering-website-intake.
		service) — to be added explicitly if the official unit doesn't
		already include an equivalent, so a persistent misconfiguration
		fails closed and visibly rather than retrying forever
	•	dependency ordering: cloudflared should start After= network.target
		at minimum, and arguably After= catering-website-intake.service
		specifically, since forwarding to a receiver that isn't listening
		yet is pointless — worth deciding explicitly rather than leaving
		implicit
	•	journal privacy: cloudflared's own logs must be checked (once
		installed) for whether they ever echo request bodies, headers, or
		the Authorization value in transit — this pack assumes nothing
		about cloudflared's own logging behavior until that is verified
		against real output, the same "evidence, not assumption" standard
		LENOVO_WEBSITE_INTAKE_SYSTEMD_IMPLEMENTATION_PACK_V1.md §4.12
		already applied to the receiver's own journal
	•	no secrets in ExecStart= — the credentials-file path may appear as
		a command-line flag or config-file reference (paths are not
		secrets), but the token itself must never appear as a literal
		argument, matching the same discipline already applied to
		WEBSITE_INTAKE_TOKEN throughout this project

catering-website-intake.service itself (infra/systemd/catering-website-
intake.service) is not modified by this pack or by anything it describes
— cloudflared is a separate, additional process, not a change to the
receiver's own unit.

⸻

10. Verification plan (future execution must prove all of this — items
1-4 apply once the Tunnel is running, per §12's gate 5; items 4a/4b and
5-8 apply only once a DNS/public-hostname route exists, per §12's gate 7)

	1.	the receiver still listens only on 127.0.0.1:8083 — unchanged by
		cloudflared's presence (re-run the same bind-address check already
		used for the receiver's own install)
	2.	ports 8081 and 8082 are not exposed through the Tunnel — confirmed
		by inspecting the actual deployed ingress config (config.yml for
		locally-managed, or the Dashboard's Public Hostname list for
		remotely-managed), not just by trusting §7's schematic intent
	3.	the cloudflared service is active (systemctl status)
	4.	the ingress config validates (cloudflared's own `tunnel ingress
		validate` or equivalent, if available for the chosen install
		method and management model)
	4a.	path-matcher behavior, verified once the hostname is reachable
		(this specific check needs the DNS/public-hostname route from
		§12's gate 7 — it cannot be proven purely locally, and is
		distinct from this list's own item numbering). The confirmed
		hostname's /intake/website-form path reaches the receiver in
		both models. What "unmatched" means differs by management model
		(§6.2) and must not be asserted as identical in advance:
			•	locally-managed: the config.yml's catch-all rule
				(§7.1's `service: http_status:404`) means /, /anfragen,
				and an arbitrary unmatched path must return exactly that
				configured http_status:404 — Cloudflare requires a
				catch-all ingress rule and this is its documented
				behavior, so a literal 404 is the correct expectation
				here
			•	remotely-managed: a Dashboard Published Application's
				behavior for an unmatched path on the same hostname is
				not something this pack can assert in advance as
				necessarily a 404 — what matters and must actually be
				checked is (a) the request never reaches
				127.0.0.1:8083 — confirmed by the receiver's own journal
				showing no corresponding entry — and (b) Cloudflare's
				edge returns some non-success response to the caller;
				the actual status code and body returned must be
				recorded as observed during this verification step, not
				assumed to be 404 ahead of time
	4b.	confirm 8081 and 8082 remain unreachable through the Tunnel under
		every path tried in 4a and under the confirmed hostname directly
		on those ports — not just absent from the ingress config on paper
	5.	the confirmed target hostname actually reaches the receiver
		end-to-end (a request to the public hostname arrives at
		127.0.0.1:8083) — only meaningful once §12's gate 7 (DNS/public-
		hostname route) has actually run; not claimed to be provable
		before that route exists
	6.	no token → 401 (through the Tunnel, not just locally — proves the
		full path enforces auth, not only the receiver in isolation)
	7.	wrong token → 401 (same, through the Tunnel)
	8.	correct token → 202 (same, through the Tunnel)
	9.	duplicate submission_id (sent through the Tunnel) returns the same
		inquiry_id — re-proving 2ed5510's idempotency behavior end-to-end,
		not just against the loopback interface directly
	10.	exactly one Inquiry is created for that duplicate pair — same SQL
		baseline/post-check discipline already used for every prior
		live-test in this chain
	11.	Order and OrderVersion counts do not change — same structural
		guarantee already re-verified at every prior step, checked again
		here rather than assumed to still hold
	12.	the response does not echo submitted contact/message data — same
		leak check already performed locally, re-run against the Tunnel
		path
	13.	logs (both the receiver's journal and cloudflared's own logs) 
		contain no token or payload content
	14.	stopping cloudflared removes external reachability while the
		local receiver remains active and answering on 127.0.0.1:8083 —
		proving the Tunnel is additive, not load-bearing for the
		receiver's own correctness

None of these 14 checks are executed by this pack — they define what a
future, separately-authorized verification step must prove.

⸻

11. Rollback

Separated by what each action actually undoes, matching this project's
established host-vs-git rollback split:

	•	stop/disable cloudflared: `systemctl stop`/`disable` the cloudflared
		service — the receiver keeps running unaffected (§10.14 is exactly
		this scenario, proven in advance as an expected, safe state)
	•	remove only the Tunnel ingress rule or DNS route created by this
		specific step — not any other ingress rule that may exist on a
		reused tunnel (§6.2), if that path was chosen; a dedicated tunnel
		(the other §6.2 option) can instead be deleted entirely without
		that concern
	•	preserve catering-website-intake.service and the Core DB — neither
		is touched by any cloudflared rollback action
	•	preserve the Worker unchanged — this pack's rollback never touches
		UPSTREAM_URL/UPSTREAM_TOKEN, since this pack never sets them
	•	preserve any test Inquiry created during §10's verification unless
		a confirmed, owner-approved removal flow exists — same standing
		rule already established in
		LENOVO_WEBSITE_INTAKE_SYSTEMD_IMPLEMENTATION_PACK_V1.md §4.10; not
		re-decided here
	•	Git rollback: only relevant once/if any cloudflared config template
		or documentation is actually committed to this repository in a
		future step — `git revert` or a follow-up commit, its own
		separately authorized action, not bundled with any host-level
		rollback above

⸻

12. Step separation — future gates, none authorized by this pack

	1.	discovery — host-side (§4.1) on the Lenovo and account-side
		(§4.2) in the Cloudflare Dashboard (inspecting what, if anything,
		already exists there)
	2.	review of the discovered facts (§2's open questions get answered
		here, with real values, before anything else proceeds)
	3.	decision gate — management model (§6.2): confirm the default
		(dedicated, remotely-managed) based on gate 1/2's findings, or
		accept a reasoned departure to locally-managed only if discovery
		found an existing locally-managed tunnel worth reusing (§6.3) —
		this decision determines which of §7.1/§7.2, §8.1/§8.2, and §9's
		two sub-lists apply; it must be settled before gate 4, not
		discovered by trial and error during install
	4.	a separate explicit GO for cloudflared install and/or config,
		matching gate 3's chosen model exactly (§6.1's install-vs-reuse
		choice, plus the model-specific artifacts from §7/§8/§9)
	5.	local Tunnel verification — precisely scoped to what can actually
		be checked before any DNS/public-hostname route exists (§10 items
		1-4): the config validates; the connector starts and the
		cloudflared service is active; the Tunnel shows as connected in
		the Cloudflare Dashboard (an account-side check, same as gate 1's
		§4.2); the local receiver remains directly reachable on
		127.0.0.1:8083 throughout; and, if the installed cloudflared
		version supports it, a local ingress-rule-matching command (e.g.
		`cloudflared tunnel ingress rule`) is used to confirm the path
		matcher would route correctly — this gate does NOT claim the
		public hostname is reachable yet, since Cloudflare requires a
		published Public Hostname/DNS mapping to exist before that is
		true at all (gate 7 creates it)
	6.	decision gate — public hostname security model, decided before
		any DNS/public-hostname route is created: option A is the public
		hostname protected only by the receiver's own existing Bearer
		token (WEBSITE_INTAKE_TOKEN/UPSTREAM_TOKEN, unchanged); option B
		adds Cloudflare Access Service Auth (service tokens) as a second,
		independent layer in front of the hostname, requiring the Worker
		to send an additional pair of Access service-token headers
		alongside its existing Bearer token. This pack does not choose
		between them and does not implement option B — if the owner wants
		option B, it becomes its own separate pack with its own Worker
		secrets (a new Cloudflare Access application, new service-token
		credentials, and a worker.js change to send the extra headers),
		not folded into this Tunnel implementation
	7.	a separate explicit GO for the hostname/DNS route (making the
		Tunnel actually reachable from the public internet for the first
		time — this is the gate that makes §10 items 4a/4b/5 meaningful),
		performed only after gate 6's security model is already decided
	8.	a separate explicit GO for the Worker's UPSTREAM_URL and
		UPSTREAM_TOKEN (pointing the already-deployed Worker at the new
		Tunnel-exposed hostname+path, and matching its token to
		WEBSITE_INTAKE_TOKEN; if gate 6 chose option B, also wiring the
		Access service-token headers here — but that pairing is that
		future pack's own concern, not designed in this document)
	9.	a separate explicit GO for the Worker deploy itself (`wrangler
		deploy`, only if worker.js's own committed-but-undeployed changes,
		or the env vars above, need pushing)
	10.	final end-to-end production smoke test (§10's full checklist,
		run for real against the live public path)

No gate beyond gate 1 (discovery) is authorized by this pack. Each
subsequent gate needs its own explicit GO, its own diff/output review, and
(where code or config is committed) its own accept-then-commit cycle —
matching every prior pack in this chain.

⸻

13. Exit

Complete when this document is reviewed and frozen as accepted planning
design, with zero Lenovo operations, zero Cloudflare operations, and zero
code or config changes anywhere in this repo. Gate 1 (§12) — read-only
discovery — is the only action this pack's eventual acceptance could ever
authorize next, and even that needs its own explicit GO, separate from
accepting this document.
