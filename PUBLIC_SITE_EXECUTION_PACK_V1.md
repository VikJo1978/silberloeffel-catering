PUBLIC_SITE_EXECUTION_PACK_V1

0. Purpose

Execution pack for replacing Wix with an own public catering website, and for
fixing the intake-channel principles that future channels (incl. a phone AI
assistant) will follow. Evidence rule as in OPERATIONAL_CORE_EXECUTION_PACK_V1
§2: repo evidence + accepted WORKLOG entries win; where this pack introduces a
NEW rule (not derivable from repo evidence), it says so explicitly.

This pack fixes boundaries and contracts. It deliberately contains no visual
design, no content, and no hosting choice.

1. Identity and goal

Public site — presentation + intake frontend only. The site is a static
frontend in front of the existing External Secure Intake Layer (Cloudflare
Worker, Slice A §8). Replacing Wix is a frontend swap, not an integration
project: the worker URL stays the single public door.

2. Architecture decisions fixed by this pack

2.1 The site is static in V1
	•	no site backend, no sessions, no accounts, no database
	•	the site stores no inquiry for any duration — not even "temporarily"
	•	the only system interaction is one POST of the inquiry form to the worker
	•	the site receives only accepted/error — never data from Core or CRM

2.2 Worker URL is a stable contract
	•	the worker endpoint is the permanent public intake address
	•	Wix and the own site may run in parallel during transition — both POST to
		the same worker
	•	anti-spam (rate limit and/or Turnstile) is the worker's responsibility,
		implemented when the own site goes live (Wix-side filtering falls away)

2.3 inquiry_source taxonomy (additive, honest history)
	•	the own site gets a NEW inquiry_source value: "website" — added to the
		frozen Literal as an explicit additive accepted step when site work starts
	•	wix_form is never repurposed or renamed; historical inquiries keep their
		true origin
	•	general principle (applies to all future channels): every new channel gets
		its own additive source value; no reuse, no renaming

2.4 notes_text (additive implementation of an already-accepted optional field)
	•	SLICE_A_EXECUTION_PACK_V1 §7 lists notes_text as an optional inquiry
		field; it was never implemented — domain/inquiry.py has no such field today
	•	this pack schedules its implementation as an additive step (field +
		validators + adapters passthrough + WORKLOG entry), not as a silent edit
	•	V1 form's event type (Business / Privat / Feier) is prefixed into
		notes_text (e.g. "Anlass: Business — ..."); a dedicated event_type field
		would be a separate accepted step if the office later needs it structured

2.5 Phone number — NEW rule introduced by this pack
	•	the public form requires a phone number
	•	this is NOT derived from a frozen contract (Inquiry holds no contact
		fields; B4 takes caller-supplied match flags) — it is an operational rule
		introduced here: call verification for new/suspicious clients requires a
		number the office can call
	•	contact fields (name, phone, email) flow to the office side (HubSpot /
		office capture) for B4 classification; they do not become Core Inquiry
		fields under this pack

3. V1 site structure (fixed slugs; content is out of scope)

	•	/            Startseite — hero + CTA "Anfrage stellen"; services (3 cards);
		"So funktioniert's" in 3 steps (Anfrage → Rückruf/Angebot → Lieferung);
		testimonials; contact block
	•	/leistungen  one page for all service types (split into SEO pages only
		later, when traffic justifies it — own step)
	•	/anfrage     the inquiry form (§4)
	•	/impressum   legally required (DE)
	•	/datenschutz legally required (DSGVO; the form collects personal data)

Deliberately NOT in V1: structured menus/prices, calculators, accounts, blog,
gallery pages, multi-language, online payment, any order-status view.

4. V1 inquiry form contract

Fields mapping 1:1 to the accepted inquiry contract:
	•	event_date (required — the only hard-required domain field)
	•	time_window_text (free text, "z.B. mittags, 12–14 Uhr")
	•	location_text
	•	guest_count_estimate (integer, "ca.")
	•	planning_mode (user-friendly wording for caterer_suggestion / self_select)
	•	notes_text (after its additive implementation per §2.4; carries the
		event-type prefix)

Fields serving office-side B4 classification (never Core fields under this pack):
	•	name
	•	phone (required per §2.5)
	•	email (at least one contact channel required; phone strongly encouraged
		by UI copy)

Submission: one POST (JSON) to the worker; user-facing result is "wir rufen
Sie zurück" — which is the honest description of the real process.
No file uploads, no budget field, no menu selection in V1.

5. Future intake channels (incl. phone AI assistant)

