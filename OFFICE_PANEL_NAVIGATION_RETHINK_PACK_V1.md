OFFICE_PANEL_NAVIGATION_RETHINK_PACK_V1

0. Purpose

Planning-only pack. No code in this step. Follow-up to
OFFICE_PANEL_EXECUTION_PACK_V1 and to the safe-labels step (WORKLOG Entry
056, commit 38361bb). That step replaced raw enum/status codes with German
labels but left the page structure untouched. Owner feedback after viewing
the live panel post-commit (2026-07-08): "стало чуть понятнее, но главная
проблема осталась — это всё ещё выглядит как табличная техпанель, а не как
интуитивная офисная рабочая поверхность." This pack answers exactly what was
asked: a new Startseite structure, an inventory of what data already exists,
what can be rearranged without domain changes, and what must not be touched.
No implementation follows until this pack is reviewed and frozen.

1. Problem statement (owner's own words, condensed)

	•	attention-bar cards read as state counters, not tasks — "0 Neue
		Anfragen" instead of "Neue Anfragen prüfen"
	•	"Rückrufe offen" appeared to be missing from a screenshot — already
		clarified as not a bug: both the sidebar badge and the attention card
		read the same `_sidebar_rueckruf_count` value, which is `None` when no
		`AUERSWALD_SYNC_URL` is configured (true of the local dev launch); the
		card and badge are correctly omitted, not broken
	•	tables show `ID` as the first column — not how office staff scan a list
	•	"Wirksam: ja" reads as legalistic/technical even auf Deutsch
	•	the Startseite shows three full stacked tables (Anfragen, Aufträge,
		Diese Woche) end to end — reads as a database dump, not a work surface

2. What already exists — data inventory (evidence, not invention)

This section lists only fields and values that already exist in Core and are
already computed or renderable in office_panel.py today. Nothing here is a
new query or a new domain concept.

	•	Inquiry (`src/catering_system/domain/inquiry.py`): inquiry_id,
		event_date, inquiry_source, crm_stage (one of the frozen CRM_PIPELINE
		values, e.g. "Neue Anfrage"), customer_linkage (an opaque dict of
		customer_id/contact_id/placeholder — no name string), time_window_text,
		location_text, guest_count_estimate, planning_mode,
		call_verification_required, call_verification_status
	•	Order (`domain/order.py`): order_id, source_inquiry_id,
		candidate_order_version_id, effective_order_version_id, cancelled_at
	•	OrderVersion: version_number, event_date, time_window_text,
		location_text, guest_count_estimate, planning_mode,
		kitchen_print_confirmed_at
	•	OfficePanel.render_queue() already computes, from data already loaded,
		with no extra service calls: neue_anfragen (inquiries with no linked
		order), ohne_druck (active orders with no kitchen_print_confirmed_at on
		any version), nicht_wirksam (active orders with no
		effective_order_version_id), blockiert (active orders where
		evaluate_ready_to_send().ready is False), storniert (cancelled orders),
		and the Rückrufe count (via the existing auerswald-sync read path)
	•	WochenuebersichtService.get_week_overview(year, week) already returns
		this week's effective entries: event_date, time_window_text,
		location_text, guest_count_estimate, order_id — this is the "Diese
		Woche" table, already isolated as its own section (`id="diese-woche"`)
	•	blocker vocabularies are already human-labelled as of commit 38361bb:
		_verification_label(), _ready_to_send_blocker_label(),
		_progression_blocker_label() — reusable as-is, no new mapping needed
	•	what does NOT exist anywhere in the domain: a customer display name.
		customer_linkage only carries opaque IDs and is not currently rendered
		anywhere in the panel. A "Kunde" column showing a real name is not
		buildable from current data — see §5.

3. Proposed Startseite structure — Arbeitszentrale

Reframe the top of the Startseite around the owner's four questions, each
backed by data that already exists per §2 — no new concept, only new
grouping and new labels:

	•	"Was ist jetzt offen?" — the existing attention cards, reworded from
		counters to actions (see §4). This block stays first, unchanged in
		position, only reworded.
	•	"Welche Rückrufe warten?" — promote the Rückrufe card visually (still
		the same `_sidebar_rueckruf_count`-backed card, still omitted when
		unconfigured, still linking to /rueckruf); no new data source.
	•	"Was ist diese Woche geplant?" — the existing "Diese Woche" table,
		moved directly under the attention block instead of at the bottom of
		the page. Same query, same table, new position.
	•	"Wo gibt es Blocker?" — not a new table: a filtered view of the
		existing Aufträge table showing only orders where blockiert or
		ohne_druck is true, using the same evaluate_ready_to_send() /
		kitchen_print_confirmed_at checks already computed in render_queue().
		This turns an implicit count into a short, scannable list without a
		new query.

The full Anfragen and Aufträge tables (today's entire working queue, not
just what needs attention) move below this block, kept as their existing
`id="anfragen"` / `id="auftraege"` sections so the sidebar nav links keep
working unchanged.

4. Reordering / rewording that needs NO domain change

	•	attention cards, action-phrased instead of state-phrased (text only,
		same underlying counts, same links):
		"Neue Anfragen" → "Neue Anfragen prüfen"
		"ohne Druckbestätigung" → "Druckbestätigung fehlt"
		"noch nicht operativ wirksam" → "Aufträge noch nicht wirksam"
		"Versandfreigabe blockiert" → stays (already action-shaped)
		"storniert" → "Stornierte Aufträge prüfen" (only if count > 0; a
		card for zero cancelled orders is not an action item)
	•	table column order: move the ID column out of first position. Anfragen
		becomes Datum / Ort / CRM-Stufe / Verifizierung / Auftrag / (ID as a
		short link at the end, same `inquiry_id[:8]` truncation as today).
		Aufträge becomes Datum-equivalent... Order itself has no event_date
		(only OrderVersion does) — so Aufträge realistically reorders to
		Status / Blocker / Anfrage / Wirksam / (ID last), since a bare
		order_id-first list is what reads worst today.
	•	"Wirksam: ja" / "Wirksam: –" → "Auftrag bestätigt" / "noch nicht
		bestätigt", or a single Status column merging effective + blocked
		state into one word per row (bereit / blockiert / noch nicht
		bestätigt / storniert) instead of two separate ja/– and
		bereit/blockiert columns. Pure rewording + column merge, same
		underlying booleans (o.effective_order_version_id is not None,
		evaluate_ready_to_send().ready).
	•	Rückrufe table already has a reasonable column order (Datum/Zeit/
		Nummer/Grund/Kontakt) — no change needed there.

None of the above touches a service, a repository, or a domain type. All of
it is string/HTML layout inside office_panel.py's render_queue(),
render_inquiry(), and render_order().

5. Flagged: looks small, is not in scope for V1

	•	a "Kunde" column with a real customer name. No name field exists on
		Inquiry or Order today — only the opaque customer_linkage dict, never
		rendered. Showing a name would require either (a) a domain change to
		Inquiry (adding a display-name field — a Core pack of its own), or (b)
		resolving customer_linkage.contact_id against EspoCRM live, which is
		exactly the "no CRM→Core bridge" boundary this project has already
		frozen. Recommendation: do not add a Kunde column in this pack; at
		most, location_text can serve as the closest existing at-a-glance
		identifier row office staff already use.
	•	merging the Anfragen and Aufträge tables into one list. This is exactly
		the "vocabularies not merged" rule (§5 of OFFICE_PANEL_EXECUTION_PACK_
		V1): Inquiry (CRM/process truth) and Order (operational truth) stay
		visually and structurally separate, even when grouped under the same
		"Arbeitszentrale" heading.

6. Open decision point — page structure

Today's panel is one page with anchor-linked sections (`#anfragen`,
`#auftraege`, `#diese-woche`), chosen deliberately in the earlier sidebar-nav
step to avoid adding routes. The owner's complaint #5 ("full tables read as
a database dump") could be addressed two ways:

	•	(a) keep one page, but visually demote the full tables below an
		Arbeitszentrale summary block (§3) — smallest change, no new routes,
		no new server logic
	•	(b) give Anfragen and Aufträge their own routes (e.g. `/anfragen`,
		`/auftraege`), turning the Startseite into a pure summary/dashboard
		with links out to the full lists — closer to what "Arbeitszentrale"
		implies, but a bigger structural change (new routes, sidebar nav
		update, more test surface)

