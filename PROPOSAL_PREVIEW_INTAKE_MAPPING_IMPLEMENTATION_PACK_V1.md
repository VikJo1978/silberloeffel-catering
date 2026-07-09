PROPOSAL_PREVIEW_INTAKE_MAPPING_IMPLEMENTATION_PACK_V1

0. Purpose

Implementation-only pack. Wires the already-frozen proposal preview
(PROPOSAL_PREVIEW_MANUAL_INQUIRY_PACK_V1, frozen d7429b5, implemented
9012c35) into the already-implemented Inquiry intake fields
(INQUIRY_INTAKE_CONTEXT_FIELDS_PACK_V1 frozen 07083cc,
INQUIRY_INTAKE_CONTEXT_FIELDS_IMPLEMENTATION_PACK_V1 frozen 0c38814,
implemented a98065c). No code changes in this pack; every claim below was
checked against current code on 2026-07-10
(src/catering_system/ui/office_panel.py: parse_proposal_payload,
render_proposal_preview, render_proposal_preview_form, render_inquiry_form,
do_GET/_route_post routing; tests/unit/test_office_panel.py).

⸻

1. Current state — evidence base

parse_proposal_payload(raw) (office_panel.py:330) validates schema_version,
source, title, event_date, guest_count, selected_items[].name; proposal_id,
notes, calculated_total_net/gross and per-item quantity/prices/notes are
optional, displayed if present, never further validated.

render_proposal_preview(payload) (office_panel.py:403) renders a read-only
table (source/title/event_date/guest_count/totals/notes/proposal_id + an
items table with prices) and ends with a GET link:

	<a href="/inquiry/new?{event_date}&{guest_count_estimate}">
	    Anfrage aus Vorschau vorbereiten</a>

— built via urlencode() at office_panel.py:414-419, carrying only those two
values (2026-07-09 review narrowed this deliberately for URL-fragility
reasons — PROPOSAL_PREVIEW_MANUAL_INQUIRY_PACK_V1 §9 explicitly left
widening this to a separate, explicitly scoped follow-up; this pack is that
follow-up).

render_inquiry_form(self, phone="", event_date="", guest_count_estimate="")
(office_panel.py:761) already accepts prefill hints for two fields. Its
Kanal <select> (src_opts, office_panel.py:764) has no "selected" logic at
all today — unlike _planning_mode_select/_crm_stage_select, which do. Its
four intake_* inputs (added in a98065c, office_panel.py:783-787) are always
rendered empty; render_inquiry_form has no parameters for them yet.

Routing: GET /inquiry/new (office_panel.py:1092-1100) reads phone/event_date/
guest_count_estimate from the query string. POST /proposal-preview
(office_panel.py:1139) parses and renders only — no redirect, matching this
pack's own required shape for the new prepare step.

⸻

2. Boundary (restated, unchanged — frozen by the three packs in §0)

	•	POST /proposal-preview stays read-only — untouched by this pack
	•	the new prepare step is read-only — parses and renders only, exactly
		like /proposal-preview already does
	•	GET /inquiry/new and the new prepare route render a form only — no
		Inquiry exists until the office explicitly submits that form
	•	no Order, no OrderVersion, no wirksam/effective, no READY_TO_SEND, no
		kitchen/kiosk/release effect — nothing in this pack touches those
		code paths at all (order_service.py, operational_core_service.py,
		kiosk_server.py, WochenuebersichtService remain untouched files)
	•	no session storage, no server-side persistence of the proposal
		payload — the prepare step round-trips the already-validated payload
		through the client's own POST body only (§4)
	•	no raw full proposal JSON stored anywhere in Core — it exists only
		for the duration of one request/response cycle, twice (preview, then
		prepare), never written to any repository
	•	no prices anywhere in Inquiry, in intake_summary or any other field —
		§5's mapping rule enforces this explicitly

⸻

3. Transport decision

