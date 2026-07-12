INQUIRY_INTAKE_CONTEXT_FIELDS_PACK_V1

0. Purpose

Design-only pack. Proposes a minimal, general extension of the Inquiry
aggregate to hold intake context — freeform information about how and why an
inquiry arrived, independent of which channel produced it (phone, website,
AI telefonist, configurator export, email). This generalizes the narrow
prefill bridge from PROPOSAL_PREVIEW_MANUAL_INQUIRY_PACK_V1 (frozen d7429b5,
implemented 9012c35, live-verified 2026-07-09) into a channel-agnostic
mechanism, and closes that pack's §3 "honest gap" (no durable place to record
where an Inquiry's context came from). No code changes in this pack; every
model claim below was checked against current code on 2026-07-10
(domain/inquiry.py, services/inquiry_service.py,
repositories/{sqlite,in_memory}_inquiry_repository.py, ui/office_panel.py,
tests/unit/test_inquiry_service.py, tests/unit/test_sqlite_repositories.py,
tests/unit/test_storno.py).

⸻

1. Boundary

	•	Inquiry intake context is not operational truth — it describes how a
		request arrived, never what will be delivered
	•	intake context is not Order — creating/updating it never creates,
		converts to, or implies an Order
	•	intake context is not OrderVersion — it never populates kitchen-facing
		item/date/guest fields on any OrderVersion
	•	intake context is not kitchen truth — nothing in it is print-confirmed,
		wirksam, or READY_TO_SEND material
	•	intake context must not affect wirksam/effective — no code path from
		writing intake context may call
		operational_core_service.make_order_version_effective()
	•	intake context must not affect READY_TO_SEND — no code path from
		writing intake context may call
		operational_core_service.request_ready_to_send() or change
		evaluate_ready_to_send()'s inputs
	•	intake context must not appear in kiosk/Wochenübersicht as a delivery
		— confirmed by evidence: kiosk_server.py never imports or reads
		Inquiry at all (grep found zero references); WochenuebersichtService
		reads only OrderVersion. Adding fields to Inquiry cannot change this
		by construction, as long as no new code path bridges Inquiry data
		into Order/OrderVersion creation
	•	office action remains required for Core progression — intake context
		fields are written through the same explicit, office-initiated
		create/update paths as every other Inquiry field today; nothing in
		this pack proposes a new automatic write path

⸻

2. Why a general intake context, not a proposal-specific one

CONFIGURATOR_OFFICE_MANUAL_HANDOFF and PROPOSAL_PREVIEW_MANUAL_INQUIRY packs
solved one channel: configurator → proposal_payload_v1 → office → Inquiry.
But the office's real inbound channels are broader: a phone call the office
takes directly, a missed call callback, a future AI telefonist transcript, a
future own website inquiry form, an email. All of them carry the same shape
of information — "someone asked for something, here's what they said" —
before any of it is confirmed enough to become an Order.

