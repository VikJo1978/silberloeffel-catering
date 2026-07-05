OPERATIONAL_CORE_EXECUTION_PACK_V1

0. Purpose

This document defines the execution pack for the next operational layer of Catering System MVP, immediately after the accepted Slice A (external intake) and the accepted Slice B read-side line (B1–B27: Order/OrderVersion baseline, candidate version, derived progression-read chain).

Its purpose is:
	•	to turn "effective-switch invariant", "mandatory kitchen print acceptance gate", and "READY_TO_SEND blocked release semantics" — currently only named as frozen labels in WORKLOG.md, never specified — into one concrete, boundaried implementation target
	•	to close a real operational path (candidate → kitchen-print-confirmed → effective → READY_TO_SEND) that does not exist yet in any form, using its own directly-defined gate rule rather than borrowing one from the B7–B27 read chain (which answers a different, earlier-stage question and remains a separate, independent read line — see §10)
	•	to prevent this layer from either (a) drifting into more derived-read micro-slices, or (b) jumping into kitchen kiosk / Wochenübersicht / deployment work before this layer is closed

This document is execution-oriented, but — unlike SLICE_A_EXECUTION_PACK_V1 — it is NOT backed by a canonical STATE_MODEL_V2 / IMPLEMENTATION_SLICES_V1 / MASTER_ARCHITECTURE_INDEX_V1, because those files do not exist anywhere in this repository or its git history. Every rule below that is not directly evidenced by existing code or WORKLOG.md text is marked **[ASSUMPTION]** and must be confirmed or corrected before this pack is treated as frozen.

⸻

1. Layer identity

Name (working title, not yet bound to a slice letter)
Operational Core Layer — effective switch, mandatory kitchen print, READY_TO_SEND

**[ASSUMPTION]** Whether this continues as "Slice B" (per SLICE_A_EXECUTION_PACK_V1 §18: "Slice B... establishes local operational truth ownership") or starts a new "Slice C" is a naming decision, not a scope decision. This pack does not resolve it — pick either label when accepting this pack.

Primary goal
Give an OrderVersion a real path from "candidate" (B6) to "effective" (operationally active), gated by a mandatory kitchen print confirmation, and expose whether an Order is safely READY_TO_SEND or explicitly blocked.

Primary result
An office user can: confirm kitchen print for a candidate version → make it the effective version → request READY_TO_SEND, and the system will explicitly block that request with this layer's own reasons (§10) if the gate isn't satisfied. `RequestReadyToSend` changes no order truth either way — it only records an attempt/result event (§6.1).

⸻

2. Frozen dependencies

Binding, evidenced in this repo:
	•	existing Order / OrderVersion model (`domain/order.py`)
	•	existing candidate-version mechanism (B6)
	•	existing derived progression chain (B7–B27), in particular:
		◦	blocked-state evaluation (B7)
		◦	progression decision (B9)
		◦	checkpoint (B10)
		◦	facts (B23), reason fingerprint (B24), readiness flags (B25), severity (B21)
	•	WORKLOG.md Entry 001 "Must not be changed" list: effective-switch invariant, mandatory kitchen print as minimal acceptance gate, READY_TO_SEND blocked release semantics, derived-only role of Wochenübersicht, read-only MVP role of kitchen kiosk

Named but not evidenced anywhere in the repo (do not treat as binding text, only as binding labels):
	•	STATE_MODEL_V2, COMMANDS_AND_EVENTS_V1, ENTITY_AND_FIELD_CONTRACTS_V1, IMPLEMENTATION_SLICES_V1, PRINT_AND_DOCUMENT_CONTRACTS_V1, TEST_AND_ACCEPTANCE_MATRIX_V1

Precedence rule: if this pack ever appears to conflict with current repo evidence or an already-accepted WORKLOG.md entry, repo evidence and accepted WORKLOG entries win. A hypothetical, never-seen canonical document is not a valid reason to override either.

⸻

3. Exact scope

3.1 In scope
	•	mandatory kitchen print confirmation as a recorded fact on an OrderVersion (**[ASSUMPTION]**: modeled as a domain-level confirmation record, not a physical printer integration — see §8.2)
	•	effective-version switching: exactly one OrderVersion per Order may be "effective" at a time
	•	the effective-switch invariant: switching effective version is only allowed when the target version has a confirmed kitchen print
	•	READY_TO_SEND as a derived, blocked-by-default status: an Order is READY_TO_SEND only if it has an effective version whose kitchen print is confirmed; otherwise it is explicitly blocked, with reasons owned directly by this layer (§10) — not sourced from B7–B27
	•	the B7–B27 chain remains untouched and independent; this layer does not wire into it, extend it, or depend on it (see §10, §12)

