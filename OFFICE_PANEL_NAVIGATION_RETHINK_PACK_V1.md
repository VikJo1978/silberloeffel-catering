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
