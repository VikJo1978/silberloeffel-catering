WORKER_TO_CORE_WEBSITE_INTAKE_PACK_V1

0. Purpose

Design/implementation-only pack. Closes the gap WEBSITE_FORM_INTAKE_TO_
INQUIRY_PACK_V1 §5/§11 deliberately left open: how a submission that already
passed the Worker boundary actually reaches website_form_adapter (1baeae3),
without Core or Office Panel ever becoming a public surface. No code changes
in this pack. Every claim below was checked against current code and
deployment artifacts on 2026-07-10 (src/catering_system/intake/
website_form_adapter.py, external_secure_intake_layer.py, the other three
adapters, tests/unit/test_intake_adapters.py, DEPLOYMENT.md,
infra/systemd/*.service, infra/cloudflare_worker/worker.js,
PUBLIC_SITE_EXECUTION_PACK_V1.md, SLICE_A_EXECUTION_PACK_V1.md §8-9) —
including one decisive finding that fixes the transport decision structurally,
not just by preference (§1.3), and one field-contract gap in the already-
deployed Worker (§1.4).

⸻

1. Current state — evidence base

1.1 website_form_adapter.py (1baeae3) is a pure in-process function,
intake_from_website_form(service, raw) -> Inquiry, mirroring the other three
live adapters exactly. Zero HTTP code. Confirmed (WEBSITE_FORM_INTAKE_TO_
INQUIRY_PACK_V1 §1.2): none of the four pre-existing adapters
(manual/email/phone/wix_form) has any call site outside its own test file —
this entire package is designed, tested scaffolding, not yet wired to any
running entrypoint.

1.2 Core's only two HTTP servers (office_panel.py, kiosk_server.py) are both
explicitly LAN-only by frozen deployment rule (DEPLOYMENT.md §1a: "LAN-only:
never expose port 8081 outside the office/kitchen network — no port
forwarding, no reverse proxy to the internet"). Neither is a candidate for
receiving public or Worker traffic; this pack does not touch either file.

1.3 Decisive transport finding: infra/cloudflare_worker/worker.js is not a
design sketch — it is a real, deployed component (DEPLOYMENT.md §3 gives its
actual `wrangler deploy` command). Its code (read in full for this pack)
does exactly one outbound call after sanitizing: `fetch(env.UPSTREAM_URL,
{method: "POST", headers: {Authorization: `Bearer ${env.UPSTREAM_TOKEN}`}, 
body: JSON.stringify(clean)})`. A Cloudflare Worker runs at Cloudflare's
edge and can only reach the outside world via outbound HTTP(S) fetch — it
cannot invoke a local CLI, write to a local file, or reach a queue that
isn't itself an HTTP(S) endpoint. This makes the task's Option A (CLI/script
invocation) and Option B (local queue/file) structurally unreachable by the
already-deployed Worker without rebuilding it — not merely less preferred,
but incompatible with a piece of infrastructure this pack must not
re-architect. Option C (an HTTP(S) endpoint, token-authenticated) is the
only option compatible with the Worker exactly as it stands today.

1.4 Field-contract gap in the deployed Worker: worker.js's ALLOWED_FIELDS is
`{event_date, time_window_text, location_text, guest_count_estimate,
planning_mode, customer_linkage}` — the original wix_form/Slice-A §5.3
contract. It does not whitelist any of website_form_adapter's newer fields
(company, name, event_type, phone, email, message, submission_id) or even
inquiry_source/source. Two consequences, both flagged as open gaps (§12),
neither implemented here: (a) the Worker must be updated (its own,
separate, small change) before it can carry a real website-form submission's
full payload — today it would silently strip everything but the six
original fields; (b) the Worker has no way to tag which channel a
submission came from, so a shared receiver cannot dispatch to
intake_from_wix_form vs. intake_from_website_form by payload shape alone
without that also being added.

1.5 infra/systemd/*.service gives the exact, proven shape for any new
always-on Core-side process on the Lenovo: catering-kiosk.service and
catering-office-panel.service both use `Type=simple`, `WorkingDirectory`,
`Environment=PYTHONPATH=...`, `Restart=on-failure`, `RestartSec=3`, and (for
the write-capable one) a chmod-600 `EnvironmentFile` holding the only
secret. This pack's receiver follows the identical shape — no new
operational pattern invented.

1.6 DEPLOYMENT.md §1c confirms the Lenovo already runs 24/7 with a daily
SQLite backup cron — the receiver described here adds a third always-on
process to a host that already runs two.

⸻

2. Boundary (restated for this piece specifically)

	•	Core / Office Panel stays internal/LAN-only — untouched by this pack
	•	no public Office Panel, ever, under any interpretation of this pack
	•	no direct browser-to-Core POST — the Worker remains the only thing a
		browser ever talks to (unchanged from PUBLIC_SITE §2.1-2.2)
	•	the receiver this pack designs may create only an Inquiry, via the
		existing, unmodified website_form_adapter — no Order, no
		OrderVersion, no wirksam/effective, no READY_TO_SEND, no
		kitchen/kiosk/release effect, no CRM bridge, no AI decision
	•	no file upload, anywhere in this chain, in V1
	•	no raw arbitrary JSON stored as Core truth — the receiver forwards
		into the adapter's own field-by-field validation (website_form_
		adapter.py already refuses non-scalar values); it must not persist
		or log the full raw body

⸻

3. Transport decision

Adopted: Option C, an internal-only, token-authenticated HTTP endpoint —
not by preference alone (§1.3 makes this the only structurally compatible
choice with the already-deployed Worker) — refined for what "internal-only"
can honestly mean for a component a Cloudflare Worker must reach by outbound
fetch:

	•	a new, minimal, single-route Python HTTP server —
		src/catering_system/ui/website_intake_endpoint.py — following the
		exact http.server pattern already used by office_panel.py/
		kiosk_server.py (§1.5), not a new framework, not a new pattern
	•	exactly one route: POST /intake/website-form. No other path, no
		other Core capability reachable through it — a dramatically smaller
		surface than Office Panel's, by construction, not by policy alone
	•	authenticated the same way the Worker already authenticates to its
		upstream: a shared bearer token, checked against an
		Authorization: Bearer <token> header — reusing the exact scheme
		worker.js already implements client-side (no new auth design)
	•	on success: calls intake_from_website_form(service, parsed_payload)
		exactly as-is, returns 202 with no body beyond a bare
		acknowledgement (never echoes the created Inquiry's fields back —
		matches worker.js's own "never relay upstream body... to the public
		caller," one layer further in)
	•	on any validation failure (from the adapter) or auth failure: a 4xx,
		logged server-side only (§7) — never more detail than the Worker
		itself already returns to the public caller today (worker.js
		already replies with generic "upstream error" on any upstream
		non-2xx — this pack does not need to add detail on that side)
	•	deployed as a third systemd unit, catering-website-intake.service,
		identical shape to the existing two (§1.5), its own EnvironmentFile
		holding only the shared token, on a new port (8083 — 8081/8082
		already taken)
	•	network reachability (how the Worker's edge actually reaches this
		port without opening it to the whole internet) is explicitly an
		open gap (§12) — a Cloudflare Tunnel (cloudflared) is the
		recommended mechanism, since the Worker already lives on the same
		vendor's edge and a Tunnel would let this endpoint stay closed to
		every other public path while still being fetch()-reachable from
		the Worker; setting up the actual tunnel/DNS is ops work, not
		designed here, matching how PUBLIC_SITE §0 already scoped hosting
		choices out of that pack

Rejected: Option A/B, per §1.3 — would require rebuilding the already-
deployed Worker's fetch-based mechanism for no benefit. Rejected: Option D
(email-only fallback) as the primary V1 mechanism — not because it's unsafe,
but because §1.1-1.3 show a safe, direct mechanism is already reachable with
a small, additive step; Option D remains the correct degraded-mode fallback
when the receiver is down (§8), not the everyday path.

⸻

4. Responsibility split

Website / Worker (unchanged from PUBLIC_SITE §2.2 and worker.js's existing
code, restated for completeness):
	•	public form validation and UX (site-side, out of this repo's scope)
	•	captcha / rate limiting / spam filtering (Worker's job, scheduled per
		PUBLIC_SITE §7 "when the own site goes live" — not yet built into
		worker.js today; this pack does not build it either)
	•	consent/privacy UX (site-side, DSGVO — out of Core's scope entirely,
		per WEBSITE_FORM_INTAKE_TO_INQUIRY_PACK_V1 §4's mapping table)
	•	normalize the public payload, whitelist fields, cap body size —
		already implemented in worker.js, needs the §1.4 field-list update
	•	generate submission_id (a fresh UUID or similar) before forwarding —
		the receiver never invents one; website_form_adapter already
		degrades gracefully to intake_external_ref = None if absent
	•	call the internal intake transport (§3) with a valid bearer token
	•	no Order logic anywhere on this side — was never in scope, isn't now

Core (this pack's new receiver):
	•	re-validate the payload shape independently — never trust that the
		Worker's sanitization was sufficient; this mirrors how wix_form_
		adapter.py already re-checks types even though a normalize step ran
		first (defense-in-depth is the established pattern, not new here)
	•	call website_form_adapter — the only thing this receiver is for
	•	create Inquiry only, through the adapter, unmodified
	•	store intake context via the adapter's existing field mapping — no
		new mapping logic in the receiver itself
	•	reject invalid payloads with the adapter's own ValueError/TypeError,
		translated to a 4xx — no separate validation logic duplicated
	•	log accepted/rejected outcomes (inquiry_id or rejection reason class,
		never the raw payload — §7)
	•	zero public exposure beyond the one token-gated route

⸻

5. Payload contract

The receiver accepts exactly the fields website_form_adapter.py already
supports (1baeae3) — no new fields invented here, no existing ones dropped:

	event_date, guest_count_estimate, location_text, time_window_text,
	company, name, event_type, phone, email, message, submission_id

crm_stage / call_verification_required / call_verification_status stay
accepted-if-present (adapter already supports overriding them) but the
Worker/site has no legitimate reason to ever send them — documented as
adapter-compatibility, not an expected real input.

Required at this layer: event_date only — matching the adapter's own
requirement exactly (ValueError if missing/invalid), nothing stricter added
here.

A note on guest_count_estimate, addressed explicitly rather than silently
decided either way: the task brief listed it as "Required" in the payload
contract framing. website_form_adapter.py (already accepted, tested,
shipped) treats it as optional/nullable, matching Inquiry.
guest_count_estimate's own domain type (int | None). This pack keeps it
optional at the payload-contract level too — making it a hard requirement
here would silently introduce a stricter rule than the adapter it's built on
top of, without its own justification. If the owner wants guest_count_
estimate to be a true hard requirement for the public channel specifically,
that is a small, explicit, separate decision (either a receiver-level check
or a UI-required field on the site form) — not assumed here.

Contact info (phone / email / message): NOT required at this layer, matching
WEBSITE_FORM_INTAKE_TO_INQUIRY_PACK_V1 §9/§11's own explicit, already-
accepted recommendation ("a payload missing all contact info... is still
accepted... any such requirement would be site/form-side UX, not an
adapter-level rejection"). Requiring at least one contact path, if wanted,
belongs on the site form itself (client-side UX, matching how PUBLIC_SITE
§2.5 already makes phone a required field in the form's own design) — not
duplicated as a second enforcement point here. Repeating this rule at every
layer is exactly the kind of duplicated-vocabulary risk this project
consistently avoids elsewhere (inquiry_source vs. a second intake_source
field, §4 of INQUIRY_INTAKE_CONTEXT_FIELDS_PACK_V1).

Optional: company, name, event_type, location_text, time_window_text,
message, submission_id — exactly as the adapter already treats them.

⸻

6. Validation / security

	•	auth: a single shared bearer token (WEBSITE_INTAKE_TOKEN, its own
		env var, its own chmod-600 file — never the same secret as
		OFFICE_PANEL_PASSWORD or the Worker's own UPSTREAM_TOKEN, even
		though it plays an analogous role structurally); a missing or
		wrong token is a 401, logged as an auth failure only (no payload
		details)
	•	rate limiting: the Worker's job (§4) — not duplicated here; if the
		receiver ever needs its own floor (e.g. against a compromised or
		misbehaving Worker token), that is a future, separate hardening
		step, not designed here
	•	captcha: the Worker/site's job (§4), unrelated to this layer
	•	max payload size: the receiver enforces its own cap independently of
		the Worker's 16 KB (defense-in-depth, matching the "never trust the
		previous layer alone" principle already stated in §4) — a generous
		but bounded limit, e.g. 32 KB, comfortably above what even a long
		message (adapter's own 5000-char cap) plus every other field could
		produce
	•	no file upload: the receiver only accepts Content-Type:
		application/json; anything else (multipart, binary) is a 415,
		rejected before any parsing is attempted
	•	no arbitrary JSON persistence: the receiver must never log or store
		the full raw request body — only the adapter's own already-defined
		field values ever reach Inquiry, and logs stay outcome-only (§7)
	•	GDPR/privacy: contact data (phone/email/message) lives only in
		intake_message, exactly as WEBSITE_FORM_INTAKE_TO_INQUIRY_PACK_V1 §4
		already decided — this pack adds no new place contact data could
		land, and does not touch customer_linkage

⸻

7. Duplicate / retry behavior

Not solved structurally in V1 — documented honestly rather than glossed
over. website_form_adapter.py has no idempotency check; InquiryRepository
has no "find by intake_external_ref" query today (adding one would be a
domain/repository change, out of scope for this design-only pack). A Worker
retry (its own fetch() has no built-in retry logic today, per §1.3's code
reading, but a future Worker change or a flaky network path could still
double-send) would create two Inquiries sharing the same intake_
external_ref.

Risk assessed as low-severity for V1: a duplicate is an extra Inquiry, not
an extra Order — the cheapest possible object to have two of, per
INQUIRY_INTAKE_CONTEXT_FIELDS_PACK_V1 §2's own framing. The office already
has to read every new Inquiry by hand; spotting an obvious duplicate (same
event_date, same intake_subject, submitted minutes apart) is well within
that existing review step, the same judgment call an office worker already
makes for e.g. an accidental double phone call today.

Mitigation, deferred to its own future step, not this pack: a repository-
level lookup (list_all() filtered by intake_external_ref, or a dedicated
query method) that the receiver could check before calling create_inquiry,
returning the existing Inquiry instead of creating a second one. Left
undesigned here because it touches the repository layer, which this pack is
explicitly not allowed to change.

⸻

8. Operational failure handling

	•	failed submissions (adapter rejects, receiver is down, network
		fails): nothing is retried automatically anywhere in this chain
		today — the Worker's existing fetch() call either succeeds or the
		Worker replies "upstream error" to the browser (already-existing
		code, §1.3); a failed submission that isn't retried by the visitor
		is lost, with no automatic capture
	•	the Worker returns success to the site only after the receiver
		accepted (i.e. after the Inquiry actually exists) — this is already
		true of worker.js's existing logic (`upstream.ok` gates the
		response), nothing new needed here
	•	the website shows a generic success/failure message either way —
		site-side UX, out of this pack's scope (matches PUBLIC_SITE §4's
		"wir rufen Sie zurück" framing for the honest general case)
	•	no admin retry/manual fallback UI exists or is designed here — if a
		submission is lost, the visitor's only recourse is retrying the
		form or using another channel (phone/email), which already exist
		as separate, working intake paths (manual_adapter.py/
		email_adapter.py/phone_adapter.py, exercised through the Office
		Panel today)
	•	recommended cheap safety net, not designed in detail: an email
		notification as a secondary channel alongside the receiver call —
		mirroring PUBLIC_SITE §5.1's own "Stage 1: assistant only emails a
		call summary" pattern for the phone AI, which this project already
		accepted as a reasonable low-effort safety net elsewhere. Whether
		to build this now or treat occasional lost submissions as an
		acceptable V1 risk is an open decision for the owner (§12), not
		decided here

⸻

9. Non-goals

	•	no code in this pack — domain/services/routes/tests untouched
	•	no change to office_panel.py or kiosk_server.py
	•	no change to worker.js's deployed behavior (the §1.4 field-list gap
		is named, not fixed, here)
	•	no Order/OrderVersion/READY_TO_SEND/wirksam/kitchen/kiosk effect
	•	no CRM bridge, no AI decision
	•	no file upload support
	•	no idempotency/deduplication implementation (§7 — deferred)
	•	no admin UI, no retry queue, no email-fallback implementation (§8 —
		named as a recommendation only)
	•	no Cloudflare Tunnel / DNS / networking setup (§3 — ops work, named
		as the recommended mechanism, not configured here)
	•	no rate limiting or captcha implementation (Worker's job, not built
		here or there in this pack)
	•	no wix_form wiring through this same receiver — explicitly a
		separate, undecided question (§1.4, §12)

⸻

10. Tests for future implementation

Following test_office_panel.py's live-socket HTTP pattern (the closest
existing precedent for a small, single-purpose Python HTTP server in this
repo) plus test_intake_adapters.py's existing adapter-level assertions:

	•	a valid, correctly-authenticated payload creates exactly one Inquiry
	•	the created Inquiry's inquiry_source == "website_form"
	•	intake_subject/message/summary/external_ref are stored exactly as
		website_form_adapter.py's own tests already prove (this pack's
		receiver adds no new mapping logic to re-test independently — an
		integration-level smoke test through the HTTP layer is enough,
		full field-mapping correctness stays website_form_adapter's own
		test file's job)
	•	event_date/guest_count_estimate stored correctly
	•	location_text/time_window_text stored when provided
	•	no Order is created (InMemoryOrderRepository stays empty)
	•	no OrderVersion is created
	•	no READY_TO_SEND evaluation is triggered (structural: the receiver's
		code never imports operational_core_service)
	•	kiosk/Wochenübersicht output is unchanged before/after — same
		byte-identical-comparison technique as a98065c's own boundary tests
	•	an invalid payload (missing event_date, malformed JSON, guest_count
		out of the adapter's 1-2000 range) is rejected with a 4xx, and
		creates no Inquiry
	•	a request with a missing or wrong bearer token is rejected with 401
		and never reaches the adapter at all (a spy/mock on
		intake_from_website_form asserting it was never called is the
		sharpest version of this test)
	•	a non-JSON or oversized body is rejected before parsing
		(Content-Type / size checks, §6)
	•	duplicate submission_id behavior: documented as NOT deduplicated in
		V1 (§7) — the test proves the current, honest behavior (two
		requests with the same submission_id create two Inquiries), not a
		dedup guarantee that doesn't exist; this test exists specifically
		so a future implementer can't accidentally believe dedup already
		works
	•	all existing website_form_adapter.py tests (21, from 1baeae3)
		continue to pass unmodified — this pack's receiver is a thin
		wrapper around that adapter, not a reimplementation

⸻

11. Acceptance criteria for the future implementation step

	•	website_intake_endpoint.py exists, single route, no other Core
		capability reachable through it
	•	auth is required and independently testable (401 without a valid
		token, adapter never called)
	•	full existing suite stays green; new tests follow §10
	•	no change to domain/services/repositories/office_panel.py/
		kiosk_server.py
	•	no Order/OrderVersion/READY_TO_SEND/wirksam code path reachable from
		the new receiver
	•	no file upload handling anywhere
	•	no raw payload persistence anywhere
	•	systemd unit follows the existing two units' exact shape (§1.5)

⸻

12. Open gaps — not decided here, flagged for the owner

	•	network reachability mechanism for the receiver (§3): Cloudflare
		Tunnel (recommended) vs. a narrowly-firewalled public port with
		only the token as protection — an ops decision, not a code one
	•	worker.js's ALLOWED_FIELDS/TEXT_FIELDS update to actually carry
		website_form's fuller payload (§1.4) — a small, separate, future
		change to a file this pack does not touch
	•	whether wix_form should ever be wired through this same receiver
		(shared dispatch by a source field) or keep needing its own
		separate wiring later (§1.4, §9) — undecided, not blocking this
		pack
	•	whether guest_count_estimate should become a hard requirement at
		the public-channel level, contradicting the adapter's own optional
		design (§5) — flagged, not decided
	•	idempotency/deduplication by intake_external_ref (§7) — needs a
		repository-layer change, deferred
	•	whether an email-fallback safety net (§8) is worth building now or
		an acceptable V1 gap — deferred to the owner
	•	the shared bearer token's rotation/storage mechanism beyond "its own
		chmod-600 env file" (§6) — no rotation policy designed here,
		matching that none exists yet for OFFICE_PANEL_PASSWORD or
		UPSTREAM_TOKEN either (not a new gap this pack introduces, an
		existing one it inherits)

⸻

13. Exit

Complete when this document is reviewed and frozen as accepted design, with
zero code changes in this repo. Implementation (website_intake_endpoint.py,
its systemd unit, and §10's tests) is a separate future step, needing its
own GO and diff review. worker.js's field-list update, the Tunnel/networking
setup, and any of §12's other open gaps each need their own explicit
decision — none authorized by this pack on their own.