This pack recommends (a) for V1: it satisfies every complaint in §1 without
adding routes, and (b) can follow later as its own small step if (a) still
doesn't feel like enough once seen live. Needs owner confirmation before
implementation — this is the one open question in this pack.

7. Hard out of scope (must-fail if folded in)

	•	Angebot erstellen, PDF erstellen, Senden — no price/offer/document
		concept exists in Core; that domain belongs to the separate
		fingerfood-app repo, and no configurator→Core bridge is accepted
	•	Preise in any form
	•	Ablehnen / any "rejected" Inquiry state — does not exist in
		CRM_PIPELINE today
	•	merging Inquiry and Order into one entity, one list, or one vocabulary
		(§5 tripwire, restated in §5 above)
	•	any Core schema, domain, service, or repository change — this pack is
		strictly office_panel.py HTML/layout and label text
	•	any new external data source beyond the already-integrated
		auerswald-sync read path
	•	a customer display-name field (see §5)

8. Access control / architecture invariants

Unchanged from OFFICE_PANEL_EXECUTION_PACK_V1 §3/§7: LAN-only, single shared
office auth, no per-user roles, single-threaded server (the invariant that
makes `_sidebar_rueckruf_count` safe as a module global stays load-bearing
and is not touched by this pack).

9. Acceptance

	•	every reworded label and every reordered column maps 1:1 onto a value
		already computed today; diff review confirms no new query, no new
		service call, no new domain logic
	•	Anfragen and Aufträge stay visually and structurally distinct — no row,
		card, or table mixes the two
	•	sidebar nav anchors (`#anfragen`, `#auftraege`, `#diese-woche`) keep
		working if option (a) from §6 is chosen; updated together with routes
		if (b) is chosen instead
	•	all 222 existing tests stay green; new/updated tests cover the reworded
		attention-card text and the new Blocker sub-list, not new behavior
	•	owner reviews a live screenshot against the original five complaints in
		§1 before this is considered done

