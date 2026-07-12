WOCHENUEBERSICHT_EXECUTION_PACK_V1

0. Purpose

Execution pack for the Wochenübersicht layer, next after the accepted operational
core (OPERATIONAL_CORE_EXECUTION_PACK_V1, WORKLOG Entries 036–039). Same evidence
rule as that pack §2: repo evidence + accepted WORKLOG entries win over the
never-seen canonical documents; the only binding label here is WORKLOG Entry 001
"derived-only role of Wochenübersicht".

1. Identity and goal

Wochenübersicht — kitchen-facing weekly overview, derived-only.
Goal: one read model answering "what does the kitchen deliver in ISO week X?",
computed on demand from Core truth (orders + effective versions). Consumed next
by the kitchen kiosk (own pack).

2. Scope

In scope:
	•	a derived, read-only weekly overview for a given ISO year/week
	•	an order appears only if it has a resolvable effective OrderVersion whose
		event_date falls in the requested week — effective is the only kitchen truth
	•	because the operational gate requires a confirmed kitchen print before any
		version becomes effective, every listed entry is print-confirmed by construction
	•	one additive read method on OrderRepository: list_orders() (both adapters)
	•	deterministic ordering: event_date, then time_window_text, then order_id

Out of scope (must-fail if folded in):
	•	persistence of the overview (no WochenübersichtVersion snapshots — the frozen
		role is derived-only; versioned snapshots would need their own accepted pack)
	•	any write/command surface, any kitchen acceptance mechanics
	•	kiosk HTTP/UI (next pack), buffet cards, driver logic
	•	candidate or latest-historical versions leaking into the overview — effective only

3. Shape

	•	domain/wochenuebersicht.py: frozen WochenuebersichtEntry (order_id,
		effective_order_version_id, version_number, event_date, time_window_text,
		location_text, guest_count_estimate, planning_mode) and frozen
		Wochenuebersicht (iso_year, iso_week, entries tuple)
	•	services/wochenuebersicht_service.py: get_week_overview(iso_year, iso_week)
		— pure read, no events, no writes

4. Acceptance

	•	orders without an effective version never appear
	•	effective versions outside the requested ISO week never appear
	•	ordering is deterministic
	•	no mutation of any repository state on read
	•	existing suites remain green

5. Exit

Complete when the read model + service + tests pass and a WORKLOG entry records it.
Next after acceptance (non-binding): kitchen kiosk pack.
