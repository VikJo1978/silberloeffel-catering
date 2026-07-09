PROPOSAL_PREVIEW_MANUAL_INQUIRY_PACK_V1

0. Purpose

Design-only pack. Defines the next possible step after
CONFIGURATOR_OFFICE_MANUAL_HANDOFF_PACK_V1 (frozen 334cd11, implemented
read-only in c6886ba/1cfcb02 and fingerfood-app fffc60b): a safe, manual,
office-initiated write-step from the proposal preview into Core, creating an
Inquiry and nothing else. This pack authorizes no implementation; code happens
only after this design is reviewed, frozen, and a GO with its own narrow diff
plan exists. Evidence rule as in OPERATIONAL_CORE_EXECUTION_PACK_V1 §2 — every
claim below about the domain model was checked against current code
(domain/inquiry.py, services/inquiry_service.py, services/order_service.py,
ui/office_panel.py) on 2026-07-09.

⸻

1. Boundary

	•	proposal payload (proposal_payload_v1) stays proposal data, never truth
		— unchanged from the handoff pack §1
	•	the preview stays not operational truth; rendering it stays a read-only
		step; POST /proposal-preview continues to write nothing
	•	Core write happens only through one explicit, additional, manual office
		action after the preview — never as a side effect of pasting, parsing,
		or viewing
	•	the first and only write-step designed here creates an Inquiry — not an
		Order, not an OrderVersion
	•	Order and OrderVersion continue to arise only through the existing,
		unchanged manual flow: inquiry detail view → "In Auftrag umwandeln" →
		convert_inquiry_to_order (B5 call-verification gate intact)
	•	no kitchen/kiosk/release/READY_TO_SEND/Wochenübersicht effect of any
		kind: a freshly created Inquiry is invisible to all of them by
		construction (they read Orders/OrderVersions only)

⸻

2. Why Inquiry, not Order/OrderVersion

	•	Inquiry is the domain's designated entry object: unconverted, it drives
		nothing operational — no kitchen sheet, no week view, no release gate.
		It is the cheapest Core object to create and the cheapest to abandon
		(CRM stage "Abgelehnt / verloren" exists for exactly that)
	•	Order requires operational confirmation the proposal cannot carry: the
		domain gates conversion behind B5 (call verification), and
		convert_inquiry_to_order immediately creates OrderVersion v1 — kitchen-
		facing semantics (print confirm, wirksam, READY_TO_SEND) attach from
		that moment on
	•	OrderVersion is operational order truth per OPERATIONAL_CORE pack;
		writing proposal items into one would make unconfirmed Angebot data
		kitchen-visible — exactly what the frozen boundary forbids
	•	the payload is Angebotsphase data: prices, item selection, and totals
		are what was offered, not what was agreed. Core deliberately has no
		price/Angebot concept at all (checked: no price field exists anywhere
		in domain/), so there is nothing in Core that could hold them even by
		accident — this asymmetry is a feature and stays

⸻

3. Allowed transfer into Inquiry — checked against the actual model

Inquiry fields today (domain/inquiry.py): event_date (date),
inquiry_source (Literal: wix_form/email/phone/manual), crm_stage,
customer_linkage (IDs only: customer_id/contact_id/placeholder),
time_window_text, location_text, guest_count_estimate (int|None),
planning_mode, call_verification_required/status. There is no title field, no
customer/company name field, no free-text notes field.

May prefill as editable form defaults (real fields exist):
	•	event_date → the Inquiry form's Datum field, prefilled, office can
		change it before submitting — a hint until submit, like every other
		form value
	•	guest_count → guest_count_estimate, prefilled — the field is named
		"estimate" in the domain; that is exactly the payload's epistemic level

May show as read-only page context only (no field exists; never persisted):
	•	title (company/event name) — customer_linkage carries IDs, not names;
		inventing a name field is a domain change, out of scope here
	•	source marker ("Quelle: fingerfood-configurator, proposal_payload_v1")
	•	selected_items summary (compact: item names + count, no prices)
	•	notes (Freitext aus Angebotsphase)
	Precedent: GET /inquiry/new?phone=... already renders "Anruf von: ..." as
	page context that is never written anywhere (Entry 058, §11 addendum §14).
	This pack reuses that exact mechanic — same route, same pattern.

Must NOT transfer, in any form:
	•	calculated prices (net/gross/unit/total) as anything — Core has no
		place for them and gets none
	•	selected_items as structured order/kitchen items — they never become
		OrderVersion content through this step
	•	proposal_id as an operational identifier — it stays configurator-local
	•	any recommendation/ranking metadata
	•	any "offer sent" status — CRM stage starts at "Neue Anfrage" like every
		manually created Inquiry; the office moves stages manually as always
	•	nothing into time_window_text or location_text unless the office types
		it themselves — abusing these semantically specific fields as a dump
		for proposal notes would be a hidden vocabulary merge