10. Phased plan

Now (this pack): decide §6 (a) vs (b); freeze scope.
Next (implementation, in order, each shown as a diff plan before coding,
matching the safe-labels-step workflow):
	1.	reword attention cards (§4, first bullet) — text only
	2.	regroup Startseite into the Arbeitszentrale block (§3) — layout only
	3.	add the Blocker sub-list (§3, fourth bullet) — filter, no new query
	4.	reorder table columns + merge Wirksam/Status (§4) — layout only
	5.	WORKLOG acceptance entry
Later (own steps, not this pack): §6 option (b) if needed; any customer
display-name resolution (needs its own Core or CRM-bridge pack first).

⸻

11. Addendum — Action Dashboard (2026-07-08)

Context: §1–§10 above were written and §6 option (a) was implemented and
shipped (commit ab47533, WORKLOG Entry 057) — reworded attention cards,
Diese Woche promoted, a Blocker sub-list, ID demoted. Owner + external
reviewer follow-up concluded (a) alone is not enough: the Startseite still
reads as "all the data" rather than "what do I do now." This addendum
authorizes the next increment — turning the Startseite into an action
dashboard — following the same scoping discipline as the base pack. Still
planning-only; no code in this addendum.

12. What changes on the Startseite

The Startseite (`GET /`) stops showing the full Anfragen/Aufträge tables.
It shows three queues only, each a short list of rows that need an action,
built from data already computed today — no new query, no new domain
field:
	•	Rückruf nötig — today's `_sidebar_rueckruf_count`-backed list
		(fetch_missed_board), same source as `/rueckruf` today, just the top
		N rows inline instead of only a count + link
	•	Neue Anfragen — today's `neue_anfragen` list (inquiries with no
		linked order), unchanged
	•	Aufträge mit nächstem Schritt — today's `blockiert` list (already a
		superset of `ohne_druck`, since `kitchen_print_not_confirmed` is one
		of `evaluate_ready_to_send`'s own reasons — confirmed in
		domain/ready_to_send.py), the same list §6a's "Wo gibt es Blocker?"
		already renders. This addendum's queue replaces that block rather
		than duplicating it: same data, richer per-row action (see §14)
