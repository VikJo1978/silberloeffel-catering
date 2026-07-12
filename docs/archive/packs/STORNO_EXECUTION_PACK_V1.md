STORNO_EXECUTION_PACK_V1

0. Purpose

Execution pack for order cancellation (Storno) — the operational gap named in
WORKLOG discussions and deliberately deferred by OPERATIONAL_CORE_EXECUTION_PACK_V1
§6.3 and OFFICE_PANEL_EXECUTION_PACK_V1 §6 ("cancel needs its own Core pack
first, panel second"). Evidence rule as in OPERATIONAL_CORE_EXECUTION_PACK_V1 §2.

1. Core decision

Cancellation is a new explicit fact, not a deletion and not a rollback:
	•	Order gains exactly one field: cancelled_at: datetime | None
	•	immutable version history stays untouched — nothing is deleted or reverted
	•	candidate/effective references stay as they were at cancellation time
		(historical truth); their meaning is neutralized by the derived reads below

2. Command

	•	CancelOrder(order_id) — sets cancelled_at, emits OrderCancelled
	•	idempotent: repeat cancel returns unchanged, emits nothing (same pattern
		as ConfirmKitchenPrint §8.4)
	•	not revocable in this pack (no UncancelOrder; own pack if ever wanted)
	•	allowed at any stage, incl. after effective/READY_TO_SEND (real world:
		client cancels the day before delivery)
	•	no cancellation-reason field in Core V1 — the reason is office context
		and belongs in the CRM note

3. Consequences on existing layers (explicit amendments)

	•	operational commands are refused on a cancelled order:
		ConfirmKitchenPrint, MakeOrderVersionEffective raise
	•	order-side mutations are refused on a cancelled order:
		create_relevant_order_change_version, set_candidate_order_version raise
		(explicit amendment of accepted B2/B6 behavior — recorded here)
	•	READY_TO_SEND: a cancelled order is blocked with a NEW reason in the
		operational vocabulary (order_cancelled) — READY_TO_SEND stays derived;
		the two-vocabulary separation (OPERATIONAL_CORE §10) is untouched
	•	Wochenübersicht: cancelled orders never appear (the kitchen must not
		deliver a cancelled order); kiosk inherits this via the read model
	•	B7–B27 progression chain: NOT amended — it answers the earlier-stage
		question and stays as accepted
	•	Order field boundary (OPERATIONAL_CORE §7, guard test): amended to
		exactly three operational fields — kitchen_print_confirmed_at,
		effective_order_version_id, cancelled_at

4. Persistence

	•	SQLite orders table gains cancelled_at (nullable); defensive in-place
		migration (ALTER TABLE ADD COLUMN when missing) since pre-Storno
		databases may already exist from bring-up preparations

5. Must-fail conditions

	•	cancellation deletes or mutates any OrderVersion or history row
	•	cancellation is implemented as a status enum instead of a timestamp fact
	•	a cancelled order remains reachable by any operational command
	•	a cancelled order appears in the Wochenübersicht
	•	the cancelled reason is merged into the progression (B7) vocabulary
	•	an uncancel path is folded in silently

6. Exit

Complete when the command + guards + derived consequences pass tests, existing
suites stay green, and a WORKLOG entry records it. The office-facing Storno
button belongs to the office panel implementation, not to this pack.