Honest gap, decided-not-designed here: the created Inquiry cannot durably
record "came from configurator proposal X" because no existing field can hold
it — inquiry_source is a closed Literal without a configurator value, and
there is no notes field. V1 accepts this: the marker is visible during
creation (page context) and gone after. If the owner wants a persistent
marker, that is a separate, explicitly reviewed domain change (either a new
inquiry_source value or an optional free-text field on Inquiry) with its own
pack — this pack neither authorizes nor pre-designs it.

⸻

4. Manual flow

	1.	office opens /proposal-preview (existing)
	2.	office pastes the proposal JSON (existing)
	3.	office sees the preview with the not-truth warning (existing)
	4.	NEW: the rendered preview additionally offers one navigation action:
		"Anfrage aus Vorschau vorbereiten" — a link to the existing
		GET /inquiry/new carrying the transferable hints as query parameters
		(event_date, guest count, plus the display-only context of §3). It is
		a GET link: following it still writes nothing
	5.	office lands on the existing Inquiry creation form: Datum and Gäste
		(ca.) prefilled but editable; title/source/items-summary/notes shown
		above the form as read-only context, exactly like the phone hint
	6.	office reviews, corrects, fills the rest (Kanal, Zeitfenster, Ort,
		Planungsmodus, Rückruf-Verifizierung) and explicitly submits the
		existing POST /inquiry/new — this submit is the one and only write,
		through the unchanged InquiryService.create_inquiry path with its
		existing validation
	7.	after the Inquiry exists, everything downstream is the existing,
		untouched flow: verification if required, then optionally
		"In Auftrag umwandeln" — no automatic Order creation, no shortcut

	No new POST route is needed. No session state, no server-side storage of
	the payload, no persistence between steps: the hints live in the GET
	query string and die with the page.

⸻

5. Required safety UI

	•	the action says Anfrage ("Anfrage aus Vorschau vorbereiten"), never
		Auftrag — creating an Auftrag from a proposal is not a thing
	•	the prefilled form shows: "Vorschau-Daten werden nur als Hinweise
		übernommen — bitte prüfen und ggf. korrigieren" (wording may adapt to
		panel style; meaning fixed)
	•	the explicit submit of the existing form is the confirmation — no
		additional confirm dialog is required, because the office still has to
		review and actively submit; nothing is pre-created
	•	the source marker ("Quelle: fingerfood-configurator,
		proposal_payload_v1") is shown as page context during creation; see
		§3's honest gap for why it is not persisted in V1
	•	no hidden write on preview POST: POST /proposal-preview keeps rendering
		only; the write stays behind the separate form submit on
		POST /inquiry/new

⸻

6. Non-goals / forbidden

This pack does not authorize, and a future implementation of it must not do:
	•	auto-create Inquiry on JSON preview POST (or on GET, or on parse)
	•	auto-create Order, in any variant
	•	auto-create OrderVersion, in any variant
	•	auto-set effective/wirksam
	•	auto-READY_TO_SEND or any release-gate effect
	•	write proposal prices anywhere in Core, as anything
	•	write selected_items as confirmed kitchen/order items
	•	kitchen/kiosk/release logic changes
	•	CRM → Core bridge
	•	configurator direct write into Core (the configurator repo is not
		touched by this pack at all)
	•	persistence of the preview payload anywhere outside the one explicitly
		submitted Inquiry (no drafts table, no session store, no file drop)
	•	new source of truth; Inquiry created this way is an ordinary Inquiry,
		not a special kind
	•	domain model changes (no new fields, no new inquiry_source values, no
		vocabulary merges) — see §3's honest gap for the one known temptation

⸻

7. Acceptance criteria for the future implementation step

Defined now so the later GO has a fixed target; none of this is built yet:
	•	POST /proposal-preview still writes nothing — proven by the existing
		"creates nothing in Core" test continuing to pass unchanged
	•	the write requires the explicit, separate office submit on the
		existing POST /inquiry/new — no other path creates anything
	•	at most one Inquiry per submit; repository state proves exactly one
		new Inquiry after the action, zero before it
	•	zero Orders and zero OrderVersions created anywhere in the flow —
		asserted directly against the order repository
	•	kiosk/Wochenübersicht and READY_TO_SEND evaluation unchanged before vs
		after — a fresh Inquiry is invisible to both
	•	an invalid proposal payload cannot reach the prefill step (the
		existing parser already rejects it with 400 before any preview
		renders, and the prefill link only exists on a rendered preview)
	•	prefilled event_date/guest_count are editable in the form and the
		submitted values win — the payload does not override office input
	•	the source marker is visible on the prefilled form (page context);
		persisting it is out of scope per §3
	•	full existing suite stays green; new tests follow the live-socket
		pattern of tests/unit/test_office_panel.py

⸻

8. Exit

Complete when this document is reviewed and frozen as accepted design, with
zero code changes in this repo and zero changes in fingerfood-app. The
implementation is a separate future step: it needs its own GO, its own narrow
diff plan against this pack's §4/§5/§7, and the usual review-before-code
discipline. Anything this pack marked as an honest gap or open decision
(persistent source marker) needs its own pack before any code touches it.