3.2 Out of scope (deferred to later packs)
	•	Wochenübersicht generation
	•	kitchen kiosk UI (or any UI/API layer at all — none exists in this repo yet)
	•	buffet cards
	•	driver / logistics
	•	real HubSpot wiring (stays a noop stub), Cloudflare Worker, deployment onto "kitchen Lenovo"
	•	physical printer integration (see §8.2 — this pack models print confirmation as a domain fact, not a print driver)
	•	AI
	•	any further derived-read-only projection on top of the B7–B27 chain (explicit must-fail condition, see §12)

⸻

4. Domain target

By the end of this layer, the system must be able to:
	•	record a kitchen print confirmation against a specific OrderVersion
	•	promote a kitchen-print-confirmed OrderVersion to effective, replacing any prior effective version for that Order (prior effective version remains in immutable history, per B2/B3)
	•	refuse to promote a version to effective if its kitchen print is not confirmed
	•	compute whether an Order is READY_TO_SEND or blocked, using a small blocked-reason vocabulary owned directly by this layer (§10) — not the B7–B27 chain, which answers a different question
	•	refuse to mark an Order READY_TO_SEND while blocked

It must not claim that:
	•	kitchen print has been physically performed (only that it has been confirmed as a domain fact — see §8.2)
	•	Wochenübersicht or kiosk visibility has been established
	•	any operational truth exists outside this Order/OrderVersion axis

⸻

5. Entities touched

May be touched directly:
	•	OrderVersion — add kitchen print confirmation fact (**[ASSUMPTION]** field shape: `kitchen_print_confirmed_at: datetime | None`, immutable once set, consistent with existing immutable-version-history rule from B2)
	•	Order — add effective version reference (**[ASSUMPTION]** field shape: `effective_order_version_id: str | None`, distinct from `candidate_order_version_id` from B6) and a derived READY_TO_SEND read, not a stored status field; this layer owns the gate rule directly per §10

Must not be touched:
	•	Inquiry / CRM axis (Slice A boundaries remain intact)
	•	Wochenübersicht, kiosk (do not exist yet — do not create scaffolding for them here)

⸻

6. Commands and events