The attention-bar counters (§4) stay at the very top, unchanged — they are
the "at a glance" summary; the three queues below are the work surface that
replaces the old full tables. Their `#anfragen`/`#auftraege` anchor links
must be repointed to the new routes in §13, not to in-page anchors that no
longer contain the full tables.
"Diese Woche" (§3) stays as its existing compact 5-column mini-view — it is
already short and non-tabular-feeling; no change needed here.

13. Full lists move to separate routes — exact inventory

Of the four full lists named in the discussion, only two actually need new
routes; the other two already exist elsewhere and should be linked to, not
rebuilt:
	•	Anfragen — needs a new route, `GET /anfragen`: the exact table §6a
		already built (Datum/Ort/CRM-Stufe/Verifizierung/Auftrag/ID), moved
		verbatim out of render_queue() into its own render method
	•	Aufträge — needs a new route, `GET /auftraege`: same, the exact
		Freigabe/Blocker/Anfrage/Bestätigt/ID table, moved verbatim
	•	Rückrufliste — already has its own route, `GET /rueckruf` (built in
		the earlier Rückrufe step). No new route needed; the dashboard queue
		in §12 is a subset view of the same data, not a duplicate surface
	•	Woche (full week / multi-week) — already exists as the kitchen kiosk
		(`catering_system.ui.kiosk_server`, separate read-only service,
		reuses the same `WochenuebersichtService.get_week_overview`). Per
		OFFICE_PANEL_EXECUTION_PACK_V1 §6, Wochenübersicht editing/rebuilding
		inside the office panel is out of scope — "the panel may at most
		link to the kiosk view." No new office-panel route; a link to the
		existing kiosk is enough if a full week view is wanted from the
		panel. The exact cross-service link (kiosk runs on a different port,
		8082 in local dev) is a small implementation detail for the coding
		step, not a scope decision — flagged here so it isn't forgotten, not
		blocking this addendum
Sidebar nav updates from anchor links to real routes: "Anfragen" →
`/anfragen`, "Aufträge" → `/auftraege`; "Diese Woche" and "Rückrufliste"
entries are unchanged (still `/#diese-woche` and `/rueckruf`).

14. Exact action → route/service-call mapping (no pseudo-actions)

Per the rule "if there is no exact existing action behind a button, that
button must not appear," every row action below is traced to the existing
route it already POSTs to today, unchanged:

Rückruf nötig (per row):
	•	"Erledigt" → `POST /rueckruf/resolve` (existing — identical to the
		button already on `/rueckruf` today)
	•	"Anfrage erfassen" → a plain link to `GET /inquiry/new` (existing
		route/form). Not a prefill in the domain sense: Inquiry
		(domain/inquiry.py) has no phone/contact field at all today — only
		event_date, time_window_text, location_text, guest_count_estimate,
		planning_mode, call_verification_*, and the opaque customer_linkage.
		"Prefilled" can only mean the phone number is carried as a query
		param and shown as read-only page context above the form (e.g. "Anruf
		von: 0171...") for the office worker's own reference — it is never
		written into any Inquiry field, because no such field exists. Adding
		one is a domain decision this addendum does not make (see §15)

Neue Anfragen (per row, exactly one primary action, chosen the same way
render_inquiry() already decides which button to show today):
	•	if `inq.call_verification_required and inq.call_verification_status
		!= "verified"` → "Telefonisch verifiziert" → `POST
		/inquiry/{id}/verify` (existing route, today only on the inquiry
		detail page — moving it inline to the dashboard row is reuse of the
		same call, not a new action)
	•	else → "In Auftrag umwandeln" → `POST /inquiry/{id}/convert`
		(existing route)
	•	"Öffnen" (plain navigation link to `GET /inquiry/{id}`) may sit
		alongside as a secondary link, not a second button — opening the
		detail page is navigation, not an action, so it does not break the
		"one primary action per row" rule

Aufträge mit nächstem Schritt (per row, exactly one primary action). NOT
derived from `evaluate_ready_to_send(order_id).reasons[0]` directly — an
earlier draft of this addendum said so and that was wrong, caught during
implementation: `operational_core_service.make_order_version_effective()`
itself refuses a version whose kitchen print isn't confirmed (raises
ValueError), but a freshly-converted order's first READY_TO_SEND reason is
`no_effective_version`, not `kitchen_print_not_confirmed` (the facts check
order in that sequence). Following `reasons[0]` literally would have shown
"Wirksam machen" before the version was even printed — a button that fails
the moment it's clicked, exactly the invented-pseudo-action failure mode
§14's own rule exists to prevent. Correct resolution, derived from the
target OrderVersion's own fields instead:
	•	resolve the target version the same way as before: `order.candidate_
		order_version_id` if it names a real version of this order, else the
		highest `version_number` (display fallback, not new truth)
	•	if that version's `kitchen_print_confirmed_at is None` → "Druck
		bestätigen" → `POST /order/{id}/print-confirm` (existing route)
	•	else if `version.order_version_id != order.effective_order_version_id`
		→ "Wirksam machen" → `POST /order/{id}/effective` (existing route)
	•	else → no button (should not occur for a row in `blockiert`, defensive
		only)
	•	cancelled orders cannot occur here: `blockiert` is filtered from
		`active_orders`, which already excludes cancelled orders
	•	"Öffnen" (plain navigation link to `GET /order/{id}`) may sit
		alongside as a secondary link, same reasoning as above