5.1 Decision: Role 1 only, staged
	•	the phone AI assistant is fixed as an INBOUND NOTE-TAKER / INTAKE
		PRODUCER only; it never becomes anything else without its own pack
	•	Stage 1 (decided): the assistant only emails a call summary to the
		office inbox. This is NOT an integration — no Core changes, no CRM
		wiring, no new source value. The office reads the email and captures
		the inquiry through the existing office-controlled channels (Slice A),
		exactly as with any email or live call today
	•	Stage 1 source convention: the office captures such inquiries as
		inquiry_source = "phone" (the client's real channel was a call; the
		email is only the delivery mechanism of the note); "AI-assisted call"
		belongs in the CRM note, not in Core
	•	the assistant's email is an office aid — a conversation summary, NOT a
		trusted operational fact and NOT an "almost-ready inquiry"; the office
		treats it with the same skepticism as any inbound note and verifies
		with the client where needed
	•	the CRM marker stays a free-text note only — it must never evolve into a
		semi-structured format intended for machine parsing (that would be the
		§5.2 hidden-bridge risk in slow motion)
	•	Stage 2 (only if call volume ever makes manual transfer a bottleneck):
		the assistant switches from emailing to emitting the §5.3 payload to a
		secured endpoint; the additive inquiry_source value "phone_ai" is
		introduced at that point — not pre-created as a ghost value
	•	Role 2 (AI performing the verification call) is explicitly forbidden:
		call_verification_status = "verified" means a HUMAN verified the client;
		letting AI set it would silently change frozen trust semantics. If ever
		wanted, it needs its own pack that introduces an explicit human/AI
		distinction — never a reuse of the existing status
	•	Role 3 (AI answering operational questions — "where is my order") is
		out of scope like public status tracking: own pack, much later, if ever

5.2 Channel principles fixed now
	•	new channel → new additive inquiry_source value; no reuse, no renaming
	•	the AI assistant is a note-taker / intake producer only: never a
		verification authority, never order-side, never kitchen-side (consistent
		with Slice A §3.2 which already holds AI out of scope)
	•	no automated bridge may turn assistant output into inquiries behind the
		office's back — neither an email parser ("assistant email → auto-created
		inquiry") nor a CRM→Core sync. Both would be a hidden intake path that
		bypasses the worker's validation and (for CRM) would invert the frozen
		direction "CRM is visibility, not truth". Automation, when wanted, is
		Stage 2 through the §5.3 contract — nothing else
	•	call artifacts (recording, transcript, recording-consent records — the
		latter legally required in DE) live vendor-/office-side like HubSpot
		data; Core receives only the structured inquiry

5.3 Stable intake payload contract (dormant until Stage 2 or other producers)
	•	the worker's sanitized payload shape IS the universal contract for
		"a normalized public inquiry": event_date (ISO), time_window_text,
		location_text, guest_count_estimate (int), planning_mode,
		customer_linkage, plus notes_text after §2.4
	•	any future producer (own site, phone AI Stage 2, anything else)
		integrates by emitting this shape to a secured server-side endpoint —
		one page of spec, not an integration project
	•	changes to this shape are additive-only and require an accepted step

6. Must-fail conditions

This pack's implementation is not accepted if any of the following happens:
	•	the site stores or proxies inquiries anywhere besides the worker POST
	•	the site gains a backend, session state, or any read access to Core/CRM
	•	sanitization at the worker is weakened because "the frontend is ours now"
	•	wix_form is repurposed for the own site
	•	notes_text (or any field) is added to the domain without its own
		explicit additive step and WORKLOG entry
	•	kitchen / READY_TO_SEND / Wochenübersicht / order data gets any public
		representation
	•	an AI channel writes anything other than a normalized inquiry, or touches
		verification status
	•	assistant output is turned into inquiries by any automated bridge (email
		parser, CRM→Core sync) instead of office capture or the §5.3 contract
	•	secrets appear in browser-served content

7. Phased plan

Now (this pack; no code):
	•	accept this document: taxonomy principle, static-site boundary, worker
		URL as stable contract, phone rule, Role-1-only decision, payload contract

Later (when site work actually starts; each an explicit step):
	•	additive inquiry_source "website" + website adapter (twin of
		wix_form_adapter)
	•	additive notes_text implementation per §2.4
	•	anti-spam on the worker
	•	the five pages + form per §3/§4; Wix→site switchover (parallel period OK)

Much later (own packs, only on proven need):
	•	phone AI channel (phone_ai source value + producer integration per §5.3)
	•	SEO page split, gallery, structured menu content (never in Core),
		client-facing status anything, multi-language

8. What must not be mixed
	•	site content with Core (Core is not a CMS)
	•	form fields with operational fields
	•	worker with business logic
	•	AI assistant with trust gates