6.1 Commands and reads allowed in this layer
	•	ConfirmKitchenPrint(order_id, order_version_id) — idempotent; fails if order_version_id does not belong to order_id; does not imply effective switch; does not touch candidate version
	•	MakeOrderVersionEffective(order_id, order_version_id) — must fail if kitchen print not confirmed for that version; must fail if order_version_id does not belong to order_id
	•	evaluate_ready_to_send(order_id) — pure read, not a command: computes and returns READY_TO_SEND or blocked-with-reasons; mutates nothing, emits nothing. Always available regardless of whether anyone "attempts" to send.
	•	RequestReadyToSend(order_id) — the actual command an office user invokes when trying to send. Internally calls evaluate_ready_to_send; on blocked, the command fails and emits OrderReadyToSendBlocked; on success it emits OrderReadyToSend. RequestReadyToSend does not change order truth in either branch — it only records an attempt/result event, via the narrow event log (same pattern as Slice A's InquiryCreated/InquiryUpdated).

(Renamed from the earlier draft's single `AttemptMarkReadyToSend`: since READY_TO_SEND stays derived and unstored per §10, the check itself must be a query, and only the user-facing "trying to send" action is a command with event side effects.)

6.2 Events expected
	•	KitchenPrintConfirmed
	•	OrderVersionMadeEffective
	•	OrderReadyToSend
	•	OrderReadyToSendBlocked (carries reasons defined directly by this layer's own gate rule — see §10; not the B7–B27 progression-blocked vocabulary, which answers a different, earlier-stage question)

6.3 Commands explicitly deferred beyond this layer
	•	any Wochenübersicht command
	•	any kiosk display command
	•	any buffet card or driver command
	•	any command that reverts an effective version back to a prior one (**[ASSUMPTION]**: not clearly required by anything evidenced; treat as out of scope unless the user confirms it's needed)

⸻

7. Minimal field scope

New fields required (subject to confirmation):

On OrderVersion:
	•	`kitchen_print_confirmed_at: datetime | None`

On Order:
	•	`effective_order_version_id: str | None`

No new fields on Inquiry. No new persisted status/enum field for READY_TO_SEND — it must stay derived (consistent with B7–B27's "no new persisted truth axis" discipline, which must extend here too).

⸻

8. Mandatory kitchen print gate

8.1 Role

Kitchen print confirmation is the minimal acceptance gate before any OrderVersion may become operationally effective. This is named explicitly in WORKLOG.md Entry 001 as a "must not be changed" rule.

8.2 Required behavior — **[ASSUMPTION, needs user confirmation]**

This pack assumes kitchen print confirmation is a domain-level fact ("someone in the kitchen confirmed this version was printed and reviewed"), recorded through `ConfirmKitchenPrint`, and does NOT assume:
	•	a physical printer driver integration
	•	a specific print document format/layout

If the real intent is a physical print pipeline (actual paper output to a kitchen printer), that is materially larger scope (driver/protocol work, hardware access) and must be split into its own pack — do not silently fold it into this one.

8.3 Forbidden behavior

The gate must not:
	•	be bypassable by directly setting `effective_order_version_id` without a prior `kitchen_print_confirmed_at`
	•	be satisfied implicitly by candidate-version selection (B6) alone
	•	be weakened by a "convenience" override path

8.4 Confirmation rules
	•	`ConfirmKitchenPrint` is only valid for an `order_version_id` that exists and belongs to `order_id`
	•	confirming an already-confirmed version is idempotent (no error, no duplicate side effect, no new event on repeat)
	•	confirmation is not revocable within this layer (no `RevokeKitchenPrintConfirmation` command — out of scope unless explicitly requested)
	•	confirming an old/superseded version does not retroactively make it effective, and does not affect whichever version is currently effective

⸻

9. Effective-switch invariant

	•	Exactly one effective OrderVersion per Order at any time
	•	Switching effective version is a command (`MakeOrderVersionEffective`), never an implicit side effect of another command
	•	Prior effective version is not deleted or mutated — full immutable version history (B2/B3) remains intact
	•	Effective version is distinct from candidate version (B6) and from "latest historical version" (B3) — all three remain independently readable
	•	`MakeOrderVersionEffective` may target any OrderVersion belonging to the order that satisfies the kitchen print gate — not only the current candidate version — unless a later accepted pack explicitly narrows this
	•	`effective_order_version_id` may be `None` (no effective version yet)
	•	When set, `effective_order_version_id` must reference an existing OrderVersion belonging to the same Order — this is a checked invariant, not just a convention
	•	Making a version effective never implicitly changes `candidate_order_version_id` (B6) — the two fields are updated independently unless a future pack explicitly decides otherwise

⸻

10. READY_TO_SEND blocked release semantics

	•	This layer defines its own gate rule directly, in code, as the single source of truth: an Order is READY_TO_SEND only if it has an `effective_order_version_id`, and that version's `kitchen_print_confirmed_at` is set. Nothing about this rule is delegated to the B7–B27 chain.
	•	If not satisfied, the Order is blocked. The blocked reason(s) for *this* gate belong to a small, new, explicit vocabulary owned by this layer (e.g. `NO_EFFECTIVE_VERSION`, `KITCHEN_PRINT_NOT_CONFIRMED`) — not a reinterpretation of B23/B24/B25.
	•	The existing B7–B27 progression chain answers a different, earlier-stage question (can this inquiry convert to an order / is a candidate version resolvable) and may still be surfaced alongside this layer's own result as separate, additional context on an operator screen later — but it is a second, independent read model, not the mechanism this gate depends on. Do not merge the two reason vocabularies.
	•	READY_TO_SEND must remain a derived read, not a stored status column (see §7)

⸻

11. Acceptance criteria

This layer is accepted only if all of the following are true:
	•	kitchen print can be confirmed against a specific OrderVersion
	•	an OrderVersion cannot become effective without a prior kitchen print confirmation
	•	exactly one effective version exists per Order after a successful switch
	•	prior effective version remains in immutable history
	•	READY_TO_SEND is blocked by default and only succeeds when the gate is satisfied
	•	blocked reasons for this gate come from this layer's own small vocabulary (§10), not a reinterpretation of B23–B25
	•	no new persisted status/truth axis is introduced beyond the two fields in §7
	•	Slice A and B1–B27 boundaries remain intact

⸻

12. Must-fail conditions

This layer must be considered not accepted if any of the following happens:
	•	kitchen print confirmation is skippable via any code path
	•	more than one effective version can exist per Order simultaneously
	•	effective-switch silently deletes or mutates prior version history
	•	READY_TO_SEND is implemented as a stored enum/status field rather than derived
	•	this layer's write-side gate logic (§8, §9, §10) is implemented to depend on B21/B23/B24/B25 outputs as its source of truth, instead of defining its own direct rule (that would invert the dependency: write-side truth must not depend on a read-side derived chain built for a different question)
	•	this layer expands into Wochenübersicht, kiosk, buffet cards, or driver logic under a "convenience" argument
	•	this layer produces another derived-read-only micro-projection instead of the write-side commands defined in §6.1

⸻

13. Explicit freeze boundaries

While implementing this layer, the following must not be changed:
	•	Slice A boundaries (Entry 006/007/009 in WORKLOG.md)
	•	B1–B27 read-side contracts and their existing tests
	•	immutable OrderVersion history (B2/B3)
	•	candidate-version semantics (B6) — effective version is additive, not a replacement for candidate
	•	no Wochenübersicht, kiosk, buffet card, or driver behavior introduced here

⸻

14. Recommended execution order

	1.	add `kitchen_print_confirmed_at` to OrderVersion + `ConfirmKitchenPrint` command (idempotent, ownership-checked per §8.4) + tests
	2.	add `effective_order_version_id` to Order + `MakeOrderVersionEffective` command, gated by step 1, with the invariants in §9 checked + tests
	3.	define this layer's own blocked-reason vocabulary (§10) and implement `evaluate_ready_to_send` (pure read) directly against steps 1–2 — do not consult B7–B27 for this rule
	4.	implement `RequestReadyToSend` command wrapping step 3 with event emission only (§6.1–6.2), no new persisted status
	5.	verify no regression in Slice A / B1–B27 suite
	6.	write the acceptance snapshot in WORKLOG.md

This order may be operationally adjusted, but step 3's independence from B7–B27 is not optional — that dependency direction (write-side truth depending on a read-side chain built for a different question) is exactly what §12 forbids.

⸻

15. Minimal deliverables

	•	`ConfirmKitchenPrint`, `MakeOrderVersionEffective`, `evaluate_ready_to_send`, `RequestReadyToSend` service methods
	•	the two new fields (§7)
	•	a derived READY_TO_SEND read model with its own blocked-reason vocabulary (§10), independent of B7–B27
	•	unit tests for: gate-blocked promotion attempt, successful promotion, blocked READY_TO_SEND, unblocked READY_TO_SEND, immutable history preserved after switch, repeat-confirm idempotency, confirm-then-switch-old-version-has-no-effect
	•	WORKLOG acceptance entry

⸻

16. What must not be changed while implementing this layer

	•	no physical printer integration folded in silently (§8.2)
	•	no new persisted status axis beyond §7
	•	no dependency of this layer's write-side gate logic on the B7–B27 read chain (§10, §12)
	•	no further B-style derived-read micro-slicing under this pack

⸻

17. Exit condition

This layer is complete only when:
	•	the full path candidate → kitchen-print-confirmed → effective → READY_TO_SEND (or explicitly blocked) works end-to-end with tests
	•	this layer's gate rule and blocked-reason vocabulary are defined and owned directly by this layer, not delegated to B7–B27
	•	no scope has leaked into Wochenübersicht / kiosk / deployment

If any of these is missing, this layer remains incomplete.

⸻

18. Next layer after acceptance (non-binding planning note, not a roadmap commitment)

Likely next candidates, in no confirmed order:
	•	Wochenübersicht generation (derived-only)
	•	kitchen kiosk (read-only MVP UI) — first UI/API layer in the project
	•	real HubSpot wiring / Cloudflare Worker / deployment onto kitchen Lenovo

Each needs its own execution pack before implementation starts, for the same reason this one was written: WORKLOG labels without a backing spec are exactly what produced the B15–B27 micro-slicing pattern. The order above is a guess, not a decision — confirm scope and order only once this layer is actually closed.