15. Explicit non-goals

	•	no automatic Inquiry creation from a missed call — the auerswald-sync
		integration keeps its standing rule ("never writes into Core, never
		creates an Inquiry automatically"); §14's "Anfrage erfassen" is a
		link the office worker clicks and completes themselves, never a
		background action
	•	no new phone/contact field added to Inquiry in this step — the
		"prefill" in §14 is page-context display only, not a stored value;
		adding a real field is a separate Core domain decision, not part of
		this addendum
	•	"Freigabe anfordern" (`POST /order/{id}/ready`, i.e.
		`request_ready_to_send`) is explicitly NOT one of the §14 next-step
		actions. Reading operational_core_service.py: it "changes no order
		truth in either branch" — it only emits an audit event
		(OrderReadyToSend / OrderReadyToSendBlocked) and does not affect
		`ready`, which is derived purely from facts (effective version +
		print confirmation, domain/ready_to_send.py). Treating it as a
		blocker-resolving action would misrepresent what it does. It stays
		on the order detail page only, exactly as today
	•	no merging of the three queues into one list — Rückruf/Neue
		Anfragen/Aufträge mit nächstem Schritt stay three visually distinct
		blocks, each mapped to exactly one of the three vocabularies that
		§5 already keeps apart. A row from one queue never appears in
		another
	•	no Angebot/PDF/Senden/Preise/Ablehnen, no Core schema/domain/service/
		repository change, no configurator→Core bridge — unchanged from §7
	•	hiding ID/CRM-Stufe/Verifizierung/etc. from the Startseite is a
		visibility decision only: every one of those fields stays exactly as
		shipped in §6a on the new `/anfragen` and `/auftraege` routes (§13)
		and on the existing detail pages — nothing is removed from the
		system
	•	the office panel does not grow CRM features (contact history, notes,
		follow-up scheduling) — EspoCRM stays the side-context/deep-link
		target per OFFICE_PANEL_EXECUTION_PACK_V1 §2; this addendum only
		reshapes how existing Core-owned actions are surfaced

16. Open items before coding

	•	kiosk cross-service link mechanics (§13, Woche) — needs a base-URL
		decision (env var vs. hardcoded local port), small and not scope-
		affecting, resolve at diff-plan time for that specific piece
	•	exact row count / truncation for each queue (e.g. top 5–10 as
		DeepSeek suggested) vs. showing all — a display detail, not a scope
		question, decide during the diff-plan step

Resolved (owner confirmed, 2026-07-08):
	•	§12's "Aufträge mit nächstem Schritt" REPLACES §6a's "Wo gibt es
		Blocker?" heading/section — it is not shown alongside it. Same
		underlying `blockiert` list; showing both would put two near-
		identical attention zones on the Startseite ("here are the
		blockers" and "here's what to do about them"), which reintroduces
		the overload this addendum exists to remove. The implementation step
		must delete §6a's "Wo gibt es Blocker?" block, not add a second one
		next to it.