Option A — GET query string to /inquiry/new (today's mechanism, widened):
rejected for intake_message/intake_summary. A verbose call-relayed note
(hundreds of characters) or a multi-item selected_items summary, combined
with title/proposal_id in the same query string, plausibly exceeds
comfortable GET URL length (~2000 chars is the practical safe ceiling across
browsers/proxies) and multiline text survives query-string encoding
awkwardly (percent-encoded newlines, harder to eyeball in a browser's
address bar). This is exactly the fragility 2026-07-09's review flagged —
it gets worse, not better, once real free text is involved.

Option B — POST prepare step, writes nothing: adopted for V1. The preview
page's "Anfrage aus Vorschau vorbereiten" becomes a small embedded form
(method="post", action="/proposal-preview/prepare") carrying one hidden
field — the payload, re-serialized — plus the existing button. The new route
re-parses it with the exact same parse_proposal_payload() already used by
/proposal-preview (single source of truth for validation, zero duplicated
logic), builds the mapping (§5), and renders render_inquiry_form() directly
— no redirect, matching /proposal-preview's own existing no-redirect
convention (office_panel.py:1139-1145's comment: "nothing is persisted... so
there is deliberately no redirect"). Longer text travels safely in a POST
body; no new persistence is introduced; the only write anywhere remains the
pre-existing, unmodified POST /inquiry/new submit.

Option C — server-side temp/session storage: rejected, not designed further.
Adds hidden state, a cleanup/expiry question, and a second thing that could
silently diverge from "nothing is persisted" if ever mis-implemented. Option
B achieves the same UX (no re-pasting JSON) with zero new state.

Hidden-field payload shape: json.dumps(payload) — the already-validated
dict, re-serialized. Not the office's original raw textarea text (no need to
thread that through separately); re-serializing a dict that already passed
parse_proposal_payload() is safe and byte-for-byte re-parseable.

⸻

4. Field mapping

From the parsed proposal_payload_v1 dict, at prepare time:

	event_date          → render_inquiry_form's event_date          (unchanged shape)
	guest_count         → render_inquiry_form's guest_count_estimate (str(int), unchanged shape)
	source (constant)   → inquiry_source = "configurator"            (NEW — see §5.1)
	title               → intake_subject                             (NEW)
	notes (optional)    → intake_message                             (NEW; "" if absent)
	selected_items      → intake_summary, compact human-readable, NO prices (NEW; §5.2)
	proposal_id(optional) → intake_external_ref                      (NEW; "" if absent)

Never mapped, under any circumstance:
	•	calculated_total_net / calculated_total_gross
	•	unit_price / total_price / any per-item price
	•	selected_items as anything other than the compact name+quantity
		summary text in §5.2 — never structured, never OrderVersion.items
		(no such field exists on OrderVersion; this pack does not add one)

5.1 inquiry_source preselection — a real, small gap found while writing this
pack: render_inquiry_form's Kanal <select> has no way to preselect an option
today (§1). This pack's implementation step must add that — a new
inquiry_source: str = "" parameter and a selected="selected" attribute in
src_opts's generation when the option matches, mirroring the existing
_planning_mode_select/_crm_stage_select helpers' pattern exactly. "configurator"
is already a valid, office-dropdown-visible value (a98065c: _OFFICE_SOURCES
includes it) — so no domain/service change is needed, only this rendering gap.

5.2 intake_summary format — one line per selected item, name and quantity
only, joined by "\n" (renders correctly inside the existing <textarea
name="intake_summary">, which already preserves newlines):

	{name} × {quantity}      — when the item has a quantity
	{name}                   — when it doesn't (quantity is optional per
	                            parse_proposal_payload's own validation, §1)

Example, matching the task's own sample:

	Brötchen Mix 1 × 10
	Brötchen Mix 3 × 10

"×" (multiplication sign) chosen for consistency with existing German UI
copy conventions in this file (e.g. Küchenzettel-adjacent tables). No unit
price, no total price, no per-item notes — those stay preview-page-only,
exactly as today.

⸻

6. Exact UI/route plan

render_proposal_preview(payload) — the trailing prepare link becomes an
embedded form, replacing the plain <a href="/inquiry/new?...">:

	<form method="post" action="/proposal-preview/prepare">
	<input type="hidden" name="payload_json" value="{escaped json.dumps(payload)}">
	<button type="submit">Anfrage aus Vorschau vorbereiten</button>
	</form>

The existing "Weitere Vorschau anzeigen" link stays a plain GET link,
unchanged.

render_inquiry_form(...) — four more optional string parameters, all
defaulting to "": inquiry_source, intake_subject, intake_message,
intake_summary, intake_external_ref. (inquiry_source's default "" means "no
option preselected," matching today's behavior when the parameter is
omitted — the existing GET-hint call site at office_panel.py:1092-1100 is
untouched and keeps working exactly as today, since it never passes
inquiry_source.) The four intake_* inputs already exist in the form's HTML
(a98065c) — this step only makes their value="{_e(...)}" attributes use the
new parameters instead of always being empty.

New route — _route_post gains one branch, structurally identical to the
existing POST /proposal-preview branch:

	elif parts == ["proposal-preview", "prepare"]:
	    payload = parse_proposal_payload(self._form().get("payload_json", ""))
	    summary = "\n".join(
	        f"{item['name']} × {item['quantity']}"
	        if item.get("quantity") is not None
	        else item["name"]
	        for item in payload["selected_items"]
	    )
	    self._html(panel.render_inquiry_form(
	        event_date=payload["event_date"],
	        guest_count_estimate=str(payload["guest_count"]),
	        inquiry_source="configurator",
	        intake_subject=payload["title"],
	        intake_message=payload.get("notes") or "",
	        intake_summary=summary,
	        intake_external_ref=payload.get("proposal_id") or "",
	    ))

No redirect — same convention as /proposal-preview's own POST handler and
for the same reason (nothing was written, so there is nothing to redirect
away from). Auth: inherited automatically, like every other route, from
do_POST's existing _authorized() check — no new auth logic. Error handling:
inherited automatically from do_POST's existing except (ValueError, KeyError)
→ _error_page(...) — a tampered or malformed hidden field re-fails the exact
same validation /proposal-preview already enforces, with the exact same
office-readable error text (§9's "invalid proposal cannot reach prepare").

⸻

7. Exact non-goals

	•	no change to parse_proposal_payload()'s validation rules
	•	no change to what /proposal-preview itself renders or accepts
	•	no change to GET /inquiry/new's existing phone/event_date/
		guest_count_estimate query-hint path — additive only
	•	no new domain/service/repository code — "configurator" is already a
		valid, already-implemented inquiry_source (a98065c); no new intake
		field is added here, only prefill wiring for the four that already
		exist
	•	no session, no cookie, no server-side temp storage of any kind
	•	no automatic Inquiry creation anywhere in this flow — the prepare
		route renders a form, nothing more
	•	no kitchen/kiosk/release/READY_TO_SEND code touched
	•	no configurator (fingerfood-app) changes — the payload shape is
		already exactly what fffc60b exports; this pack only changes how the
		catering-repo's office panel consumes it after preview

⸻

8. Tests

Extending tests/unit/test_office_panel.py, following its existing live-
socket HTTP pattern:

	•	POST /proposal-preview with a valid payload still creates no
		Inquiry/Order/OrderVersion — existing test_proposal_preview_
		creates_nothing_in_core continues to pass unmodified; this pack adds
		no write path to that route, so no new assertion is needed there,
		only continued green
	•	a successful preview response contains the new prepare <form
		action="/proposal-preview/prepare"> and its button text "Anfrage aus
		Vorschau vorbereiten" (replaces the old plain-link assertion in
		whichever existing test checked for that string, e.g. the current
		test class around office_panel.py's prepare-link tests from 9012c35)
	•	POST /proposal-preview/prepare with a valid payload renders
		render_inquiry_form with: Kanal preselected to "configurator"
		(assert the configurator <option> carries selected), event_date and
		guest_count_estimate prefilled (unchanged shape from today),
		intake_subject == title, intake_message == notes, intake_summary
		containing each item as "{name} × {quantity}" (no "€", no price
		figures anywhere in the response body), intake_external_ref ==
		proposal_id
	•	POST /proposal-preview/prepare creates no Inquiry, no Order, no
		OrderVersion — same InMemory-repository-assertion shape as
		test_creating_inquiry_with_intake_context_creates_no_order_or_
		orderversion (a98065c), applied to this new route instead
	•	an explicit POST /inquiry/new submit after prepare, with office-
		edited values (different event_date, different intake_subject),
		creates an Inquiry carrying the edited values, not the proposal's
		original ones — same "explicit submit overrides hints" shape as
		test_manual_submit_wins_over_query_hints (9012c35), extended to the
		intake fields
	•	intake_summary and the full response body never contain
		unit_price/total_price/calculated_total_net/calculated_total_gross
		values or a "€" sign anywhere — a direct negative assertion, the
		sharpest test for §2's "no prices" boundary
	•	selected_items are never written as OrderVersion.items — same
		dataclasses.fields()-based structural assertion pattern as
		test_convert_inquiry_with_intake_context_does_not_leak_into_order
		(a98065c), reused after converting an Inquiry created via this new
		flow
	•	kiosk/Wochenübersicht output is unchanged before vs. after a prepare-
		then-submit cycle — same WochenuebersichtService before/after
		byte-identical-result shape as test_intake_context_does_not_change_
		wochenuebersicht (a98065c)
	•	an invalid/tampered payload_json posted directly to
		/proposal-preview/prepare (bypassing the preview step) returns 400
		with the same office-readable error text as /proposal-preview's own
		invalid-JSON case — proves "invalid proposal cannot reach prepare"
		structurally, not just by convention (§9 acceptance criterion)
	•	long intake_message/intake_summary (e.g. a multi-paragraph note, a
		15-item selected_items list) round-trips through the POST body
		correctly — a concrete regression guard for why Option B was chosen
		over Option A

⸻

9. Acceptance criteria for the future implementation step

	•	POST /proposal-preview remains unmodified in behavior (existing test
		passes unchanged)
	•	the new /proposal-preview/prepare route parses, maps, and renders
		only — zero calls to InquiryService.create_inquiry or any repository
		write method anywhere in its code path
	•	GET /inquiry/new's existing query-hint behavior is unmodified
		(existing 9012c35 tests pass unchanged)
	•	Inquiry is created only by the pre-existing, unmodified explicit POST
		/inquiry/new submit
	•	no Order, no OrderVersion, no READY_TO_SEND/wirksam change anywhere
		in the new flow — proven by repository-state assertions, not just
		absence of a code path claim
	•	no price figure (unit_price, total_price, calculated_total_net/gross)
		appears anywhere in intake_subject/intake_message/intake_summary/
		intake_external_ref or their rendered HTML
	•	kiosk/Wochenübersicht output is byte-identical before/after
	•	full existing suite (273 tests as of a98065c) stays green; new tests
		follow this pack's §8 list

⸻

10. Risks / mitigations

	•	Risk: hidden-field payload tampering (an office user edits the hidden
		json.dumps(payload) value before submitting the prepare form).
		Mitigation: irrelevant to the truth boundary — the prepare route only
		ever renders a form; even a maliciously edited hidden payload cannot
		create Core data by itself, since the only write is the separate,
		still-fully-validated POST /inquiry/new submit the office makes
		afterward. At most a tampered payload produces a misleading prefill,
		which the office reviews before submitting — same trust level as
		today's plain-text form fields.
	•	Risk: a very large selected_items list makes intake_summary long
		enough to be unwieldy in a 3-row textarea. Mitigation: cosmetic only,
		not a boundary issue — the field remains freely editable text; no
		length cap is enforced, consistent with every other intake field
		(INQUIRY_INTAKE_CONTEXT_FIELDS_IMPLEMENTATION_PACK_V1 §3's "no
		maximum length enforced" precedent).
	•	Risk: this pack's HTML change to render_proposal_preview's prepare
		link (link → form) could break an existing test asserting on the old
		<a href="/inquiry/new?..."> shape. Mitigation: named explicitly in
		§8 — the implementation step must update that assertion, not just
		add new ones; called out here so it isn't missed as "just an
		addition."
	•	Risk: inquiry_source preselection touches shared rendering code
		(src_opts) used by both the plain GET-hint path and this new prepare
		path. Mitigation: the new parameter defaults to "" (no
		preselection), so the existing GET-hint call site's output is
		provably unchanged — a regression test for that call site's exact
		current HTML output should be added or confirmed alongside this
		change.

⸻

11. Exit

Complete when this document is reviewed and frozen as accepted
implementation plan, with zero code changes in this repo. Actual
implementation is its own next step, needing its own GO and diff review
before any commit, per this project's standing discipline. Website-form and
AI-telefonist mappings (INQUIRY_INTAKE_CONTEXT_FIELDS_PACK_V1 §6/§7) remain
out of scope here, unchanged from every prior pack in this chain.
