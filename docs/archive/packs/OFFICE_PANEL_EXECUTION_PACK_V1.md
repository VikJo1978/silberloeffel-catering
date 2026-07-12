OFFICE_PANEL_EXECUTION_PACK_V1

0. Purpose

Execution pack for the office panel — the primary office working interface and
the only write path from office staff into Core. Derived from the step-by-step
daily office cycle (7 of 9 daily actions are Core actions; only calls/mail/
follow-up are CRM work), which settled the interface question: panel primary,
CRM secondary. Evidence rule as in OPERATIONAL_CORE_EXECUTION_PACK_V1 §2.

1. Identity and goal

Office panel — a small server-rendered UI over the existing Core services
(InquiryService, OrderService, OperationalCoreService). It is a thin skin over
already-accepted operations: this pack adds NO new domain semantics, no new
gates, no new truth. If an action isn't already a Core service call, it doesn't
belong in the panel.

2. CRM context fixed by this pack

	•	CRM = EspoCRM, self-hosted on the office server (decision recorded here;
		replaces the earlier HubSpot assumption). The HubSpot HTTP client built
		under INTEGRATION_DEPLOYMENT_EXECUTION_PACK_V1 stays in the repo as an
		unwired artifact — not deleted, not wired
	•	an own/self-written CRM is permanently out of scope: CRM is a replaceable
		external tool behind the sync boundary, never a build target
	•	CRM is the secondary tool: contacts, communication history, notes, tasks,
		follow-ups. The office's daily operational work happens in the panel
	•	inquiry mirrors in EspoCRM are OPTIONAL and deferred: the panel owns the
		working queue, so the Core→Espo sync adapter is not required for V1 of
		anything. When wanted, it is its own additive step (Core→CRM push
		direction only, like the HubSpot design)

3. Topology invariants (placement is an implementation choice, these are not)

	•	the panel writes only into Core on the kitchen Lenovo
	•	kitchen operations (Core, kiosk, gates, print) must never depend on
		office-server availability
	•	the panel is LAN-only — never exposed to the internet
	•	no CRM→Core bridge exists in any form; EspoCRM needs no network route or
		credential to Core, and the topology should enforce that (firewall rule,
		not just convention)
	•	where the panel's HTTP/UI process runs (on the Lenovo next to Core, or as
		a thin LAN client to it) is decided at implementation time — any choice
		is acceptable that preserves the four invariants above

4. V1 scope

Working queue (read):
	•	active inquiries and orders in one place — the office's primary list

Inquiry actions:
	•	create inquiry (UI over the existing manual/phone capture path)
	•	update inquiry
	•	mark verified-by-call (verify_customer_by_call — the B5 gate input)

Order actions:
	•	convert inquiry → order (gate-checked; on refusal the panel shows why)
	•	create new order version
	•	print view (kitchen order sheet — a derived, printable rendering of a
		version; introduced by this pack as a read-only view, no new semantics)
	•	confirm kitchen print
	•	make version effective
	•	request READY_TO_SEND

CRM linkage:
	•	read-only deep-links out to the EspoCRM contact card / communication
		context ("open client in CRM"); nothing flows back

5. Blocked-reason display — two vocabularies, never merged

The panel shows reasons from two separate, already-accepted read models:
	•	progression reasons (B7 vocabulary: verification unsatisfied, candidate
		missing/not resolvable) — for inquiry→order and candidate-related views
	•	operational gate reasons (ready_to_send.py vocabulary: no effective
		version, kitchen print not confirmed, ...) — for the READY_TO_SEND view

Per OPERATIONAL_CORE_EXECUTION_PACK_V1 §10 these vocabularies must not be
merged, mapped onto each other, or blended in UI copy. The panel renders each
where it belongs and nowhere else.

6. Hard out of scope (must-fail if folded in)

	•	CRM write-back into Core, or any CRM→Core automation
	•	kitchen kiosk behavior (the kiosk stays a separate read-only surface)
	•	Wochenübersicht editing (it stays derived-only; the panel may at most
		link to the kiosk view)
	•	analytics / dashboards / reporting
	•	rich Espo sync automation
	•	public access of any kind (see §3: LAN-only)
	•	a second truth: no panel-side storage beyond Core; no caching layer that
		can disagree with Core
	•	new domain semantics smuggled in as "UI convenience" (e.g. a cancel/
		revoke/reprint action that has no accepted Core operation behind it —
		such needs land as their own Core pack first, panel second)

7. Access control (V1)

	•	minimal shared office authentication (basic auth or equivalent) — unlike
		the kiosk, the panel is a write surface and must not be anonymous
	•	per-user accounts/roles are deferred; the audit trail in V1 is the event
		log plus single-office-trust, matching MVP reality

8. Acceptance

	•	every panel action maps 1:1 onto an existing accepted service call; diff
		review confirms no new domain logic in the panel layer
	•	gates behave in the UI exactly as in Core: a blocked conversion or
		blocked READY_TO_SEND shows the correct vocabulary's reasons and
		performs nothing
	•	print view renders a version faithfully and is print-usable
	•	write attempts without authentication are rejected
	•	kiosk, Wochenübersicht, and all existing suites remain green and
		untouched

9. Phased plan

Now (this pack): accept boundaries; no code in this step.
Next (implementation steps, in order):
	1.	working queue + inquiry create/update/verify
	2.	convert + versions
	3.	print view + confirm print + effective + READY_TO_SEND (reason display
		per §5)
	4.	auth + WORKLOG acceptance entry
Later (own steps): EspoCRM deep-links (needs a running Espo), Espo sync
adapter (optional mirrors), any cancel/revoke/reprint semantics (Core pack
first).
