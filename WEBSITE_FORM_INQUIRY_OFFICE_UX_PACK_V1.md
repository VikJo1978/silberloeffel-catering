WEBSITE_FORM_INQUIRY_OFFICE_UX_PACK_V1

0. Purpose

Design/implementation-only pack. Specifies how the Office Panel should
present an Inquiry whose inquiry_source is "website_form" (1baeae3), so the
office can tell at a glance that it's a website submission, not yet an
order, and needs review — without changing Core truth, without adding a new
contact/customer model, without touching the receiver, Worker, or any
deployment artifact. No code changes in this pack. Every claim below was
checked against current code on 2026-07-10 (src/catering_system/domain/
inquiry.py, src/catering_system/ui/office_panel.py — render_anfragen,
render_inquiry, render_inquiry_form, update_inquiry, verify-related routing
— src/catering_system/intake/website_form_adapter.py,
tests/unit/test_office_panel.py, WEBSITE_FORM_INTAKE_TO_INQUIRY_PACK_V1.md,
WORKER_TO_CORE_WEBSITE_INTAKE_PACK_V1.md,
WEBSITE_INTAKE_RECEIVER_DEPLOYMENT_PACK_V1.md).

⸻

1. Current state — evidence base

1.1 render_anfragen() (office_panel.py:663, the Inquiry list) has six
columns today: Datum, Ort, CRM-Stufe, Verifizierung, Auftrag, ID. No Kanal/
source column exists. Its search helper _matches() checks only inquiry_id,
location_text, event_date, and crm_stage — inquiry_source and intake_subject
are not searchable either. An office worker cannot currently distinguish a
website_form Inquiry from a manual/phone/email one without opening it.

1.2 render_inquiry() (office_panel.py:826, the detail view) already shows
more than the task brief assumed — checked field by field, not asserted:
	•	Kanal is already a table row, but renders the raw enum value
		("website_form", not a human label) — office_panel.py:877
	•	intake_subject/intake_message/intake_summary/intake_external_ref are
		already shown as conditional table rows, only when non-empty
		(a98065c, office_panel.py:862-874) — labeled "Betreff", "Nachricht",
		"Zusammenfassung", "Externe Referenz"
	•	event_date, guest_count_estimate ("Gäste"), location_text ("Ort"),
		time_window_text ("Zeitfenster") are already shown, source-agnostic
	•	Verifizierung already shows a human label via _verification_label()
		(office_panel.py:115) and CALL_VERIFICATION_STATUS_LABELS
		(office_panel.py:95-101) — "pending" already renders as
		"Rückrufprüfung ausstehend" today, not the raw enum
	•	intake_message is already HTML-escaped via _e() before rendering
		(same as every other field on this page) — no new escaping work
		needed, only confirmed as already correct

1.3 Decisive finding — the "must verify before convert" boundary is
already structurally enforced, not a UX nice-to-have this pack needs to
build: website_form_adapter.py (1baeae3) defaults call_verification_required
= True, call_verification_status = "pending" for every website_form Inquiry
(matching email_adapter.py/phone_adapter.py's own precedent for
indirect/unverified channels). ProgressionService.evaluate_inquiry_to_order_
progression() (called at office_panel.py:830, existing, unchanged) already
blocks conversion while a required verification is unsatisfied — B5, frozen
since Slice A. A fresh website_form Inquiry is therefore already unconvertible
until an office worker clicks the existing "Telefonisch verifiziert" button
(office_panel.py:836-841, → POST /inquiry/{id}/verify →
InquiryService.verify_customer_by_call(), existing, unchanged). This pack's
job is making that state legible at a glance, not building a new gate.

1.4 The update form ("Anfrage bearbeiten", office_panel.py:887-900) has no
call_verification field at all — verification can only change through the
dedicated button. This is deliberate existing behavior (a general field
editor cannot accidentally self-verify) and this pack does not touch it.

