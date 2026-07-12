INQUIRY_INTAKE_CONTEXT_FIELDS_IMPLEMENTATION_PACK_V1

0. Purpose

Implementation-only pack. Turns INQUIRY_INTAKE_CONTEXT_FIELDS_PACK_V1
(frozen 07083cc, design-only) into a concrete, file-by-file technical plan:
domain model, service validation, SQLite migration, repository roundtrip,
Office Panel form/display, the future proposal-preview mapping, and tests.
No code changes in this pack. Every claim below was checked against current
code on 2026-07-10 (domain/inquiry.py, services/inquiry_service.py,
repositories/{sqlite,in_memory}_inquiry_repository.py, ui/office_panel.py,
intake/*.py, tests/unit/test_inquiry_service.py,
tests/unit/test_sqlite_repositories.py, tests/unit/test_storno.py,
tests/unit/test_intake_adapters.py, tests/unit/test_hubspot_office_intake_
http.py) — including one correction to the frozen design pack's evidence,
flagged explicitly in §1.

⸻

1. Correction to the frozen design pack — read before anything else

07083cc §4 says wix_form "is retired as the term... simply no longer offered
on new writes," implying _ALLOWED_SOURCES could drop it. New evidence found
while writing this implementation pack shows that is unsafe as stated:

	src/catering_system/intake/ contains four existing, tested adapter
	modules (manual_adapter.py, email_adapter.py, phone_adapter.py,
	wix_form_adapter.py — INTEGRATION_DEPLOYMENT_EXECUTION_PACK_V1's intake
	layer), each hardcoding its own inquiry_source and calling through
	InquiryService.create_inquiry — the real, validated write path, not a
	direct dataclass construction. wix_form_adapter.py:98 writes
	inquiry_source="wix_form" through that exact validator.
	tests/unit/test_intake_adapters.py (11+ tests) and
	tests/unit/test_inquiry_service.py:46/220 exercise this value through
	the same validated path. Removing "wix_form" from _ALLOWED_SOURCES would
	make every call to intake_from_wix_form(...) raise ValueError and break
	that entire test file.

Resolution (adopted here, does not reopen 07083cc's actual intent): keep
"wix_form" in the domain Literal and in _ALLOWED_SOURCES — do not remove it.
"Retire the term" is implemented exactly the way it already partially is
today: _OFFICE_SOURCES (the Office Panel's manual dropdown) simply never
offers it — that asymmetry between the full write-validator set and the
narrower office-visible set already exists in current code (§3) and is the
correct, minimal way to honor "not a base term going forward" without
breaking a real, working, tested integration this pack was never asked to
touch. If the owner later wants to decommission the Wix adapter itself, that
is its own separate, explicitly scoped change — not silently bundled here.

⸻

2. Domain model — src/catering_system/domain/inquiry.py

InquirySource widens from Literal["wix_form", "email", "phone", "manual"] to:

	InquirySource = Literal[
	    "wix_form",       # kept — see §1; not office-offered, not new-default
	    "manual",
	    "phone_by_office",
	    "missed_call",
	    "ai_telefonist",
	    "website_form",
	    "configurator",
	    "email",
	]

Four new fields appended to the Inquiry dataclass, each defaulting to None so
every existing keyword-argument construction call site keeps working
unmodified (11 direct `Inquiry(...)` call sites found: sqlite_inquiry_
repository.py, inquiry_service.py, and 9 test files — dataclass field-
ordering rule requires defaulted fields after non-defaulted ones, which
appending at the end satisfies automatically):

	intake_subject: str | None = None
	intake_message: str | None = None
	intake_summary: str | None = None
	intake_external_ref: str | None = None

No changes to any existing field, no renames, no reordering of existing
fields (reordering would still be a source-compatible dataclass change since
all current call sites use keyword arguments, but is unnecessary churn — not
done).

⸻

3. InquiryService validation — src/catering_system/services/inquiry_service.py

_ALLOWED_SOURCES (line 31) widens to the same 8-value set as §2's Literal —
single source of truth for both stays informal (as today: the Literal is a
type hint only, _ALLOWED_SOURCES is the actual runtime gate; this pack does
not introduce a shared constant module, matching the existing pattern where
CRM_PIPELINE/PLANNING_MODES live in domain/inquiry.py but
_ALLOWED_SOURCES/validate_inquiry_source stay local to inquiry_service.py —
not touched, out of scope to refactor).

create_inquiry(...) and update_inquiry(...) both gain four new optional
keyword parameters: intake_subject: str | None = None, intake_message,
intake_summary, intake_external_ref — following exactly the same optional-
field pattern update_inquiry already uses for guest_count_estimate (the
_UNSET sentinel distinguishes "not provided, keep current" from "explicitly
set to None" on update; create_inquiry has no such ambiguity since there is
no prior value).

Normalization rule (one consistent choice, per the task's explicit ask):
empty/whitespace-only string → None, on write, for all four fields. Rationale:
matches how the office already experiences other free-text fields in this UI
(time_window_text/location_text stay "" not None today, but those are
NOT NULL TEXT columns with an established "" convention already tested — see
§7). intake_* fields are new NULLable columns with no such precedent to
preserve, and "None" is the more honest representation of "nothing was
entered" for a genuinely optional field the SQL schema itself marks nullable.
Trimming happens once, in InquiryService (not in the domain dataclass, which
stays a plain value holder with no logic, and not in Office Panel, which
would then need the same logic duplicated for any future non-HTTP caller
like a website-form or AI-telefonist adapter). No maximum length enforced —
no existing free-text Inquiry field (time_window_text, location_text)
enforces one either; consistent with that absence, not a new gap.

Source visibility split (three tiers, all already implied by current code
structure, made explicit here):
	•	write-allowed (_ALLOWED_SOURCES, enforced): all 8 values
	•	office-dropdown-visible (_OFFICE_SOURCES in office_panel.py): manual,
		phone_by_office, email, website_form, configurator — ai_telefonist
		and missed_call and wix_form excluded from the dropdown; see §5 for
		why each is excluded
	•	adapter-only (never in any dropdown, only ever set by their own
		adapter's hardcoded value): wix_form (existing), and in the future
		website_form/ai_telefonist/missed_call once/if their own adapters
		exist — until then those three values are reachable only through the
		Office Panel's manual dropdown, which is correct: nothing today
		writes them automatically, so a human picking them by hand from the
		dropdown is the only path, exactly matching this pack's boundary
		(§1 of 07083cc: office action remains required)

⸻

4. SQLite migration — repositories/sqlite_inquiry_repository.py

Exact column additions, following SQLiteOrderRepository's proven pattern
(sqlite_order_repository.py:52-56, STORNO pack §4) verbatim:

	intake_subject TEXT
	intake_message TEXT
	intake_summary TEXT
	intake_external_ref TEXT

(SQLite has no column-level NOT NULL/NULL distinction to declare beyond
omitting NOT NULL — "TEXT" alone is nullable, matching guest_count_estimate's
existing "INTEGER" column, which is the one other nullable column in this
table today.)

__init__ gains, immediately after self._conn.executescript(_SCHEMA) and
before self._conn.commit():

	cols = {r[1] for r in self._conn.execute("PRAGMA table_info(inquiries)").fetchall()}
	for col in ("intake_subject", "intake_message", "intake_summary", "intake_external_ref"):
	    if col not in cols:
	        self._conn.execute(f"ALTER TABLE inquiries ADD COLUMN {col} TEXT")

(A loop over four columns rather than four repeated if-blocks — the STORNO
precedent only had one column so didn't need this shape; four columns with
identical TEXT-nullable treatment justify the loop instead of copy-pasting
the STORNO single-column snippet four times.)

_SCHEMA's CREATE TABLE gains the four columns too (for brand-new databases,
so the ALTER TABLE loop is a no-op on first creation, exactly like
cancelled_at is already both in orders' CREATE TABLE and defensively
ALTER-checked in SQLiteOrderRepository).

⸻

5. Repository roundtrip

save() (INSERT OR REPLACE): the positional value tuple grows from 13 to 17
entries — inquiry.intake_subject, inquiry.intake_message,
inquiry.intake_summary, inquiry.intake_external_ref appended at the end, and
the SQL literal VALUES (?, ?, ..., ?) grows from 13 to 17 placeholders. This
is a positional INSERT (no column list) — order must match the CREATE
TABLE's column order exactly, which is why §4 appends the four columns at
the end of the schema, matching where they're appended in the dataclass.

_row_to_inquiry(): four new keyword arguments, read straight from
row[13]..row[16] with no validator call — deliberately consistent with how
inquiry_source itself is already read (§1 of 07083cc's evidence: no
read-time validation for free-form/loosely-typed columns). Values are
already None for any pre-migration row NOT re-saved since the ALTER TABLE
ran (SQLite backfills new columns as NULL for existing rows automatically —
no explicit UPDATE needed, same as STORNO's cancelled_at).

update(): unchanged — it already delegates to save() after an existence
check (sqlite_inquiry_repository.py:104-107); no new logic needed since
save()'s positional tuple already carries the new fields.

in_memory_inquiry_repository.py: no change needed at all — it stores whole
Inquiry objects by reference in a dict (in_memory_inquiry_repository.py:8-13)
and never destructures fields; the new dataclass fields ride along for free.
This asymmetry (SQLite needs real migration work, in-memory needs none) is
expected and requires no reconciliation.

⸻

6. Office Panel — src/catering_system/ui/office_panel.py

_OFFICE_SOURCES (line 32) widens from ("phone", "email", "manual") to:

	("manual", "phone_by_office", "email", "website_form", "configurator")

phone dropped in favor of phone_by_office (clearer that this is the office
taking a call directly, distinct from missed_call — matches the source list
given in the task). ai_telefonist and missed_call are deliberately absent
from the dropdown per §3's tier split — nothing writes them yet, and hand-
picking "ai_telefonist" from a dropdown before any AI telefonist integration
exists would be a misleading option to offer the office. wix_form stays
absent, per §1.

render_inquiry_form() (currently phone/event_date/guest_count_estimate
prefill params, office_panel.py:751 onward) gains four new optional form
fields, inserted after the existing "Rückruf-Verifizierung nötig" checkbox
and before the submit button — kept last so the existing fields' visual
order and every existing test asserting on that order (e.g. matching on
`name="event_date"` position) stays unaffected:

	<p><label>Betreff</label><input name="intake_subject"></p>
	<p><label>Nachricht</label><textarea name="intake_message" rows="4"></textarea></p>
	<p><label>Zusammenfassung</label><textarea name="intake_summary" rows="3"></textarea></p>
	<p><label>Externe Referenz</label><input name="intake_external_ref"></p>

A one-line warning directly above these four fields, matching the existing
`.subtitle` CSS class already used for the phone-hint and proposal-preview
warnings:

	<p class="subtitle">Intake-Kontext — keine Auftrags-/Küchenfreigabe.</p>

V1 field shapes, chosen deliberately narrow per the task's "not huge UI"
instruction: intake_subject and intake_external_ref single-line (short,
identifier-like); intake_message and intake_summary both textareas
(intake_message longer — call transcript/email body; intake_summary
shorter/3 rows — a compact rundown, not a second transcript field). All four
optional — no `required` attribute, matching every other non-Datum field in
this form today.

create_inquiry() (office_panel.py, OfficePanel class) reads the four new
form keys with `.get(..., "")` — same pattern already used for
time_window_text/location_text — and passes them straight through to
InquiryService.create_inquiry(...); the service does the trim-to-None
normalization (§3), not this method, keeping office_panel.py a thin
rendering/routing layer as documented in its own module docstring
("adds no domain semantics").

render_inquiry() (detail view, office_panel.py:795 onward): the four intake
fields are added as additional rows in the existing summary `<table>`
(alongside Datum/Kanal/Zeitfenster/Ort/Gäste/CRM-Stufe/Verifizierung), shown
only when non-None/non-empty — an empty intake context does not clutter the
detail page with four "–" rows for old Inquiries created before this pack.
The update form gains the same four inputs as render_inquiry_form(), so the
office can edit intake context after creation like every other field.

Explicitly NOT touched: render_anfragen() (list view) — intake context stays
detail-page-only in V1, keeping the existing list columns unchanged, per the
task's "not huge UI" instruction and 07083cc §1's "office action remains
required" (nothing about list-view surfacing is required for that). render_
queue() (Startseite), render_auftraege(), render_order(), kiosk_server.py,
WochenuebersichtService — none of these read Inquiry today (kiosk/
Wochenübersicht confirmed zero references in 07083cc §1) and none gain any
new read of it here.

⸻

7. Proposal-preview mapping (future, not this step)

Per 07083cc §8/§9: the existing prepare-link (office_panel.py's
render_proposal_preview(), reviewed and narrowed 2026-07-09) continues to
pass only event_date + guest_count_estimate as URL query parameters — this
pack does not reopen that narrowing. Once the fields from §2-§6 above exist,
a later, separate implementation step may extend render_inquiry_form() to
also accept intake_subject/intake_message/intake_summary/intake_external_ref
as prefill parameters and render_proposal_preview()'s prepare-link to pass
payload.title / payload.notes / a compact selected_items summary (no prices)
/ payload.proposal_id through some transport — deliberately left open here
whether that transport is still query parameters or something else, since
07083cc §9 flagged URL-fragility as the reason the current link stays
narrow. This pack only makes the destination fields exist; wiring the
configurator source into them is out of scope for this implementation step.

⸻

8. Website form / AI Telefonist (future, not this step)

Both stay exactly as scoped in 07083cc §6/§7: no adapter code, no auto-
create-Inquiry path, nothing implemented here. §3's source-visibility tiers
above already accommodate them (website_form is office-dropdown-visible
today since the office may want to manually log a website submission before
any real website-form adapter exists; ai_telefonist is adapter-only until an
actual integration is designed and approved).

⸻

9. Tests

Domain/service (tests/unit/test_inquiry_service.py):
	•	all 8 sources accepted by create_inquiry (extends the existing
		test_create_works_for_each_allowed_inquiry_source loop, which today
		iterates the same _ALLOWED_SOURCES the implementation widens — the
		existing test needs no new assertions, just picks up the wider set
		automatically since it iterates the constant)
	•	an unrecognized source (e.g. "carrier_pigeon") still rejected —
		existing test_invalid_inquiry_source_rejected already covers this
		shape; add one case using a plausible-but-wrong new value to prove
		the widening didn't accidentally admit an unbounded set
	•	wix_form still accepted (regression guard for §1's correction —
		explicit new test, since this is the one claim this pack corrects)
	•	each of the four intake_* fields: empty string normalizes to None,
		whitespace-only normalizes to None, a real value passes through
		unchanged, omitted (not passed) defaults to None
	•	intake fields are fully optional — create_inquiry with none of the
		four still succeeds (regression guard matching the task's explicit
		ask)
	•	update_inquiry can set/clear each intake field independently,
		following the existing _UNSET-sentinel pattern already tested for
		guest_count_estimate

SQLite (tests/unit/test_sqlite_repositories.py):
	•	test_inquiry_roundtrip_preserves_all_fields extended: _sample_inquiry()
		gains explicit intake_* values (not left at the None default) so the
		existing equality assertion (`loaded == inquiry`) actually exercises
		the new columns, not just their absence
	•	new migration test, mirroring test_storno.py::test_sqlite_roundtrip_
		and_pre_storno_migration exactly: hand-build a pre-this-pack
		inquiries table (today's 13-column CREATE TABLE, by literal SQL, not
		by importing the updated schema), insert one row via raw SQL, open
		it with the updated SQLiteInquiryRepository, assert the row loads
		with all four intake_* fields as None, then save() a new Inquiry
		with real intake values through the same connection and confirm a
		second SQLiteInquiryRepository open round-trips them correctly

Office Panel (tests/unit/test_office_panel.py — future addition, not
touched by this pack, listed here as the target for the next step):
	•	manual Inquiry creation with all four intake fields populated —
		created Inquiry carries them, visible on the detail page
	•	manual Inquiry creation with none of the four still works exactly as
		today — existing tests (_create_inquiry helper and its callers)
		continue to pass unmodified, since the four new fields are optional
		form inputs with no required attribute
	•	the Kanal dropdown contains exactly the five office-visible sources
		from §3/§6 — an explicit list-equality assertion, not just presence
		checks, so a future accidental addition/removal is caught
	•	intake context appears on the Inquiry detail page, not on
		render_anfragen()'s list view, not on any order page
	•	kiosk output (existing kiosk test fixtures) is unaffected by an
		Inquiry carrying intake context — a repository-level assertion, not
		an HTTP one, since kiosk_server.py doesn't read Inquiry at all (no
		route to even exercise)

Boundary (cross-cutting, wherever it fits best in the above files):
	•	creating an Inquiry with all four intake fields populated creates no
		Order and no OrderVersion — assert both repositories' list methods
		stay empty except for whatever the test itself set up
	•	no READY_TO_SEND evaluation is triggered or changed by an intake-only
		write — evaluate_ready_to_send() is Order-keyed and never called
		from any Inquiry write path; a test asserting no new code path calls
		it is effectively the same shape as 07083cc §10's "byte-identical
		kiosk/Wochenübersicht output" proof, applied to READY_TO_SEND instead
	•	convert_inquiry_to_order (order_service.py:33) does not read any of
		the four new fields or the widened source set — existing behavior,
		confirmed unchanged by inspection (order_service.py's imports and
		field reads are untouched by this pack); a regression test converts
		an Inquiry with populated intake fields and asserts the resulting
		Order/OrderVersion carry none of the intake_* values anywhere
		(neither field exists on Order/OrderVersion, so this is really an
		absence-of-crash + absence-of-new-fields-leaking assertion)

Proposal-preview (future, once §7 above is separately implemented):
	•	POST /proposal-preview still writes nothing — the existing
		test_proposal_preview_creates_nothing_in_core continues to pass
		unmodified by this pack, since this pack does not touch
		render_proposal_preview() at all
	•	explicit Inquiry submit remains required even after intake mapping
		exists — no new automatic path introduced

⸻

10. Acceptance criteria for this implementation step

	•	full existing suite passes unmodified in intent (existing tests may
		gain new sample data as described in §9, but no existing assertion
		changes meaning or is deleted)
	•	SQLite migration is backward-compatible: an old core.db (13-column
		inquiries table) opens successfully and all pre-existing rows load
		with intake_* as None
	•	old core.db can boot the office panel and kiosk exactly as before —
		no crash, no schema error, no behavior change for any pre-existing
		Inquiry
	•	no kitchen/kiosk/release changes — kiosk_server.py and
		WochenuebersichtService remain untouched files
	•	no Order/OrderVersion semantics changed — order_service.py and
		operational_core_service.py remain untouched files
	•	proposal selected_items remain context only — render_proposal_
		preview() and parse_proposal_payload() remain untouched files in
		this step (§7 defers that wiring)
	•	wix_form stays a valid, working write value (§1's regression guard)

⸻

11. Exit

Complete when this document is reviewed and frozen as accepted
implementation plan, with zero code changes in this repo. Actual
implementation is its own next step: code changes to domain/inquiry.py,
services/inquiry_service.py, repositories/sqlite_inquiry_repository.py, and
ui/office_panel.py, plus the test additions in §9, following this pack's
exact field lists, column order, and normalization rule — needing its own GO
and its own diff review before any commit, per this project's standing
review-before-code discipline. §7/§8 (proposal-preview mapping, website-form
and AI-telefonist adapters) stay explicitly out of scope for that next step
too, unless separately opened.