Storing only event_date + guest_count_estimate (today's Inquiry) already
loses the substance of the request: what was actually asked for, in the
requester's own words or the taker's summary. But the fix must not smuggle
Order/CRM semantics into Inquiry: Inquiry stays the cheap, disposable,
pre-operational object it is today (see PROPOSAL_PREVIEW_MANUAL_INQUIRY §2 —
unconverted, it drives nothing operational). A general, small, freeform
context is the narrowest fix that serves every channel without inventing a
structured order-items model, a CRM contact model, or a call-log model inside
Core.

⸻

3. Current model — evidence base

Inquiry (domain/inquiry.py) fields today: inquiry_id, event_date, created_at,
updated_at, inquiry_source, crm_stage, customer_linkage (IDs only),
time_window_text, location_text, guest_count_estimate, planning_mode,
call_verification_required/status. No free-text field exists anywhere on
Inquiry today (confirmed absence, not oversight).

inquiry_source is a closed vocabulary duplicated in three places, none of
which currently include configurator/ai_telefonist/website_form/
missed_call/phone_by_office:
	•	domain/inquiry.py:9 — InquirySource = Literal["wix_form", "email",
		"phone", "manual"] (type hint only, not runtime-enforced)
	•	services/inquiry_service.py:31 — _ALLOWED_SOURCES = frozenset({
		"wix_form", "email", "phone", "manual"}) (the actual write-time
		validator, called from create_inquiry/update_inquiry)
	•	ui/office_panel.py:32 — _OFFICE_SOURCES = ("phone", "email", "manual")
		(the "Kanal" dropdown the office fills by hand — narrower still,
		excludes wix_form because the office never picks that channel itself)

Load-path evidence: sqlite_inquiry_repository.py's _row_to_inquiry casts
inquiry_source straight from the TEXT column with no validator call (unlike
crm_stage/planning_mode/call_verification_status, which are re-validated on
load). This matters for §7: widening the write-time allowed set is low-risk
for already-stored rows, because nothing re-validates old values on read.

Migration precedent exists in this exact repo: SQLiteOrderRepository (§4 of
the STORNO pack) adds a column to a pre-existing table with
PRAGMA table_info(...) + ALTER TABLE ... ADD COLUMN, tested by
tests/unit/test_storno.py::test_sqlite_roundtrip_and_pre_storno_migration
(builds an old-shape table by hand, opens it with the current repository
class, asserts the column appears with a safe default, and that a second
open after a write round-trips correctly). This pack's future implementation
should follow that exact pattern — it is proven, not proposed.

⸻

4. inquiry_source: extend, do not duplicate

Design decision, made here explicitly rather than left for the implementer:
the "source of incoming request" concept already exists as inquiry_source.
Adding a second, parallel intake_source field with an overlapping-but-
different vocabulary would create exactly the kind of dual-classification
confusion this project's "vocabularies not merged" rule exists to prevent —
except in reverse: two fields for one concept, which office staff would fill
inconsistently (e.g. Kanal=phone but a hypothetical intake_source=
ai_telefonist on the same record).

Recommendation: intake_source is inquiry_source, widened. Not a new column —
a wider allowed-value set on the existing one, and a new set of UI options
where the office (or a future integration) sets it. Per this pack's brief,
wix_form is retired as the term (no Wix; a custom site is planned) and the
allowed set becomes:

	manual, phone_by_office, missed_call, ai_telefonist, website_form,
	configurator, email

Backward compatibility: any already-stored "wix_form"/"phone" value stays
readable (§3 — no read-time validation), simply no longer offered on new
writes. If the owner later needs to distinguish historic wix_form rows,
that is a reporting question, not a live-domain one — out of scope here.

	•	what it means: which channel/actor originated this inquiry
	•	who may set it: whoever creates the Inquiry — office (manual dropdown,
		as today), or a future automated integration (configurator prefill
		link, AI telefonist, website form) once each is explicitly approved
		to write Inquiry at all
	•	editable by office: yes, always, like every other Inquiry field today
	•	what it does NOT mean: not a CRM lead-source field, not an Order
		source, not a billing/marketing attribution field — purely "how did
		the request arrive," nothing downstream reads it for any operational
		decision today, and this pack proposes none

⸻

5. New fields — proposed, checked against the model, not asserted

Four new optional fields, all nullable TEXT, all editable by office, none
read by any operational logic (evaluate_ready_to_send, progression service,
kiosk, Wochenübersicht — none of these take Inquiry as input beyond what
already flows through Order at conversion time, per §1).

intake_subject
	•	what it means: a short, human title/headline for the request — "what
		is this about" at a glance (e.g. an event name, a company name, "Café
		Sommer — Weihnachtsfeier")
	•	who may set it: whoever fills the Inquiry form; may be prefilled from
		an external source (e.g. configurator's proposal title) as a
		suggestion, never as truth
	•	where it comes from: office typing, or a prefill hint from a proposal/
		call/form (page-context or form default, same mechanic as the
		existing event_date/guest_count_estimate prefill — see §8)
	•	editable by office: yes
	•	what it does NOT mean: not a customer/company master-data field (that
		remains customer_linkage's job — IDs only, per domain/inquiry.py); not
		searchable/indexed CRM data in this pack

intake_message
	•	what it means: the substance of the request in the requester's own
		words, or as directly transcribed/relayed — a phone summary, an email
		body excerpt, a website form's free-text field, an AI telefonist's
		call transcript excerpt
	•	who may set it: same as intake_subject
	•	where it comes from: office typing, transcript/relay from a future
		integration
	•	editable by office: yes
	•	what it does NOT mean: not a structured wishlist, not confirmed dietary
		requirements, not anything the kitchen reads — it is prose, read by a
		human office worker forming their own judgment

intake_summary
	•	what it means: a short, human-readable summary of what was asked for —
		may include a plain-text rundown of proposed items ("2x Brötchen Mix,
		10 Personen") when it comes from a proposal export, or a call summary
		("Kunde möchte Buffet für Firmenfeier, ca. 30 Personen, Rückruf
		gewünscht") when it comes from a phone channel
	•	who may set it: same as above
	•	where it comes from: same as above; for the configurator channel
		specifically, a compact name+quantity rendering of selected_items
		(see §8) — never prices
	•	editable by office: yes
	•	what it does NOT mean: NOT a confirmed kitchen item list; NOT
		OrderVersion.items (no such field exists on OrderVersion today and
		this pack does not add one); reading this text does not obligate the
		kitchen to anything — only a real OrderVersion, created through the
		existing conversion flow, does that

intake_external_ref (optional)
	•	what it means: an opaque, local identifier from the originating system
		— e.g. a configurator proposal_id, a future website form submission
		id, a future AI telefonist call id
	•	who may set it: whoever/whatever writes the Inquiry; typically an
		integration, since a human office worker rarely has or needs this
	•	where it comes from: the external system's own local ID
	•	editable by office: yes (can be cleared/corrected), but ordinarily
		left as set at creation
	•	what it does NOT mean: NOT an operational identifier — nothing in Core
		looks it up, joins on it, or treats it as authoritative; it is a
		breadcrumb for a human to trace "where did this come from," not a
		foreign key the domain relies on

All four are optional (nullable), independent of each other, and independent
of the existing structured fields (event_date, guest_count_estimate,
time_window_text, location_text, planning_mode) — none of them are replaced
or overloaded.

⸻

6. AI Telefonist

AI Telefonist may capture, for later manual entry or (once separately
approved) automated prefill: caller phone, name if given, event date if
given, guest estimate if given, event type/wishes, callback urgency, call
summary.

AI Telefonist must not, under this pack or any future pack unless explicitly
re-opened: create Order; create OrderVersion; set wirksam/effective; set
READY_TO_SEND; send anything to kitchen/kiosk; silently create operational
truth of any kind.

If AI Telefonist is ever wired to write anything automatically, the ceiling
for a first step — matching the precedent set by the configurator handoff —
is a pre-inquiry intake record or a draft/hint, never a live Inquiry created
without office review, unless that specific automatic-Inquiry-creation step
is separately designed, reviewed, and frozen on its own. This pack does not
authorize automatic Inquiry creation from any source, AI telefonist included.

⸻

7. Website form

Uses the term Website-Anfrageformular (custom future site) — not Wix,
consistent with wix_form's retirement in §4.

The website form may create or prepare an Inquiry only through a controlled,
office-visible flow — the same shape as this pack's other channels: land the
office on the existing Inquiry form with prefilled/context hints, requiring
an explicit office submit. Direct auto-create-Inquiry-on-form-submit is
explicitly not authorized here; if the owner wants that later (skipping
office review for website submissions), it needs its own separate,
explicitly approved pack — the tradeoff (spam/bogus submissions creating real
Inquiries unattended) is a product decision, not a technical detail.

Website form must not create Order/OrderVersion, under any circumstance,
with or without office review at the Inquiry stage.

⸻

8. Configurator mapping

The existing proposal_payload_v1 → Inquiry bridge (PROPOSAL_PREVIEW_MANUAL_
INQUIRY_PACK_V1, implemented 9012c35) maps today only event_date and
guest_count into query-string prefill hints. Under this pack's fields, that
mapping widens to:

	•	intake_source = "configurator"
	•	intake_subject = payload.title
	•	intake_message = payload.notes
	•	intake_summary = compact "name × quantity" rendering of
		payload.selected_items (no prices — same restriction as the frozen
		pack's §3 "Must NOT transfer" list)
	•	intake_external_ref = payload.proposal_id, when present

Prices (calculated_total_net/gross, unit_price, total_price) and the raw
selected_items structure remain proposal context only — they are shown on
the read-only preview page (unchanged) and never written into Inquiry in any
form, structured or serialized. Nothing about this widens what the frozen
9012c35 implementation currently passes through the URL query string — see
§9's explicit non-goal on this point; how these values reach the form (query
string vs. a different transport) is an implementation-step decision, not
decided here.

⸻

9. Strictly forbidden in V1

	•	structured Order items on Inquiry, in any form
	•	confirmed prices anywhere on Inquiry
	•	calculated_total_net/gross treated as Core truth (they stay proposal
		display data on the existing preview page only)
	•	the raw full proposal JSON stored as, or treated as, operational truth
	•	automatic Order creation from intake context, from any channel
	•	automatic OrderVersion creation from intake context, from any channel
	•	AI Telefonist auto-creating an Order or a live Inquiry unattended
	•	website form auto-creating an Order, or auto-creating a live Inquiry
		unattended (see §7)
	•	configurator direct write into Core (unchanged from the frozen
		handoff pack — still no bridge)
	•	CRM bridge of any kind
	•	kitchen/kiosk/release logic changes
	•	READY_TO_SEND logic changes
	•	a customer master-data model rewrite — customer_linkage stays
		IDs-only; intake_subject is not a company-name field replacement for
		it
	•	widening the URL-query prefill mechanism to carry intake_subject/
		intake_message/intake_summary/intake_external_ref as query
		parameters — PROPOSAL_PREVIEW_MANUAL_INQUIRY_PACK_V1's review
		(2026-07-09) explicitly narrowed the prepare-link to event_date +
		guest_count_estimate only, for URL-fragility and page-context-is-
		enough reasons that still apply; this pack does not reopen that
		decision — if intake context should also prefill from the
		configurator flow, that is a separate, explicitly scoped follow-up

⸻

10. Acceptance criteria for a future implementation step

Design only now; none of this is built. Fixed here so a later GO has a
concrete target:

	•	existing Inquiry fields preserved — no field renamed or removed,
		dataclass gains fields only
	•	SQLite migration follows the proven precedent (§3): PRAGMA
		table_info(...) check + ALTER TABLE ... ADD COLUMN for each new
		column, defensively run on every repository open, matching
		SQLiteOrderRepository's pattern exactly
	•	a test proves backward compatibility the same way
		test_storno.py::test_sqlite_roundtrip_and_pre_storno_migration does:
		hand-build an old-shape inquiries table, open it with the updated
		SQLiteInquiryRepository, confirm existing rows load with the new
		fields defaulting to None/empty, confirm a second open after a write
		round-trips correctly
	•	existing flows still pass unmodified: manual Inquiry creation, the
		phone-hint flow (?phone=...), the proposal-preview prefill flow
		(?event_date=...&guest_count_estimate=...) — none of their existing
		tests change meaning, only new tests are added
	•	inquiry_source's widened allowed-value set is enforced only at
		write-time (service-layer validator), matching current behavior;
		read-time stays permissive per §3's evidence
	•	no Order or OrderVersion is created as a side effect of writing any
		intake context field, under any test scenario
	•	no READY_TO_SEND/kiosk/Wochenübersicht change is observable before vs.
		after intake context is written to an Inquiry — a repository-level
		test asserting kiosk/Wochenübersicht output is byte-identical is the
		concrete proof, same technique as this pack's own live-verification
		checkpoint (2026-07-09, isolated DB copy)
	•	tests prove intake context is stored only on Inquiry — never copied
		onto Order or OrderVersion at conversion time
		(convert_inquiry_to_order's existing behavior, order_service.py:33,
		stays unchanged: it reads inquiry.guest_count_estimate/event_date/
		time_window_text/location_text/planning_mode only — intake_subject/
		message/summary/external_ref/widened source are not among the
		fields it currently reads, and this pack does not add them)

⸻

11. Exit

Complete when this document is reviewed and frozen as accepted design, with
zero code changes in this repo. The implementation is a separate future
step, needing its own GO, its own narrow diff plan against this pack's
§4/§5/§10, and the same review-before-code discipline as every prior step in
this chain. §6/§7's AI-telefonist and website-form automatic-write questions
are explicitly deferred, not decided — each needs its own pack if and when
the owner wants to open it.