1.5 No customer/contact model exists or is proposed anywhere in this chain
— phone/email/message already live only inside intake_message as labeled
text lines (website_form_adapter.py's own §4 mapping, already accepted).
This pack does not introduce one; §5 explicitly keeps them inside the single
existing intake_message block.

⸻

2. UX problem, stated precisely

Given §1's evidence, the actual gap is narrower than "build detail-view
support" (that already exists) — it is:

	•	the list view gives no signal at all that a row is a website
		submission, or that it's stuck waiting on verification
	•	the detail view's existing Kanal/Verifizierung rows are technically
		present but not visually distinct enough to read as "this one needs
		attention" in a quick scan
	•	nothing currently tells the office, in plain language, "this is not
		yet an order" — the progression block message ("Konvertierung
		blockiert") is accurate but generic, written for any blocked
		Inquiry, not specifically reassuring for a fresh, expected-to-be-
		blocked website submission

⸻

3. Boundary (restated for this piece specifically)

	•	Office UX only — no Core truth model change, no domain field added
		or renamed
	•	no automatic Order creation, no automatic OrderVersion creation —
		the existing, unmodified "In Auftrag umwandeln" button (already
		gated by B5, §1.3) remains the only conversion path
	•	no READY_TO_SEND, no wirksam/effective, no kitchen/kiosk/release
		effect — nothing in this pack touches operational_core_service.py,
		kiosk_server.py, or WochenuebersichtService
	•	no public endpoint, no Worker/Tunnel/systemd change — this pack is
		entirely inside office_panel.py's existing rendering surface
	•	no AI decision, no CRM bridge — unrelated to display wording
	•	no new Contact/customer model — phone/email/message stay inside
		intake_message exactly as today (§1.5)

⸻

4. Inquiry list decision

Add one new column, Kanal, between CRM-Stufe and Verifizierung, rendering a
short human label (§8) instead of the raw inquiry_source string — via a new,
small, dedicated label dict, following CALL_VERIFICATION_STATUS_LABELS's own
established pattern exactly (a separate dict per vocabulary, never merged
with the verification-status or progression-blocker dicts — §5 "vocabularies
not merged," already a standing rule in this file's own module docstring).

Add a second new column, Betreff, showing intake_subject truncated to a
short length (e.g. 40 chars with an ellipsis marker) when present, "–"
otherwise — meaningful mainly for configurator/website_form-originated
Inquiries; manual/phone/email rows simply show "–", no regression for them.

Verifizierung's existing column stays, with one visual addition: when
call_verification_required is true and status isn't "verified", wrap the
cell's text in the existing .blocked CSS class (already defined, already
used elsewhere on this page for blocked states) — a plain color cue, no new
CSS, no new concept, just making an already-shown fact easier to scan for.

Search (_matches(), office_panel.py:666-669) gains two more fields to check
against: inquiry_source and intake_subject — a small, in-place addition to
the existing tuple passed into _matches(), not a new search mechanism.

Resulting column order: Datum, Ort, Kanal, Betreff, CRM-Stufe, Verifizierung,
Auftrag, ID. Not adding a column for intake_message/intake_summary/
intake_external_ref — those stay detail-view-only, matching this project's
repeated "not huge UI" instruction from every prior intake-related pack.

⸻

5. Inquiry detail decision

Kanal row: render through the same new label dict as §4, so office_panel.py
:877's `{_e(inq.inquiry_source)}` becomes `{_e(_source_label(inq.
inquiry_source))}` — "Website-Anfrage" instead of "website_form". Every
other channel gets an equally short German label (§8); an unrecognized
future value falls back to the raw string, matching _verification_label's
and _progression_blocker_label's own existing fallback convention
(office_panel.py:115-119) — never a crash, never a silently blank field.

New banner, shown only when inquiry_source == "website_form", placed
directly above the existing summary table (same position/weight as the
proposal-preview's own .proposal-banner, reusing that exact CSS class — no
new style rule needed): "Website-Anfrage — noch kein Auftrag. Nur
Intake-Kontext, keine Küchenfreigabe." (§8's exact wording). This is the
one genuinely new visual element this pack adds to the detail page.

intake_subject/intake_message/intake_summary/intake_external_ref: already
correctly rendered (§1.2) — no change needed beyond their existing
conditional-row behavior. This pack explicitly does not split intake_message
into separate phone/email/message fields — §1.5's boundary holds; the
labeled-lines format (website_form_adapter.py's own output: "Telefon: …
\nE-Mail: …\nWunsch: …") already reads clearly as one block, and inventing
per-line parsing in the UI would be exactly the kind of premature structured-
contact-model creep every prior pack in this chain has deliberately avoided.

Verifizierung row: unchanged rendering, already correct (§1.2) — no new
work, kept here only for completeness of the field-by-field review the task
asked for.

⸻

6. Verification / Rückruf decision

The existing "Telefonisch verifiziert" button/action (§1.3) is reused
as-is, unmodified. Decision, not left open: keep its label universal across
all channels rather than branching it to something website_form-specific
like "Rückruf erledigt". Reasoning: the action's real meaning never changes
— a human confirmed the client by phone — regardless of which channel the
Inquiry originated from; a channel-conditional label would need new
branching logic for a cosmetic difference only, and this project's own
established preference (visible throughout this pack chain) is the smallest
change that says what's actually true. If the owner prefers the
website-specific wording anyway, that is a one-line follow-up, not
re-opening this decision (§12).

No new action is added. "Mark verification status" beyond the existing
verify button is not proposed — the update form deliberately has no
verification field (§1.4), and this pack does not change that; adding one
would let a general edit silently flip trust state, which is exactly what
the current design already avoids on purpose.

Convert button: unchanged, still gated by the existing B5 progression check
(§1.3) — this pack adds no new gate because none is needed; the existing one
already does the job for website_form's default call_verification_required
= True.

⸻

7. Action flow (restated as a flow, not a list)

	1.	office opens /anfragen, now sees Kanal + Betreff columns and a
		visually distinct Verifizierung cell for anything still pending
	2.	office opens a website_form row → detail page shows the new banner,
		the (now human-labeled) Kanal row, and the existing intake context
		rows exactly as before
	3.	office reads intake_message (phone/email/message together) and
		intake_summary, forms a judgment — this is manual review, not
		automated anything
	4.	office either clicks "Telefonisch verifiziert" after a real call, or
		edits fields via the existing "Anfrage bearbeiten" form (event_date,
		location, guest count, intake context — all already editable,
		unchanged)
	5.	once verified, "In Auftrag umwandeln" becomes available — the
		existing, unmodified conversion path, unchanged by this pack
	6.	no step in this flow is automatic; every arrow is an explicit office
		click, exactly as today

⸻

8. German UI wording — exact placement, not a loose list

Kanal label dict (new, small, office_panel.py-local, mirrors
CALL_VERIFICATION_STATUS_LABELS's shape):
	•	"website_form" → "Website-Anfrage"
	•	"configurator" → "Angebots-Import" (matches the sidebar link text
		already used for the proposal-preview flow, 9012c35 — consistent
		naming, not invented fresh)
	•	"manual" → "Manuell erfasst"
	•	"phone_by_office" → "Telefon (Büro)"
	•	"email" → "E-Mail"
	•	"phone" / "wix_form" → their existing raw values stay as fallback
		(legacy/adapter-compatible per prior packs' own decision — not
		office-offered in the create dropdown already, §1.5 of
		INQUIRY_INTAKE_CONTEXT_FIELDS_IMPLEMENTATION_PACK_V1, no new label
		needed for values the office never picks by hand)
	•	"missed_call" / "ai_telefonist" → left unlabeled (fallback to raw
		value) — neither is reachable yet (no adapter writes them), a label
		would be speculative

Detail-page banner (website_form only, §5): "Website-Anfrage — noch kein
Auftrag. Nur Intake-Kontext, keine Küchenfreigabe."

List-page Verifizierung cell, pending+required case: no new string — reuses
the already-existing "Rückrufprüfung ausstehend" (CALL_VERIFICATION_STATUS_
LABELS, unchanged), just wrapped in .blocked for visibility (§4).

Not introduced: "Vom Kunden über Website übermittelt" as a separate string
— redundant with the Kanal label + banner together already saying exactly
that; adding a third phrase for the same fact would be noise, not clarity,
against this project's own "not huge UI" instruction repeated in every
intake-related pack so far.

⸻

9. Tests for future implementation

Following test_office_panel.py's existing live-socket + _create_inquiry
helper pattern:

	•	a website_form Inquiry (created via _create_inquiry with
		inquiry_source="website_form") appears in /anfragen with a Kanal
		cell reading "Website-Anfrage", not the raw string
	•	a manual/email/phone Inquiry's Kanal cell shows its own label,
		proving the dict covers more than one branch, not just website_form
	•	an Inquiry with intake_subject set shows a truncated Betreff cell in
		the list; one without shows "–"
	•	a pending, verification-required Inquiry's Verifizierung cell in the
		list carries the .blocked class (a direct HTML-fragment assertion,
		matching how existing tests already check for class="blocked"
		elsewhere in this file)
	•	the detail page for a website_form Inquiry contains the exact banner
		text from §8
	•	the detail page for a non-website_form Inquiry (e.g. manual) does
		NOT contain that banner — proving it's conditional, not global
	•	the detail page's intake_message renders HTML-escaped (a message
		containing "<script>" or "&" renders as text, not live markup) —
		regression guard confirming §1.2's "already correct" claim stays
		true after this pack's changes land near it
	•	/anfragen's search now matches on inquiry_source ("website_form" as
		a query string finds the row) and on intake_subject content
	•	the existing "Telefonisch verifiziert" button/label is unchanged for
		every source, including website_form — no new branch, no new label,
		confirmed by a direct string assertion
	•	no Order is created by opening/viewing any of these pages — a
		structural assertion (InMemoryOrderRepository stays empty across
		every new test in this file)
	•	no OrderVersion is created — same structural assertion
	•	convert stays blocked for an unverified, verification-required
		website_form Inquiry — re-confirms §1.3's existing, unmodified B5
		gate still fires exactly as before this pack's rendering changes
	•	kiosk/Wochenübersicht output is unchanged before/after rendering any
		of these new list/detail elements — same byte-identical-comparison
		technique already used in a98065c/5d5e007's own boundary tests

⸻

10. Non-goals

	•	no new Inquiry/domain field, no renamed field
	•	no new customer/contact model — phone/email/message stay inside
		intake_message, unsplit (§1.5, §5)
	•	no new verification action beyond the existing "Telefonisch
		verifiziert" button (§6)
	•	no automatic conversion, no new progression rule — B5 stays exactly
		as it is (§1.3, §7)
	•	no change to update_inquiry()'s field set or to the create form
		beyond nothing (this pack only touches render_anfragen and
		render_inquiry's read-side rendering, plus the small label dict —
		office_panel.py's write paths are untouched)
	•	no kitchen/kiosk/release/READY_TO_SEND change of any kind
	•	no receiver/Worker/Tunnel/systemd change — unrelated layer, already
		covered by three prior packs in this chain
	•	no AI decision, no CRM bridge

⸻

11. Acceptance criteria for the future implementation step

	•	/anfragen shows Kanal and Betreff columns; existing columns/order
		otherwise preserved
	•	Kanal values render through the new label dict everywhere they
		appear (list + detail), with a safe fallback for unlabeled values
	•	the website_form-only banner appears on exactly the Inquiries it
		should and nowhere else
	•	search covers inquiry_source and intake_subject in addition to the
		existing fields
	•	full existing suite stays green; new tests follow §9
	•	no Core/domain/service/repository file changed
	•	no kiosk_server.py, WochenuebersichtService, order_service.py, or
		operational_core_service.py file changed
	•	the existing verify/convert action routes and their gating are
		unmodified — this pack changes rendering only

⸻

12. Open gaps — not decided here, flagged for the owner

	•	whether "Telefonisch verifiziert" should get a website_form-specific
		alternate label ("Rückruf erledigt") — §6 recommends keeping it
		universal; a one-line change either way if the owner disagrees
	•	exact truncation length for the list's Betreff column (this pack
		suggested 40 chars as a starting point, not a hard requirement)
	•	whether "configurator" really deserves the "Angebots-Import" label
		reuse in this new dict, or a slightly different phrase reading
		better in a table-column context vs. a sidebar link — a wording
		nuance, not a structural question
	•	whether missed_call/ai_telefonist should get real labels once (if
		ever) an adapter actually writes them — deferred, matching every
		prior pack's own "don't label what nothing produces yet" discipline

⸻

13. Exit

Complete when this document is reviewed and frozen as accepted design, with
zero code changes in this repo. Implementation (the label dict, the two new
list columns, the detail-page banner, the search extension, and §9's tests)
is a separate future step, needing its own GO and diff review, per this
project's standing discipline.
