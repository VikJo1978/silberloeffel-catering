WEBSITE_FORM_INTAKE_TO_INQUIRY_PACK_V1

0. Purpose

Design/implementation-only pack. Answers the open question left by
INQUIRY_INTAKE_CONTEXT_FIELDS_PACK_V1 §7 and PUBLIC_SITE_EXECUTION_PACK_V1
§7's phased plan: how a future custom Website-Anfrageformular becomes an
Inquiry, using the intake context fields shipped in a98065c/5d5e007. No code
changes in this pack. Every claim below was checked against current code and
accepted packs on 2026-07-10 (domain/inquiry.py, services/inquiry_service.py,
intake/*.py, tests/unit/test_intake_adapters.py,
PUBLIC_SITE_EXECUTION_PACK_V1.md, SLICE_A_EXECUTION_PACK_V1.md §8-9,
INQUIRY_INTAKE_CONTEXT_FIELDS_PACK_V1.md,
INQUIRY_INTAKE_CONTEXT_FIELDS_IMPLEMENTATION_PACK_V1.md) — including two
reconciliation findings against PUBLIC_SITE_EXECUTION_PACK_V1, flagged
explicitly in §1.

⸻

1. Current state — evidence base, including two reconciliation findings

1.1 Inquiry model today (domain/inquiry.py): inquiry_id, event_date,
created_at, updated_at, inquiry_source, crm_stage, customer_linkage
(IDs-only TypedDict: customer_id/contact_id/placeholder — never raw
name/phone/email), time_window_text (str), location_text (str),
guest_count_estimate (int|None), planning_mode (caterer_suggestion |
self_select — a "who picks items" switch, NOT a catering-style/Anlass
field), call_verification_required/status, and the four intake fields
(intake_subject/message/summary/external_ref, all str|None, added a98065c).
No name/phone/email/company field exists or should be invented (task brief's
own instruction, confirmed correct against the model).

1.2 The intake/ package (manual_adapter.py, email_adapter.py,
phone_adapter.py, wix_form_adapter.py) is pure scaffolding today — decisive
finding: grep for each adapter's function name across src/ finds call sites
only inside itself and its own test file. None are wired to any live
entrypoint. office_panel.py's own create_inquiry() calls
InquiryService.create_inquiry(...) directly, bypassing manual_adapter.py's
intake_from_manual entirely. There is no main.py/app.py wiring any of them
to a running process. This matters for §5: adding a fifth adapter function
of the same shape is the lowest-risk possible step — it changes the risk
profile of nothing currently running.

1.3 wix_form_adapter.py's actual shape (the precedent this pack follows):
a plain function intake_from_wix_form(service, raw: Mapping) -> Inquiry.
Calls external_secure_intake_layer.normalize_public_wix_inquiry_payload()
first (currently just .strip()s two text fields — a thin, wix-specific
pass), then does its own defensive type/presence checks (event_date is a
date instance, text fields are str, guest_count is int-or-absent), then
calls service.create_inquiry(inquiry_source="wix_form", ...). No HTTP code
anywhere in this file.

1.4 External Secure Intake Layer is a frozen architectural role
(SLICE_A_EXECUTION_PACK_V1 §8.1-8.3): "For MVP, this role may be implemented
via Cloudflare Worker." Required: receive external input, validate/
sanitize/normalize, protect secrets from browser exposure, pass into
controlled office-facing flow. Forbidden: become operational truth, bypass
controlled inquiry flow, expose secrets. PUBLIC_SITE_EXECUTION_PACK_V1
(frozen 1bb385e, before a98065c) builds directly on this: the future site is
static (§2.1 — no backend, no sessions, no database, stores nothing), POSTs
once to the Worker (§2.2 — "the worker endpoint is the permanent public
intake address"), and anti-spam (rate limit/Turnstile) is explicitly the
Worker's job, scheduled for when the site goes live. office_panel.py itself
carries an even harder rule (DEPLOYMENT.md): "LAN-only: never expose port
8081 outside the office/kitchen network — no port forwarding, no reverse
proxy to the internet." Between these two frozen documents, a public POST
landing directly on Core's HTTP surface is already forbidden, not merely
undesirable.

1.5 Reconciliation finding A — inquiry_source naming conflict.
PUBLIC_SITE_EXECUTION_PACK_V1 §2.3 (frozen 1bb385e) named the future site's
source value "website". a98065c (2026-07-10, after 1bb385e) implemented
"website_form" instead, in domain/inquiry.py's Literal, InquiryService.
_ALLOWED_SOURCES, and office_panel.py's _OFFICE_SOURCES dropdown — already
shipped, already covered by 284 passing tests. This pack recommends keeping
"website_form" (breaking already-shipped, tested code to match a
planning-only pack's earlier wording would be pure churn) and treats
PUBLIC_SITE §2.3's "website" spelling as superseded. This needs the owner's
explicit acknowledgment (§11) — it is a naming reconciliation, not a
reopening of PUBLIC_SITE's actual architecture decisions (§1.4 stands).

1.6 Reconciliation finding B — notes_text vs intake_message/subject/summary.
PUBLIC_SITE §2.4 scheduled notes_text (from SLICE_A §7's original field
list, never implemented) as a future additive field, to carry the site
form's free text plus an event-type prefix. It was never built under that
name. The four intake_* fields (a98065c) now do a broader version of the
same job — freeform, office-facing, explicitly not-truth. This pack treats
intake_subject/intake_message as already fulfilling what notes_text was
meant to provide; notes_text itself does not need separate implementation.
PUBLIC_SITE §2.5 additionally deferred contact fields (name/phone/email) to
an unspecified "office-side (HubSpot/office capture)" path, outside Core —
at the time nothing existed that could honestly hold free text on Inquiry.
That gap is now closed: §4 below stores them in intake_message, which is
explicitly documented (INQUIRY_INTAKE_CONTEXT_FIELDS_PACK_V1 §5) as
never-truth, human-reviewed prose — a narrower, more honest fulfillment of
§2.5's actual constraint ("do not become [structured] Core Inquiry fields")
than the vague path §2.5 left open. HubSpot itself is confirmed one-directional
(Core → HubSpot, "CRM is visibility, not truth" — PUBLIC_SITE §5.2); it is
not, and was never, a second capture path for contact info.

⸻

2. Product decision: website form creates Inquiry directly — validated, with the actual safety boundary named

The task's hypothesis is accepted: a website form submission may create an
Inquiry directly, with no separate pre-inquiry/review-inbox concept. Two
independent reasons, both evidence-based rather than assumed:

	•	Inquiry already is the cheap, disposable, pre-operational review
		object (INQUIRY_INTAKE_CONTEXT_FIELDS_PACK_V1 §2: "Inquiry is the
		domain's designated entry object... the cheapest Core object to
		create and the cheapest to abandon"). A separate staging/review-inbox
		concept would duplicate Inquiry's own job — exactly the kind of
		redundant-vocabulary problem this project has twice already avoided
		on purpose (intake_source vs. widened inquiry_source, §4 of
		INQUIRY_INTAKE_CONTEXT_FIELDS_PACK_V1)
	•	the real safety boundary was already fixed, before this pack, by
		SLICE_A §8 and PUBLIC_SITE §2.1-2.2 (§1.4 above): the Worker is the
		mandatory gate — sanitization, secret protection, and (once the site
		is live) anti-spam/rate-limiting all happen there, before anything
		reaches a Core-side adapter. "Direct" Inquiry creation is safe
		specifically because the untrusted-input problem is already solved
		one layer up, by already-accepted, already-frozen design — this pack
		does not re-solve it and must not weaken it

The safety boundary in one sentence: public traffic never reaches Core
directly (§1.4); by the time any adapter function like the one this pack
specifies runs, the input has already passed through the frozen Worker
boundary — this pack's own defensive validation (§6) is a second layer,
never the first.

⸻

3. Boundary (restated for this channel specifically)

Even though website form submissions may create an Inquiry directly:

	•	it creates only an Inquiry — never an Order, never an OrderVersion
	•	inquiry_source = "website_form" (§1.5) — never invented, never reused
		from another channel
	•	everything free-text goes into intake context fields only — never
		into customer_linkage (IDs-only, per §1.1), never into a new
		structured field
	•	no wirksam/effective change, no READY_TO_SEND change — this channel
		touches nothing beyond InquiryService.create_inquiry, exactly like
		manual/email/phone/wix_form today
	•	no kitchen/kiosk/release effect — a fresh Inquiry is invisible to
		both by construction (07083cc §1's evidence: neither reads Inquiry)
	•	no automatic conversion to Order — the existing, unchanged, manual
		"In Auftrag umwandeln" office action remains the only path, subject
		to the same B5 call-verification gate as every other Inquiry
	•	no customer master-data rewrite — customer_linkage stays exactly as
		narrow as it is today
	•	no CRM bridge in either direction — HubSpot sync (if/when live) stays
		Core → HubSpot only, per §1.6's evidence
	•	no AI decision of any kind — this pack is about a form submission,
		not an assistant; AI Telefonist stays out of scope per
		INQUIRY_INTAKE_CONTEXT_FIELDS_PACK_V1 §6/PUBLIC_SITE §5
	•	no prices anywhere — a public inquiry form has no pricing concept to
		begin with; nothing here introduces one

⸻

4. Field mapping — checked field-by-field against the actual model, not assumed

Website form field → Inquiry field, with the honest-fit reasoning:

	event_date            → event_date            (real field; required, as today)
	guest_count_estimate  → guest_count_estimate   (real field; optional, nullable as today)
	delivery/location text (optional) → location_text (real field — honest
	                          fit; do not detour this into intake_message
	                          just because it's new-adjacent, when a real
	                          field already exists for exactly this)
	preferred time window (optional, if the form collects it) → time_window_text
	                          (real field, same reasoning)
	planning_mode          → left at its default (caterer_suggestion) —
	                          NOT derived from "desired catering type."
	                          planning_mode is a who-selects-items switch
	                          (two values only); "desired catering type"
	                          (Buffet/Fingerfood/style) is a different
	                          concept entirely and must not be force-fit
	                          into it — it goes into intake_subject/message
	                          instead (see below)
	inquiry_source (constant) → "website_form"      (§1.5)

	name / company                     ┐
	event_type / Anlass / desired      ├→ intake_subject: one short line,
	catering type                      │  "{company/name}" + " — " +
	                                   │  "{event_type}" when both present,
	                                   ┘  whichever is present alone otherwise

	phone, email, free-form message/   → intake_message: labeled lines,
	wishes                               e.g. "Telefon: 0151…\nE-Mail:
	                                      a@b.de\nWunsch: ...". This is the
	                                      §1.6 resolution — contact details
	                                      live here as reviewed prose, never
	                                      as structured fields

	(none — auto-generated, not        → intake_summary: one adapter-
	 user-submitted)                     generated line, e.g. "Website-
	                                      Anfrage — {guest_count} Personen,
	                                      {event_date}" — a quick-glance
	                                      office aid, same role as the
	                                      configurator's computed item
	                                      summary (not raw user text)

	website submission id (optional)   → intake_external_ref (opaque
	                                      breadcrumb only, per
	                                      INQUIRY_INTAKE_CONTEXT_FIELDS_
	                                      PACK_V1 §5 — never an operational
	                                      identifier)

	consent/privacy marker             → not mapped to Core at all (§8) —
	                                      DSGVO consent recording is a
	                                      site/Worker-side concern (matches
	                                      PUBLIC_SITE §3's own /datenschutz
	                                      scoping); Inquiry is not a
	                                      consent ledger

No structured Order items, no prices, no raw JSON blob anywhere in this
mapping — matches the task's own explicit prohibition and this project's
established pattern from the configurator mapping (5d5e007).

⸻

5. Transport / API decision

Already substantially decided by frozen documents (§1.4) — this section
states the conclusion precisely rather than re-litigating it, and narrows
the one piece those documents left open (the Core-side adapter shape).

Rejected: Option A, a public POST endpoint inside the existing Core/Office
app. Forbidden twice over — DEPLOYMENT.md's LAN-only rule for the only
write-capable server that exists (office_panel.py), and SLICE_A §8.3's
"must not bypass controlled inquiry flow." Adding a public route to
office_panel.py (or any new Core-hosted server) would mean Core itself
becomes the public door, contradicting both frozen rules directly.

Rejected: Option C, website stores/emails only, office manually creates
Inquiry via the existing form. Not rejected as unsafe — rejected as
unnecessary regression from what's already possible: the intake fields and
the manual/email/wix_form adapter precedent already let a controlled
adapter create the Inquiry directly and safely (§2), so falling back to
pure-manual for this specific channel would be strictly less useful without
being any safer, since the real risk (untrusted public input) is already
handled by the Worker regardless of what happens after it.

Adopted: Option B, narrowed to exactly what PUBLIC_SITE_EXECUTION_PACK_V1
§7 already scheduled — "additive inquiry_source 'website' [see §1.5 for the
resolved spelling] + website adapter (twin of wix_form_adapter)." Concretely,
for this pack's V1 scope:

	•	a new src/catering_system/intake/website_form_adapter.py, mirroring
		wix_form_adapter.py's exact shape: intake_from_website_form(service,
		raw: Mapping) -> Inquiry, its own _intake_from_website_form_body
		helper, defensive type/presence checks, then service.create_inquiry
		(inquiry_source="website_form", ...) with the §4 mapping applied
	•	a new normalize_public_website_inquiry_payload() in
		external_secure_intake_layer.py, alongside the existing wix-specific
		one, doing the same class of thin, adapter-specific normalization
		(trim text fields) — not a redesign of that module
	•	no new HTTP route, anywhere, in this repo. Confirmed by §1.2: the
		four existing adapters already have zero live wiring — this pack
		adds a fifth adapter of the identical, already-accepted shape, not a
		new category of component
	•	wiring the Worker to actually invoke this adapter (a secured
		Core-reachable call path that does not exist today, for any
		channel) is explicitly out of scope here — deferred to its own,
		separate, narrowly-scoped future pack, matching PUBLIC_SITE §7's own
		"Later (when site work actually starts)" phasing. Until that step
		exists, a website submission reaching the office happens the same
		way phone/email do today: a human reads it (from wherever the
		Worker delivers it — email, a small admin view — both explicitly
		out of scope, site/Worker-side per PUBLIC_SITE §2.1) and creates the
		Inquiry, either by hand through the existing Office Panel form, or
		by whoever operates the eventual wiring calling
		intake_from_website_form directly, in-process — the function itself
		does not care which

⸻

6. Validation rules

Following wix_form_adapter.py's existing defensive-check pattern, plus new,
explicitly-flagged rules for this specifically public-facing channel (same
"NEW rule introduced by this pack" convention PUBLIC_SITE §2.5 already used):

	•	event_date: required; must parse as a real date. Missing/invalid →
		ValueError, same as wix_form_adapter today
	•	guest_count_estimate: optional (nullable, as today); if present must
		be a positive int. NEW: capped to a sane range, 1-2000 — public
		input gets a bound office-typed input never needed, since nothing
		stopped an office worker from typing an absurd number on purpose,
		but nothing should let a bot submit one by accident either
	•	location_text / time_window_text: optional str, trimmed (existing
		normalize-helper pattern); NEW: soft length cap ~500 chars each,
		truncated with a trailing "… (gekürzt)" marker rather than rejected
		— consistent with intake_message's own truncate-not-reject choice
		below, for the same reason (a legitimate long answer shouldn't be
		thrown away wholesale)
	•	intake_subject: NEW cap ~200 chars, truncated with marker
	•	intake_message: NEW cap ~5000 chars, truncated with marker — generous
		enough for a real message, bounded enough that no single submission
		can produce an unreasonably large row
	•	intake_summary: adapter-generated, not user-controlled — no cap
		needed structurally, but its own template stays a single short line
		by construction
	•	intake_external_ref: optional; NEW cap ~200 chars (an opaque ID has
		no legitimate reason to be longer)
	•	no file uploads: any non-scalar (list/dict/binary) value in a field
		this adapter expects to be a string is rejected with TypeError,
		mirroring wix_form_adapter's existing type-check pattern exactly —
		not silently coerced, not silently dropped
	•	no arbitrary JSON payload stored anywhere: unlike the configurator's
		prepare-step hidden field (5d5e007), which round-trips an
		office-authenticated, already-validated payload for one request
		cycle and persists nothing, this adapter must never serialize its
		raw input into intake_external_ref or any other field — only the
		specific, individually-validated values from §4 ever reach Inquiry

⸻

7. Security / spam notes

	•	spam risk: the Worker's job (§1.4/§5), not this pack's — rate
		limiting and/or Turnstile, scheduled in PUBLIC_SITE §7 for when the
		site goes live. This pack's adapter-level validation (§6) is
		defense-in-depth, not the primary control, exactly mirroring how
		wix_form_adapter.py already re-checks types even though
		normalize_public_wix_inquiry_payload ran first
	•	captcha: explicitly the Worker's concern per PUBLIC_SITE §2.2; not
		designed here, not required here — this pack would still be
		internally consistent even if Turnstile ships later than the
		adapter, since the adapter itself never has a public network path
		in V1 (§5)
	•	validation of event_date/guest_count: §6
	•	max length for message: §6
	•	no arbitrary JSON payload stored: §6
	•	no file uploads in V1: §6 — the form itself should also not offer a
		file input (site-side scope, PUBLIC_SITE §4 already says "no file
		uploads... in V1")
	•	no public access to Office Panel: unaffected by this pack — nothing
		here touches office_panel.py, port 8081 stays LAN-only (§1.4)
	•	internal-only Core endpoint: moot for this pack's V1 scope — no
		endpoint of any visibility is added (§5); when a real wiring step
		is eventually designed, it must be internal-only/authenticated, not
		public, consistent with §1.4's frozen rule

⸻

8. Non-goals

	•	no new HTTP route or server in this repo, public or internal (§5)
	•	no Worker-side implementation or design (Cloudflare-side, out of
		this repo, already scoped by SLICE_A §8 and PUBLIC_SITE §2)
	•	no site frontend content, pages, or hosting decisions (already
		explicitly out of scope per PUBLIC_SITE §0)
	•	no automatic Order/OrderVersion creation, ever, from this channel
	•	no customer/contact master-data model — customer_linkage stays
		IDs-only
	•	no consent/DSGVO record inside Core (§4's mapping table)
	•	no rewrite of notes_text as a separate field — superseded per §1.6
	•	no renaming of the already-shipped "website_form" source value to
		match PUBLIC_SITE §2.3's older "website" spelling (§1.5) — that
		would be a breaking migration for no functional gain
	•	no captcha/rate-limit implementation (Worker's job, §7)
	•	no wiring of a real network path from the Worker into this adapter —
		separate future pack (§5)

⸻

9. Tests for future implementation

Following tests/unit/test_intake_adapters.py's existing pattern exactly
(spy on InquiryService.create_inquiry, assert on the returned Inquiry):

	•	a valid website form payload creates exactly one Inquiry via
		intake_from_website_form
	•	the created Inquiry has inquiry_source == "website_form"
	•	event_date and guest_count_estimate are stored correctly from the
		payload
	•	location_text/time_window_text are stored when provided, "" when
		absent — same convention as the other adapters
	•	intake_subject correctly combines company/name and event_type per
		§4's rule (both present, only one present, neither present → None)
	•	intake_message contains phone/email/message as labeled lines
	•	intake_summary is the adapter-generated one-liner, not raw user text
	•	intake_external_ref is set when a submission id is present, None
		otherwise
	•	no Order is created (InMemoryOrderRepository stays empty)
	•	no OrderVersion is created
	•	no READY_TO_SEND evaluation is triggered (no code path in the
		adapter touches operational_core_service at all — a structural,
		import-based assertion is sufficient, matching a98065c's own
		"kiosk/Wochenübersicht unchanged" proof style)
	•	invalid event_date (missing or unparseable) raises, mirroring
		wix_form_adapter's existing test shape exactly
	•	invalid guest_count_estimate (negative, zero, non-int, or > 2000 per
		§6) raises
	•	an intake_message longer than the §6 cap is truncated, not rejected,
		and carries the truncation marker
	•	a payload missing all contact info (no phone, no email, no message)
		is still accepted — the task's brief lists these as things to
		collect, not as domain-enforced requirements; Inquiry itself has no
		concept of "required contact info," so any such requirement would
		be site/form-side UX, not an adapter-level rejection (flagged as an
		open question in §11, not decided here)
	•	a non-scalar value (list/dict) in any string-typed field raises
		TypeError, matching wix_form_adapter's own defensive pattern
	•	no raw JSON payload ends up in intake_external_ref or any other
		field — a direct assertion that the field's value is never equal to
		(or a superset containing) the full input mapping
	•	all four existing intake adapter test files (manual/email/phone/
		wix_form) continue to pass unmodified — this pack adds a fifth
		module, touches none of the existing four

⸻

10. Acceptance criteria for the future implementation step

	•	website_form_adapter.py exists, mirrors wix_form_adapter.py's shape,
		zero HTTP code
	•	inquiry_source "website_form" — already valid today (a98065c), no
		domain/service change needed for the source value itself
	•	full existing suite (284 tests as of 5d5e007) stays green; new tests
		follow §9
	•	no new route in office_panel.py, kiosk_server.py, or anywhere else
	•	no Order/OrderVersion/READY_TO_SEND/wirksam code path reachable from
		the new adapter
	•	no file upload handling anywhere
	•	no raw payload persistence anywhere

⸻

11. Open gaps — not decided here, flagged for the owner

	•	naming reconciliation (§1.5): explicit owner acknowledgment that
		"website_form" (shipped) supersedes PUBLIC_SITE §2.3's "website"
		wording — low-stakes, but should be a recorded decision, not a
		silent drift
	•	whether missing contact info (no phone, no email, no message) should
		ever block Inquiry creation at the adapter level, vs. staying a
		site-side form-UX concern only (§9's last-but-one test documents
		the current recommendation: don't block at the adapter)
	•	the actual Worker → Core wiring mechanism (§5's deferred piece) —
		needs its own pack once the site is actually being built, per
		PUBLIC_SITE §7's phasing; this pack deliberately does not guess at
		it
	•	whether a real "website_form_adapter" implementation step happens
		before or independently of the actual public site going live (the
		adapter can exist and be tested — like the other four — long before
		any live traffic reaches it)

⸻

12. Exit

Complete when this document is reviewed and frozen as accepted design, with
zero code changes in this repo. Implementation (the adapter file, the
normalize helper, and §9's tests) is a separate future step, needing its own
GO and diff review, per this project's standing discipline. The Worker-side
implementation and the actual network wiring into Core remain out of scope
for that step too, per §5/§11, unless separately opened.
