KIOSK_EXECUTION_PACK_V1

0. Purpose

Execution pack for the kitchen kiosk — the first UI surface in the project.
Binding label from WORKLOG Entry 001: "read-only MVP role of kitchen kiosk".
Evidence rule as in OPERATIONAL_CORE_EXECUTION_PACK_V1 §2.

1. Identity and goal

Kitchen kiosk — read-only HTML view of the Wochenübersicht for the kitchen
display on the kitchen Lenovo. Goal: the kitchen can see the current ISO week's
deliveries (effective versions only) in a browser, with zero write capability.

2. Scope

In scope:
	•	stdlib-only HTTP server (http.server) — no new dependencies, matching the
		zero-dependency runtime of the rest of the repo
	•	GET-only: any other method answers 405; unknown paths answer 404
	•	renders the Wochenübersicht read model for the current ISO week by default;
		?year=&week= query parameters select another week (still read-only)
	•	all user-originating text (location, time window) HTML-escaped
	•	a runnable entrypoint (python -m catering_system.ui.kiosk_server) taking
		--db (SQLite path) and --port, for deployment on the kitchen Lenovo
	•	pure render function separated from the HTTP handler so the HTML is testable
		without sockets

Out of scope (must-fail if folded in):
	•	any mutating endpoint, form, or button — the kiosk writes nothing, ever
	•	auth/user management (kiosk is a trusted kitchen-LAN display in MVP)
	•	office UI, CRM UI, buffet cards, driver views
	•	JavaScript frameworks / frontend build tooling

3. Acceptance

	•	GET / renders the current week's entries from Core truth via
		WochenuebersichtService only
	•	POST/PUT/DELETE/PATCH → 405; unknown path → 404
	•	HTML-injection via order text fields is escaped
	•	server code contains no repository write calls
	•	existing suites remain green

4. Exit

Complete when render + handler tests pass and a WORKLOG entry records it.
Next after acceptance (non-binding): HubSpot wiring / secure intake worker /
deployment pack.
